# 桌面打包与 Release

`.github/workflows/release.yml` 在三个原生 runner 上分别构建：

| runner | 下载包 |
| --- | --- |
| `windows-2022` | `Windows-x64.zip` |
| `macos-14`（arm64） | `macOS-AppleSilicon.zip` |
| `macos-15-intel`（x86_64） | `macOS-Intel.zip` |

CI 使用 Python 3.12。每个任务运行回归测试、前端检查、PyInstaller 打包和打包后 HTTP／合成聊天分析测试。全部任务成功后，版本标签才会创建一个同时包含三套 ZIP 与校验文件的 GitHub Release。构建矩阵是验证环境，不代表已验证全部旧版系统。

## 发布

1. 合并代码，确认要发布的提交。
2. 在该提交创建并推送未使用的版本标签，例如 `git tag v1.1.0`、`git push origin v1.1.0`。
3. 等待 Actions 的 **Desktop release** 完成。Release 说明自动读取 `docs/release-notes.md`，用户在 Assets 选择系统和芯片。

手动运行工作流或打开 PR 也会验证三平台并上传 Actions artifacts，但不会创建公开 Release。工作流的发布任务仅授予 `contents: write`，构建任务只读仓库。重复发布同一个已存在 Release 不覆盖原下载文件，应使用新版本标签。

## 本机构建

必须在目标系统和 CPU 架构上打包，不能在 Mac 上生成 Windows exe。

```bash
python -m pip install -r requirements-build.txt -r requirements-dev.txt
python scripts/build_release.py --version v1.1.0
```

产物位于 `dist/release/`。打包仅选取程序资源、第三方许可和合成示例，不包含本机 `.wechat-packages`、真实导出、日志、密钥和虚拟环境。Mac ZIP 使用 `ditto` 保留 `.app` 的符号链接和可执行权限；Windows ZIP 必须整包解压，exe 依赖旁边的 `_internal` 目录。

打包后的资源与用户数据分离：Mac 数据目录为 `~/Library/Application Support/ChatArchiveTool`；Windows 为 `%LOCALAPPDATA%/ChatArchiveTool`。`CHATARCHIVE_DATA_DIR` 可覆盖数据目录，冒烟测试使用独立临时目录。报告继续写入用户选定的输入档案旁。

应用使用本机浏览器显示界面。Mac v0.1.6 的原生 AppKit 启动层负责重新打开和退出：关闭标签页后再次双击 App 会重开界面；可用菜单栏“聊天档案”打开或退出。页面退出会同时结束原生 App，菜单栏退出会等待后台清理。

Mac 构建额外编译 `native/mac_launcher.swift`，将原 PyInstaller 主程序作为 `ChatArchiveToolBackend` 单独重新签名，再签主 App。打包测试默认执行原生生命周期验证；受限且没有图形会话的本地命令环境可显式使用 `--skip-native-launcher-check`，但必须另行验证桌面启动，发布 CI 不跳过。

## 可选组件与签名

桌面包包含核心分析和 HTTPS CA 证书。新语音识别引擎／模型不打包；需要新转写请用源码版安装 `requirements.txt`。Windows 微信组件保持按需安装，Mac 微信内置 SQLCipher、DAT/HEVC 解码和原生只读密钥扫描组件，首次准备必须由用户勾选说明后主动触发。修改微信签名前备份同版本程序；实际连接使用系统授权弹窗，不使用终端密码流程。原生 ZIP 分享作为可选导入途径保留。Apple 芯片 Mac 的 QQ 可安装并启动 QCE。组件、账号配置、密钥及缓存不打包。真实微信直连和媒体导出需用户自行验收。

Mac 构建另外需要 Xcode Command Line Tools 中的 Swift 和 Clang 编译器。`build_wechat_reader.py` 编译只读扫描器，并仅用内存合成样本自检，不访问微信进程。`build_wechat_share.py` 编译 `WeChatShare.appex`，先签嵌套扩展再重新签主 App；扩展仅有沙盒和用户选择文件读写权限，没有网络、应用组或微信进程读取权限。`VERSION` 同时驱动界面、Info.plist 和发行标签校验。

当前 Mac 构建只有 PyInstaller 的本地 ad-hoc 签名，尚未使用 Apple Developer ID 正式签名或完成 Apple 公证；Windows exe 也没有发布者代码签名。`codesign --verify` 通过只说明签名和包完整性校验通过，不代表 Apple 已审核或公证，也不保证下载后不会被 Gatekeeper 拦截。

用户遇到“Apple 无法验证”时，按 [README 中的 Mac 首次打开步骤](../README.md#mac-open-anyway) 对该应用单独批准打开；发布说明模板也包含同样步骤。

要消除这类未公证拦截，需要维护者提供 Apple Developer ID Application 签名证书及公证凭据，在 CI 中完成正式签名、提交 Apple 公证并附加公证票据后再分发。重新压缩 ZIP 或再次执行本地 ad-hoc 签名不能替代这一流程。参考 [Apple Developer ID 签名与公证说明](https://developer.apple.com/developer-id/)。

参考：[PyInstaller 跨系统构建](https://pyinstaller.org/en/stable/usage.html)、[GitHub runner 架构](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。
