import json,pathlib,sys,threading,time,unittest,urllib.request,urllib.error
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from web_app import Controller,make_server,date_filter
from test_core import test_directory

class WebTests(unittest.TestCase):
 def test_local_server_starts_without_reverse_dns(self):
  with patch('socket.getfqdn',side_effect=AssertionError('No DNS during startup')):
   server=make_server()
   try:
    self.assertEqual(server.server_address[0],'127.0.0.1')
    self.assertEqual(server.server_name,'localhost')
    self.assertGreater(server.server_port,0)
   finally:server.server_close()
 def test_date_timezone_and_validation(self):
  result=date_filter('2026-10-01','2026-10-01')
  self.assertEqual(result['endTime']-result['startTime'],86399)
  with self.assertRaises(ValueError):date_filter('2026-10-02','2026-10-01')
 def test_export_state_stop_and_complete(self):
  c=Controller();c.token='private-test-token';c.sessions=[{'chatType':1,'peerUid':'test','name':'合成测试'}]
  entered=threading.Event();release=threading.Event()
  def merge(*a):
   a[5]('处理消息 4/10，语音：测试');entered.set();release.wait(3)
   return {'messageCount':10,'voiceTranscription':{'完成':2}}
  class Client:
   def __init__(self,*a):pass
   def export(self,*a):return 'mock.json','mock.zip'
  with test_directory() as d,patch('web_app.QCE',Client),patch('web_app.bundle',side_effect=merge):
   c.start({'platform':'QQ','mode':'direct','session':0,'output':d})
   self.assertTrue(entered.wait(2));self.assertEqual(c.snapshot()['progress'],40)
   with self.assertRaises(ValueError):c.start({'platform':'QQ','mode':'direct','session':0,'output':d})
   release.set()
   for _ in range(100):
    if not c.snapshot()['busy']:break
    time.sleep(.01)
   state=c.snapshot();self.assertEqual(state['status'],'complete');self.assertEqual(state['messageCount'],10);self.assertEqual(state['voiceCount'],2);self.assertTrue(state['result']);self.assertNotIn('private-test-token',json.dumps(state))
 def test_http_assets_auth_origin_and_archive(self):
  with test_directory() as d:
   c=Controller();c.last=pathlib.Path(d);(c.last/'index.html').write_text('<script>window.test=1</script>',encoding='utf-8')
   server=make_server(c);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
   def get(path,headers=None):return urllib.request.urlopen(urllib.request.Request(base+path,headers=headers or {}),timeout=2)
   try:
    with get('/') as r:
     html=r.read().decode();cookie=r.headers['Set-Cookie'].split(';')[0]
     self.assertIn(server.auth,html);self.assertIn('让每段聊天',html);self.assertIn('HttpOnly',r.headers['Set-Cookie'])
    with get('/style.css') as r:self.assertEqual(r.status,200)
    with self.assertRaises(urllib.error.HTTPError):get('/api/state')
    with get('/api/state',{'X-Archive-Token':server.auth}) as r:self.assertFalse(json.load(r)['busy'])
    request=urllib.request.Request(base+'/api/stop',data=b'{}',headers={'X-Archive-Token':server.auth,'Content-Type':'application/json','Origin':'https://unrelated.example'})
    with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(request)
    self.assertEqual(e.exception.code,403)
    with self.assertRaises(urllib.error.HTTPError):get('/archive/index.html')
    with get('/archive/index.html',{'Cookie':cookie}) as r:self.assertIn("'unsafe-inline'",r.headers['Content-Security-Policy'])
    with self.assertRaises(urllib.error.HTTPError):get('/archive/../app.py',{'Cookie':cookie})
   finally:server.shutdown();server.server_close();thread.join(2)

if __name__=='__main__':unittest.main()
