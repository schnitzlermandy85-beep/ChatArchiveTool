"""Connection regression tests use synthetic data, never real login sessions."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

import desktop_exporters as desktop
import wechat_connect as helper
import web_app


class ConnectionGuideTests(unittest.TestCase):
    def setUp(self):
        # Synthetic readable target; never depend on this machine's real app.
        for target in ('desktop_exporters.inspect_wechat', 'wechat_preflight.inspect_wechat'):
            mock = patch(target, return_value={'blocked': False, 'code': 'eligible'})
            mock.start(); self.addCleanup(mock.stop)

    def test_account_selection_is_explicit_when_multiple_accounts_exist(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, 'home', return_value=Path(tmp)):
            root = Path(tmp) / 'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files'
            first = root / 'account1/db_storage'; first.mkdir(parents=True)
            self.assertEqual(helper.choose_database(), first)
            second = root / 'account2/db_storage'; second.mkdir(parents=True)
            with self.assertRaisesRegex(helper.ConnectionFailure, 'multiple_accounts'):
                helper.choose_database()
            self.assertEqual(helper.choose_database(selected=str(second)), second.resolve())
            with self.assertRaisesRegex(helper.ConnectionFailure, 'invalid_account'):
                helper.choose_database(selected=tmp)

    def test_pending_timeout_prevents_delayed_terminal_from_starting(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(desktop, 'tools_root', return_value=Path(tmp)):
            job = Path(tmp) / 'connections/wechat' / ('a' * 32); job.mkdir(parents=True)
            (job.parent / 'current.json').write_text(json.dumps({'id': job.name}))
            (job / 'status.json').write_text(json.dumps({'phase': 'pending', 'code': 'terminal_pending', 'at': 1}))
            self.assertEqual(desktop.connection_status()['code'], 'timeout')
            self.assertTrue((job / 'cancel').exists())
            (job / 'status.json').write_text(json.dumps({'phase': 'authorizing', 'code': 'password', 'at': 1}))
            self.assertTrue(desktop.connection_status()['active'])
            desktop.cancel_wechat()
            self.assertEqual(desktop.connection_status()['code'], 'cancelling')

    def test_initialize_uses_live_helper_and_rejects_duplicate_jobs(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(desktop, 'tools_root', return_value=Path(tmp)), patch.object(desktop, 'mac_arm', return_value=True), patch.object(desktop, 'wxvault_binary', return_value=Path(__file__)), patch.object(desktop, 'open_terminal_script') as terminal:
            desktop.initialize_wechat()
            command = terminal.call_args.args[1]
            self.assertIn('wechat_connect', command)
            self.assertNotIn(' init', command)
            with self.assertRaisesRegex(ValueError, '正在进行'):
                desktop.initialize_wechat()
            self.assertEqual(terminal.call_count, 1)

    def test_setup_rejects_arbitrary_command_and_url(self):
        with patch.object(sys, 'platform', 'darwin'), patch.object(desktop.subprocess, 'run') as run:
            with self.assertRaises(ValueError): desktop.open_setup('https://arbitrary.test')
            run.assert_not_called()
            desktop.open_setup('developer-tools')
            self.assertEqual(run.call_args.args[0], ['/usr/bin/open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_DevTools'])

    def test_running_qq_requires_manual_exit_without_launching_or_killing_it(self):
        with patch.object(desktop, 'qce_launcher', return_value=Path('/mock/launcher.sh')), patch.object(desktop, 'mac_arm', return_value=True), patch.object(desktop.subprocess, 'run', return_value=Mock(returncode=0)) as run, patch.object(desktop, 'open_terminal_script') as terminal:
            with self.assertRaisesRegex(ValueError, '退出 QQ'):
                desktop.start_qce()
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0], ['/usr/bin/pgrep', '-x', 'QQ'])
            terminal.assert_not_called()

    def test_qq_existing_external_service_does_not_install_or_launch(self):
        controller = web_app.Controller()
        with patch.object(desktop, 'local_port_open', return_value=True), patch.object(desktop, 'install_component') as install, patch.object(desktop, 'start_qce') as start, patch.object(desktop, 'refresh_qce_token', return_value='synthetic'), patch('web_app.QCE') as qce:
            qce.return_value.sessions.return_value = [{'peerUid': 'test', 'chatType': 1}]
            controller.prepare_qq({'address': 'http://127.0.0.1:5000'})
            install.assert_not_called(); start.assert_not_called()
            self.assertEqual(len(controller.sessions), 1)
            self.assertEqual(controller.token, 'synthetic')

    def test_qq_prepare_installs_starts_and_refreshes_new_token(self):
        controller = web_app.Controller()
        with patch.object(desktop, 'local_port_open', return_value=False), patch.object(desktop, 'install_component') as install, patch.object(desktop, 'start_qce') as start, patch.object(desktop, 'refresh_qce_token', return_value='after-start'), patch('web_app.QCE') as qce:
            qce.return_value.sessions.return_value = []
            controller.prepare_qq({})
            install.assert_called_once(); start.assert_called_once()
            self.assertEqual(controller.token, 'after-start')
            self.assertEqual(controller.state['status'], 'connected')

    def test_qq_cancel_does_not_install(self):
        controller = web_app.Controller(); controller.stop.set()
        with patch.object(desktop, 'local_port_open', return_value=True), patch('web_app.QCE'), self.assertRaises(web_app.Cancelled):
            controller.prepare_qq({})

    @unittest.skipUnless(sys.platform == 'darwin', 'Interactive helper only runs on macOS')
    def test_authorization_failure_does_not_attach_or_modify_config(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, 'home', return_value=Path(tmp)), patch.object(helper.signal, 'signal'), patch.object(helper, 'choose_database', return_value=Path(tmp)), patch.object(helper, 'collect_salts', return_value=['11' * 16]), patch.object(helper.subprocess, 'run') as run, patch.object(helper.subprocess, 'Popen') as popen:
            job = Path(tmp) / 'job'; job.mkdir()
            request = job / 'request.json'; request.write_text(json.dumps({'executable': __file__, 'hook': __file__}))
            run.side_effect = [Mock(returncode=0, stdout='/usr/bin/lldb'), Mock(returncode=0, stdout='123'), Mock(returncode=1)]
            self.assertEqual(helper.run(request), 1)
            self.assertEqual(json.loads((job / 'status.json').read_text())['code'], 'authorization_cancelled')
            popen.assert_not_called()
            self.assertFalse((Path(tmp) / '.wxvault/config.json').exists())
            self.assertEqual(run.call_args.args[0], ['/usr/bin/sudo', '-v'])

    def test_lldb_reader_detaches_on_unexpected_setup_failure(self):
        fake = types.SimpleNamespace(eStateExited=1, eStateCrashed=2, eStateDetached=3)
        path = Path(__file__).resolve().parents[1] / 'vendor/wechat_live/hook.py'
        spec = importlib.util.spec_from_file_location('live_reader_test', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'lldb': fake}): spec.loader.exec_module(module)
        debugger = Mock(); process = debugger.GetSelectedTarget.return_value.GetProcess.return_value
        process.GetState.return_value = 5; process.IsValid.return_value = True
        with patch.object(module, 'read_session', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError): getattr(module, '__lldb_init_module')(debugger, {})
        process.Detach.assert_called_once()
        process.Kill.assert_not_called()

    @unittest.skipUnless(sys.platform == 'darwin', 'Interactive helper only runs on macOS')
    def test_live_helper_validates_before_saving_and_never_runs_old_init(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, 'home', return_value=Path(tmp)), patch.object(helper.signal, 'signal'), patch.object(helper, 'choose_database', return_value=Path(tmp)), patch.object(helper, 'collect_salts', return_value=['11' * 16]), patch.object(helper.subprocess, 'run') as run, patch.object(helper.subprocess, 'Popen') as popen:
            job = Path(tmp) / 'job'; job.mkdir()
            request = job / 'request.json'; request.write_text(json.dumps({'executable': __file__, 'hook': __file__}))
            run.side_effect = [Mock(returncode=0, stdout='/usr/bin/lldb'), Mock(returncode=0, stdout='123'), Mock(returncode=0), Mock(returncode=0), Mock(returncode=0), Mock(returncode=0, stdout=b'{"meta":{"status":"ok"}}')]
            def child(args, **kwargs):
                private = Path(next(a.split('=', 1)[1] for a in args if a.startswith('CHATARCHIVE_LIVE_JOB=')))
                (private / 'pairs.json').write_text('[]')
                return Mock(poll=Mock(return_value=0), returncode=0)
            popen.side_effect = child
            self.assertEqual(helper.run(request), 0)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertIn('--check', commands[3]); self.assertNotIn('--check', commands[4])
            self.assertTrue(all('init' not in command for command in commands))
            self.assertEqual(json.loads((job / 'status.json').read_text())['phase'], 'complete')
            config = Path(tmp) / '.wxvault/config.json'
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            attach = popen.call_args.args[0]
            self.assertIn('process attach --pid 123', attach)
            self.assertTrue(all('kill' not in value and 'launch' not in value for value in attach))

    def test_reader_cancel_removes_breakpoints_and_detaches(self):
        fake = types.SimpleNamespace(eStateExited=1, eStateCrashed=2, eStateDetached=3,
            SBProcess=types.SimpleNamespace(eBroadcastBitStateChanged=1), SBListener=Mock(), SBEvent=Mock())
        path = Path(__file__).resolve().parents[1] / 'vendor/wechat_live/hook.py'
        spec = importlib.util.spec_from_file_location('live_reader_cancel_test', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'lldb': fake}): spec.loader.exec_module(module)
        debugger = Mock(); target = debugger.GetSelectedTarget.return_value; process = target.GetProcess.return_value
        process.GetState.return_value = 5; process.IsValid.return_value = True
        process.GetMemoryRegions.return_value.GetSize.return_value = 0
        target.BreakpointCreateByName.side_effect = [Mock(GetID=Mock(return_value=i)) for i in (11, 12, 13)]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'CHATARCHIVE_LIVE_JOB': tmp}), patch.object(module.os, 'chown', create=True):
            root = Path(tmp); (root / 'salts.json').write_text('["' + '11' * 16 + '"]'); (root / 'cancel').touch()
            getattr(module, '__lldb_init_module')(debugger, {})
            self.assertEqual(json.loads((root / 'reader.json').read_text())['code'], 'cancelled')
            self.assertEqual(json.loads((root / 'pairs.json').read_text()), [])
        self.assertEqual(target.BreakpointDelete.call_count, 3)
        process.Detach.assert_called_once(); process.Kill.assert_not_called()

    def test_permissions_are_classified_without_echoing_diagnostics(self):
        self.assertEqual(helper.classify_lldb_error('attach failed: Operation not permitted sensitive-string'), 'developer_permission')
        self.assertEqual(helper.classify_lldb_error('some error'), 'reader_failed')


if __name__ == '__main__': unittest.main()
