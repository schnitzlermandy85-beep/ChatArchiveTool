"""Exercise the actual local HTTP analysis workflow and its privacy boundary."""
import datetime
import json
import pathlib
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from web_app import Controller, make_server
from test_core import test_directory


def fixture(root):
    archive = pathlib.Path(root) / 'archive'
    archive.mkdir()
    start = datetime.datetime(2026, 10, 1, 10, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    records = []
    for i, text in enumerate(['最近有点累', '想聊聊吗？', '谢谢你愿意听', '我们周末见面吧', '好，周六下午', '到时候联系']):
        stamp = start + datetime.timedelta(minutes=i * 2)
        records.append({'id':str(i + 1), 'timestamp':int(stamp.timestamp() * 1000), 'time':stamp.isoformat(),
                        'sender':{'uid':'a' if i % 2 == 0 else 'b', 'name':'真实姓名甲' if i % 2 == 0 else '真实姓名乙', 'isSelf':i % 2 == 0},
                        'analysisText':text, 'text':text, 'voiceText':'', 'system':False, 'parts':[{'type':'text', 'text':text}]})
    (archive / 'messages.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in records), encoding='utf-8')
    return archive


class RelationshipWebTests(unittest.TestCase):
    def wait_done(self, controller):
        deadline = time.monotonic() + 8
        while controller.snapshot()['busy'] and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertFalse(controller.snapshot()['busy'])

    def test_preview_required_and_cloud_consent_before_request(self):
        with test_directory() as root:
            c = Controller()
            archive = fixture(root)
            with self.assertRaises(ValueError):
                c.start_analysis({'mode':'local', 'previewId':'invented'})
            preview = c.prepare_analysis({'archive':str(archive), 'relationship':'partner'})
            public = json.dumps(preview, ensure_ascii=False)
            self.assertNotIn('真实姓名甲', public)
            self.assertNotIn(str(archive), public)
            with patch('web_app.analyze_prepared') as call:
                with self.assertRaises(ValueError):
                    c.start_analysis({'mode':'ai','previewId':preview['previewId'], 'endpoint':'https://example.com/v1/chat/completions','model':'test','apiKey':'never-save-secret', 'consent':False})
                call.assert_not_called()
            self.assertNotIn('never-save-secret', json.dumps(c.snapshot()))
            c.analysis_preview['created'] -= 901
            with self.assertRaises(ValueError):
                c.start_analysis({'mode':'local','previewId':preview['previewId']})

    def test_all_relationships_generate_report_without_network(self):
        with test_directory() as root:
            archive = fixture(root)
            c = Controller()
            for relationship in ('friend','family','partner','best_friend'):
                preview = c.prepare_analysis({'archive':str(archive),'relationship':relationship})
                with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Local analysis must not use network')):
                    c.start_analysis({'mode':'local','previewId':preview['previewId']})
                    self.wait_done(c)
                state = c.snapshot()
                self.assertEqual(state['status'], 'complete', state['stage'])
                self.assertTrue(state['analysisResult'])
                html = (c.analysis_last / 'report.html').read_text(encoding='utf-8')
                self.assertNotIn('真实姓名甲', html)
                self.assertIn('离线', html)
                self.assertEqual(state['analysisReportUrl'], '/analysis/report.html')

    def test_http_authenticated_inspect_prepare_start_and_report(self):
        with test_directory() as root:
            archive = fixture(root)
            c = Controller()
            server = make_server(c)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = 'http://127.0.0.1:' + str(server.server_port)
            def request(path, payload=None, authenticated=True, cookie=''):
                headers = {'X-Archive-Token':server.auth} if authenticated else {}
                if cookie: headers['Cookie'] = cookie
                if payload is not None: headers['Content-Type'] = 'application/json'
                return urllib.request.urlopen(urllib.request.Request(base + path, data=None if payload is None else json.dumps(payload).encode(), headers=headers), timeout=5)
            try:
                with request('/') as response:
                    cookie = response.headers['Set-Cookie'].split(';')[0]
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request('/api/analysis/inspect', {}, authenticated=False)
                self.assertEqual(error.exception.code, 403)
                with request('/api/analysis/inspect', {'archive':str(archive)}) as response:
                    inspected = json.load(response)
                self.assertEqual(len(inspected['participants']), 2)
                with request('/api/analysis/prepare', {'archive':str(archive), 'relationship':'friend', 'customPrompt':'重点分析主动联系，并提供消息证据。'}) as response:
                    preview = json.load(response)
                self.assertIn('重点分析主动联系', preview['preview']['systemPrompt'])
                with request('/api/analysis/start', {'previewId':preview['previewId'],'mode':'local'}) as response:
                    self.assertTrue(json.load(response)['ok'])
                self.wait_done(c)
                with self.assertRaises(urllib.error.HTTPError): request('/analysis/report.html')
                with request('/analysis/report.html', cookie=cookie) as response:
                    self.assertIn('text/html', response.headers['Content-Type'])
                    self.assertIn('frame-ancestors', response.headers['Content-Security-Policy'])
                with self.assertRaises(urllib.error.HTTPError): request('/analysis/../messages.jsonl', cookie=cookie)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)

    def test_real_compatible_api_transport_and_explicit_failure_report(self):
        captured=[]
        invalid={'value':False}
        class CompatibleAPI(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                captured.append((self.path,body,self.headers.get('Authorization')))
                supplied=json.loads(body['messages'][1]['content'])
                messages=supplied['messages']
                portraits=[]
                for person in supplied['participants']:
                    evidence=next(m['id'] for m in messages if m['participantId']==person['id'])
                    portraits.append({'participantId':person['id'],'description':'在这些文字里表达了日常需求。','strengths':['愿意表达'],'communicationNeeds':['可以确认回应方式'],'evidenceIds':[evidence]})
                result={'summary':'基于提供片段的沟通回顾。','findings':[{'title':'共同安排','observation':'片段出现了见面安排。','interpretation':'可以进一步确认双方的期待。','alternatives':['记录可能缺少线下交流。'],'evidenceIds':['invented'] if invalid['value'] else [messages[0]['id']]}],'portraits':portraits,'suggestions':['与对方核对具体语境。']}
                encoded=json.dumps({'choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)}}]},ensure_ascii=False).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
        provider=ThreadingHTTPServer(('127.0.0.1',0),CompatibleAPI)
        thread=threading.Thread(target=provider.serve_forever,daemon=True);thread.start()
        try:
            with test_directory() as root:
                archive=fixture(root);c=Controller()
                for fail in (False,True):
                    invalid['value']=fail
                    preview=c.prepare_analysis({'archive':str(archive),'relationship':'partner'})
                    c.start_analysis({'previewId':preview['previewId'],'mode':'ai','endpoint':f'http://127.0.0.1:{provider.server_port}/v1','model':'test-model','apiKey':'test','consent':True})
                    self.wait_done(c)
                    state=c.snapshot()
                    self.assertEqual(state['status'],'complete',state['stage'])
                    self.assertEqual(state['analysisSummary']['mode'],'local_fallback' if fail else 'ai')
                    report=(c.analysis_last/'report-data.json').read_text(encoding='utf-8')
                    self.assertNotIn('apiKey',report)
                    self.assertEqual(captured[-1][1]['messages'][1]['content'],preview['preview']['payloadText'])
                    self.assertEqual(captured[-1][2],'Bearer test')
                    self.assertNotIn('真实姓名甲',json.dumps(captured[-1][1],ensure_ascii=False))
                    self.assertNotIn('真实姓名乙',json.dumps(captured[-1][1],ensure_ascii=False))
                self.assertEqual(len(captured),2)
        finally:
            provider.shutdown();provider.server_close();thread.join(2)

    def test_full_date_range_over_multiple_real_api_requests(self):
        captured=[]
        class FullAPI(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                supplied=json.loads(body['messages'][1]['content'])
                captured.append((self.path,body,supplied))
                by_person={}
                def collect(value):
                    if isinstance(value,list):
                        for item in value:collect(item)
                    elif isinstance(value,dict):
                        if value.get('participantId') in ('P1','P2'):
                            ids=[value['id']] if 'id' in value else value.get('evidenceIds',[])
                            by_person.setdefault(value['participantId'],[]).extend(ids)
                        for item in value.values():collect(item)
                collect(supplied)
                people=supplied.get('participants') or [{'id':person} for person in by_person]
                portraits=[{'participantId':person['id'],'description':'在文字中表达共同安排。','strengths':['表达安排'],'communicationNeeds':['确认联系预期'],'evidenceIds':[by_person[person['id']][0]]}
                           for person in people if by_person.get(person['id'])]
                ids=list(dict.fromkeys(mid for values in by_person.values() for mid in values))
                result={'summary':'基于全部批次的沟通回顾。','findings':[{'title':'共同安排','observation':'出现共同安排的文字。','interpretation':'可讨论联系预期。','alternatives':['线下交流可补充语境。'],'evidenceIds':ids[:2]}],'portraits':portraits,'suggestions':['核对双方的联系预期。']}
                encoded=json.dumps({'choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)}}]},ensure_ascii=False).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
        provider=ThreadingHTTPServer(('127.0.0.1',0),FullAPI)
        thread=threading.Thread(target=provider.serve_forever,daemon=True);thread.start()
        try:
            with test_directory() as root:
                archive=fixture(root)
                path=archive/'messages.jsonl'
                originals=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
                records=[]
                for index in range(32):
                    message=dict(originals[index%2])
                    message.update(id=f'source-{index}',time=f'2026-10-01T10:{index:02d}:00+08:00',analysisText='周末一起计划见面。'+('沟通背景。'*220))
                    records.append(message)
                outside=dict(records[0],id='outside',time='2026-09-30T10:00:00+08:00')
                media=dict(records[0],id='media',analysisText='',text='',parts=[{'type':'image'}])
                path.write_text('\n'.join(json.dumps(record,ensure_ascii=False) for record in [outside,*records,media]),encoding='utf-8')
                c=Controller()
                preflight=c.prepare_analysis({'archive':str(archive),'relationship':'friend','begin':'2026-10-01','end':'2026-10-01','batchChars':8000})
                preview=preflight['preview']
                self.assertEqual(preview['coverage']['sentMessageCount'],32)
                self.assertGreater(len(preview['batches']),1)
                c.start_analysis({'previewId':preflight['previewId'],'mode':'ai','endpoint':f'http://127.0.0.1:{provider.server_port}/compatible','model':'demo','apiKey':'dem','consent':True})
                self.wait_done(c)
                state=c.snapshot()
                self.assertEqual(state['status'],'complete',state['stage'])
                self.assertEqual(state['analysisSummary']['mode'],'ai',state['stage'])
                batches=captured[:len(preview['batches'])]
                sent=[message['id'] for _,_,payload in batches for message in payload['messages']]
                self.assertEqual(len(sent),32)
                self.assertEqual(len(set(sent)),32)
                self.assertEqual(set(sent),{message['id'] for message in preview['sample']})
                for expected,(_,request,payload) in zip(preview['batches'],batches):
                    self.assertEqual(request['messages'][0]['content'],expected['systemPrompt'])
                    self.assertEqual(request['messages'][1]['content'],expected['payloadText'])
                public=json.loads((c.analysis_last/'report-data.json').read_text(encoding='utf-8'))
                self.assertEqual(public['coverage']['analyzedTextMessageCount'],32)
                self.assertNotIn('evidence',public)
                self.assertNotIn('preview',public)
                self.assertNotIn('原文证据',(c.analysis_last/'report.html').read_text(encoding='utf-8'))
                self.assertTrue(all(path=='/compatible/chat/completions' for path,_,_ in captured))
        finally:
            provider.shutdown();provider.server_close();thread.join(2)


if __name__ == '__main__':
    unittest.main()
