"""Real SQLCipher/DAT/MP4 fixtures, no WeChat account or process access."""
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import mac_wechat_export as reader
import mac_wechat_setup as setup
from wechat_adapter import bundle_wechat
from vendor.wechat_mac.models import Layout


@unittest.skipUnless(sys.platform == 'darwin', 'Mac SQLCipher wheel')
class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.account = self.root / 'wxid_test_abcd'
        self.peer = 'filehelper'
        self.table = 'Msg_' + hashlib.md5(self.peer.encode()).hexdigest()
        self.keys = {}
        self.live = []
        self.addCleanup(lambda: [db.close() for db in self.live])
        self.contact = self.database('contact/contact.db', [
            ('CREATE TABLE contact(username, nick_name, remark)', ()),
            ("INSERT INTO contact VALUES('filehelper','文件传输助手','')", ())])
        self.shards = []
        for number in range(2):
            source = self.database(f'message/message_{number}.db', [
                ('CREATE TABLE Name2Id(user_name)', ()),
                ("INSERT INTO Name2Id VALUES('wxid_test')", ()),
                (f'CREATE TABLE {self.table}(local_id, local_type, create_time, real_sender_id, message_content, server_id)', ())])
            self.shards.append(str(source))
        self.layout = Layout('v4', str(self.account), self.account.name, self.shards,
                             str(self.contact), media_root=str(self.account / 'msg'))

    def database(self, relative, statements):
        from sqlcipher3 import dbapi2
        path = self.account / 'db_storage' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(relative.encode()).hexdigest()
        db = dbapi2.connect(str(path))
        db.execute('PRAGMA key = "x\'' + key + '\'"')
        db.execute('PRAGMA cipher_compatibility=4')
        for sql, args in statements:
            db.execute(sql, args)
        db.commit()
        with path.open('rb') as stream:
            self.keys[stream.read(16).hex()] = key
        self.live.append(db)
        return path

    def message(self, shard, local_id, kind, body, stamp=1700000000):
        # Contacts are live[0], then the two shards.
        db = self.live[shard + 1]
        db.execute(f'INSERT INTO {self.table} VALUES(?,?,?,?,?,?)', (local_id, kind, stamp, 1, body, str(stamp + local_id)))
        db.commit()

    def resources(self):
        image_hash, video_hash = 'a' * 32, 'b' * 32
        self.database('message/message_resource.db', [
            ('CREATE TABLE ChatName2Id(user_name)', ()),
            ("INSERT INTO ChatName2Id VALUES('filehelper')", ()),
            ("INSERT INTO ChatName2Id VALUES('other')", ()),
            ('CREATE TABLE MessageResourceInfo(chat_id, message_local_id, message_local_type, packed_info)', ()),
            ('INSERT INTO MessageResourceInfo VALUES(2,3,43,?)', (('c' * 32).encode(),)),
            ('INSERT INTO MessageResourceInfo VALUES(1,2,3,?)', (image_hash.encode(),)),
            ('INSERT INTO MessageResourceInfo VALUES(1,3,43,?)', (video_hash.encode(),))])
        from PIL import Image
        from Crypto.Cipher import AES
        out = io.BytesIO(); Image.new('RGB', (16, 16), (23, 67, 180)).save(out, format='PNG')
        self.png = out.getvalue()
        pad = 16 - len(self.png) % 16
        data = reader.image_dat.V1_SIG + struct.pack('<II', len(self.png), 0) + b'\x00'
        data += AES.new(reader.image_dat.V1_KEY, AES.MODE_ECB).encrypt(self.png + bytes([pad]) * pad)
        self.image_file = self.account / 'msg/attach' / hashlib.md5(self.peer.encode()).hexdigest() / '2023-11/Img' / (image_hash + '.dat')
        self.image_file.parent.mkdir(parents=True, exist_ok=True); self.image_file.write_bytes(data)
        self.video_file = self.account / 'msg/video/2023-11' / (video_hash + '.mp4')
        self.video_file.parent.mkdir(parents=True, exist_ok=True)
        import av
        with av.open(str(self.video_file), 'w') as container:
            stream = container.add_stream('mpeg4', rate=1)
            stream.width = 16; stream.height = 16; stream.pix_fmt = 'yuv420p'
            frame = av.VideoFrame.from_image(Image.new('RGB', (16, 16), 'green'))
            for packet in stream.encode(frame): container.mux(packet)
            for packet in stream.encode(): container.mux(packet)

    def export(self):
        with patch.object(reader, 'load_connection', return_value=(self.layout, self.keys)):
            return reader.export_wechat_mac('文件传输助手', self.root / 'out', log=lambda _: None)

    def test_all_shards_wal_text_image_video_and_archive(self):
        self.resources()
        self.message(0, 1, 1, '  完整文字\n第二行  ')
        self.message(0, 2, 3, '<msg><img/></msg>')
        self.message(0, 3, 43, '<msg><videomsg/></msg>')
        # Keep the WAL open/uncheckpointed to catch immutable-source omissions.
        self.live[2].execute('PRAGMA journal_mode=WAL')
        self.live[2].execute('PRAGMA wal_autocheckpoint=0')
        import zstandard
        compressed = zstandard.ZstdCompressor().compress('最新分片消息'.encode())
        self.message(1, 1, 1, compressed, 1700000050)
        before = {str(p): p.read_bytes() for p in (self.account / 'db_storage').rglob('*') if p.is_file()}
        source = self.export()
        data = json.loads(source.read_text())
        self.assertEqual(len(data['messages']), 4)
        self.assertEqual(data['messages'][0]['content'], '  完整文字\n第二行  ')
        self.assertEqual(data['messages'][-1]['content'], '最新分片消息')
        media = [m['media'] for m in data['messages'] if 'media' in m]
        self.assertTrue(all(m['available'] for m in media), media)
        self.assertEqual((source.parent / media[0]['path']).read_bytes(), self.png)
        self.assertEqual((source.parent / media[1]['path']).read_bytes(), self.video_file.read_bytes())
        result = bundle_wechat(source, self.root / 'archive', transcribe=False, log=lambda _: None)
        self.assertEqual(result['messageCount'], 4)
        rows = [json.loads(s) for s in (self.root / 'archive/messages.jsonl').read_text().splitlines()]
        self.assertEqual(len({r['id'] for r in rows}), 4)
        self.assertEqual(result['media']['image'], 1)
        self.assertEqual(result['media']['video'], 1)
        for path, value in before.items(): self.assertEqual(Path(path).read_bytes(), value)

    def test_wrong_shard_key_stops_without_partial_archive(self):
        self.message(0, 1, 1, 'must not partially export')
        with Path(self.shards[1]).open('rb') as stream:
            self.keys.pop(stream.read(16).hex())
        with self.assertRaisesRegex(ValueError, '分片'):
            self.export()
        self.assertFalse((self.root / 'out/source/chat_full_parsed.json').exists())

    def test_no_order_based_image_guess_and_missing_video(self):
        self.resources()
        self.message(0, 99, 3, '<msg><img/></msg>')
        self.message(0, 3, 43, '<msg><videomsg/></msg>')
        self.video_file.unlink()
        records = json.loads(self.export().read_text())['messages']
        self.assertTrue(all(not m['media']['available'] for m in records))

    def test_cancel_does_not_read_database(self):
        stop = threading.Event(); stop.set()
        with self.assertRaises(reader.Cancelled), patch.object(reader, 'copy_database') as copy:
            reader.validate_keys(self.layout, self.keys, stop)
        copy.assert_not_called()

    def test_v2_account_key_and_image_decode(self):
        from Crypto.Cipher import AES
        from PIL import Image
        uin = 12345678
        suffix = hashlib.md5(str(uin).encode()).hexdigest()[:4]
        account = self.root / 'Documents/xwechat_files' / ('wxid_test_' + suffix)
        layout = Layout('v4', str(account), account.name)
        cache = self.root / 'Documents/app_data/cache/kvcomm'
        cache.mkdir(parents=True)
        (cache / f'key_{uin}_example.statistic').touch()
        key, xor = reader.image_dat.derive_image_key(layout)
        self.assertEqual(key, hashlib.md5(f'{uin}wxid_test'.encode()).hexdigest()[:16])
        buffer = io.BytesIO(); Image.new('RGB', (16, 16), 'red').save(buffer, format='PNG')
        data = buffer.getvalue(); first, middle, tail = data[:32], data[32:-8], data[-8:]
        frame = reader.image_dat.V2_SIG + struct.pack('<II', 32, 8) + b'\0'
        frame += AES.new(key.encode(), AES.MODE_ECB).encrypt(first + bytes([16]) * 16)
        frame += middle + bytes(b ^ xor for b in tail)
        self.assertEqual(reader.image_dat.decode_to_displayable(frame, key, xor)[0], data)
        other = Layout('v4', str(account.with_name('wxid_other_ffff')), 'wxid_other_ffff')
        self.assertEqual(reader.image_dat.derive_image_key(other), (None, None))

    def test_repeated_shard_ids_never_borrow_each_others_media(self):
        self.resources()
        self.message(0, 2, 3, '<msg><img/></msg>')
        self.message(1, 2, 3, '<msg><img/></msg>', 1700000300)
        data = json.loads(self.export().read_text())
        self.assertTrue(all(not m['media']['available'] for m in data['messages']))


class SetupTests(unittest.TestCase):
    def test_prepare_requires_explicit_consent_without_touching_wechat(self):
        with patch.object(setup.sys, 'platform', 'darwin'), patch.object(setup, 'admin') as admin:
            with self.assertRaisesRegex(ValueError, '勾选'): setup.prepare(False)
            admin.assert_not_called()

    def test_running_wechat_is_never_signed_or_quit(self):
        with patch.object(setup.sys, 'platform', 'darwin'), patch.object(setup, 'scanner_path', return_value=Path(__file__)), patch.object(setup, 'app_path', return_value=Path('/Applications/WeChat.app')), patch.object(setup, 'running_pid', return_value=123), patch.object(setup, 'admin') as admin:
            with self.assertRaisesRegex(ValueError, '退出微信'): setup.prepare(True)
            admin.assert_not_called()

    def test_private_keys_are_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'keys.json'
            reader.private_json(path, {'test': 'synthetic'})
            if os.name != 'nt': self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_admin_failure_does_not_leak_backend_output(self):
        import subprocess
        response = subprocess.CompletedProcess([], 1, b'private material', b'private material')
        with patch.object(setup.subprocess, 'run', return_value=response):
            with self.assertRaises(ValueError) as caught: setup.admin(['/a path/test', "x'$(false)"])
            self.assertNotIn('private material', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
