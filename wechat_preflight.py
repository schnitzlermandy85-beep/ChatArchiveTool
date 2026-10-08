"""Read-only checks for the documented macOS live-process access boundary.

Apple: com.apple.security.cs.debugger cannot access a SIP-protected target
without get-task-allow. FDA and sudo do not add that target entitlement.
No process attach, account data, signing changes or password prompts here.
"""
import functools
import plistlib
from pathlib import Path
import re
import subprocess
import sys


@functools.lru_cache(maxsize=1)
def sip_enabled():
    try:
        result = subprocess.run(['/usr/bin/csrutil', 'status'], capture_output=True, timeout=5)
        text = result.stdout.decode(errors='replace').lower()
        if result.returncode == 0 and 'disabled' in text:
            return False
        if result.returncode == 0 and 'enabled' in text:
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


@functools.lru_cache(maxsize=4)
def signature_info(path, modified):
    try:
        details = subprocess.run(['/usr/bin/codesign', '-dv', path], capture_output=True, timeout=5)
        entitlements = subprocess.run(['/usr/bin/codesign', '-d', '--entitlements', ':-', path], capture_output=True, timeout=5)
        if details.returncode or entitlements.returncode:
            return None
        flags = re.search(rb'flags=0x([0-9a-fA-F]+)', details.stderr)
        if flags is None:
            return None
        raw = entitlements.stdout.strip()
        rights = plistlib.loads(raw) if raw else {}
        return {'hardened': bool(int(flags[1], 16) & 0x10000),
                'debuggable': rights.get('com.apple.security.get-task-allow') is True}
    except (OSError, ValueError, plistlib.InvalidFileException, subprocess.TimeoutExpired):
        return None


def inspect_wechat(app=None):
    if sys.platform != 'darwin':
        return {}
    if app is None:
        candidates = [Path('/Applications/WeChat.app'), Path.home() / 'Applications/WeChat.app']
        app = next((p for p in candidates if p.is_dir()), None)
    if app is None:
        return {'code': 'app_missing', 'blocked': True, 'title': '没有找到电脑微信',
                'detail': '请先安装电脑微信。已有导出文件可直接导入。', 'topic': 'wechat'}
    app = Path(app)
    binary = app / 'Contents/MacOS/WeChat'
    try:
        info = signature_info(str(app), binary.stat().st_mtime_ns)
    except OSError:
        info = None
    if info and info['hardened'] and not info['debuggable'] and sip_enabled() is not False:
        return {'code': 'protected_client', 'blocked': True,
                'title': '当前原版 Mac 微信不支持此直读方式',
                'detail': '系统保护阻止读取已登录微信；输入管理员密码、开启完全磁盘访问也不能解除这项限制。不会再弹出密码窗口。可在 Windows 使用 wechat-chat-export 导出，再把整个结果文件夹复制到 Mac 导入。',
                'topic': 'wechat'}
    if info is None:
        return {'code': 'unverified_client', 'blocked': True,
                'title': '暂时无法确认微信是否允许读取',
                'detail': '请确认微信安装完整。暂不启动读取或要求密码；可先导入已有导出文件。', 'topic': 'wechat'}
    return {'code': 'eligible', 'blocked': False, 'title': '可以尝试实验性读取',
            'detail': '签名检查通过仅表示可尝试，尚不代表聊天数据已成功读取。', 'topic': 'wechat'}
