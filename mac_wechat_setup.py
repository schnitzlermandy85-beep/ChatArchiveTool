"""Explicit graphical setup; never called automatically on startup/export.

The user quits WeChat manually before signing and logs in manually afterwards.
Only codesign and the small read-only native scanner request admin privileges.
"""
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile

from core import ROOT
from platform_support import data_root
from mac_wechat_export import config_path, private_json, layout_for, validate_keys, load_connection, check_stop


def scanner_path():
    return ROOT / ('native/wechat_keys' if getattr(sys, 'frozen', False) else 'build/native/wechat_keys')


def app_path():
    for path in (Path('/Applications/WeChat.app'), Path.home() / 'Applications/WeChat.app'):
        if path.is_dir() and not path.is_symlink():
            return path
    raise ValueError('没有找到电脑微信，请将 WeChat.app 安装在“应用程序”中')


def admin(argv, timeout=180):
    # Shell and AppleScript quoting are separate. No raw user text in code.
    command = shlex.join([str(x) for x in argv])
    script = 'do shell script ' + json.dumps(command, ensure_ascii=False) + ' with administrator privileges'
    try:
        result = subprocess.run(['/usr/bin/osascript', '-e', script], capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ValueError('系统授权或读取超时，请关闭未完成的授权窗口后重试。没有退出微信') from None
    if result.returncode:
        # Backend output may contain key material; never put it in app logs.
        if b'-128' in result.stderr:
            raise ValueError('已取消系统授权，可以稍后重试')
        raise ValueError('系统授权操作未完成。请检查微信是否已按提示关闭或重新登录；若读取仍被系统拒绝，请停止重试。详细步骤见“帮助 → 连接微信”')
    return result.stdout


def running_pid():
    result = subprocess.run(['/usr/bin/pgrep', '-x', '-u', str(os.getuid()), 'WeChat'], capture_output=True, timeout=5)
    pids = result.stdout.split()
    if len(pids) > 1:
        raise ValueError('检测到多个微信进程，请只保留需要导出的微信账号')
    return int(pids[0]) if pids else None


def prepared(app):
    from wechat_preflight import signature_info
    binary = app / 'Contents/MacOS/WeChat'
    info = signature_info(str(app), binary.stat().st_mtime_ns)
    return info is not None and not info['hardened']


def capability():
    installed = scanner_path().is_file()
    if installed:
        try:
            import sqlcipher3, Crypto.Cipher.AES, av
        except ImportError:
            installed = False
    configured = config_path().is_file()
    return {'wechatMacSupported': True, 'wechatInstalled': installed,
            'wechatConfigured': configured, 'wechatReady': installed and configured,
            'wechatPreflight': {}, 'wechatConnection': {
                'code': 'complete' if configured else 'setup', 'active': False,
                'title': '已保存本机连接，可导出或重新检查' if configured else '首次使用：准备读取 → 登录微信 → 连接并检查',
                'detail': '导出时重新校验全部消息分片。微信升级或切换账号后，请重新准备和连接。' if configured else
                '准备读取会修改微信程序签名，需要先手动退出微信，随后重新打开并登录。授权使用 macOS 弹窗，无需终端。',
                'topic': 'wechat'}}


def prepare(accepted=False, log=print, stop=None):
    if sys.platform != 'darwin':
        raise ValueError('此准备步骤仅用于 Mac')
    if accepted is not True:
        raise ValueError('请先阅读并勾选“了解微信签名修改与重新登录”，再准备读取')
    if not scanner_path().is_file():
        raise ValueError('当前安装包缺少 Mac 读取组件，请下载完整 Mac 安装包')
    app = app_path()
    if running_pid():
        raise ValueError('请先在微信菜单选择“退出微信”（⌘Q），再点击准备读取。关闭窗口不等于退出；本工具不会替你退出')
    check_stop(stop)
    if prepared(app):
        log('微信读取条件已准备好，请打开微信并登录，再点击连接并检查')
        return
    with (app / 'Contents/Info.plist').open('rb') as stream:
        version = str(plistlib.load(stream).get('CFBundleVersion', 'unknown'))
    backup_root = data_root(ROOT) / 'components/wechat-mac/backups'
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix='before-sign-', dir=backup_root)) / 'WeChat.app'
    log('正在备份原微信程序签名副本（不复制聊天数据）…')
    shutil.copytree(app, backup, symlinks=True)
    private_json(backup.parent / 'backup.json', {'app': str(app), 'version': version})
    check_stop(stop)
    if running_pid():
        raise ValueError('微信又被打开了，请手动退出后重新准备')
    log('请在 macOS 授权弹窗中确认。修改微信签名后，截图、录屏等权限可能需要重新授权')
    try:
        admin(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', app])
        from wechat_preflight import signature_info
        signature_info.cache_clear()
        if not prepared(app):
            raise ValueError('微信签名检查未通过，已停止连接，请使用备份恢复程序')
    except Exception:
        log('准备未完成。已保留原微信程序备份；如微信无法打开，可点击“恢复微信程序”')
        raise
    config_path().unlink(missing_ok=True)
    log('准备完成。请点击打开微信并重新登录，打开目标聊天后，再点击连接并检查')


def restore(accepted=False, log=print):
    if sys.platform != 'darwin' or accepted is not True:
        raise ValueError('请先在 Mac 界面勾选确认，再恢复微信程序')
    if running_pid():
        raise ValueError('请先手动退出微信（⌘Q），再恢复程序')
    app = app_path()
    root = data_root(ROOT) / 'components/wechat-mac/backups'
    backups = sorted(root.glob('before-sign-*/WeChat.app'), key=lambda p: p.parent.stat().st_mtime, reverse=True)
    if not backups:
        raise ValueError('没有本工具创建的微信程序备份，可从微信官网下载并覆盖安装程序；不要删除聊天数据目录')
    source = backups[0]
    with (app / 'Contents/Info.plist').open('rb') as stream:
        version = str(plistlib.load(stream).get('CFBundleVersion', 'unknown'))
    info = json.loads((source.parent / 'backup.json').read_text())
    if info.get('version') != version or info.get('app') != str(app):
        raise ValueError('微信已升级或移动，请从微信官网下载当前版本覆盖安装，避免恢复旧版程序')
    admin(['/usr/bin/ditto', source, app])
    verified = subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], capture_output=True)
    if verified.returncode:
        raise ValueError('恢复后的程序校验未通过，请从微信官网下载并覆盖安装')
    config_path().unlink(missing_ok=True)
    from wechat_preflight import signature_info
    signature_info.cache_clear()
    log('微信程序已恢复，聊天数据未修改。可以重新打开微信')


def connect(db_dir='', log=print, stop=None):
    if sys.platform != 'darwin':
        raise ValueError('此连接步骤仅用于 Mac')
    config_path().unlink(missing_ok=True)
    layout = layout_for(db_dir)
    if not prepared(app_path()):
        raise ValueError('请先准备读取，再重新打开微信并登录。微信升级后需要重新准备')
    pid = running_pid()
    if not pid:
        raise ValueError('请先打开微信并登录，打开要导出的聊天，再点击连接并检查')
    check_stop(stop)
    log('请在系统弹窗授权读取。保持微信登录；本次扫描不会暂停或退出微信')
    output = admin([scanner_path(), str(pid), str(os.getuid())])
    check_stop(stop)
    try:
        candidates = json.loads(output)
        if not isinstance(candidates, list) or len(candidates) > 1024:
            raise ValueError()
        import re
        keys = {}
        for value in candidates:
            if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{96}', value):
                raise ValueError()
            salt, key = value[64:], value[:64]
            if salt in keys and keys[salt] != key:
                raise ValueError()
            keys[salt] = key
        if not keys:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('未获取唯一有效的读取密钥。请确认微信已登录、目标聊天已打开；无需重复输入密码或关闭系统保护') from None
    log('正在验证全部消息分片，不读取聊天正文到日志…')
    validate_keys(layout, keys, stop)
    check_stop(stop)
    private_json(config_path(), {'dbDir': str(Path(layout.account_dir) / 'db_storage'), 'keys': keys})
    log('微信数据库检查通过，可以填写准确好友备注或群名并导出文字、图片、视频')


def check(log=print, stop=None):
    layout, keys = load_connection()
    try:
        validate_keys(layout, keys, stop)
    except ValueError:
        config_path().unlink(missing_ok=True)
        raise
    log('已验证所有本机消息分片，媒体可用情况将在导出结果中列出')


def self_check():
    """Exercise bundled crypto/codec dependencies on synthetic data only."""
    import io
    import hashlib
    import struct
    import sqlite3
    from sqlcipher3 import dbapi2
    from Crypto.Cipher import AES
    from PIL import Image
    import av
    import pysilk
    from mac_wechat_export import decrypt_database
    from vendor.wechat_mac.image_dat import V1_SIG, V1_KEY, decode_to_displayable
    subprocess.run([str(scanner_path()), '--self-test'], check=True, capture_output=True)
    with tempfile.TemporaryDirectory(prefix='chatarchive-selfcheck-') as tmp:
        source = Path(tmp) / 'synthetic.db'
        key = hashlib.sha256(b'public synthetic check only').hexdigest()
        db = dbapi2.connect(str(source))
        try:
            db.execute('PRAGMA key = "x\'' + key + '\'"')
            db.execute('CREATE TABLE fixture(text)')
            db.execute("INSERT INTO fixture VALUES('合成文字')")
            db.commit()
        finally:
            db.close()
        with source.open('rb') as stream:
            salt = stream.read(16).hex()
        output = decrypt_database(source, {salt: key}, tmp)
        with sqlite3.connect(output) as clear:
            assert clear.execute('SELECT text FROM fixture').fetchone()[0] == '合成文字'
        buffer = io.BytesIO()
        Image.new('RGB', (16, 16), 'blue').save(buffer, format='PNG')
        png = buffer.getvalue(); pad = 16 - len(png) % 16
        encrypted = V1_SIG + struct.pack('<II', len(png), 0) + b'\0' + AES.new(V1_KEY, AES.MODE_ECB).encrypt(png + bytes([pad]) * pad)
        assert decode_to_displayable(encrypted)[0] == png
        # HEVC decoder availability (image format used by newer WeChat).
        assert av.Codec('hevc', 'r').is_decoder
