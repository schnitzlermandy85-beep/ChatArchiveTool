# Build on the target OS/architecture: python -m PyInstaller ChatArchiveTool.spec
import sys
from pathlib import Path

root = Path(SPECPATH)
mac_binaries = [(str(root / 'build/native/wechat_keys'), 'native')] if sys.platform == 'darwin' else []
datas = [(str(root / name), name) for name in ('web', 'vendor')]
datas += [(str(root / name), '.') for name in ('viewer.html', 'THIRD_PARTY_NOTICES.md', 'VERSION')]
a = Analysis(
    ['app.py'],
    pathex=[str(root / 'vendor/wechat_export')],
    binaries=mac_binaries, datas=datas,
    hiddenimports=['packaging', 'packaging.tags', 'packaging.requirements',
                   'packaging.utils', 'packaging.version', 'exporter_core'] + (['sqlcipher3', 'sqlcipher3.dbapi2', 'Crypto.Cipher.AES', 'av', 'pysilk'] if sys.platform == 'darwin' else []),
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['faster_whisper', 'numpy', 'pip', 'setuptools'] + (['tkinter'] if sys.platform == 'darwin' else []),
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ChatArchiveTool',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=sys.platform != 'darwin', disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ChatArchiveTool')
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='ChatArchiveTool.app', bundle_identifier='com.chatarchivetool.desktop',
                 info_plist={'CFBundleDisplayName': 'ChatArchiveTool',
                             'NSHighResolutionCapable': True,
                             'LSUIElement': True,
                             'CFBundleShortVersionString': (root / 'VERSION').read_text().strip().lstrip('v'),
                             'CFBundleVersion': (root / 'VERSION').read_text().strip().lstrip('v')})
