## v0.1.4：Mac 微信改为原生 ZIP 导出

- 停用会触发密码授权的 Mac 微信初始化、进程读取入口。新版不再启动微信调试器。
- Mac 包加入“导出聊天 ZIP · ChatArchiveTool”分享扩展：微信多选消息 → 合并转发到其他应用 → 保存 ZIP → 回本工具整合。需微信提供该功能（4.1.13 起）。
- 支持原生 ZIP/TXT、媒体附件和 Dukou 批次 ZIP；保留原始 ZIP/TXT，缺失附件明确标注。
- 界面显示真实版本号，增加无需终端的新手操作步骤。
- Windows 微信和 QQ 路径保留。

仅导出选中的消息，不代表全部历史。原生 TXT 没有账号 ID，时间只有分钟精度，语音可能只剩占位；该路径暂不自动转写，也暂不能直接用于要求身份确认的关系分析。真实微信的菜单与文件接收仍需用户在自己的客户端验证。

| 电脑 | 下载文件后缀 |
| --- | --- |
| Windows x64 | Windows-x64.zip |
| Mac M 系列 | macOS-AppleSilicon.zip |
| Mac Intel | macOS-Intel.zip |

Mac 解压后把 App 拖入“应用程序”，退出旧版，从新位置打开，右上角应显示 v0.1.4。选择微信，点“启用微信转发入口”，再按界面步骤操作。旧版不会因下载新 ZIP 自动替换。

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
