"""Prepare an owned copy; Finder, under the user's control, installs it.

No elevated writes to /Applications, no automatic replacement or app launch.
An installation is complete only after the destination's signature is verified.
"""
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tempfile

from core import ROOT
from platform_support import data_root
from mac_wechat_export import private_json, check_stop


def root():
    return data_root(ROOT) / 'components/wechat-mac'


def allowed_apps():
    return (Path('/Applications/WeChat.app'), Path.home() / 'Applications/WeChat.app')


def version(app):
    with (app / 'Contents/Info.plist').open('rb') as stream:
        return str(plistlib.load(stream)['CFBundleVersion'])


def signature(app):
    result = subprocess.run(['/usr/bin/codesign', '-d', '--verbose=4', str(app)], capture_output=True, timeout=30)
    digest = re.search(rb'^CDHash=([0-9a-f]{40})$', result.stderr, re.M)
    flags = re.search(rb'flags=0x([0-9a-fA-F]+)', result.stderr)
    if result.returncode or not digest or not flags:
        raise ValueError('无法核对微信程序签名，请先确认微信安装完整')
    return {'hash': digest[1].decode(), 'hardened': bool(int(flags[1], 16) & 0x10000)}


def verify(app):
    result = subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError('微信程序完整性检查未通过，已停止；没有替换已安装的微信')


def pending():
    path = root() / 'pending-install.json'
    if not path.exists():
        return None
    try:
        info = json.loads(path.read_text())
        source, target = Path(info['source']), Path(info['target'])
        valid = (source.name == 'WeChat.app' and source.parent.parent == root()
                 and source.parent.name.startswith('install-')
                 and source.resolve() == source and target in allowed_apps()
                 and target.resolve() == target and info['kind'] in ('prepare', 'restore')
                 and re.fullmatch('[0-9a-f]{40}', info['hash'])
                 and re.fullmatch('[0-9a-f]{40}', info['originalHash'])
                 and isinstance(info['version'], str))
        if not valid:
            raise ValueError()
        return info
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('待安装记录无效，请重新点击准备读取；不会执行自动替换') from None


def find_backup(app, build, digest=None):
    folders = sorted((root() / 'backups').glob('before-sign-*'), key=lambda p: p.stat().st_mtime, reverse=True)
    for folder in folders:
        backup = folder / 'WeChat.app'
        try:
            info = json.loads((folder / 'backup.json').read_text())
            if info.get('app') != str(app) or info.get('version') != build or backup.is_symlink():
                continue
            verify(backup)
            if digest is None or signature(backup)['hash'] == digest:
                return backup
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
    return None


def stage(app, kind='prepare', log=print, stop=None):
    if app not in allowed_apps() or app.resolve() != app:
        raise ValueError('请从标准“应用程序”位置选择微信，不支持符号链接')
    verify(app)
    original, build = signature(app), version(app)
    try:
        old = pending()
    except ValueError:
        old = None  # An explicit new preparation can replace an invalid record.
    if old and old['kind'] == kind and old['target'] == str(app) and old['version'] == build and old['originalHash'] == original['hash']:
        source = Path(old['source'])
        try:
            verify(source)
            if signature(source)['hash'] == old['hash']:
                log('已复用校验通过的安装副本，无需再次备份。请打开安装文件夹，完成 Finder 替换后检查安装结果。')
                return
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    check_stop(stop)
    backup = find_backup(app, build, original['hash'] if kind == 'prepare' else None)
    if kind == 'restore' and backup is None:
        raise ValueError('没有可验证的同版本备份，请从微信官网下载当前版本覆盖安装；不要删除聊天数据')
    if backup is None:
        backups = root() / 'backups'
        backups.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder = Path(tempfile.mkdtemp(prefix='before-sign-', dir=backups))
        backup = folder / 'WeChat.app'
        log('正在备份微信程序（不复制聊天数据）…')
        shutil.copytree(app, backup, symlinks=True)
        verify(backup)
        private_json(folder / 'backup.json', {'app': str(app), 'version': build})
    else:
        log('已复用同版本且签名一致的程序备份。')
    check_stop(stop)
    root().mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = Path(tempfile.mkdtemp(prefix='install-', dir=root()))
    staged = folder / 'WeChat.app'
    published = False
    try:
        log('正在生成安装副本，已安装的微信保持不变…')
        shutil.copytree(backup if kind == 'restore' else app, staged, symlinks=True)
        check_stop(stop)
        if kind == 'prepare':
            result = subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(staged)], capture_output=True, timeout=180)
            if result.returncode:
                raise ValueError('本地副本签名失败，原微信未修改。请保留错误步骤反馈；无需反复输入管理员密码')
        verify(staged)
        signed = signature(staged)
        if kind == 'prepare' and signed['hardened']:
            raise ValueError('副本的读取条件未通过检查，原微信未修改')
        check_stop(stop)
        (folder / '拖到这里安装').symlink_to(app.parent, target_is_directory=True)
        (folder / '安装说明.txt').write_text(
            '请先退出微信。不要双击本文件夹中的微信。\n'
            '把 WeChat.app 拖到“拖到这里安装”，系统询问时选“替换”，等待复制完成。\n'
            '返回 ChatArchiveTool，点击“我已替换，检查安装”。检查通过前不要启动微信。\n'
            '这只替换程序，不删除聊天数据。若取消替换，可稍后返回继续。\n', encoding='utf-8')
        private_json(root() / 'pending-install.json', {'source': str(staged), 'target': str(app),
            'version': build, 'originalHash': original['hash'], 'hash': signed['hash'], 'kind': kind})
        published = True
    finally:
        if not published:
            shutil.rmtree(folder)
    log('副本已准备好，尚未安装。请点“打开安装文件夹”，将 WeChat.app 拖到“拖到这里安装”并确认替换；完成后点“我已替换，检查安装”。')


def open_folder():
    info = pending()
    if not info:
        raise ValueError('请先点击准备读取，生成安装副本')
    if version(Path(info['target'])) != info['version']:
        raise ValueError('微信已升级，请重新准备，不能安装旧版本副本')
    source = Path(info['source'])
    verify(source)
    if signature(source)['hash'] != info['hash']:
        raise ValueError('安装副本已经变化，请重新准备')
    subprocess.run(['/usr/bin/open', str(source.parent)], check=True, timeout=15)


def confirm():
    info = pending()
    if not info:
        raise ValueError('没有待检查的安装，请先准备读取')
    app = Path(info['target'])
    if version(app) != info['version']:
        raise ValueError('微信版本已变化，请重新准备，不能用旧副本覆盖新版')
    if signature(app)['hash'] != info['hash']:
        raise ValueError('尚未检测到替换完成。请在 Finder 确认替换并等待复制结束；仅关闭安装文件夹不算完成')
    verify(app)
    (root() / 'pending-install.json').unlink()
    return info['kind']
