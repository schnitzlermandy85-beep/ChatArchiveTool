"""Synthetic native-format receipts; no user chats, login or process attach."""
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from core import Cancelled
from wechat_adapter import bundle_wechat
from wechat_native import parse_transcript, validated_entries
import native_share
import web_app

TEXT = '·测试甲\n2026年10月8日 09:00\n你好\n第二行\n\n·测试乙\n2026年10月8日 09:01\n[图片] 同名.png\n[视频] clip.mp4\n[语音]\n\n·测试甲\n2026年10月8日 09:02\n重复\n\n·测试甲\n2026年10月8日 09:02\n重复\n'


class NativeWeChatTests(unittest.TestCase):
    def archive(self, source, body=TEXT, extras=None):
        with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('聊天记录.txt', body.encode('utf-8'))
            for name, data in (extras or {}).items(): z.writestr(name, data)

    def test_native_receipt_media_duplicates_and_truthful_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / '微信聊天.zip'
            self.archive(source, extras={'聊天记录内的图片、视频和文件/同名.png': b'PNG-fixture', 'media/clip.mp4': b'VIDEO-fixture'})
            before = source.read_bytes()
            result = bundle_wechat(source, root / 'out', transcribe=False, log=lambda _: None)
            rows = [json.loads(line) for line in (root / 'out/messages.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(result['messageCount'], 4)
            self.assertEqual(len({r['id'] for r in rows}), 4)
            self.assertEqual(result['historyCompleteness'], 'selected_messages_only')
            self.assertEqual(rows[0]['text'], '你好\n第二行')
            self.assertTrue(all(r['sender']['uid'] is None and r['sender']['isSelf'] is None for r in rows))
            self.assertEqual(result['media']['missing_audio'], 1)
            self.assertEqual([p['available'] for p in rows[1]['parts'] if p['type'] != 'text'], [True, True, False])
            self.assertEqual((root / 'out/source-native/original.zip').read_bytes(), before)
            self.assertEqual(source.read_bytes(), before)
            first_ids = [r['id'] for r in rows]
            bundle_wechat(source, root / 'out', transcribe=False, log=lambda _: None)
            self.assertEqual(first_ids, [json.loads(line)['id'] for line in (root / 'out/messages.jsonl').read_text(encoding='utf-8').splitlines()])

    def test_ambiguous_media_is_not_assigned_to_the_wrong_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'wx.zip'
            self.archive(source, extras={'a/同名.png': b'A', 'b/同名.png': b'B'})
            result = bundle_wechat(source, root / 'out', log=lambda _: None)
            self.assertEqual(result['media']['missing_image'], 1)

    def test_rejects_traversal_symlink_case_collision_and_duplicate_files(self):
        cases = [['../escape'], ['a/F.png', 'A/f.png'], ['p', 'p/file'], ['/absolute'], ['C:/file']]
        for names in cases:
            with self.subTest(names=names), io.BytesIO() as buffer:
                with zipfile.ZipFile(buffer, 'w') as z:
                    for name in names: z.writestr(name, b'x')
                buffer.seek(0)
                with zipfile.ZipFile(buffer) as z, self.assertRaises(ValueError): validated_entries(z)
        # Windows' ZIP writer normalizes backslashes. Put the malicious raw
        # filename into both headers after writing so every OS sees the same ZIP.
        with io.BytesIO() as buffer:
            with zipfile.ZipFile(buffer, 'w') as z: z.writestr('a/b', b'x')
            raw = buffer.getvalue().replace(b'a/b', b'a\\b')
            with zipfile.ZipFile(io.BytesIO(raw)) as z, self.assertRaises(ValueError): validated_entries(z)
        with io.BytesIO() as buffer:
            with zipfile.ZipFile(buffer, 'w') as z:
                link = zipfile.ZipInfo('symlink'); link.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(link, b'/etc/passwd')
            buffer.seek(0)
            with zipfile.ZipFile(buffer) as z, self.assertRaises(ValueError): validated_entries(z)

    def test_dukou_batches_do_not_import_the_root_index_as_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'batch.zip'
            with zipfile.ZipFile(source, 'w') as z:
                z.writestr('聊天记录.txt', '聊天：合成批次\n本批文件…')
                for i in [1, 2]:
                    z.writestr(f'batches/{i:04d}/聊天记录.txt', TEXT)
                    z.writestr(f'batches/{i:04d}/media/同名.png', bytes([i]))
            result = bundle_wechat(source, root / 'out', log=lambda _: None)
            self.assertEqual(result['messageCount'], 8)
            rows = [json.loads(line) for line in (root / 'out/messages.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len({r['id'] for r in rows}), 8)
            images = [p['path'] for r in rows for p in r['parts'] if p['type'] == 'image']
            self.assertEqual(len(set(images)), 2)

    def test_unknown_and_invalid_times_fail_without_fabricating_records(self):
        for body in ['ordinary file', '·甲\n2026年2月30日 10:00\n坏日期\n']:
            with self.assertRaises(ValueError): parse_transcript(body)
        rows = parse_transcript('\ufeff' + TEXT.replace('\n', '\r\n'))
        self.assertEqual(len(rows), 4)
        self.assertIsNotNone(rows[0][1].tzinfo)

    def test_cancel_and_empty_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'wx.zip'; self.archive(source)
            stop = threading.Event(); stop.set()
            with self.assertRaises(Cancelled): bundle_wechat(source, root / 'out', stop=stop)
            with self.assertRaisesRegex(ValueError, '日期范围'):
                bundle_wechat(source, root / 'out', filters={'startTime': 9999999999}, log=lambda _: None)

    def test_mac_legacy_api_and_frozen_helper_cannot_launch_reader(self):
        import app
        with patch.object(sys, 'platform', 'darwin'), patch('desktop_exporters.initialize_wechat') as initialize:
            controller = web_app.Controller()
            for action in ('install-wechat', 'init-wechat', 'check-wechat'):
                with self.assertRaisesRegex(ValueError, '不再进行密码初始化'): controller.component_action(action)
            with patch.object(sys, 'argv', ['app', '--helper', 'wechat_connect', 'nonexistent.json']), patch('wechat_connect.run') as reader:
                self.assertEqual(app.entrypoint(), 2)
                reader.assert_not_called()
            initialize.assert_not_called()
            self.assertFalse(controller.snapshot()['wechatReady'])

    def test_share_activation_checks_election_not_only_exit_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / 'Test.app'; (app / 'Contents/PlugIns/WeChatShare.appex').mkdir(parents=True)
            with patch.object(native_share, 'app_bundle', return_value=app), patch.object(native_share.subprocess, 'run') as run:
                run.return_value.stdout = '  ' + native_share.IDENTIFIER
                with self.assertRaisesRegex(ValueError, '尚未启用'): native_share.enable_share()
                run.return_value.stdout = '+ ' + native_share.IDENTIFIER + '(0.1.4)'
                self.assertIn('已启用', native_share.enable_share())
