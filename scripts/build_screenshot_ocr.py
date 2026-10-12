"""Compile Apple's offline Vision helper; does not access WeChat or screenshots."""
from pathlib import Path
import platform
import subprocess
ROOT = Path(__file__).resolve().parents[1]
def build():
    work = ROOT / 'build/screenshot-ocr'
    work.mkdir(parents=True, exist_ok=True)
    output = work / 'screenshot-ocr'
    subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-O',
                    '-module-cache-path', str(work / 'module-cache'),
                    '-target', platform.machine() + '-apple-macosx12.0',
                    str(ROOT / 'native/screenshot_ocr.swift'), '-framework', 'Vision',
                    '-framework', 'ImageIO', '-o', str(output)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(output)], check=True)
    return output
if __name__ == '__main__':
    print(build())
