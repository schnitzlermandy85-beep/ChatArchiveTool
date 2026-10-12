"""Installation state tests use synthetic bundles; never access installed apps."""
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import mac_wechat_install as install


class InstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.app = self.base / 'Applications/WeChat.app'
        (self.app / 'Contents/MacOS').mkdir(parents=True)
        (self.app / 'Contents/MacOS/WeChat').write_bytes(b'official')
        (self.app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion': 'test'}))
        (self.app / 'Contents/extension').write_bytes(b'unchanged extension')
        for name, value in [('root', self.base / 'component'), ('allowed_apps', (self.app,))]:
            mock = patch.object(install, name, return_value=value)
            mock.start(); self.addCleanup(mock.stop)
        mock = patch.object(install.subprocess, 'run', side_effect=self.command)
        self.run = mock.start(); self.addCleanup(mock.stop)
        self.fail_sign = False

    def command(self, args, **kwargs):
        app = Path(args[-1])
        if args[0] == '/usr/bin/open':
            return subprocess.CompletedProcess(args, 0, b'', b'')
        content = (app / 'Contents/MacOS/WeChat').read_bytes()
        if '--verify' in args:
            return subprocess.CompletedProcess(args, int(content == b'corrupt'), b'', b'')
        if '--sign' in args:
            self.assertNotEqual(app, self.app)
            self.assertNotIn('--deep', args)
            if self.fail_sign:
                return subprocess.CompletedProcess(args, 1, b'', b'private output')
            (app / 'Contents/MacOS/WeChat').write_bytes(b'prepared')
            return subprocess.CompletedProcess(args, 0, b'', b'')
        digest = hashlib.sha1(content).hexdigest()
        flags = '10000' if content == b'official' else '2'
        return subprocess.CompletedProcess(args, 0, b'', f'CDHash={digest}\nflags=0x{flags}\n'.encode())

    def stage(self, kind='prepare'):
        install.stage(self.app, kind=kind, log=lambda _: None)
        return install.pending()

    def test_stage_leaves_installed_app_untouched_and_confirm_requires_replacement(self):
        info = self.stage()
        self.assertEqual((self.app / 'Contents/MacOS/WeChat').read_bytes(), b'official')
        self.assertEqual((Path(info['source']) / 'Contents/extension').read_bytes(), b'unchanged extension')
        with self.assertRaisesRegex(ValueError, '尚未检测到替换'):
            install.confirm()
        self.assertIsNotNone(install.pending())
        shutil.copytree(info['source'], self.app, dirs_exist_ok=True)
        self.assertEqual(install.confirm(), 'prepare')
        self.assertIsNone(install.pending())

    def test_restart_and_repeated_prepare_reuse_verified_copy_and_backup(self):
        first = self.stage()
        second = self.stage()
        self.assertEqual(first, second)
        self.assertEqual(len(list((install.root() / 'backups').glob('before-sign-*'))), 1)
        self.assertEqual(len(list(install.root().glob('install-*'))), 1)

    def test_sign_failure_never_publishes_installation(self):
        self.fail_sign = True
        with self.assertRaisesRegex(ValueError, '原微信未修改') as error:
            self.stage()
        self.assertNotIn('private output', str(error.exception))
        self.assertIsNone(install.pending())
        self.assertEqual((self.app / 'Contents/MacOS/WeChat').read_bytes(), b'official')
        self.assertFalse(list(install.root().glob('install-*')))

    def test_pending_path_tampering_is_rejected_before_opening(self):
        info = self.stage()
        info['source'] = str(self.base / 'unrelated/WeChat.app')
        (install.root() / 'pending-install.json').write_text(json.dumps(info))
        self.run.reset_mock()
        with self.assertRaisesRegex(ValueError, '记录无效'):
            install.open_folder()
        self.run.assert_not_called()

    def test_changed_installed_version_is_not_accepted(self):
        info = self.stage()
        shutil.copytree(info['source'], self.app, dirs_exist_ok=True)
        (self.app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion': 'new'}))
        with self.assertRaisesRegex(ValueError, '版本已变化'):
            install.confirm()
        self.assertIsNotNone(install.pending())

    def test_restore_also_requires_finder_confirmation(self):
        info = self.stage()
        shutil.copytree(info['source'], self.app, dirs_exist_ok=True)
        install.confirm()
        restore = self.stage('restore')
        self.assertEqual((self.app / 'Contents/MacOS/WeChat').read_bytes(), b'prepared')
        shutil.copytree(restore['source'], self.app, dirs_exist_ok=True)
        self.assertEqual(install.confirm(), 'restore')
        self.assertEqual((self.app / 'Contents/MacOS/WeChat').read_bytes(), b'official')


if __name__ == '__main__':
    unittest.main()
