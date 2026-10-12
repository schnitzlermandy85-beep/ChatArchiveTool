import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import screenshot_import as mod

class ScreenshotTests(unittest.TestCase):
 def setUp(self):
  self.service=mod.ScreenshotImport();self.generation=self.service.reset()['generation']
  self.output=tempfile.TemporaryDirectory()
 def tearDown(self):
  self.service.temp.cleanup();self.output.cleanup()
 def upload(self):
  stream=io.BytesIO();Image.new('RGB',(200,300),'white').save(stream,format='PNG')
  with patch.object(mod,'capability',return_value=True),patch.object(mod.subprocess,'run') as run:
   run.return_value.returncode=0
   run.return_value.stdout=json.dumps([{'text':'测试文字','confidence':.9,'box':[.1,.2,.3,.1]}]).encode()
   result=self.service.upload({'generation':self.generation,'data':base64.b64encode(stream.getvalue()).decode()})
  return result['id']
 def payload(self,image):
  return {'generation':self.generation,'reviewed':True,'output':self.output.name,'order':[image],
   'rows':[{'image':image,'box':[.1,.2,.3,.1],'text':'人工核对文字 <script>','sender':'self','kind':'text','time':''}]}
 def test_unknown_time_and_source_preserved(self):
  image=self.upload();p=self.payload(image);target,summary=self.service.export(p)
  row=json.loads((target/'messages.jsonl').read_text())
  self.assertIsNone(row['timestamp']);self.assertEqual(row['time'],'时间未知')
  self.assertFalse(summary['analysisEligible']);self.assertEqual(summary['historyCompleteness'],'screenshots_only')
  self.assertTrue((target/row['original']['path']).is_file())
  self.assertNotIn('<script>',(target/'data/messages-00000.js').read_text())
 def test_analysis_rejects_partial_dates(self):
  from relationship import prepare_analysis
  image=self.upload();p=self.payload(image)
  p['rows'] += [{**p['rows'][0],'sender':'other','time':'2026-10-10T09:31:00+08:00'},
                {**p['rows'][0],'sender':'self','time':'2026-10-10T09:32:00+08:00'}]
  target,_=self.service.export(p)
  with self.assertRaisesRegex(ValueError,'未知时间'):prepare_analysis(target,'friend',{'selfId':'screenshot:self'})
 def test_crop_and_confirmed_time(self):
  image=self.upload();p=self.payload(image);r=p['rows'][0];r.update(kind='sticker',time='2026-10-10T09:30:00+08:00')
  target,summary=self.service.export(p)
  with Image.open(target/'media/screenshot-00001.png') as im:self.assertEqual(im.size,(60,30))
  self.assertTrue(summary['analysisEligible']);self.assertTrue(json.loads((target/'media-manifest.json').read_text())[0]['isScreenshotCrop'])
 def test_review_required_and_invalid_input_never_published(self):
  image=self.upload();p=self.payload(image)
  for edit in [{'reviewed':False},{'generation':'old'},{'order':['../bad']}]:
   with self.assertRaises(ValueError):self.service.export({**p,**edit})
  for edit in [{'box':[0,0,2,1]},{'box':[0,0,float('nan'),1]},{'time':'2026-10-10T09:30:00'},{'image':'../bad'},{'sender':'arbitrary'}]:
   with self.assertRaises(ValueError):self.service.export({**p,'rows':[{**p['rows'][0],**edit}]})
  self.assertEqual(list(Path(self.output.name).iterdir()),[])
 def test_reset_invalidates_previous_draft(self):
  image=self.upload();p=self.payload(image);self.service.reset()
  with self.assertRaises(ValueError):self.service.export(p)
 def test_corrupt_image_rejected(self):
  with patch.object(mod,'capability',return_value=True):
   with self.assertRaises(ValueError):self.service.upload({'generation':self.generation,'data':base64.b64encode(b'not an image').decode()})
 def test_repeated_export_does_not_overwrite(self):
  image=self.upload();p=self.payload(image);a,_=self.service.export(p);b,_=self.service.export(p)
  self.assertNotEqual(a,b);self.assertTrue((a/'messages.jsonl').exists())
if __name__=='__main__':unittest.main()
