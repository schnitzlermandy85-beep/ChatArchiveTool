"""WeChat upstream process bridge and chatarchive/1 normalizer."""
from __future__ import annotations
import pathlib,json,subprocess,sys,os,queue,threading,hashlib,shutil,datetime
from collections import Counter
from core import ROOT,Cancelled,Transcriber,write_json,safe_child,emojis,save_archive,child_python

def runtime_path():
 local=ROOT/'.wechat-packages'
 return local if local.exists() else ROOT.parent.parent/'work/wechat-runtime/packages'

def export_wechat(keyword,dest,db_dir='',log=print,stop=None,filters=None):
 stop=stop or threading.Event();dest=pathlib.Path(dest).resolve();dest.mkdir(parents=True,exist_ok=True)
 if not keyword.strip():raise ValueError('请输入微信好友准确备注、昵称、wxid或群名')
 if not (runtime_path()/'wechatauto').exists():raise RuntimeError('微信导出依赖尚未安装，请先点击“安装微信组件”')
 request=dest/'wechat-request.json';cancel=dest/'wechat-cancel';cancel.unlink(missing_ok=True)
 write_json(request,{'keyword':keyword.strip(),'out':str(dest/'source'),'db_dir':db_dir or None,'cancel':str(cancel),'runtime':str(runtime_path()),'filters':filters or {}})
 env=os.environ.copy();env['PYTHONIOENCODING']='utf-8';env['PYTHONUTF8']='1'
 events=queue.Queue()
 process=subprocess.Popen([child_python(),str(ROOT/'wechat_worker.py'),str(request)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 def reader():
  try:
   for line in process.stdout:events.put(line.rstrip())
  finally:events.put(None)
 threading.Thread(target=reader,daemon=True).start();result=None;error=None;sent=False
 while True:
  if stop.is_set() and not sent:
   cancel.write_text('cancel',encoding='ascii');sent=True;log('正在停止微信导出，等待当前读取阶段结束并清理临时缓存…')
  try:line=events.get(timeout=.2)
  except queue.Empty:continue
  if line is None:break
  if line.startswith('CHATARCHIVE_RESULT:'):result=json.loads(line.split(':',1)[1])
  elif line.startswith('CHATARCHIVE_ERROR:'):error=line.split(':',1)[1]
  else:log(line)
 code=process.wait();request.unlink(missing_ok=True);cancel.unlink(missing_ok=True)
 if stop.is_set():raise Cancelled('微信导出已停止，临时缓存清理流程已执行')
 if code or not result:raise RuntimeError(error or '微信导出组件失败，请检查Windows微信版本及登录状态')
 return pathlib.Path(result['json'])

def timestamp_ms(value):
 if isinstance(value,(int,float)):return int(value if value>10**11 else value*1000)
 d=datetime.datetime.fromisoformat(str(value).replace('Z','+00:00'))
 if d.tzinfo is None:d=d.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
 return int(d.timestamp()*1000)

def bundle_wechat(source,dest,model='',transcribe=True,log=print,stop=None,filters=None):
 stop=stop or threading.Event();filters=filters or {};source=pathlib.Path(source).resolve()
 if source.is_dir():source=source/'chat_full_parsed.json'
 meta=json.loads(source.read_text(encoding='utf-8-sig'))
 if not isinstance(meta,dict) or 'exporter_version' not in meta or not isinstance(meta.get('messages'),list):raise ValueError('请选择wechat-chat-export导出的chat_full_parsed.json或它所在的文件夹')
 original=meta['messages'];expected=meta.get('message_count')
 if expected is not None and expected!=len(original):raise ValueError('微信消息数与导出清单不一致')
 dest=pathlib.Path(dest).resolve();dest.mkdir(parents=True,exist_ok=True)
 cache_file=dest/'transcription-cache.json';cache=json.loads(cache_file.read_text(encoding='utf-8')) if cache_file.exists() else {};engine=None
 records=[];attachments=[];stats=Counter();voices=Counter();seen=set()
 for i,m in enumerate(original):
  if stop.is_set():raise Cancelled('已停止整合，已保存的语音转写可继续使用')
  stamp=timestamp_ms(m.get('timestamp') if m.get('timestamp') is not None else m['time'])
  if stamp<filters.get('startTime',0)*1000 or stamp>filters.get('endTime',2**63)*1000:continue
  identity=[m.get('source_db'),m.get('local_id'),m.get('server_id'),m.get('sort_seq')]
  if all(v is None for v in identity):raise ValueError('微信消息缺少稳定ID，无法可靠关联转写')
  mid='wx-'+hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
  if mid in seen:raise ValueError('微信消息ID重复，请核对来源数据库与local_id')
  seen.add(mid);rawtype=m.get('type_code',1)
  try:code=int(rawtype);code=code & 0xff if code>0xffff else code
  except (ValueError,TypeError):code=1
  media=m.get('media') or {};text=str(m.get('content') or '')
  kind={3:'image',34:'audio',43:'video',62:'video',47:'sticker'}.get(code)
  if not kind and media:kind={'voice':'audio','emoji':'sticker'}.get(media.get('kind'),media.get('kind'))
  parts=[];voice='';item=None
  if text and text not in ('[图片]','[语音]','[视频]','[动画表情]'):parts.append({'type':'text','text':text})
  else:text=''
  if kind in ('image','audio','video','sticker','file'):
   path=None;name=pathlib.Path(str(media.get('path') or '')).name
   if media.get('path'):
    candidate=safe_child(source.parent,str(media['path']))
    if candidate.is_file():
     digest=hashlib.sha256(candidate.read_bytes()).hexdigest();out=safe_child(dest,'resources/'+kind+'/'+digest+candidate.suffix.lower());out.parent.mkdir(parents=True,exist_ok=True)
     if candidate!=out:shutil.copyfile(candidate,out)
     path=out
   item={'type':kind,'filename':name or '['+kind+']','available':bool(path),'path':path.relative_to(dest).as_posix() if path else None,'md5':media.get('md5'),'duration':media.get('duration'),'reason':media.get('reason')}
   stats[kind]+=1
   if not path:stats['missing_'+kind]+=1
   if kind=='audio':
    prior=m.get('transcript') or media.get('transcript') or '';key=mid+':'+(hashlib.sha256(path.read_bytes()).hexdigest() if path else 'missing')+':'+model
    if prior:result={'status':'完成','text':str(prior),'origin':m.get('transcript_source') or 'source','machineGenerated':True}
    elif key in cache and cache[key]['status'] in ('完成','未识别出语音'):result=cache[key]
    elif not path:result={'status':'缺失音频','text':''}
    elif path.suffix.lower()=='.silk':result={'status':'解码失败','text':'','error':'保留SILK原文件，需安装rust-silk解码器后重新导出'}
    elif not transcribe:result={'status':'未转写','text':''}
    else:
     if engine is None:log('加载本地语音模型');engine=Transcriber(model)
     try:
      transcript=engine.run(path);result={'status':'完成' if transcript else '未识别出语音','text':transcript,'model':model,'machineGenerated':True}
     except Exception as e:result={'status':'失败','text':'','error':str(e)}
     cache[key]=result;write_json(cache_file,cache)
    item['transcription']=result;voices[result['status']]+=1;voice=result['text']
   parts.append(item);attachments.append({'messageId':mid,**item})
  if not parts:parts=[{'type':'text','text':text or str(m.get('content') or '[消息]')}]
  emoji=emojis(text);stats['unicodeEmoji']+=len(emoji)
  sender={'uid':m.get('sender_username'),'name':m.get('sender') or '未知发送者','isSelf':m.get('is_self'),'resolutionStatus':m.get('sender_status')}
  records.append({'id':mid,'timestamp':stamp,'time':datetime.datetime.fromtimestamp(stamp/1000,datetime.timezone.utc).isoformat(),'sender':sender,'system':code==10000,'text':text,'voiceText':voice,'analysisText':'\n'.join(t for t in [text,voice] if t),'emoji':emoji,'parts':parts,'original':m})
  if i%100==0:log(f'整合微信消息 {i+1}/{len(original)}')
 if not records:raise ValueError('所选日期范围内没有微信消息')
 records.sort(key=lambda m:m['timestamp'])
 metadata={'chatInfo':{'name':meta.get('chat_name'),'type':meta.get('chat_type')}}
 result=save_archive(records,attachments,metadata,dest,dict(stats),dict(voices),platform='WeChat',exporter='wechat-chat-export',log=log)
 result['senderResolutionCounts']=dict(Counter(m['sender']['resolutionStatus'] or 'unknown' for m in records));result['filter']=filters
 write_json(dest/'manifest.json',result);return result
