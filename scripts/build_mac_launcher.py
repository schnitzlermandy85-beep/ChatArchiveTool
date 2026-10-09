"""Install the AppKit reopen/lifecycle shell around the PyInstaller backend."""
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build(app):
    contents = Path(app) / 'Contents/MacOS'
    executable = contents / 'ChatArchiveTool'
    backend = contents / 'ChatArchiveToolBackend'
    executable.rename(backend)
    # The former main executable was sealed with the bundle's Info.plist.
    # Re-sign it as nested helper code before sealing the new main executable.
    subprocess.run(['codesign', '--force', '--sign', '-', str(backend)], check=True)
    work = ROOT / 'build/mac-launcher'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-O',
                    '-module-cache-path', str(work / 'module-cache'),
                    '-target', platform.machine() + '-apple-macosx12.0',
                    str(ROOT / 'native/mac_launcher.swift'), '-framework', 'AppKit',
                    '-o', str(executable)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(executable)], check=True)
