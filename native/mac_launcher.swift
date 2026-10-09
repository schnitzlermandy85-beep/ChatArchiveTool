// AppKit owns the application lifecycle; the frozen Python worker owns exports.
// A browser tab is a view, so closing it must not discard a running task.
import AppKit
import Darwin

final class Launcher: NSObject, NSApplicationDelegate {
    let worker: URL
    let testMode: Bool
    let session: URL
    var process: Process?
    var timer: Timer?
    var status: NSStatusItem?
    var currentURL: URL?
    var shutdownToken: String?
    var stopping = false
    var opens = 0
    var started = Date()

    init(worker: URL, testMode: Bool) throws {
        self.worker = worker
        self.testMode = testMode
        session = FileManager.default.temporaryDirectory.appendingPathComponent("chatarchive-launch-" + UUID().uuidString)
        super.init()
        try FileManager.default.createDirectory(at: session, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let show = NSMenuItem(title: "打开聊天档案", action: #selector(showWindow), keyEquivalent: "")
        show.target = self; menu.addItem(show)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "退出 ChatArchiveTool", action: #selector(quitApp), keyEquivalent: "")
        quit.target = self; menu.addItem(quit)
        status = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        status?.button?.title = "聊天档案"
        status?.button?.toolTip = "ChatArchiveTool · 点击可重新打开界面或退出"
        status?.menu = menu
        let child = Process()
        child.executableURL = worker; child.arguments = ["--no-browser"]
        var env = ProcessInfo.processInfo.environment
        env["CHATARCHIVE_LAUNCH_READY"] = session.appendingPathComponent("ready.json").path
        child.environment = env
        child.terminationHandler = { [weak self] child in
            DispatchQueue.main.async { self?.finished(child.terminationStatus) }
        }
        process = child
        do {
            try child.run()
            timer = Timer.scheduledTimer(withTimeInterval: 0.15, repeats: true) { [weak self] _ in self?.pollReady() }
        } catch {
            report("无法启动聊天工具", error.localizedDescription)
            finish()
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        return true
    }

    @objc func showWindow() {
        guard !stopping, let url = currentURL else { return } // startup poll opens when ready
        if testMode {
            opens += 1
            recordTest()
        } else if !NSWorkspace.shared.open(url) {
            report("浏览器未能打开", "工具已启动，可将此地址复制到浏览器：\n" + url.absoluteString)
        }
    }

    func pollReady() {
        guard !stopping else { return }
        let ready = session.appendingPathComponent("ready.json")
        if let data = try? Data(contentsOf: ready),
           let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let address = value["url"] as? String, let url = URL(string: address),
           url.scheme == "http", url.host == "127.0.0.1", url.port != nil,
           value["pid"] as? Int32 == process?.processIdentifier {
            timer?.invalidate(); timer = nil
            currentURL = url
            shutdownToken = value["token"] as? String
            showWindow()
            if testMode {
                // Exercise the same delegate callback Finder/Dock uses, without opening browser tabs.
                _ = applicationShouldHandleReopen(NSApp, hasVisibleWindows: false)
                _ = applicationShouldHandleReopen(NSApp, hasVisibleWindows: false)
                if ProcessInfo.processInfo.environment["CHATARCHIVE_TEST_MENU_QUIT"] == "1" {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.quitApp() }
                }
            }
        } else if Date().timeIntervalSince(started) > 45 {
            report("启动等待时间较长", "请在菜单栏“聊天档案”中退出后重试。启动日志位于资源库/Application Support/ChatArchiveTool/logs/startup.log。")
            timer?.invalidate(); timer = nil
            quitApp()
        }
    }

    func recordTest() {
        guard let dir = ProcessInfo.processInfo.environment["CHATARCHIVE_DATA_DIR"], let url = currentURL else { return }
        let value: [String: Any] = ["url": url.absoluteString, "opens": opens,
                                   "pid": process?.processIdentifier ?? 0]
        if let data = try? JSONSerialization.data(withJSONObject: value) {
            try? data.write(to: URL(fileURLWithPath: dir).appendingPathComponent("launcher-test.json"), options: .atomic)
        }
    }

    @objc func quitApp() {
        if testMode { fputs("launcher: menu quit requested\n", stderr) }
        NSApp.terminate(nil)
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let child = process, child.isRunning else { return .terminateNow }
        if !stopping {
            stopping = true
            status?.button?.title = "正在退出…"
            if let url = currentURL, let token = shutdownToken {
                // Use the same authenticated graceful stop as the in-page button.
                var request = URLRequest(url: url.appendingPathComponent("api/shutdown"))
                request.httpMethod = "POST"; request.httpBody = Data("{}".utf8)
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                request.setValue(token, forHTTPHeaderField: "X-Archive-Token")
                request.timeoutInterval = 10
                URLSession.shared.dataTask(with: request) { [weak self] _, response, error in
                    if error != nil || (response as? HTTPURLResponse)?.statusCode != 200 {
                        DispatchQueue.main.async {
                            guard let self = self, self.process?.isRunning == true else { return }
                            self.stopping = false; self.status?.button?.title = "聊天档案"
                            self.report("退出请求未完成", "请打开聊天档案页面，点击“退出工具”后重试。")
                        }
                    }
                }.resume()
            } else {
                child.interrupt() // Startup has not exposed an HTTP endpoint yet.
            }
        }
        // Keep the normal AppKit run loop alive until the child exits. A delayed
        // termination loop can prevent main-queue callbacks on older macOS.
        return .terminateCancel
    }

    func finished(_ code: Int32) {
        if testMode { fputs("launcher: backend exited \(code)\n", stderr) }
        if code != 0 && !stopping {
            report("聊天工具意外退出", "请重新打开 App。若仍失败，请查看资源库/Application Support/ChatArchiveTool/logs/startup.log。")
        }
        finish() // Child has exited, so the next termination request is immediate.
    }

    func report(_ title: String, _ message: String) {
        if testMode { fputs(title + ": " + message + "\n", stderr); return }
        let alert = NSAlert(); alert.messageText = title; alert.informativeText = message
        alert.addButton(withTitle: "好"); alert.runModal()
    }

    func finish() { NSApp.terminate(nil) }

    func applicationWillTerminate(_ notification: Notification) {
        timer?.invalidate()
        try? FileManager.default.removeItem(at: session)
    }
}

let executable = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
let worker = executable.deletingLastPathComponent().appendingPathComponent("ChatArchiveToolBackend")
let args = Array(CommandLine.arguments.dropFirst()).filter { !$0.hasPrefix("-psn_") }
if !args.isEmpty && args != ["--launcher-test"] {
    // CLI checks/helpers keep their exit status and PID; never start the AppKit shell.
    let values = ([worker.path] + args).map { strdup($0) } + [nil]
    values.withUnsafeBufferPointer { buffer in _ = execv(worker.path, buffer.baseAddress!) }
    perror("ChatArchiveToolBackend"); exit(1)
}
let application = NSApplication.shared
application.setActivationPolicy(.accessory)
do {
    let delegate = try Launcher(worker: worker, testMode: args == ["--launcher-test"] || ProcessInfo.processInfo.environment["CHATARCHIVE_LAUNCHER_TEST"] == "1")
    application.delegate = delegate
    withExtendedLifetime(delegate) { application.run() }
} catch {
    fputs("Unable to create launcher session: \(error)\n", stderr)
    exit(1)
}
