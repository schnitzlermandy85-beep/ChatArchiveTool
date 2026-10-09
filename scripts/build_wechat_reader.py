"""Compile and test the bounded reader; never touches a WeChat process."""
from pathlib import Path
import subprocess


def build(target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parents[1] / 'native/wechat_keys.c'
    subprocess.run(['/usr/bin/xcrun', 'clang', '-O2', '-Wall', '-Wextra',
                    '-mmacosx-version-min=12.0', str(source), '-o', str(target)], check=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(target)], check=True)
    subprocess.run([str(target), '--self-test'], check=True)


if __name__ == '__main__':
    build(Path(__file__).resolve().parents[1] / 'build/native/wechat_keys')
