"""Reusable local QCE adapter. No account login or cloud transcription implemented here."""
from __future__ import annotations
import json, pathlib, zipfile, hashlib, shutil, time, datetime, urllib.request, urllib.parse, threading, csv, re, wave, io
from collections import Counter
ROOT=pathlib.Path(__file__).resolve().parent
class Cancelled(Exception):pass

def child_python():
 import sys
 exe=pathlib.Path(sys.executable)
 console=exe.with_name('python.exe')
 return str(console) if exe.name.lower()=='pythonw.exe' and console.is_file() else str(exe)


def child_command(helper, *args):
 import sys
 if helper not in ('filepicker', 'wechat_worker', 'wechat_connect'):raise ValueError('Unknown helper')
 if getattr(sys, 'frozen', False):return [sys.executable, '--helper', helper, *map(str,args)]
 return [child_python(), str(ROOT/(helper+'.py')), *map(str,args)]


def write_json(path,data):
 path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
def safe_child(root,name):
 name=str(name)
 if pathlib.PureWindowsPath(name).drive or pathlib.PureWindowsPath(name).root:raise ValueError('非法文件路径')
 root=pathlib.Path(root).resolve();p=(root/name.replace('\\','/')).resolve()
 if not p.is_relative_to(root):raise ValueError('非法文件路径')
 return p

def emojis(s):
 # Keep variation selectors, skin tones, keycaps, flags, and ZWJ sequences intact.
 out=[];i=0
 def base(c):return 0x1F000<=ord(c)<=0x1FAFF or 0x2600<=ord(c)<=0x27BF or c in '©®™'
 while i<len(s):
  c=s[i];keycap=c in '#*0123456789' and i+1<len(s) and (s[i+1]=='\u20e3' or s[i+1:i+3]=='\ufe0f\u20e3')
  if not base(c) and not keycap:i+=1;continue
  j=i+1
  if 0x1F1E6<=ord(c)<=0x1F1FF and j<len(s) and 0x1F1E6<=ord(s[j])<=0x1F1FF:j+=1
  while j<len(s):
   if s[j] in ('\ufe0f','\ufe0e','\u20e3') or 0x1F3FB<=ord(s[j])<=0x1F3FF:j+=1
   elif s[j]=='\u200d' and j+1<len(s) and base(s[j+1]):j+=2
   else:break
  out.append(s[i:j]);i=j
 return out

class QCEError(RuntimeError):
 def __init__(self,message,status=None):
  super().__init__(message);self.status=status

class QCE:
 def __init__(self,base='http://127.0.0.1:40653',token='',timeout=60):
  u=urllib.parse.urlsplit(base)
  if u.scheme!='http' or u.hostname not in ('localhost','127.0.0.1','::1') or u.username or u.password:raise ValueError('QCE地址必须是本机HTTP地址')
  self.timeout=timeout;self.base=base.rstrip('/');self.token=token;self.op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 def request(self,path,body=None):
  if not path.startswith('/') or path.startswith('//'):raise ValueError('非法API路径')
  req=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
  try:
   with self.op.open(req,timeout=self.timeout) as r:result=json.load(r)
  except urllib.error.HTTPError as e:raise QCEError(f'QCE HTTP {e.code}：请打开 QQ 原版导出界面检查登录和令牌；确认有效后再连接',e.code) from None
  except urllib.error.URLError:raise RuntimeError('无法连接 QQ 导出服务：请先安装并启动 QQ 导出组件，在终端扫码登录；仅打开普通 QQ 无法连接。若已启动，请核对 QCE 地址与端口。') from None
  if not result.get('success',True):raise RuntimeError(str(result.get('error') or result.get('message') or 'QCE请求失败'))
  return result.get('data',result)
 def health(self):
  data=self.request('/health')
  if not isinstance(data,dict) or data.get('status')!='healthy' or data.get('mode') not in ('plugin','standalone'):
   raise QCEError('这个端口没有返回受支持的 QQChatExporter 状态，请核对服务地址')
  return data
 def sessions(self):
  # Upstream recent-contacts is an optional special-contact supplement.
  # A bridge error there must not hide the working friends and groups lists.
  try:contacts=self.request('/api/recent-contacts?limit=2000').get('contacts',[])
  except RuntimeError:contacts=[]
  seen={(int(c['chatType']),str(c['peerUid'])) for c in contacts}
  for kind,endpoint,key in [(1,'friends','friends'),(2,'groups','groups')]:
   page=1
   while True:
    d=self.request(f'/api/{endpoint}?page={page}&limit=2000')
    for f in d.get(key,[]):
     uid=str(f.get('uid') or f.get('groupCode') or '')
     if uid and (kind,uid) not in seen:
      contacts.append({'chatType':kind,'peerUid':uid,'name':f.get('remark') or f.get('groupName') or f.get('nick') or f.get('nickname') or uid});seen.add((kind,uid))
    if not d.get('hasNext'):break
    page+=1
  return [c for c in contacts if int(c.get('chatType',0)) in (1,2)]
 def export(self,peer,dest,filter_,log,stop,roaming=False):
  dest=pathlib.Path(dest);dest.mkdir(parents=True,exist_ok=True);source=dest/'source';source.mkdir(exist_ok=True)
  paths=[];tasks=[]
  for fmt,endpoint in [('JSON','/api/messages/export'),('STREAMING_ZIP','/api/messages/export-streaming-zip')]:
   body={'peer':{'chatType':int(peer['chatType']),'peerUid':str(peer['peerUid'])},'sessionName':peer.get('name') or peer.get('peerName') or '聊天','format':fmt,'filter':filter_,'options':{'outputDir':str(source.resolve()),'includeResourceLinks':True,'includeSystemMessages':True,'skipDownloadResourceTypes':[],'skipFileDownload':False}}
   if roaming:endpoint='/api/messages/roaming/export'
   log('创建 QCE '+fmt+' 导出任务');task=self.request(endpoint,body);tid=task['taskId'];tasks.append(tid)
   while True:
    if stop.is_set():self.request('/api/tasks/'+urllib.parse.quote(tid,safe='')+'/cancel',{});raise Cancelled('已停止QCE任务')
    state=self.request('/api/tasks/'+urllib.parse.quote(tid,safe=''));status=state.get('status')
    if status=='completed':break
    if status in ('failed','cancelled','error'):raise RuntimeError('QCE导出未完成：'+str(state.get('message',status)))
    log(fmt+'：'+str(state.get('progress',0))+'% '+str(state.get('message','')));stop.wait(2)
   path=pathlib.Path(state.get('filePath') or task['filePath'])
   if not path.is_file():raise RuntimeError('QCE没有返回本机可读取的导出文件：'+str(path))
   paths.append(path)
   if state.get('roamingScan',{}).get('partial'):log('注意：QCE漫游结果可能不完整')
  return paths

def load_messages(source):
 source=pathlib.Path(source)
 if source.is_file() and source.suffix.lower()=='.zip':
  with zipfile.ZipFile(source) as z:
   for n in z.namelist():
    if n.endswith('manifest.json'):
     meta=json.loads(z.read(n));prefix=n[:-len('manifest.json')]
     if 'chunked' not in meta:continue
     msgs=[]
     for c in meta['chunked']['chunks']:
      msgs.extend(json.loads(l) for l in z.read(prefix+c['relativePath']).decode('utf-8-sig').splitlines() if l.strip())
     return validate_messages(meta,msgs)
  raise ValueError('不是QCE JSONL压缩包；请另选结构化消息文件')
 if source.is_dir():
  meta=json.loads((source/'manifest.json').read_text(encoding='utf-8-sig'));msgs=[]
  for c in meta['chunked']['chunks']:
   f=safe_child(source,c['relativePath']);msgs.extend(json.loads(l) for l in f.read_text(encoding='utf-8-sig').splitlines() if l.strip())
 elif source.suffix.lower()=='.jsonl':
  meta={};msgs=[json.loads(l) for l in source.read_text(encoding='utf-8-sig').splitlines() if l.strip()]
 else:
  meta=json.loads(source.read_text(encoding='utf-8-sig'));msgs=meta.get('messages',[])
 return validate_messages(meta,msgs)

def validate_messages(meta,msgs):
 if not msgs:raise ValueError('没有找到消息')
 if len({str(m['id']) for m in msgs})!=len(msgs):raise ValueError('消息ID重复，不能可靠关联媒体和转写')
 expected=meta.get('statistics',{}).get('totalMessages')
 if expected is not None and expected!=len(msgs):raise ValueError('消息数量与导出清单不一致')
 return meta,msgs

class Transcriber:
 def __init__(self,model):
  import numpy as np
  from faster_whisper import WhisperModel
  self.np=np;self.model=WhisperModel(model,device='cpu',compute_type='int8',cpu_threads=4)
 def run(self,path):
  np=self.np
  if path.suffix.lower()=='.wav':
   with wave.open(str(path)) as w:
    if w.getsampwidth()!=2:raise ValueError('WAV不是PCM16')
    rate=w.getframerate();channels=w.getnchannels();a=np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16).astype(np.float32)/32768
    if channels>1:a=a.reshape(-1,channels).mean(axis=1)
   if rate!=16000:a=np.interp(np.arange(round(len(a)*16000/rate))*rate/16000,np.arange(len(a)),a).astype(np.float32)
  else:
   import av
   chunks=[];resampler=av.audio.resampler.AudioResampler(format='s16',layout='mono',rate=16000)
   with av.open(str(path),mode='r') as container:
    for frame in container.decode(audio=0):
     for res in resampler.resample(frame):chunks.append(res.to_ndarray().reshape(-1))
    for res in resampler.resample(None):chunks.append(res.to_ndarray().reshape(-1))
   a=np.concatenate(chunks).astype(np.float32)/32768 if chunks else np.zeros(0,dtype=np.float32)
  if len(a)==0:return ''
  segments,_=self.model.transcribe(a,language='zh',beam_size=5,vad_filter=True,condition_on_previous_text=False)
  return ''.join(s.text for s in segments).strip()

def bundle(source,media_zip,dest,model='',transcribe=True,log=print,stop=None,cache_seed=None):
 stop=stop or threading.Event();dest=pathlib.Path(dest).resolve();dest.mkdir(parents=True,exist_ok=True)
 meta,msgs=load_messages(source);log(f'读取 {len(msgs)} 条消息')
 media_root=dest/'resources';media_root.mkdir(exist_ok=True);allfiles=[]
 with zipfile.ZipFile(media_zip) as z:
  if z.testzip():raise ValueError('媒体ZIP校验失败')
  native=json.loads(z.read('data/manifest.json'))
  native_ids=set()
  for c in native['chunks']:
   for line in z.read(c['file']).decode('utf-8-sig').splitlines():
    line=line.strip().rstrip(',')
    if line.startswith('{"id":'):native_ids.add(str(json.loads(line)['id']).removeprefix('msg-'))
  if native_ids!={str(m['id']) for m in msgs}:raise ValueError('消息文件和媒体ZIP的消息ID不一致，请选择同一会话和日期范围的两份导出')
  for n in z.namelist():
   if n.startswith('resources/') and not n.endswith('/'):
    path=safe_child(dest,n);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(z.read(n))
    allfiles.append(path)
 # Exact original filename/stem or QCE's hash_filename naming, never size/time guessing.
 file_index={}
 for f in allfiles:
  file_index.setdefault(f.name.lower(),[]).append(f)
  if '_' in f.name:file_index.setdefault(f.name.split('_',1)[1].lower(),[]).append(f)
  if f.suffix.lower()=='.wav':
   stem=f.stem.split('_',1)[-1];file_index.setdefault(stem+'.amr',[]).append(f);file_index.setdefault(stem+'.silk',[]).append(f)
 cache_file=dest/'transcription-cache.json';cache=json.loads(cache_file.read_text(encoding='utf-8')) if cache_file.exists() else {};engine=None
 seed=cache_seed or {};normalized=[];attachments=[];stats=Counter();voice_states=Counter()
 for i,m in enumerate(msgs):
  if stop.is_set():raise Cancelled('处理已停止；已完成的转写已保存，使用同一输出目录可继续')
  content=m.get('content',{});elements=content.get('elements',[]);parts=[];body=[];voice_text=[];seen_media=set()
  for e in elements:
   typ=e.get('type');d=e.get('data') or {}
   if typ=='text':
    t=str(d.get('text') or d.get('content') or '');parts.append(t);body.append({'type':'text','text':t})
   elif typ in ('image','audio','video','file'):
    fn=str(d.get('filename') or '');kind='sticker' if typ=='image' and d.get('subType')=='sticker' else typ
    if (typ,fn) in seen_media:continue
    seen_media.add((typ,fn));candidates=list(dict.fromkeys(file_index.get(fn.lower(),[])));path=candidates[0] if len(candidates)==1 else None
    item={'type':kind,'filename':fn,'path':path.relative_to(dest).as_posix() if path else None,'available':bool(path),'md5':d.get('md5'),'duration':d.get('duration')};stats[kind]+=1
    if not path:stats['missing_'+kind]+=1
    if typ=='audio':
     digest=hashlib.sha256(path.read_bytes()).hexdigest() if path else None;key=f'{m["id"]}:{digest}:{model}'
     prior=m.get('voiceTranscription') or {};prior_text=prior.get('text') or content.get('voiceTranscript')
     if prior.get('status') in ('完成','未识别出语音'):
      result={'status':prior['status'],'text':prior.get('text',''),'origin':'source','machineGenerated':True}
     elif str(m['id']) in seed and seed[str(m['id'])].get('状态') in ('完成','未识别出语音'):
      sr=seed[str(m['id'])];result={'status':sr['状态'],'text':sr['转写'],'origin':'seed','machineGenerated':True}
     elif key in cache and cache[key]['status'] in ('完成','未识别出语音'):result=cache[key]
     elif not path:result={'status':'缺失音频','text':''}
     elif not transcribe:result={'status':'未转写','text':''}
     else:
      if engine is None:
       if not model:raise ValueError('请选择已下载的Whisper模型目录或模型名称')
       log('加载本地语音模型');engine=Transcriber(model)
      try:
       text=engine.run(path);result={'status':'完成' if text else '未识别出语音','text':text,'model':model,'machineGenerated':True}
      except Exception as exc:result={'status':'失败','text':'','error':str(exc)}
      cache[key]=result;write_json(cache_file,cache)
     item['transcription']=result;voice_states[result['status']]+=1
     if result['text']:voice_text.append(result['text'])
    body.append(item);attachments.append({'messageId':str(m['id']),**item})
   elif typ in ('face','emoji','marketface','sticker'):
    body.append({'type':'qqemoji','text':str(d.get('text') or d.get('name') or '['+str(d.get('id') or d.get('faceIndex') or d.get('faceId') or typ)+']'),'data':d});stats['qqemoji']+=1
   elif typ=='reply':body.append({'type':'reply','text':str(d.get('text') or d.get('content') or '[引用回复]'),'data':d})
  if not parts and not body:body=[{'type':'text','text':str(content.get('text',''))}];parts=[str(content.get('text',''))]
  text=''.join(parts);unicode_emoji=emojis(text);stats['unicodeEmoji']+=len(unicode_emoji)
  sender=m.get('sender') or {};normalized.append({'id':str(m['id']),'timestamp':m.get('timestamp'),'time':m.get('time'),'sender':sender,'system':bool(m.get('system') or m.get('type')=='system'),'text':text,'voiceText':'\n'.join(voice_text),'analysisText':'\n'.join([t for t in [text,*voice_text] if t]),'emoji':unicode_emoji,'parts':body,'original':m})
  if i%100==0 or i==len(msgs)-1:log(f'处理消息 {i+1}/{len(msgs)}，语音：'+str(dict(voice_states)))
 return save_archive(normalized,attachments,meta,dest,dict(stats),dict(voice_states),log=log)

def save_archive(normalized,attachments,meta,dest,stats,voice_states,platform='QQ',exporter='QQChatExporter',log=print):
 dest=pathlib.Path(dest);msgs=normalized

 with (dest/'messages.jsonl').open('w',encoding='utf-8') as f:
  for m in normalized:f.write(json.dumps(m,ensure_ascii=False)+'\n')
 write_json(dest/'media-manifest.json',attachments)
 summary={'format':'chatarchive/1','platform':platform,'chat':meta.get('chatInfo',{}),'messageCount':len(msgs),'firstTime':msgs[0].get('time'),'lastTime':msgs[-1].get('time'),'media':stats,'voiceTranscription':dict(voice_states),'historyCompleteness':'unknown','sourceExporter':exporter,'originalMediaNotRecoverable':True}
 write_json(dest/'manifest.json',summary)
 with (dest/'analysis.txt').open('w',encoding='utf-8') as f:
  for m in normalized:
   if not m['system'] and m['analysisText']:f.write(f'[{m["time"]}] {m["sender"].get("name","未知")}：{m["analysisText"]}\n')
 data=dest/'data';data.mkdir(exist_ok=True);chunks=[]
 for i in range(0,len(normalized),1000):
  name=f'messages-{i//1000:05d}.js';chunks.append('data/'+name);view=[{k:v for k,v in m.items() if k!='original'} for m in normalized[i:i+1000]]
  encoded=json.dumps(view,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029');(data/name).write_text('window.CHAT.push(...'+encoded+');',encoding='utf-8')
 template=(ROOT/'viewer.html').read_text(encoding='utf-8');template=template.replace('<!--CHUNKS-->',''.join('<script src="'+x+'"></script>' for x in chunks))
 (dest/'index.html').write_text(template,encoding='utf-8');log('完成：'+str(dest/'index.html'));return summary
