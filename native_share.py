"""Manage only this application's share extension, never the WeChat client."""
from pathlib import Path
import subprocess
import sys

IDENTIFIER = 'com.chatarchivetool.desktop.WeChatShare'
MAC_ROUTE = 'Mac 微信已改用原生聊天 ZIP 导出，不再进行密码初始化。请在微信多选消息，合并转发到“导出聊天 ZIP · ChatArchiveTool”，再导入保存的 ZIP。'


def app_bundle():
    if sys.platform != 'darwin' or not getattr(sys, 'frozen', False): return None
    app = Path(sys.executable).resolve().parents[2]
    return app if app.suffix == '.app' else None


def version():
    try: return (Path(__file__).resolve().parent / 'VERSION').read_text(encoding='ascii').strip()
    except OSError: return 'dev'


def share_status():
    app = app_bundle()
    return {'appVersion': version(), 'wechatNative': sys.platform == 'darwin',
            'wechatShareBundled': bool(app and (app / 'Contents/PlugIns/WeChatShare.appex').is_dir())}


def enable_share():
    app = app_bundle()
    extension = app / 'Contents/PlugIns/WeChatShare.appex' if app else None
    if not extension or not extension.is_dir():
        raise ValueError('请下载新版 Mac 桌面包，移到“应用程序”再打开；源码运行不包含微信转发入口。已有 ZIP 可直接导入。')
    if '/AppTranslocation/' in str(app):
        raise ValueError('请先退出本工具，把解压后的 ChatArchiveTool.app 拖入“应用程序”，从那里打开，再启用微信转发入口。')
    try:
        subprocess.run(['/usr/bin/pluginkit', '-a', str(extension)], check=True, capture_output=True, timeout=15)
        subprocess.run(['/usr/bin/pluginkit', '-e', 'use', '-i', IDENTIFIER], check=True, capture_output=True, timeout=15)
        result = subprocess.run(['/usr/bin/pluginkit', '-m', '-i', IDENTIFIER], check=True, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ValueError('未能启用分享入口。请确认新版 App 已放在“应用程序”，然后到“系统设置 → 通用 → 登录项与扩展 → 共享”开启 ChatArchiveTool，再重新打开微信的转发菜单。') from None
    if not any(line.lstrip().startswith('+') and IDENTIFIER in line for line in result.stdout.splitlines()):
        raise ValueError('转发入口尚未启用。请打开“系统设置 → 通用 → 登录项与扩展 → 共享”，开启 ChatArchiveTool，然后在微信重新打开转发菜单。')
    return '转发入口已启用。回到微信，多选消息 → 合并转发到其他应用 → 导出聊天 ZIP · ChatArchiveTool。'
