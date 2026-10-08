本版修复与使用说明：

- 纠正 Mac 微信支持范围：原版受保护微信不能用当前方案直读。在密码提示前检查系统和应用签名，避免反复授权；保留 wechat-chat-export 的 Windows 导出 → Mac 导入流程。
- 对照 QQChatExporter v6.3.2 接入 `/health`，区分未扫码、仅查看模式、令牌失败；最近联系人补充接口失败不再挡住好友和群聊。新增打开 QQChatExporter 原版导出界面的入口。
- 新增可搜索的应用内帮助，按 QQ、微信、权限、终端、API、保存与导入等主题提供步骤，适合第一次使用。
- 导出与本地分析不需要 API；AI 分析由用户核对发送内容并授权。

## 选择你的下载版本

在下方 **Assets** 选择带系统名称的 ZIP，无需另装 Python：

| 电脑 | 文件名包含 | 打开方式 |
| --- | --- | --- |
| Windows 64 位 | `Windows-x64.zip` | 完整解压后打开 `ChatArchiveTool/ChatArchiveTool.exe` |
| Mac，Apple 芯片（M 系列） | `macOS-AppleSilicon.zip` | 解压后将 `ChatArchiveTool.app` 拖到“应用程序”并打开 |
| Mac，Intel 芯片 | `macOS-Intel.zip` | 解压后将 `ChatArchiveTool.app` 拖到“应用程序”并打开 |

Mac 芯片类型见苹果菜单 →“关于本机”。`Source code` 是开发者源码包，不是免安装桌面版。每个 ZIP 附有 SHA-256 校验文件。

支持导入聊天归档、本地关系分析、可选 AI API 和中文 HTML 报告。解压包中的 `examples/synthetic-chat` 可直接用于体验。点击界面电源按钮退出程序。

Apple 芯片 Mac 新增 QQ 组件安装／启动和微信 wxvault 安装／连接入口。原版受保护的 Mac 微信当前不支持直读，Apple 芯片和 Intel Mac 均可导入已有微信文件。QQ 在用户本机的真实服务已验证在线且成功读取会话列表；尚未据此声称全部聊天和媒体完成导出验收。新语音转写需要源码版安装可选语音依赖；桌面包保留原始音频并复用已有转写。QQ 直连需先启动并登录 QQChatExporter。

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
