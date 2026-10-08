// Native macOS share entry. Inspired by Dukou's documented NSItemProvider flow.
// No WeChat process access, password, network entitlement or app-group dependency.
import AppKit
import UniformTypeIdentifiers

@objc(ChatArchiveShareViewController)
final class ShareViewController: NSViewController {
    private let status = NSTextField(wrappingLabelWithString: "将微信选中的聊天保存为 ZIP，然后回到 ChatArchiveTool 选择这个文件。")
    private var saveButton: NSButton!
    private var staged: URL?

    override func loadView() {
        view = NSView(frame: NSRect(x: 0, y: 0, width: 400, height: 190))
        let title = NSTextField(labelWithString: "导出微信聊天 ZIP")
        title.font = .boldSystemFont(ofSize: 18)
        saveButton = NSButton(title: "选择保存位置…", target: self, action: #selector(save))
        let cancel = NSButton(title: "取消", target: self, action: #selector(cancelShare))
        let buttons = NSStackView(views: [saveButton, cancel])
        let stack = NSStackView(views: [title, status, buttons])
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 16
        stack.translatesAutoresizingMaskIntoConstraints = false; view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
            stack.topAnchor.constraint(equalTo: view.topAnchor, constant: 24)
        ])
        preferredContentSize = view.frame.size
    }

    @objc private func save() {
        guard let context = extensionContext else { return }
        let providers = context.inputItems.compactMap { $0 as? NSExtensionItem }.flatMap { $0.attachments ?? [] }
        guard providers.count == 1, let provider = providers.first else {
            status.stringValue = "请选择一批合并转发的聊天记录。一次保存一个 ZIP。"; return
        }
        saveButton.isEnabled = false
        let types = provider.registeredTypeIdentifiers
        let type = types.first { UTType($0)?.conforms(to: .zip) == true }
            ?? types.first { UTType($0)?.conforms(to: .data) == true && $0 != UTType.fileURL.identifier }
        if let type {
            provider.loadFileRepresentation(forTypeIdentifier: type) { [weak self] url, error in
                self?.stage(url, error: error)
            }
        } else if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
            _ = provider.loadObject(ofClass: NSURL.self) { [weak self] object, error in
                guard let url = object as? URL else { self?.stage(nil, error: error); return }
                let scoped = url.startAccessingSecurityScopedResource()
                defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                var coordinationError: NSError?
                NSFileCoordinator().coordinate(readingItemAt: url, options: .withoutChanges, error: &coordinationError) { readable in
                    self?.stage(readable, error: error)
                }
                if let coordinationError { self?.fail(coordinationError) }
            }
        } else {
            status.stringValue = "微信没有提供聊天 ZIP。请先多选消息，再选择合并转发到其他应用。"
            saveButton.isEnabled = true
        }
    }

    // The item provider's temporary file disappears when its callback returns.
    // Copy synchronously inside that callback; only our own copy crosses queues.
    private func stage(_ url: URL?, error: Error?) {
        do {
            if let error { throw error }
            guard let url else { throw failure("微信没有返回文件，请重新多选并合并转发。") }
            let values = try url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey, .isSymbolicLinkKey])
            guard values.isRegularFile == true, values.isSymbolicLink != true,
                  let size = values.fileSize, size > 0, size <= 1_073_741_824 else {
                throw failure("文件为空或超过 1 GB，请缩小所选消息范围。")
            }
            let handle = try FileHandle(forReadingFrom: url)
            defer { try? handle.close() }
            guard try handle.read(upToCount: 4) == Data([0x50, 0x4b, 0x03, 0x04]) else {
                throw failure("收到的不是 ZIP。请多选聊天并合并转发，不要单独转发一条文字。")
            }
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
            let copy = directory.appendingPathComponent("微信聊天.zip")
            do {
                try FileManager.default.copyItem(at: url, to: copy)
                try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: copy.path)
            } catch {
                try? FileManager.default.removeItem(at: directory); throw error
            }
            DispatchQueue.main.async { [weak self] in
                guard let self else { try? FileManager.default.removeItem(at: directory); return }
                self.staged = copy; self.chooseDestination(copy)
            }
        } catch { fail(error) }
    }

    private func chooseDestination(_ copy: URL) {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.zip]
        let formatter = DateFormatter(); formatter.dateFormat = "yyyy-MM-dd-HHmmss"
        panel.nameFieldStringValue = "微信聊天-\(formatter.string(from: Date())).zip"
        panel.title = "保存选中的微信聊天"
        panel.message = "记住所选文件夹。保存后在 ChatArchiveTool 中选择这个 ZIP。"
        panel.begin { [weak self] response in
            guard let self else { return }
            defer { self.cleanup() }
            guard response == .OK, let destination = panel.url else {
                self.saveButton.isEnabled = true; return
            }
            do {
                // NSSavePanel authorizes only the user-selected destination.
                let data = try Data(contentsOf: copy, options: .mappedIfSafe)
                try data.write(to: destination, options: .atomic)
                try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: destination.path)
                self.status.stringValue = "ZIP 已保存。回到 ChatArchiveTool → 微信 → 选择刚保存的 ZIP → 开始整合。"
                self.saveButton.title = "完成"; self.saveButton.action = #selector(self.finish); self.saveButton.isEnabled = true
            } catch { self.fail(error) }
        }
    }

    private func failure(_ message: String) -> NSError {
        NSError(domain: "ChatArchiveShare", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
    private func fail(_ error: Error) {
        DispatchQueue.main.async { [weak self] in
            self?.status.stringValue = "保存未完成：\(error.localizedDescription)"; self?.saveButton.isEnabled = true
        }
    }
    private func cleanup() {
        if let staged { try? FileManager.default.removeItem(at: staged.deletingLastPathComponent()) }
        staged = nil
    }
    @objc private func finish() { cleanup(); extensionContext?.completeRequest(returningItems: nil) }
    @objc private func cancelShare() { cleanup(); extensionContext?.cancelRequest(withError: NSError(domain: NSCocoaErrorDomain, code: NSUserCancelledError)) }
}
