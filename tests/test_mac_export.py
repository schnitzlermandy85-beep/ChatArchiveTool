import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error

import core
import desktop_exporters as desktop
import mac_wechat as mac
import web_app
from wechat_adapter import bundle_wechat


class MacExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.override = patch('mac_wechat.cache_root', return_value=self.cache)
        self.override.start()
        self.addCleanup(self.override.stop)
        self.addCleanup(self.temp.cleanup)
        contact = sqlite3.connect(mac.cache_file('contact/contact.db'))
        contact.execute('CREATE TABLE contact(username TEXT, nick_name TEXT, remark TEXT)')
        contact.executemany('INSERT INTO contact VALUES(?,?,?)', [('wxid_peer','同名','好友'),('wxid_me','同名','')])
        contact.commit(); contact.close()
        self.shards = {}
        for i in range(2):
            relative = f'message/message_{i}.db'
            path = mac.cache_file(relative)
            self.shards[relative] = str(path)
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE Name2Id(user_name TEXT)')
            db.executemany('INSERT INTO Name2Id VALUES(?)',[('wxid_peer',),('wxid_me',)])
            table = 'Msg_' + hashlib.md5(b'wxid_peer').hexdigest()
            db.execute(f'CREATE TABLE [{table}](local_id INTEGER, local_type INTEGER, create_time INTEGER, real_sender_id INTEGER, message_content BLOB, server_id INTEGER, sort_seq INTEGER)')
            db.executemany(f'INSERT INTO [{table}] VALUES(?,?,?,?,?,?,?)', [(n,1,1000+i*400+n,1+n%2,'合成消息 '+str(n),i*1000+n,n) for n in range(301)])
            db.commit(); db.close()

    def backend(self, args, stop=None, timeout=300):
        if args[0] == 'sessions': return {'sessions':[], 'meta':{'status':'ok'}}
        if args[0] == '--debug-source':
            return {'username':'wxid_peer','meta':{'status':'ok','unknown_shards':[], 'shard_paths':self.shards}}
        raise AssertionError(args)

    def test_full_multishard_export_keeps_real_sender_ids_and_601_plus_messages(self):
        with patch('mac_wechat.run_wxvault', side_effect=self.backend), patch('mac_wechat.own_username',return_value='wxid_me'):
            source=mac.export_wechat_mac('好友',self.root/'out',log=lambda _:None)
        exported=json.loads(source.read_text())
        self.assertEqual(exported['message_count'],602)
        self.assertEqual({r['sender_username'] for r in exported['messages']},{'wxid_me','wxid_peer'})
        self.assertTrue(any(r['is_self'] for r in exported['messages']))
        summary=bundle_wechat(source,self.root/'archive',transcribe=False,log=lambda _:None)
        self.assertEqual(summary['messageCount'],602)
        self.assertEqual(summary['senderResolutionCounts'],{'resolved':602})
        self.assertEqual(len({(m['source_db'],m['local_id']) for m in exported['messages']}),602)

    def test_dates_use_epoch_filter_and_no_default_recent_limit(self):
        with patch('mac_wechat.run_wxvault',side_effect=self.backend):
            source=mac.export_wechat_mac('wxid_peer',self.root/'out',filters={'startTime':1200,'endTime':1405},log=lambda _:None)
        rows=json.loads(source.read_text())['messages']
        self.assertEqual(len(rows),107)
        self.assertTrue(all(1200<=r['timestamp']<=1405 for r in rows))

    def test_ambiguous_names_rejected_but_exact_username_wins(self):
        with self.assertRaisesRegex(ValueError,'唯一匹配'):
            mac.exact_contact(mac.contacts(),'同名')
        self.assertEqual(mac.exact_contact(mac.contacts(),'wxid_peer')['username'],'wxid_peer')

    def test_unknown_shards_fail_instead_of_partial_success(self):
        def backend(args,*a,**k):
            data=self.backend(args)
            if args[0]=='--debug-source':data['meta']['unknown_shards']=['message/message_9.db']
            return data
        with patch('mac_wechat.run_wxvault',side_effect=backend), self.assertRaisesRegex(ValueError,'未解锁'):
            mac.export_wechat_mac('好友',self.root/'out',log=lambda _:None)
        self.assertFalse((self.root/'out/source/chat_full_parsed.json').exists())

    def test_cache_path_outside_component_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'缓存路径'):
            mac.read_snapshot(self.root/'other.db')

    def test_images_extracted_and_unsupported_voice_is_not_silently_lost(self):
        image={'type_code':3,'source_db':'message/message_1.db','local_id':8,'timestamp':1700,'_raw_xml':'<msg/>'}
        def extract(args,*a,**k):
            output=Path(args[args.index('--output')+1]);output.write_bytes(b'\x89PNG\r\n\x1a\nsynthetic')
            return {'output':str(output)}
        with patch('mac_wechat.run_wxvault',side_effect=extract):mac.add_media(image,'wxid_peer',self.root,None)
        self.assertTrue(image['media']['available'])
        self.assertTrue((self.root/image['media']['path']).is_file())
        voice={'type_code':34,'_raw_xml':'<msg/>'}
        mac.add_media(voice,'wxid_peer',self.root,None)
        self.assertFalse(voice['media']['available'])
        self.assertIn('尚不支持',voice['media']['reason'])

    def test_compressed_text_and_cancellation(self):
        import zstandard
        raw='中文压缩消息'.encode()
        self.assertEqual(mac.decode_content(zstandard.ZstdCompressor().compress(raw)),raw.decode())
        stop=threading.Event();stop.set()
        with self.assertRaises(core.Cancelled):
            list(mac.rows_from_snapshot(next(iter(self.shards.values())),'message/message_0.db','wxid_peer',{}, {},stop))

    def test_unresolved_senders_are_not_assigned_to_peer(self):
        path=next(iter(self.shards.values()))
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.execute('DELETE FROM Name2Id')
            db.commit()
        row=next(mac.rows_from_snapshot(path,'message/message_0.db','wxid_peer',{},{}))
        self.assertIsNone(row['sender_username'])
        self.assertEqual(row['sender_status'],'unresolved')


class ExportComponentTests(unittest.TestCase):
    def test_archive_traversal_and_symlinks_rejected(self):
        for name,link in [('../escape',False),('symlink',True),('C:/escape',False)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as t:
                p=Path(t);archive=p/'bad.tar.gz'
                with tarfile.open(archive,'w:gz') as tar:
                    item=tarfile.TarInfo(name)
                    if link:item.type=tarfile.SYMTYPE;item.linkname='/etc'
                    else:item.size=1
                    tar.addfile(item,None if link else io.BytesIO(b'x'))
                with self.assertRaises(ValueError):desktop.extract_archive(archive,p/'out')
                self.assertFalse((p/'escape').exists())

    def test_download_checksum_prevents_install(self):
        with tempfile.TemporaryDirectory() as t, patch('desktop_exporters.urllib.request.urlopen',return_value=io.BytesIO(b'wrong')):
            with self.assertRaisesRegex(ValueError,'SHA-256'):
                desktop.download_verified('https://example.test/file','0'*64,Path(t)/'out',log=lambda _:None)

    def test_no_terminal_launch_for_unsupported_intel(self):
        with patch.object(sys,'platform','darwin'), patch('platform.machine',return_value='x86_64'), patch('desktop_exporters.open_terminal_script') as terminal:
            with self.assertRaises(ValueError):desktop.install_component('qce')
            with self.assertRaises(ValueError):desktop.initialize_wechat()
            terminal.assert_not_called()

    def test_qq_connect_refreshes_token_created_after_app_start(self):
        controller=web_app.Controller();controller.token='old'
        with patch('desktop_exporters.refresh_qce_token',return_value='new'),patch('web_app.QCE') as qce,patch.object(controller,'launch',side_effect=lambda op,job:job()):
            qce.return_value.sessions.return_value=[]
            controller.connect({})
            self.assertEqual(qce.call_args.args[1],'new')
            self.assertEqual(controller.token,'new')
            controller.connect({'token':'explicit'})
            self.assertEqual(qce.call_args.args[1],'explicit')

    def test_qq_connection_error_explains_missing_service(self):
        qce=core.QCE()
        with patch.object(qce.op,'open',side_effect=urllib.error.URLError('refused')):
            with self.assertRaisesRegex(RuntimeError,'仅打开普通 QQ'):
                qce.sessions()

    def test_component_operations_are_allowlisted_and_busy_guarded(self):
        controller=web_app.Controller()
        with self.assertRaises(ValueError):controller.component_action('arbitrary-command')
        controller.state['busy']=True
        with patch('desktop_exporters.start_qce') as start:
            with self.assertRaises(ValueError):controller.component_action('start-qq')
            start.assert_not_called()


if __name__=='__main__':unittest.main()
