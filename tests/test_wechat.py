import json,pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from test_core import test_directory
from wechat_adapter import bundle_wechat,timestamp_ms

class WeChatTests(unittest.TestCase):
 def fixture(self,p):
  media=p/'media';media.mkdir();(media/'pic.jpg').write_bytes(b'test-image');(media/'face.gif').write_bytes(b'test-sticker');(media/'voice.wav').write_bytes(b'test-voice')
  def msg(i,code,content,media=None,**kw):
   return {'source_db':'message_0.db','local_id':i,'server_id':100+i,'sort_seq':i,'type_code':code,'time':'2026-10-01 10:00:00','sender':'好友','sender_username':'wxid_friend','is_self':False,'sender_status':'resolved','content':content,'media':media,**kw}
  messages=[msg(1,1,'你好👩🏽‍💻❤️'),msg(2,3,'[图片]',{'kind':'image','path':'media/pic.jpg'}),msg(3,47,'[动画表情]',{'kind':'sticker','path':'media/face.gif','md5':'abc'}),msg(4,34,'[语音]',{'kind':'voice','path':'media/voice.wav'}),msg(5,34,'[语音]',None,transcript='微信已有的语音文字',transcript_source='wechat'),msg(6,3,'[图片]',{'kind':'image','available':False,'reason':'已过期'}),msg(7,10000,'拍了拍'),msg(8,1,'未知身份',sender_status='unmapped_sender_id')]
  source=p/'chat_full_parsed.json';source.write_text(json.dumps({'exporter_version':'1.3.4','chat_name':'合成测试会话','chat_type':'private','message_count':len(messages),'messages':messages},ensure_ascii=False),encoding='utf-8');return source
 def test_media_transcription_identity_and_resume(self):
  with test_directory() as d:
   p=pathlib.Path(d);source=self.fixture(p)
   with patch('wechat_adapter.Transcriber') as transcriber:
    transcriber.return_value.run.return_value='新的语音文字'
    stats=bundle_wechat(source,p/'out',model='test',log=lambda _:None)
    transcriber.return_value.run.assert_called_once()
   with patch('wechat_adapter.Transcriber',side_effect=AssertionError('cached')):bundle_wechat(source,p/'out',model='test',log=lambda _:None)
   rows=[json.loads(l) for l in (p/'out/messages.jsonl').read_text(encoding='utf-8').splitlines()]
   self.assertEqual(stats['platform'],'WeChat');self.assertEqual(stats['media']['sticker'],1);self.assertEqual(stats['media']['unicodeEmoji'],2);self.assertEqual(stats['media']['missing_image'],1)
   by_id={r['original']['local_id']:r for r in rows}
   self.assertEqual(stats['voiceTranscription'],{'完成':2});self.assertTrue(by_id[7]['system']);self.assertEqual(by_id[8]['sender']['resolutionStatus'],'unmapped_sender_id');self.assertEqual(by_id[4]['analysisText'],'新的语音文字');self.assertEqual(by_id[5]['voiceText'],'微信已有的语音文字')
   for r in rows:
    for part in r['parts']:
     if part.get('available'):self.assertTrue((p/'out'/part['path']).is_file())
 def test_import_does_not_modify_source(self):
  with test_directory() as d:
   p=pathlib.Path(d);source=self.fixture(p);before=source.read_bytes();bundle_wechat(source,p/'out',transcribe=False,log=lambda _:None);self.assertEqual(source.read_bytes(),before)
 def test_media_path_escape_rejected(self):
  with test_directory() as d:
   p=pathlib.Path(d);source=self.fixture(p);meta=json.loads(source.read_text(encoding='utf-8'));meta['messages'][1]['media']['path']='../outside.jpg';source.write_text(json.dumps(meta),encoding='utf-8')
   with self.assertRaises(ValueError):bundle_wechat(source,p/'out',transcribe=False,log=lambda _:None)
 def test_date_filter(self):
  with test_directory() as d:
   p=pathlib.Path(d);source=self.fixture(p)
   with self.assertRaisesRegex(ValueError,'日期范围'):bundle_wechat(source,p/'out',transcribe=False,log=lambda _:None,filters={'startTime':timestamp_ms('2026-10-02')//1000})
 def test_duplicate_id_rejected(self):
  with test_directory() as d:
   p=pathlib.Path(d);source=self.fixture(p);meta=json.loads(source.read_text(encoding='utf-8'));meta['messages'].append(meta['messages'][0]);meta['message_count']+=1;source.write_text(json.dumps(meta),encoding='utf-8')
   with self.assertRaisesRegex(ValueError,'ID重复'):bundle_wechat(source,p/'out',transcribe=False,log=lambda _:None)
 def test_timestamp_timezone(self):
  self.assertEqual(timestamp_ms('2026-10-01 08:00:00'),timestamp_ms('2026-10-01T00:00:00Z'))
 def test_worker_local_sticker_and_contact_ambiguity(self):
  import types,hashlib,base64,xml.etree.ElementTree as ET
  import wechat_worker
  with test_directory() as d:
   p=pathlib.Path(d);account=p/'account';account.mkdir()
   data=base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7');digest=hashlib.md5(data).hexdigest();(account/(digest+'.gif')).write_bytes(data)
   row={'local_id':1,'_db_rel':'message.db','local_type':47,'create_time':1,'message_content':'<msg><emoji md5="'+digest+'"/></msg>'}
   fake=types.SimpleNamespace(load_rows=lambda db,u:[row],low_type=lambda n:n,decode_blob=lambda v:v or '',xml_root=lambda v:ET.fromstring(v))
   db=types.SimpleNamespace(account_dir=str(account),search_contact=lambda k:[{'username':'wxid_friend','remark':k}])
   def export(keyword,out,**options):
    fake.find_contact(db,keyword);rows=fake.load_rows(db,'wxid_friend');out=pathlib.Path(out);out.mkdir();source=out/'chat_full_parsed.json';source.write_text(json.dumps({'messages':[{'source_db':r['_db_rel'],'local_id':r['local_id']} for r in rows]}));return {'json':str(source)}
   fake.export_chat=export
   config=p/'request.json';config.write_text(json.dumps({'runtime':str(p),'keyword':'好友','out':str(p/'export'),'cancel':str(p/'cancel')}))
   # Use installed Pillow only for worker verification; archive import itself stays stdlib.
   from wechat_adapter import runtime_path
   with patch.dict(sys.modules,{'exporter_core':fake}):
    sys.path.insert(0,str(runtime_path()))
    try:
     wechat_worker.run(config)
     msg=json.loads((p/'export/chat_full_parsed.json').read_text(encoding='utf-8'))['messages'][0];self.assertTrue(msg['media']['available']);self.assertEqual(msg['media']['md5'],digest)
     db.search_contact=lambda k:[{'remark':k},{'remark':k}]
     with self.assertRaisesRegex(ValueError,'唯一匹配'):fake.find_contact(db,'同名')
    finally:sys.path.remove(str(runtime_path()))

if __name__=='__main__':unittest.main()
