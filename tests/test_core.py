import json,pathlib,tempfile,threading,unittest,zipfile,sys
from unittest.mock import patch
from contextlib import contextmanager
import uuid,shutil
@contextmanager
def test_directory():
 root=pathlib.Path(__file__).resolve().parents[1]/".test-work"
 root.mkdir(exist_ok=True);p=root/uuid.uuid4().hex;p.mkdir()
 try:yield str(p)
 finally:
  if p.resolve().is_relative_to(root.resolve()):shutil.rmtree(p)

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from core import safe_child,emojis,load_messages,bundle,QCE,Cancelled

class ArchiveTests(unittest.TestCase):
 def test_path_escape(self):
  with test_directory() as d:
   with self.assertRaises(ValueError):safe_child(d,'../escape')
   with self.assertRaises(ValueError):safe_child(d,'C:/Windows/escape')
 def test_emoji_clusters(self):
  self.assertEqual(emojis('你好👩🏽‍💻 🇨🇳 1️⃣ ❤️'),['👩🏽‍💻','🇨🇳','1️⃣','❤️'])
 def test_duplicate_chunk_ids(self):
  with test_directory() as d:
   p=pathlib.Path(d);(p/'manifest.json').write_text(json.dumps({'chunked':{'chunks':[{'relativePath':'chunk.jsonl'}]}}));(p/'chunk.jsonl').write_text('{"id":"1"}\n{"id":"1"}')
   with self.assertRaises(ValueError):load_messages(p)
 def fixture(self,p,native_id='1'):
  m={'id':'1','timestamp':1000,'time':'1970-01-01T00:00:01Z','sender':{'name':'A'},'content':{'elements':[{'type':'audio','data':{'filename':'abc.amr'}}]}}
  source=p/'source.json';source.write_text(json.dumps({'messages':[m]}));media=p/'media.zip'
  with zipfile.ZipFile(media,'w') as z:
   z.writestr('data/manifest.json',json.dumps({'chunks':[{'file':'data/chunks/a.js'}]}));z.writestr('data/chunks/a.js',json.dumps({'id':'msg-'+native_id})+'\n');z.writestr('resources/audios/hash_abc.wav',b'fake-test-audio')
  return source,media
 def test_pairing_rejected(self):
  with test_directory() as d:
   p=pathlib.Path(d);a,b=self.fixture(p,'2')
   with self.assertRaises(ValueError):bundle(a,b,p/'out',transcribe=False,log=lambda _:None)
 def test_transcript_resume_and_merge(self):
  with test_directory() as d:
   p=pathlib.Path(d);a,b=self.fixture(p)
   with patch('core.Transcriber') as engine:
    engine.return_value.run.return_value='测试语音'
    bundle(a,b,p/'out',model='test',log=lambda _:None)
    engine.return_value.run.assert_called_once()
   with patch('core.Transcriber',side_effect=AssertionError('should reuse cache')):
    bundle(a,b,p/'out',model='test',log=lambda _:None)
   record=json.loads((p/'out/messages.jsonl').read_text(encoding='utf-8').splitlines()[0]);self.assertEqual(record['analysisText'],'测试语音');self.assertEqual(record['parts'][0]['transcription']['status'],'完成');self.assertTrue((p/'out/resources/audios/hash_abc.wav').exists())
 def test_cancel_qce_task(self):
  client=QCE();event=threading.Event();event.set()
  with test_directory() as d,patch.object(client,'request',side_effect=[{'taskId':'a'},{}]) as request:
   with self.assertRaises(Cancelled):client.export({'chatType':1,'peerUid':'u'},d,{},lambda _:None,event)
   self.assertEqual(request.call_args.args[0],'/api/tasks/a/cancel')

if __name__=='__main__':unittest.main()
