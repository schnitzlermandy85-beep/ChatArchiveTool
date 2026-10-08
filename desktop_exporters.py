"""Pinned upstream export tools, installed on demand outside the application bundle."""
from __future__ import annotations
import hashlib
import json
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

from core import ROOT, Cancelled
from platform_support import data_root

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
    return {'desktopOS': sys.platform, 'qceInstallSupported': qce_supported(),
            'qceInstalled': qce_launcher() is not None,
            'wechatMac': sys.platform == 'darwin', 'wechatMacSupported': mac_arm(),
            'wechatInstalled': wxvault_binary().is_file() if mac_arm() else False,
            'wechatConfigured': wxvault_configured() if mac_arm() else False}


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
            log('微信 Mac 导出组件已安装；点击“初始化微信连接”')
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
        # The upstream launcher checks for running desktop QQ; never kill it here.
        open_terminal_script('QQ-export', 'cd -- ' + shlex.quote(str(launcher.parent)) + '\n' +
            'echo "请先完全退出桌面 QQ，再在此窗口按提示扫码登录。使用期间保持此窗口运行。"\n' +
            '/bin/bash ' + shlex.quote(str(launcher)))
    elif sys.platform == 'win32':
        os.startfile(str(launcher))
    else:
        raise ValueError('该平台没有可启动的 QQ 导出组件')


def initialize_wechat():
    if not mac_arm() or not wxvault_binary().is_file():
        raise ValueError('请先安装 Apple 芯片 Mac 微信导出组件')
    if not shutil.which('lldb'):
        raise ValueError('初始化需要 Xcode 命令行工具，请先在终端运行 xcode-select --install')
    open_terminal_script('WeChat-connect',
        'cd -- ' + shlex.quote(str(wxvault_binary().parent)) + '\n' +
        'echo "初始化会暂时退出微信，使用临时副本读取本地数据库密钥，并恢复原微信。"\n' +
        'echo "请给终端完全磁盘访问权限；管理员密码仅在系统终端输入，并在微信窗口完成登录。"\n' +
        shlex.quote(str(wxvault_binary())) + ' init')


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
                    raise ValueError('微信读取超时，请检查初始化状态和终端完全磁盘访问权限')
                if max(os.fstat(stdout.fileno()).st_size, os.fstat(stderr.fileno()).st_size) > MAX_DOWNLOAD:
                    raise ValueError('微信导出数据过大，请缩小日期范围')
                time.sleep(.1)
            check_stop(stop)
            if process.returncode:
                raise ValueError('微信组件读取失败：请先在终端完成初始化，并检查当前账号及文件访问权限；可重新初始化连接')
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
