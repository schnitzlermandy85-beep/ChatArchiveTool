"""Build and archive a native desktop package without including local user data."""
import argparse
import hashlib
from importlib.metadata import distribution
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default='dev')
    args = parser.parse_args()
    if not args.version or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_' for c in args.version):
        parser.error('Version may only contain ASCII letters, digits, dots, underscores and hyphens')
    arch = platform.machine().lower()
    if sys.platform == 'darwin':
        target = 'macOS-AppleSilicon' if arch == 'arm64' else 'macOS-Intel' if arch == 'x86_64' else None
    elif sys.platform == 'win32' and arch in ('amd64', 'x86_64'):
        target = 'Windows-x64'
    else:
        target = None
    if target is None:
        parser.error('Build on Windows x64 or macOS arm64/x86_64')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
                    '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build/pyinstaller'),
                    str(ROOT / 'ChatArchiveTool.spec')], cwd=ROOT, check=True,
                   env={**os.environ, 'PYINSTALLER_CONFIG_DIR': str(ROOT / 'build/cache')})
    name = f'ChatArchiveTool-{args.version}-{target}'
    stage = ROOT / 'build/release' / name
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    if sys.platform == 'darwin':
        shutil.copytree(ROOT / 'dist/ChatArchiveTool.app', stage / 'ChatArchiveTool.app', symlinks=True)
        executable = stage / 'ChatArchiveTool.app/Contents/MacOS/ChatArchiveTool'
    else:
        shutil.copytree(ROOT / 'dist/ChatArchiveTool', stage / 'ChatArchiveTool')
        executable = stage / 'ChatArchiveTool/ChatArchiveTool.exe'
    for filename in ('README.md', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / filename, stage / filename)
    shutil.copytree(ROOT / 'examples', stage / 'examples')
    shutil.copytree(ROOT / 'vendor/licenses', stage / 'licenses')
    # Preserve runtime notices alongside the application's vendored licenses.
    for package in ('pyinstaller', 'packaging', 'certifi', 'Pillow'):
        metadata = distribution(package)
        for item in metadata.files or []:
            if '.dist-info/' in str(item) and any(word in item.name.lower() for word in ('license', 'copying', 'notice')):
                target = stage / 'licenses' / package / item.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(metadata.locate_file(item), target)
    candidates = [Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt']
    for base in (Path(sys.base_prefix).resolve(), *Path(sys.base_prefix).resolve().parents):
        candidates += [base / 'LICENSE.txt', base / 'LICENSE']
    python_license = next((path for path in candidates if path.is_file()), None)
    if python_license is None:
        raise RuntimeError('Python runtime LICENSE not found; do not distribute without its notice')
    shutil.copy2(python_license, stage / 'licenses/Python-LICENSE.txt')
    # Exercise the actual packaged server and analysis engine before publishing.
    subprocess.run([sys.executable, str(ROOT / 'scripts/smoke_packaged.py'), str(executable)], check=True)
    release_dir = ROOT / 'dist/release'
    release_dir.mkdir(parents=True, exist_ok=True)
    archive = release_dir / (name + '.zip')
    if sys.platform == 'darwin':
        # ditto preserves .app executable permissions and symlinks.
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(stage), str(archive)], check=True)
    else:
        shutil.make_archive(str(archive.with_suffix('')), 'zip', stage.parent, stage.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    print(f'Release package: {archive}')


if __name__ == '__main__':
    main()
