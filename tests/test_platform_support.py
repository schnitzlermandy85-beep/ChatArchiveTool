import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import app
import core
import filepicker
import platform_support as support
import web_app
import wechat_adapter


class PlatformSupportTests(unittest.TestCase):
    def test_frozen_mac_data_is_outside_app(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'platform', 'darwin'), patch.object(Path, 'home', return_value=Path('/Users/example')):
            self.assertEqual(support.data_root('/Applications/ChatArchiveTool.app/Contents/Resources'), Path('/Users/example/Library/Application Support/ChatArchiveTool'))

    def test_frozen_windows_data_uses_local_appdata(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': '/tmp/user-local'}, clear=True), patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'platform', 'win32'):
            self.assertEqual(support.data_root('/readonly/install'), Path('/tmp/user-local/ChatArchiveTool'))

    def test_source_and_explicit_data_locations(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(support.data_root('/source'), Path('/source'))
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'CHATARCHIVE_DATA_DIR': temp}):
            self.assertEqual(support.data_root('/source'), Path(temp).resolve())

    def test_frozen_helper_command_does_not_run_a_python_script(self):
        with patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(core.child_command('filepicker', 'folder', 'output'), [sys.executable, '--helper', 'filepicker', 'folder', 'output'])
        with patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(core.child_command('filepicker', 'file')[1:], [str(core.ROOT / 'filepicker.py'), 'file'])
        with self.assertRaises(ValueError):
            core.child_command('untrusted')

    def test_helper_dispatch_does_not_start_server_or_log(self):
        with patch.object(sys, 'argv', ['app', '--helper', 'filepicker', 'folder', 'output']), patch('filepicker.main', return_value=0) as picker, patch('app.main') as launcher:
            self.assertEqual(app.entrypoint(), 0)
            picker.assert_called_once_with(['folder', 'output'])
            launcher.assert_not_called()
        with patch.object(sys, 'argv', ['app', '--helper', 'unknown']), patch('app.main') as launcher:
            self.assertEqual(app.entrypoint(), 2)
            launcher.assert_not_called()

    def test_mac_picker_preserves_spaces_unicode_and_cancellation(self):
        with patch.object(sys, 'platform', 'darwin'), patch('filepicker.subprocess.run') as run:
            run.return_value = Mock(stdout='/Users/example/聊天 记录/\n')
            self.assertEqual(filepicker.choose('folder'), '/Users/example/聊天 记录/')
            self.assertEqual(run.call_args.args[0][:2], ['osascript', '-e'])
            run.return_value = Mock(stdout='\n')
            self.assertEqual(filepicker.choose('file'), '')
            run.side_effect = subprocess.CalledProcessError(1, 'osascript')
            with self.assertRaises(subprocess.CalledProcessError):
                filepicker.choose('file')

    def test_open_folder_uses_native_command_without_shell(self):
        with patch.object(sys, 'platform', 'darwin'), patch('platform_support.subprocess.run') as run:
            support.open_folder('/tmp/聊天 记录')
            run.assert_called_once_with(['open', str(Path('/tmp/聊天 记录').resolve())], check=True)
        with patch.object(sys, 'platform', 'win32'), patch('platform_support.os.startfile', create=True) as start:
            support.open_folder('/tmp/archive')
            start.assert_called_once()

    def test_mac_rejects_windows_install_and_direct_export_before_side_effects(self):
        with patch.object(sys, 'platform', 'darwin'), patch('platform.machine', return_value='x86_64'):
            controller = web_app.Controller()
            self.assertFalse(controller.state['wechatSupported'])
            self.assertFalse(controller.state['wechatReady'])
            with self.assertRaises(ValueError):
                controller.install()
            with self.assertRaises(ValueError):
                controller.start({'platform': 'WeChat', 'mode': 'direct', 'output': '/unused'})
            with tempfile.TemporaryDirectory() as temp:
                destination = Path(temp) / 'not-created'
                with self.assertRaises(ValueError):
                    wechat_adapter.export_wechat('好友', destination)
                self.assertFalse(destination.exists())
                from setup_wechat import install
                with self.assertRaises(ValueError):
                    install(destination)
                self.assertFalse(destination.exists())
            self.assertFalse(controller.state['busy'])

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS source launcher')
    def test_actual_command_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(['bash', str(core.ROOT / 'start.command'), '--check'],
                env={**os.environ, 'CHATARCHIVE_DATA_DIR': temp}, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Startup check passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
