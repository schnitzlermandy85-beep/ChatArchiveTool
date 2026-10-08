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

应用使用本机浏览器显示界面。关闭标签页不会退出服务，请点击界面的电源按钮。

## 可选组件与签名

桌面包包含核心分析和 HTTPS CA 证书。新语音识别引擎／模型不打包，界面禁用未安装的转写选项；需要新转写请用源码版安装 `requirements.txt`。Windows 微信组件保持按需安装，Mac 在前后端都拒绝安装和直接读取。真实微信读取仍需使用者的客户端和数据进行验证。

当前 Mac 构建只有 PyInstaller 的本地 ad-hoc 签名，没有 Developer ID 公证；Windows exe 也没有发布者代码签名。若要提供已公证的 Mac 分发包，需要维护者自己的 Apple Developer ID 证书与公证凭据，再扩展 CI 签名流程。

参考：[PyInstaller 跨系统构建](https://pyinstaller.org/en/stable/usage.html)、[GitHub runner 架构](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。
