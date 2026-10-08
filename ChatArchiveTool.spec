# Build on the target OS/architecture: python -m PyInstaller ChatArchiveTool.spec
import sys
from pathlib import Path

root = Path(SPECPATH)
datas = [(str(root / name), name) for name in ('web', 'vendor')]
datas += [(str(root / name), '.') for name in ('viewer.html', 'THIRD_PARTY_NOTICES.md')]
a = Analysis(
    ['app.py'],
    pathex=[str(root / 'vendor/wechat_export')],
    binaries=[], datas=datas,
    hiddenimports=['packaging', 'packaging.tags', 'packaging.requirements',
                   'packaging.utils', 'packaging.version', 'exporter_core'],
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
                             'LSUIElement': True})
