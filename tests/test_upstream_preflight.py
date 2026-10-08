import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

from core import QCE, QCEError
import desktop_exporters as desktop
import wechat_preflight as preflight
import web_app


class UpstreamIntegrationTests(unittest.TestCase):
    def test_protected_mac_target_is_rejected_before_terminal_or_password(self):
        blocked = {'blocked': True, 'title': '不支持直读', 'detail': '系统保护'}
        with patch.object(desktop, 'mac_arm', return_value=True), patch.object(desktop, 'inspect_wechat', return_value=blocked), patch.object(desktop, 'open_terminal_script') as terminal:
            with self.assertRaisesRegex(ValueError, '不支持直读'): desktop.initialize_wechat()
            terminal.assert_not_called()

    def test_readonly_entitlement_check_distinguishes_protected_and_debuggable(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sys, 'platform', 'darwin'):
            app = Path(tmp) / 'WeChat.app'; binary = app / 'Contents/MacOS/WeChat'
            binary.parent.mkdir(parents=True); binary.touch()
            for debuggable, blocked in [(False, True), (True, False)]:
                with patch.object(preflight, 'signature_info', return_value={'hardened': True, 'debuggable': debuggable}), patch.object(preflight, 'sip_enabled', return_value=True):
                    self.assertEqual(preflight.inspect_wechat(app)['blocked'], blocked)
            with patch.object(preflight, 'signature_info', return_value=None):
                self.assertEqual(preflight.inspect_wechat(app)['code'], 'unverified_client')

    def test_upstream_health_does_not_mistake_open_port_for_online_qq(self):
        q = QCE()
        with patch.object(q, 'request', return_value={'status': 'healthy', 'mode': 'standalone', 'online': False}):
            self.assertEqual(q.health()['mode'], 'standalone')
        with patch.object(q, 'request', return_value={'ok': True}):
            with self.assertRaises(QCEError): q.health()

    def test_standalone_service_does_not_trigger_three_minute_retry(self):
        controller = web_app.Controller()
        with patch.object(desktop, 'local_port_open', return_value=True), patch('web_app.QCE') as factory:
            factory.return_value.health.return_value = {'mode': 'standalone', 'online': False}
            with self.assertRaisesRegex(QCEError, '独立模式'): controller.prepare_qq({})
            factory.return_value.sessions.assert_not_called()

    def test_optional_recent_contact_error_does_not_hide_friends_and_groups(self):
        q = QCE()
        def request(path):
            if path.startswith('/api/recent-contacts'): raise RuntimeError('RECENT_CONTACTS_FAILED')
            if path.startswith('/api/friends'): return {'friends': [{'uid': 'synthetic-peer', 'nick': 'Test'}], 'hasNext': False}
            return {'groups': [{'groupCode': 'synthetic-group', 'groupName': 'Test group'}], 'hasNext': False}
        with patch.object(q, 'request', side_effect=request):
            self.assertEqual({s['peerUid'] for s in q.sessions()}, {'synthetic-peer', 'synthetic-group'})

    def test_authentication_status_is_preserved_without_echoing_body(self):
        q = QCE()
        error = urllib.error.HTTPError('http://localhost', 401, 'Unauthorized', {}, io.BytesIO(b'secret-example'))
        with patch.object(q.op, 'open', side_effect=error):
            with self.assertRaises(QCEError) as caught: q.health()
        self.assertEqual(caught.exception.status, 401)
        self.assertNotIn('secret-example', str(caught.exception))
