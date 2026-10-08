"""Build a sandboxed share extension into our own app; never touch WeChat."""
import os
from pathlib import Path
import platform
import plistlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = 'com.chatarchivetool.desktop.WeChatShare'


def build(app, version):
    app = Path(app)
    bundle = app / 'Contents/PlugIns/WeChatShare.appex'
    binary = bundle / 'Contents/MacOS/WeChatShare'
    binary.parent.mkdir(parents=True, exist_ok=True)
    work = ROOT / 'build/wechat-share'
    work.mkdir(parents=True, exist_ok=True)
    # NSExtensionMain is the entry, not a standalone application main().
    main = work / 'main.swift'
    main.write_text('// Entry provided by NSExtensionMain.\n', encoding='utf-8')
    subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-O',
                    '-module-cache-path', str(work / 'module-cache'),
                    '-target', platform.machine() + '-apple-macosx12.0',
                    str(main), str(ROOT / 'native/wechat_share/ShareViewController.swift'),
                    '-framework', 'AppKit', '-framework', 'UniformTypeIdentifiers',
                    '-Xlinker', '-e', '-Xlinker', '_NSExtensionMain', '-o', str(binary)], check=True)
    info = {'CFBundleIdentifier': IDENTIFIER, 'CFBundleName': 'WeChatShare',
            'CFBundleDisplayName': '导出聊天 ZIP · ChatArchiveTool',
            'CFBundleExecutable': 'WeChatShare', 'CFBundlePackageType': 'XPC!',
            'CFBundleInfoDictionaryVersion': '6.0', 'CFBundleShortVersionString': version.lstrip('v'),
            'CFBundleVersion': version.lstrip('v'), 'LSMinimumSystemVersion': '12.0',
            'NSExtension': {'NSExtensionPointIdentifier': 'com.apple.share-services',
                            'NSExtensionPrincipalClass': 'ChatArchiveShareViewController',
                            'NSExtensionAttributes': {'NSExtensionActivationRule': {
                                'NSExtensionActivationDictionaryVersion': 2,
                                'NSExtensionActivationSupportsFileWithMaxCount': 1}}}}
    (bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    rights = work / 'share.entitlements'
    rights.write_bytes(plistlib.dumps({'com.apple.security.app-sandbox': True,
                                     'com.apple.security.files.user-selected.read-write': True}))
    subprocess.run(['codesign', '--force', '--sign', '-', '--entitlements', str(rights), str(bundle)], check=True)
    # Parent must be sealed after its nested extension. Existing PyInstaller code stays signed.
    subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    symbols = subprocess.check_output(['nm', '-u', str(binary)], text=True)
    if '_NSExtensionMain' not in symbols:
        raise RuntimeError('Missing share-extension entry point')


if __name__ == '__main__':
    import sys
    build(sys.argv[1], sys.argv[2])
