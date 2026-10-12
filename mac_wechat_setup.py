"""Explicit graphical setup; never called automatically on startup/export.

The user quits WeChat manually before signing and logs in manually afterwards.
Only codesign and the small read-only native scanner request admin privileges.
"""
import json
import os
from pathlib import Path
import plistlib
import re
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


class AdminOperationError(ValueError):
    """Only allowlisted diagnostics reach the UI; raw output can contain keys."""


def admin_failure(operation, code, detail=b''):
    text = detail.decode('utf-8', errors='replace').lower()
    stage = {'sign': '准备读取', 'scan': '连接并检查', 'restore': '恢复微信', 'diagnose': '授权诊断'}.get(operation, '系统授权')
    prefix = f'{stage}未完成（错误码 {code}）：'
    if code == -128:
        return prefix + '已取消系统授权，可以稍后重试。'
    if code in (-600, -609, -10004, -1743, -25211):
        return prefix + '系统未允许授权交互。请先把 App 放入“应用程序”，退出下载目录中的旧副本，再从应用程序重新打开；不要重复修改完全磁盘访问。'
    if operation == 'scan':
        reasons = {2: '微信进程已变化或路径不匹配，请确认正在运行的是“应用程序”中的微信。',
                   3: '可以读取微信进程，但未找到数据库密钥。请先登录并打开目标聊天，再连接。',
                   4: '系统拒绝读取微信进程。完全磁盘访问不能解除进程保护；请确认准备读取成功且已重新登录。不要关闭 SIP。',
                   5: '读取组件无法分配内存，请关闭不需要的程序后重试。'}
        if code in reasons:
            return prefix + reasons[code]
    if 'operation not permitted' in text or 'permission denied' in text:
        if operation in ('sign', 'restore'):
            component = '（微信内置扩展）' if 'wechatappex.app' in text else ''
            return prefix + f'系统拒绝修改微信程序{component}。请检查“系统设置 → 隐私与安全性 → App 管理”中的 ChatArchiveTool。若已经启用且退出重开后仍失败，请停止重试并反馈此错误码；管理员密码正确不代表程序修改权限已生效。'
        return prefix + '系统拒绝此步骤的访问，请反馈错误码和步骤名称；不要反复输入密码。'
    if 'resource fork' in text or 'finder information' in text:
        return prefix + '微信程序包含签名不接受的文件属性，请从微信官网下载程序覆盖安装后再准备；不要删除聊天数据。'
    if 'no such file' in text or 'not found' in text:
        return prefix + '找不到程序或读取组件。请完整解压新版，并把 App 放入“应用程序”。'
    if 'errsecinternalcomponent' in text or 'code signing' in text:
        return prefix + '系统签名检查失败，原程序备份已保留。请停止重复授权，使用恢复入口或反馈本错误码。'
    return prefix + '请在处理记录确认失败步骤，并反馈此错误码；不需要发送密码、密钥或聊天内容。'


def admin(argv, timeout=180, operation='diagnose'):
    # Keep the child exit status separate from AppleScript authorization errors.
    # Neither diagnostic exceptions nor logs ever include arbitrary child output.
    if operation in ('sign', 'restore'):
        raise AdminOperationError('已停用后台修改微信，请使用准备副本和 Finder 安装流程。')
    command = shlex.join([str(x) for x in argv])
    marker = 'CHATARCHIVE_ADMIN_STATUS='
    wrapped = command + ' 2>&1; result=$?; printf "\\n' + marker + '%s\\n" "$result"; exit 0'
    script = 'do shell script ' + json.dumps(wrapped, ensure_ascii=False) + ' with administrator privileges'
    try:
        if getattr(sys, 'frozen', False) and operation in ('sign', 'diagnose'):
            launcher = Path(sys.executable).with_name('ChatArchiveTool')
            if operation != 'diagnose' or list(map(str, argv)) != ['/usr/bin/id', '-u']:
                raise AdminOperationError('不支持的微信授权操作，已停止。')
            native_args = ['diagnose']
            result = subprocess.run([str(launcher), '--wechat-admin', *native_args], capture_output=True, timeout=timeout)
        else:
            result = subprocess.run(['/usr/bin/osascript', '-e', script], capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AdminOperationError('系统授权或读取超时。请关闭未完成的授权窗口后重试；工具没有退出微信。') from None
    if result.returncode:
        match = re.search(rb'\((-?\d+)\)\s*$', result.stderr.strip())
        code = int(match.group(1)) if match else result.returncode
        raise AdminOperationError(admin_failure(operation, code, result.stderr))
    output, separator, status = result.stdout.rpartition(marker.encode())
    if not separator or not re.fullmatch(rb'\d+\s*', status):
        raise AdminOperationError('系统授权返回格式异常，已停止操作。请完整解压并使用新版 App。')
    code = int(status)
    if code:
        raise AdminOperationError(admin_failure(operation, code, output))
    return output.rstrip(b'\r\n')


def diagnose(log=print):
    log('授权诊断：仅验证管理员授权，不修改微信、不读取聊天或密钥。若系统请求密码，请在 macOS 弹窗输入电脑管理员密码；系统复用已有授权时可能不再弹窗。')
    if admin(['/usr/bin/id', '-u'], operation='diagnose').strip() != b'0':
        raise AdminOperationError('系统未授予管理员执行权限，请确认使用的是电脑管理员账号。')
    log('系统授权诊断通过。若准备读取仍失败，请按它显示的具体错误码处理，而不是重复重启。')


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
    import mac_wechat_install as installer
    waiting = (installer.root() / 'pending-install.json').exists()
    configured = config_path().is_file() and not waiting
    return {'wechatMacSupported': True, 'wechatInstalled': installed,
            'wechatConfigured': configured, 'wechatReady': installed and configured,
            'wechatPreflight': {}, 'wechatConnection': {
                'code': 'installation_required' if waiting else 'complete' if configured else 'setup', 'active': False,
                'title': '副本已准备，等待你在 Finder 确认安装' if waiting else '已保存本机连接，可导出或重新检查' if configured else '首次使用：准备副本 → 安装并检查 → 登录微信',
                'detail': '打开安装文件夹，把 WeChat.app 拖到“拖到这里安装”，选择替换并等待完成，然后点击“我已替换，检查安装”。不要直接运行副本。' if waiting else '导出时重新校验全部消息分片。微信升级或切换账号后，请重新准备和连接。' if configured else
                '准备时只生成本地副本；由你在 Finder 确认替换。检查通过后再打开微信登录，全程无需终端命令。',
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
        raise ValueError('请先在微信菜单选择“退出微信”（⌘Q），再准备读取；本工具不会替你退出')
    check_stop(stop)
    import mac_wechat_install as installer
    if prepared(app):
        installer.verify(app)
        if (installer.root() / 'pending-install.json').exists():
            confirm_install(log)
        else:
            log('微信读取条件已准备好，请打开微信并登录，再点击连接并检查')
        return
    installer.stage(app, log=log, stop=stop)


def confirm_install(log=print):
    if running_pid():
        raise ValueError('请先手动退出微信，再检查安装结果')
    import mac_wechat_install as installer
    kind = installer.confirm()
    config_path().unlink(missing_ok=True)
    from wechat_preflight import signature_info
    signature_info.cache_clear()
    log('微信原程序已恢复，可以重新打开微信。' if kind == 'restore' else
        '安装检查通过。请打开“应用程序”里的微信并登录，再点击连接并检查。')


def restore(accepted=False, log=print):
    if sys.platform != 'darwin' or accepted is not True:
        raise ValueError('请先在 Mac 界面勾选确认，再恢复微信程序')
    if running_pid():
        raise ValueError('请先手动退出微信（⌘Q），再恢复程序')
    import mac_wechat_install as installer
    installer.stage(app_path(), kind='restore', log=log)


def connect(db_dir='', log=print, stop=None):
    if sys.platform != 'darwin':
        raise ValueError('此连接步骤仅用于 Mac')
    config_path().unlink(missing_ok=True)
    import mac_wechat_install as installer
    if installer.pending():
        raise ValueError('安装尚未确认，请先在 Finder 完成替换，再点击“我已替换，检查安装”')
    layout = layout_for(db_dir)
    if not prepared(app_path()):
        raise ValueError('请先准备读取，再重新打开微信并登录。微信升级后需要重新准备')
    pid = running_pid()
    if not pid:
        raise ValueError('请先打开微信并登录，打开要导出的聊天，再点击连接并检查')
    check_stop(stop)
    log('请在系统弹窗授权读取。保持微信登录；本次扫描不会暂停或退出微信')
    output = admin([scanner_path(), str(pid), str(os.getuid())], operation='scan')
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
