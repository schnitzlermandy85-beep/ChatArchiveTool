# 上游与第三方组件

- QQChatExporter：https://github.com/shuakami/qq-chat-exporter 。通过本机API使用，不内置其登录框架。
- wechat-chat-export：https://github.com/zhuzhangxue/wechat-chat-export 。固定提交 `5b56e51cd9368bc7e4c563761057b561501809d9`；原始代码位于 `vendor/wechat_export`，Apache-2.0许可证随代码保留。源文件未经修改；ChatArchive适配层独立实现。
- wechatauto-replica：https://github.com/fanyuantaier/wechatauto-replica 。安装器下载固定提交 `04ef8cbde3862cff90b5f6b42c9ebfcea44ef48d`；许可证随运行组件解包保存。
- rust-silk：https://github.com/Wangnov/rust-silk 。下载v0.1.3 Windows x64解码器并核对上游固定SHA-256；其发布文件与授权条款请见上游仓库。
- faster-whisper及微信依赖的Python软件包按各自许可证使用，wheel中的dist-info/许可证随组件保留；依赖来源为PyPI，各文件按PyPI提供的SHA-256验证。

工具目录不附带QQ或微信聊天数据、登录令牌、解密密钥。导出内容只存放在用户指定的本地目录。
