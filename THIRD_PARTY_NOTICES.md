# 上游与第三方组件

- QQChatExporter：https://github.com/shuakami/qq-chat-exporter 。通过本机API使用，不内置其登录框架。
- wechat-chat-export：https://github.com/zhuzhangxue/wechat-chat-export 。固定提交 `5b56e51cd9368bc7e4c563761057b561501809d9`；原始代码位于 `vendor/wechat_export`，Apache-2.0许可证随代码保留。源文件未经修改；ChatArchive适配层独立实现。
- wechatauto-replica：https://github.com/fanyuantaier/wechatauto-replica 。安装器下载固定提交 `04ef8cbde3862cff90b5f6b42c9ebfcea44ef48d`；许可证随运行组件解包保存。
- rust-silk：https://github.com/Wangnov/rust-silk 。下载v0.1.3 Windows x64解码器并核对上游固定SHA-256；其发布文件与授权条款请见上游仓库。
- faster-whisper及微信依赖的Python软件包按各自许可证使用，wheel中的dist-info/许可证随组件保留；依赖来源为PyPI，各文件按PyPI提供的SHA-256验证。

工具目录不附带QQ或微信聊天数据、登录令牌、解密密钥。导出内容只存放在用户指定的本地目录。

桌面分发包另外包含 Python 运行环境、PyInstaller bootloader、packaging、certifi CA 证书及 Pillow。构建时从安装的发行包复制许可至下载包中的 `licenses/`；PyInstaller 的分发例外见其 COPYING.txt，certifi 的证书与代码条款见其 LICENSE。可选语音引擎不包含在桌面包中。

## Mac 导出适配

- QQ 按需安装 shuakami/qq-chat-exporter 的 v6.3.2 官方发行包；不随本应用捆绑。Mac 安装与启动遵循其 [官方指南](https://shuakami.github.io/qq-chat-exporter/docs/macos-deploy.html)。组件保留上游归档中的通知与许可。
- 微信按需安装 [with-yang/wxvault](https://github.com/with-yang/wxvault) v0.1.0，参考提交 `aacf0de666d06e23718338fc2f81a1f71873a997` 的 CLI、缓存路径和数据库结构。上游适用 Apache-2.0，原 LICENSE 和 NOTICE 保留于 `vendor/licenses/wxvault/` 并复制到安装目录。`mac_wechat.py` 是本项目适配，未修改上游二进制。
- zstandard 用于解压微信消息正文，随桌面包保留其许可证。固定发行包下载地址与 SHA-256 见 `desktop_exporters.py`。

- `vendor/wechat_live/hook.py` 基于 wxvault v0.1.0 的 `assets/hook.py`（Apache-2.0；许可与版权通知见 `vendor/licenses/wxvault/`），改为连接已运行进程，增加有界内存扫描、AES 调用读取、取消和 finally 解除连接。不再调用上游会退出微信的 `init`。连接思路同时参考 [jackwener/wx-cli-again](https://github.com/jackwener/wx-cli-again) 的 macOS 实现；不包含其 Rust 二进制。
