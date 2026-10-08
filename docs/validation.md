# 验证记录

## macOS 与分发包验证（2026-10-08）

本次本机环境：macOS Apple Silicon、Python 3.14.6、PyInstaller 6.22.3。CI 声明 Python 3.12 的 Windows x64、Mac arm64 与 Mac Intel 三平台构建；本机验证不能替代尚未执行的 Windows／Intel CI。

- `python run_tests.py`：124 项，123 通过、1 项 Windows batch 专用测试跳过，0 失败。
- `node tests/ui_smoke.cjs`：通过；包含 Mac 微信切换到导入模式、禁止安装 Windows 组件、缺少语音引擎时禁用转写。
- `start.command --check`：通过，支持源码启动。
- `python scripts/build_release.py --version dev`：实际生成 Apple Silicon `.app` 和 ZIP。
- 打包后的程序通过独立临时目录测试：`--check`、辅助进程入口拒绝未知命令、HTTP 页面资源、平台配置、包含中文和空格路径的合成聊天、关系分析、HTML 报告与正常退出。
- `codesign --verify --deep --strict`：本地 ad-hoc 签名校验通过。未进行 Apple Developer ID 签名、公证或 Windows 签名。
- 新增源码测试覆盖数据目录分离、Mac 文件选择成功／取消／失败、Finder 打开命令、冻结程序辅助进程分派、Mac 前后端微信能力限制。文件选择对话框与 Finder 使用模拟命令，未计为实际 GUI 点击验证。
- 既有路径逃逸测试揭示 Windows 盘符路径在 Mac 上被当作相对文件名，已在归档路径校验中统一拒绝。

仍未验证：真实云端 AI、真实 QQ／微信客户端直读、新语音识别、旧版 macOS、Intel Mac、Windows 原生安装包。GUI 外观沿用原界面，未进行新的浏览器视觉验收。

## 原 Windows 源码验证记录

验证日期：2026-10-08。运行环境：Windows x64、Python 3.12；源码目录没有附带语音模型、运行包或微信读取组件。独立虚拟环境只加载声明的测试依赖 Pillow 12.3.0。

- `python run_tests.py`：115 项通过，0 失败。
- `python app.py --check`：程序导入、前端资源和本机 HTTP 绑定检查通过。
- 启动回归覆盖实际 `start.cmd --check`、实际 `app.py --no-browser`、加载页面及通过接口关闭测试服务。
- 浏览器回归覆盖快速非零退出后的回退、成功交接后避免重复打开、浏览器阻塞时本地服务仍可接收请求；浏览器打开部分使用模拟进程。
- `node tests/ui_smoke.cjs`：真实前端脚本的导航、身份、四类关系、全量请求预览、心理框架、综合规则、兼容地址、密钥与确认失效检查通过。
- 合成数据覆盖完整分批与有界综合、取消、失败回退、引用和框架 ID 校验、解释标签降级、分享 JSON 与 HTML 字段过滤。
- 源码清单与常见密钥格式扫描通过；只保留程序合成的聊天示例，真实聊天、报告、历史个人验证文件、环境与模型均未提交。

这些检查验证程序流程和约束，不验证模型解释的心理学有效性。真实云端 API、真实微信数据库读取和浏览器视觉效果未纳入本次验证。用户端“启动后无反应”的具体根因尚未复现，本次修复覆盖已在模拟中复现的浏览器启动缺陷。

复现完整 suite：安装 `requirements-dev.txt` 后运行 `python run_tests.py`。Node 交互检查是可选开发检查，应用本身不需要 Node。
