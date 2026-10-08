"""Platform capabilities and writable locations, separate from bundled assets."""
import importlib.util
import os
import platform
from pathlib import Path
import subprocess
import sys

WECHAT_UNSUPPORTED = '微信直接读取支持 Windows 和 Apple 芯片 Mac；Intel Mac 暂请导入已有文件。'


def data_root(source_root):
    """Never write into a signed/translocated .app or an installed executable."""
    if os.environ.get('CHATARCHIVE_DATA_DIR'):
        return Path(os.environ['CHATARCHIVE_DATA_DIR']).expanduser().resolve()
    if not getattr(sys, 'frozen', False):
        return Path(source_root)
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/ChatArchiveTool'
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'ChatArchiveTool'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'ChatArchiveTool'


def wechat_supported():
    return sys.platform == 'win32' or (sys.platform == 'darwin' and platform.machine().lower() == 'arm64')


def require_wechat_support():
    if not wechat_supported():
        raise ValueError(WECHAT_UNSUPPORTED)


def voice_available():
    return importlib.util.find_spec('faster_whisper') is not None


def open_folder(path):
    path = str(Path(path).resolve())
    if sys.platform == 'win32':
        os.startfile(path)
    else:
        subprocess.run(['open' if sys.platform == 'darwin' else 'xdg-open', path], check=True)
