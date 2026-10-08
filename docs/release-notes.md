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

Mac 应用暂未进行 Apple Developer ID 签名和公证。确认来源后，可在“系统设置 → 隐私与安全性”中批准打开这个应用。
