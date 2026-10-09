"""Pinned upstream export tools, installed on demand outside the application bundle."""
from __future__ import annotations
import hashlib
import json
import socket
import uuid
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import zipfile

from core import ROOT, Cancelled, child_command, write_json
from platform_support import data_root
from wechat_preflight import inspect_wechat

QCE_VERSION = 'v6.3.2'
WXVAULT_VERSION = 'v0.1.0'
PACKAGES = {
    'qce-mac': ('https://github.com/shuakami/qq-chat-exporter/releases/download/v6.3.2/NapCat-QCE-macOS-arm64-v6.3.2.tar.gz', 'a241a2a694edb317fa494e9f9a0bda79284937be97afa7bfea269741b7f15a9a'),
    'qce-win': ('https://github.com/shuakami/qq-chat-exporter/releases/download/v6.3.2/NapCat-QCE-Windows-x64-v6.3.2.zip', '3fc093ba2332b97ac17e16160d5baa6ffe0a8def6c394d515a94777fe0ca492c'),
    'wxvault': ('https://github.com/with-yang/wxvault/releases/download/v0.1.0/wxvault-macos-arm64', '3191a11314e9abb11f64d4abc0bb0ad9d68a3688d20b895ad8452b69fe2aca3f'),
}
MAX_DOWNLOAD = 256 * 1024 * 1024


def mac_arm():
    return sys.platform == 'darwin' and platform.machine().lower() == 'arm64'


def tools_root():
    return data_root(ROOT) / 'components'


def qce_supported():
    return mac_arm() or (sys.platform == 'win32' and platform.machine().lower() in ('amd64', 'x86_64'))


def qce_launcher():
    root = tools_root() / ('qce-' + QCE_VERSION)
    name = 'launcher-user.bat' if sys.platform == 'win32' else 'launcher-user.sh'
    # The upstream archive contains a single platform directory.
    matches = list(root.glob('*/' + name)) + list(root.glob(name))
    return matches[0] if len(matches) == 1 else None


def wxvault_binary():
    return tools_root() / ('wxvault-' + WXVAULT_VERSION) / 'wxvault'


def wxvault_configured():
    home = Path.home() / '.wxvault'
    return (home / 'config.json').is_file() and (home / 'all_keys.json').is_file()


def status():
    result = {'desktopOS': sys.platform, 'qceInstallSupported': qce_supported(),
            'qceInstalled': qce_launcher() is not None,
            'wechatMac': sys.platform == 'darwin', 'wechatMacSupported': False,
            'wechatInstalled': False, 'wechatConfigured': False,
            'wechatConnection': {}, 'wechatPreflight': {}}
    if sys.platform == 'darwin':
        from mac_wechat_setup import capability
        result.update(capability())
    return result


def check_stop(stop):
    if stop and stop.is_set():
        raise Cancelled('已停止导出组件任务')


def download_verified(url, digest, target, log=print, stop=None):
    log('正在下载已固定版本的导出组件…')
    request = urllib.request.Request(url, headers={'User-Agent': 'ChatArchiveTool'})
    sha = hashlib.sha256()
    size = 0
    last_progress = time.monotonic()
    with urllib.request.urlopen(request, timeout=30) as response, Path(target).open('wb') as out:
        while True:
            check_stop(stop)
            block = response.read(256 * 1024)
            if not block:
                break
            size += len(block)
            if size > MAX_DOWNLOAD:
                raise ValueError('组件下载超出大小限制')
            out.write(block)
            sha.update(block)
            if time.monotonic() - last_progress >= 5:
                log(f'已下载导出组件 {size / 1024**2:.1f} MB…')
                last_progress = time.monotonic()
    if sha.hexdigest() != digest:
        raise ValueError('组件 SHA-256 校验失败，未安装；请稍后重试')
    log('组件下载及 SHA-256 校验完成')


def extract_archive(archive, dest):
    """No absolute names, traversal, links or device nodes from release archives."""
    dest = Path(dest).resolve()
    def output(name):
        from core import safe_child
        return safe_child(dest, name)
    total = 0
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                total += item.file_size
                if total > 2 * 1024**3 or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('组件归档包含不支持的链接或过大文件')
                path = output(item.filename)
                if item.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(item) as src, path.open('wb') as dst:
                        shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(archive) as tar:
            for item in tar:
                total += item.size
                if total > 2 * 1024**3 or not (item.isdir() or item.isfile()):
                    raise ValueError('组件归档包含不支持的链接或特殊文件')
                path = output(item.name)
                if item.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(item) as src, path.open('wb') as dst:
                        shutil.copyfileobj(src, dst)
                    path.chmod(0o755 if item.mode & 0o111 else 0o644)


def install_component(component, log=print, stop=None):
    if component == 'qce':
        if not qce_supported():
            raise ValueError('自动安装 QQ 组件支持 Apple 芯片 Mac 和 Windows x64；Intel Mac 可连接自行部署的本机 QCE 服务')
        key = 'qce-mac' if mac_arm() else 'qce-win'
        destination = tools_root() / ('qce-' + QCE_VERSION)
        if qce_launcher():
            log('QQ 导出组件已安装；点击“启动 QQ 导出服务”')
            return
    elif component == 'wxvault' and mac_arm():
        key = 'wxvault'
        destination = wxvault_binary().parent
        if wxvault_binary().is_file():
            log('微信 Mac 导出组件已安装；点击“连接已登录微信”')
            return
    else:
        raise ValueError('该系统暂不支持这个导出组件')
    tools_root().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.install-', dir=tools_root()) as temp:
        temp = Path(temp)
        payload = temp / 'download'
        download_verified(*PACKAGES[key], payload, log, stop)
        staged = temp / 'component'
        staged.mkdir()
        if key == 'wxvault':
            shutil.copy2(payload, staged / 'wxvault')
            (staged / 'wxvault').chmod(0o755)
            for name in ('LICENSE', 'NOTICE'):
                shutil.copy2(ROOT / 'vendor/licenses/wxvault' / name, staged / name)
        else:
            extract_archive(payload, staged)
            filename = 'launcher-user.sh' if key == 'qce-mac' else 'launcher-user.bat'
            matches = list(staged.glob(filename)) + list(staged.glob('*/' + filename))
            if len(matches) != 1:
                raise ValueError('QQ 组件包结构不符合预期，未安装')
        check_stop(stop)
        if destination.exists():
            raise ValueError('已有不完整组件目录，请先移走该目录再重新安装：' + str(destination))
        staged.rename(destination)
    log('组件安装完成')


def open_terminal_script(name, commands):
    root = tools_root() / 'launchers'
    root.mkdir(parents=True, exist_ok=True)
    script = root / (name + '.command')
    script.write_text('#!/bin/bash\numask 077\n' + commands + '\nstatus=$?\necho "进程已结束，退出码：$status"\nread -r -p "按回车关闭此窗口…"\nexit "$status"\n', encoding='utf-8')
    script.chmod(0o700)
    subprocess.run(['/usr/bin/open', '-a', 'Terminal', str(script)], check=True)


def start_qce():
    launcher = qce_launcher()
    if launcher is None:
        raise ValueError('请先安装 QQ 导出组件')
    if mac_arm():
        running = subprocess.run(['/usr/bin/pgrep', '-x', 'QQ'], capture_output=True, timeout=5)
        if running.returncode == 0:
            raise ValueError('QQ 组件已准备好。请先在 QQ 菜单中选择退出 QQ（或按 ⌘Q），再点击准备并连接。关闭窗口不等于退出；本工具不会替你退出 QQ。')
        # The upstream launcher checks for running desktop QQ; never kill it here.
        open_terminal_script('QQ-export', 'cd -- ' + shlex.quote(str(launcher.parent)) + '\n' +
            'echo "请先完全退出桌面 QQ，再在此窗口按提示扫码登录。使用期间保持此窗口运行。"\n' +
            '/bin/bash ' + shlex.quote(str(launcher)))
    elif sys.platform == 'win32':
        os.startfile(str(launcher))
    else:
        raise ValueError('该平台没有可启动的 QQ 导出组件')


CONNECTION_MESSAGES = {
    'terminal_closed': ('连接窗口已结束', '尚未完成连接，可以重新连接；无需退出微信。', 'terminal'),
    'already_running': ('已有微信读取窗口正在运行', '请先完成或关闭前一个连接终端，再重试。', 'terminal'),
    'cancelling': ('正在取消微信连接', '如终端正在等待密码，请在该终端按 Control+C。读取过程中会先解除连接，再结束。', 'terminal'),
    'checking': ('检查连接条件', '正在检查微信是否登录及本机记录是否可读。', 'wechat'),
    'password': ('请在终端完成一次授权', '输入 Mac 登录密码后按回车；不会显示字符。密码不会进入本工具。', 'terminal'),
    'attaching': ('正在连接当前微信', '保持微信登录。如果系统询问开发者工具权限，请允许终端。', 'wechat'),
    'open_chat': ('请打开要导出的聊天', '在微信里打开目标聊天，并往上翻几页历史消息；约一分钟后自动检查结果。', 'wechat'),
    'validating': ('正在验证读取结果', '验证在本机完成，请稍候。', 'wechat'),
    'complete': ('微信连接检查通过', '现在可以填写好友备注、昵称或 wxid 并导出。', 'wechat'),
    'disk_permission': ('终端还没有文件读取权限', '打开完全磁盘访问设置，允许终端，然后完全退出终端再重试。', 'permissions'),
    'developer_permission': ('macOS 拒绝读取微信进程', '原版微信可能受强化运行时保护；管理员密码和文件访问权限不能解除该保护。请查看读取条件，停止重复授权；可使用上游导出文件。', 'wechat'),
    'protected_client': ('原版微信受到系统保护', '此 Mac 不支持当前直读方案，已在请求密码前停止。请使用 wechat-chat-export 的 Windows 导出结果或已有兼容文件。', 'wechat'),
    'unverified_client': ('尚无法确认微信读取条件', '未启动读取或请求密码。请检查安装，或导入已有文件。', 'wechat'),
    'app_missing': ('没有找到电脑微信', '请检查电脑微信的安装位置，或导入已有文件。', 'wechat'),
    'tools_missing': ('缺少 Apple 命令行工具', '点击安装系统工具，在系统弹窗中完成安装后重试。无需安装完整 Xcode。', 'permissions'),
    'wechat_not_running': ('请先登录电脑微信', '打开原来的微信并登录，再回来连接。', 'wechat'),
    'multiple_processes': ('发现多个微信进程', '请先手动关闭多余的微信副本，仅保留日常使用的微信。', 'wechat'),
    'component_missing': ('微信组件尚未安装完整', '请先点击准备微信组件。', 'wechat'),
    'no_data': ('尚未找到本机聊天记录', '请登录电脑微信，打开要导出的聊天并等待同步。手机上的记录需要先迁移到电脑。', 'wechat'),
    'multiple_accounts': ('电脑上有多个微信数据目录', '在连接与来源设置中选择当前账号的 db_storage 文件夹，再连接。', 'wechat'),
    'invalid_account': ('微信数据目录不匹配', '请选择当前用户微信数据目录中的 db_storage 文件夹，或清空该设置后重试。', 'wechat'),
    'no_keys': ('未取得可验证的读取权限', '当前客户端可能不支持此读取方法，或目标记录尚未加载。可在微信中打开目标聊天后重试；仍失败请使用导入。不要反复输入密码或退出微信。', 'wechat'),
    'partial_keys': ('部分聊天尚不能读取', '保持登录，打开目标聊天并向上翻阅后重新连接；暂不能读取的记录不会被当作完整导出。', 'wechat'),
    'authorization_cancelled': ('系统授权未完成', '可以稍后重试。Mac 登录密码不是微信密码；不要把密码填入 API Key。', 'terminal'),
    'cancelled': ('已取消连接准备', '原微信没有被本工具主动退出。', 'wechat'),
    'timeout': ('连接准备超时', '请关闭本次连接终端，确认系统授权弹窗已处理后重试。', 'wechat'),
    'reader_failed': ('当前微信读取未成功', '请先检查终端的开发者工具权限；如果仍失败，请使用导入模式。', 'wechat'),
    'unexpected_error': ('连接准备未完成', '请检查权限与系统工具。此流程不会自动退出微信；可使用导入模式。', 'wechat'),
    'save_failed': ('无法保存本机连接配置', '请检查当前用户的数据目录访问权限和磁盘空间。', 'permissions'),
    'too_many_databases': ('本机账号数据过多', '请选择当前账号的数据目录再试。', 'wechat'),
    'terminal_pending': ('请在终端窗口继续', '终端已请求打开；如果没有看到窗口，点击显示终端。', 'terminal'),
}


def connection_status():
    root = tools_root() / 'connections/wechat'
    try:
        pointer = json.loads((root / 'current.json').read_text(encoding='utf-8'))
        identifier = pointer['id']
        if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
            return {}
        data = json.loads((root / identifier / 'status.json').read_text(encoding='utf-8'))
        phase, code = data['phase'], data['code']
        if code not in CONNECTION_MESSAGES or phase not in ('pending','checking','authorizing','attaching','reading','validating','complete','failed','cancelling'):
            return {}
        active = phase not in ('complete', 'failed')
        if active and isinstance(data.get('pid'), int) and data['pid'] > 0:
            try:
                os.kill(data['pid'], 0)  # Liveness only; never signals WeChat.
            except ProcessLookupError:
                phase, code, active = 'failed', 'terminal_closed', False
            except PermissionError:
                pass
        if active and phase != 'authorizing' and time.time() - float(data.get('at', 0)) > 180:
            (root / identifier / 'cancel').touch()
            phase, code, active = 'failed', 'timeout', False
        title, detail, topic = CONNECTION_MESSAGES[code]
        return {'phase': phase, 'code': code, 'title': title, 'detail': detail, 'topic': topic, 'active': active}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def initialize_wechat(db_dir=''):
    from native_share import MAC_ROUTE
    raise ValueError(MAC_ROUTE)


def mark_wechat_verified():
    root = tools_root() / 'connections/wechat'
    if not connection_status():
        return
    pointer = json.loads((root / 'current.json').read_text())
    write_json(root / pointer['id'] / 'status.json', {'phase': 'complete', 'code': 'complete', 'at': time.time()})


def cancel_wechat():
    root = tools_root() / 'connections/wechat'
    if not connection_status().get('active'):
        return
    pointer = json.loads((root / 'current.json').read_text())
    job = root / pointer['id']
    (job / 'cancel').touch()
    previous = json.loads((job / 'status.json').read_text())
    write_json(job / 'status.json', {**previous, 'phase': 'cancelling', 'code': 'cancelling', 'at': time.time()})


def local_port_open(address='127.0.0.1', port=40653):
    try:
        with socket.create_connection((address, port), timeout=.3):
            return True
    except OSError:
        return False


def diagnostics():
    info = status()
    qq_open = local_port_open()
    qq = {'code': 'ready' if qq_open else 'not_started' if info['qceInstalled'] else 'not_installed',
          'title': 'QQ 导出服务已启动' if qq_open else 'QQ 组件已安装，服务还没有启动' if info['qceInstalled'] else '尚未安装 QQ 导出组件',
          'detail': '点击连接 QQ 读取会话；如果提示未登录，请完成扫码。' if qq_open else '点击“准备并连接 QQ”，按界面提示完成安装和启动。普通 QQ 登录不会自动开启导出服务。',
          'topic': 'qq'}
    wx = info.get('wechatConnection') or {'code': 'setup', 'title': '请安装微信组件', 'detail': '保持 Windows 微信登录，再安装读取组件。', 'topic': 'wechat'}
    return {'qq': qq, 'wechat': wx}


def open_setup(action):
    if sys.platform != 'darwin':
        raise ValueError('这个设置入口仅用于 Mac')
    targets = {'full-disk-access': 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles',
               'developer-tools': 'x-apple.systempreferences:com.apple.preference.security?Privacy_DevTools'}
    if action in targets:
        subprocess.run(['/usr/bin/open', targets[action]], check=True)
    elif action == 'install-tools':
        result = subprocess.run(['/usr/bin/xcode-select', '--install'], capture_output=True)
        if result.returncode:
            raise ValueError('系统工具可能已安装。如果仍提示缺失，请打开系统设置中的软件更新进行检查。')
    elif action == 'show-terminal':
        subprocess.run(['/usr/bin/open', '-a', 'Terminal'], check=True)
    elif action == 'open-wechat':
        subprocess.run(['/usr/bin/open', '-b', 'com.tencent.xinWeChat'], check=True)
    else:
        raise ValueError('未知设置操作')


def run_wxvault(args, stop=None, timeout=300):
    executable = wxvault_binary()
    if not executable.is_file():
        raise ValueError('请先安装微信 Mac 导出组件')
    # Bound output and keep chats and backend diagnostics out of application logs.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen([str(executable), *args], cwd=executable.parent,
            stdout=stdout, stderr=stderr)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                check_stop(stop)
                if time.monotonic() > deadline:
                    raise ValueError('微信读取超时，请检查连接状态和终端完全磁盘访问权限')
                if max(os.fstat(stdout.fileno()).st_size, os.fstat(stderr.fileno()).st_size) > MAX_DOWNLOAD:
                    raise ValueError('微信导出数据过大，请缩小日期范围')
                time.sleep(.1)
            check_stop(stop)
            if process.returncode:
                raise ValueError('微信组件读取失败：请查看微信连接步骤，检查当前账号及文件访问权限；不要反复输入密码')
            if os.fstat(stdout.fileno()).st_size > MAX_DOWNLOAD:
                raise ValueError('微信导出数据过大，请缩小日期范围')
            stdout.seek(0)
            return json.load(stdout)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def refresh_qce_token():
    path = Path.home() / '.qq-chat-exporter/security.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8')).get('accessToken', '')
        return value if isinstance(value, str) else ''
    except (OSError, ValueError):
        return ''
