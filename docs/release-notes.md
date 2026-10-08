## 选择你的下载版本

在下方 **Assets** 选择带系统名称的 ZIP，无需另装 Python：

| 电脑 | 文件名包含 | 打开方式 |
| --- | --- | --- |
| Windows 64 位 | `Windows-x64.zip` | 完整解压后打开 `ChatArchiveTool/ChatArchiveTool.exe` |
| Mac，Apple 芯片（M 系列） | `macOS-AppleSilicon.zip` | 解压后将 `ChatArchiveTool.app` 拖到“应用程序”并打开 |
| Mac，Intel 芯片 | `macOS-Intel.zip` | 解压后将 `ChatArchiveTool.app` 拖到“应用程序”并打开 |

Mac 芯片类型见苹果菜单 →“关于本机”。`Source code` 是开发者源码包，不是免安装桌面版。每个 ZIP 附有 SHA-256 校验文件。

支持导入聊天归档、本地关系分析、可选 AI API 和中文 HTML 报告。解压包中的 `examples/synthetic-chat` 可直接用于体验。点击界面电源按钮退出程序。

Apple 芯片 Mac 新增 QQ 组件安装／启动和微信 wxvault 安装／初始化入口。微信直读需完成终端授权与登录，当前支持文字和可提取图片，其余媒体保留缺失占位；Intel Mac 微信仍使用导入。真实账号端到端导出尚待用户设备验收。新语音转写需要源码版安装可选语音依赖；桌面包保留原始音频并复用已有转写。QQ 直连需先启动并登录 QQChatExporter。

<a id="mac-open-anyway"></a>

### Mac 提示“Apple 无法验证”怎么办？

首次打开时，可能看到：

> Apple 无法验证“ChatArchiveTool”是否包含可能危害 Mac 安全或泄漏隐私的恶意软件。

当前 Mac 版本只有本地 ad-hoc 签名，尚未使用 Apple Developer ID 正式签名，也未完成 Apple 公证，因此 macOS 会拦截首次打开。这个提示本身不能判断应用是否包含恶意软件。

确认安装包来自 [本仓库的 Releases](https://github.com/schnitzlermandy85-beep/ChatArchiveTool/releases)，且未被修改后，可按以下步骤打开：

1. 解压 ZIP，将 `ChatArchiveTool.app` 拖到“应用程序”文件夹，再双击一次。
2. 出现上述提示时，点击“完成”或关闭弹窗。
3. 打开 **苹果菜单 → 系统设置 → 隐私与安全性**，向下滚动到“安全性”区域。
4. 找到 ChatArchiveTool 被阻止打开的提示，点击 **“仍要打开”**。
5. 按系统提示使用 Touch ID 或输入 Mac 登录密码，再点击 **“打开”**。

此操作会为这个应用添加打开例外，之后通常可以直接双击启动。如果找不到“仍要打开”，先再次尝试打开应用，再回到“隐私与安全性”查看；由单位或学校管理的 Mac 可能需要联系管理员。

操作依据：[Apple 官方说明：在 Mac 上安全地打开 App](https://support.apple.com/zh-cn/102445)。
