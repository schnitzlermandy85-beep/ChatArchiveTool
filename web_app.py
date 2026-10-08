"""Local-only application server for the desktop web interface."""
from __future__ import annotations
import datetime,hashlib,json,mimetypes,os,pathlib,re,secrets,subprocess,sys,threading,time,urllib.parse,webbrowser
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from socketserver import TCPServer
from core import ROOT,QCE,bundle,Cancelled,safe_child,child_command
from wechat_adapter import export_wechat,bundle_wechat,runtime_path
from relationship import inspect_archive,prepare_analysis,analyze_prepared
from relationship_report import write_report
import desktop_exporters
from platform_support import data_root,wechat_supported,require_wechat_support,open_folder,voice_available

def model_path():
 for root in [ROOT/'models',ROOT.parent.parent/'work/voice-runtime/models']:
  for p in root.glob('models--Systran--faster-whisper-small/snapshots/*'):
   if (p/'model.bin').exists():return str(p)
 return 'small'

def date_filter(begin='',end=''):
 result={}
 for value,key,tail in [(begin,'startTime',False),(end,'endTime',True)]:
  if not value:continue
  try:d=datetime.datetime.strptime(value,'%Y-%m-%d').replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
  except ValueError:raise ValueError('日期请使用 YYYY-MM-DD 格式') from None
  if tail:d+=datetime.timedelta(days=1,seconds=-1)
  result[key]=int(d.timestamp())
 if result.get('startTime',0)>result.get('endTime',2**63):raise ValueError('开始日期不能晚于结束日期')
 return result

class Controller:
 def __init__(self):
  self.lock=threading.RLock();self.stop=threading.Event();self.last=None;self.sessions=[];self.token='';self.logs=[];self.seq=0
  self.analysis_last=None;self.analysis_preview=None
  self.state={'busy':False,'operation':None,'status':'ready','stage':'准备好后，开始创建你的聊天档案。','progress':None,'messageCount':None,'voiceCount':None,'result':False,'summary':None,'connection':'未连接','wechatSupported':wechat_supported(),'wechatReady':wechat_supported() and (runtime_path()/'wechatauto').exists()}
  self.state.update(desktop_exporters.status())
  if sys.platform=='darwin':self.state['wechatReady']=self.state['wechatInstalled'] and self.state['wechatConfigured']
  self.state.update(analysisArchive='',analysisResult=False,analysisReportUrl='',analysisSummary=None)
  security=pathlib.Path.home()/'.qq-chat-exporter/security.json'
  if security.exists():
   try:self.token=json.loads(security.read_text(encoding='utf-8'))['accessToken']
   except Exception:pass
 def snapshot(self):
  with self.lock:
   self.state.update(desktop_exporters.status())
   if sys.platform=='darwin':self.state['wechatReady']=self.state['wechatInstalled'] and self.state['wechatConfigured']
  with self.lock:return {**self.state,'logs':list(self.logs),'sessions':[{'index':i,'name':str(c.get('remark') or c.get('name') or c.get('peerName') or c['peerUid']),'kind':'群聊' if int(c['chatType'])==2 else '私聊'} for i,c in enumerate(self.sessions)]}
 def log(self,message):
  with self.lock:
   self.seq+=1;self.logs.append({'id':self.seq,'time':datetime.datetime.now().strftime('%H:%M:%S'),'text':str(message)});self.logs=self.logs[-160:]
   if self.state['status']=='running':
    self.state['stage']=str(message)
    match=re.search(r'(?:处理消息|整合微信消息)\s+(\d+)/(\d+)',str(message));percent=re.search(r'：\s*(\d+(?:\.\d+)?)%',str(message))
    analysis_batch=re.search(r'AI (?:分析)?批次\s+(\d+)/(\d+)',str(message))
    if self.state['operation']=='analyze' and analysis_batch:self.state['progress']=min(int(analysis_batch[1])/max(int(analysis_batch[2]),1)*85,85)
    elif self.state['operation']=='analyze' and '正在综合' in str(message):self.state['progress']=90
    elif self.state['operation']=='analyze' and '正在绘制' in str(message):self.state['progress']=95
    elif match:self.state.update(progress=min(int(match[1])/max(int(match[2]),1)*100,100),messageCount=int(match[1]))
    elif percent:self.state['progress']=min(float(percent[1]),100)
    elif '创建 QCE' in str(message) or '加载本地语音模型' in str(message):self.state['progress']=None
 def launch(self,operation,job):
  with self.lock:
   if self.state['busy']:raise ValueError('已有任务正在运行，请等待完成或停止任务')
   self.stop.clear();self.state.update(busy=True,operation=operation,status='running',stage='正在准备，请稍候。',progress=None)
   if operation not in ('connect','analyze'):self.state.update(messageCount=None,voiceCount=None)
  def run():
   try:job()
   except Cancelled as e:
    self.log(str(e))
    with self.lock:self.state.update(status='stopped',stage=str(e),progress=None)
   except Exception as e:
    self.log(str(e))
    with self.lock:
     self.state.update(status='error',stage=str(e),progress=None)
     if operation=='connect':self.state['connection']='连接失败'
   finally:
    with self.lock:self.state['busy']=False
  threading.Thread(target=run,daemon=True).start()
 def connect(self,payload):
  token=payload.get('token') or desktop_exporters.refresh_qce_token() or self.token
  client=QCE(payload.get('address') or 'http://127.0.0.1:40653',token)
  def job():
   sessions=client.sessions()
   with self.lock:self.token=token;self.sessions=sessions;self.state.update(connection=f'已连接 · {len(sessions)} 个会话',status='connected',stage='选择一个好友或群聊，即可开始导出。')
   self.log(f'已读取 {len(sessions)} 个会话')
  self.launch('connect',job)
 def start(self,p):
  platform=p.get('platform');mode=p.get('mode');transcribe=bool(p.get('transcribe',True))
  if platform not in ('QQ','WeChat') or mode not in ('direct','import'):raise ValueError('请选择QQ或微信以及导出方式')
  if not str(p.get('output') or '').strip():raise ValueError('请选择保存位置')
  dest=pathlib.Path(p['output']).expanduser().resolve();model=str(p.get('model') or model_path());filters=date_filter(p.get('begin',''),p.get('end','')) if mode=='direct' else {}
  client=peer=None;keyword=str(p.get('keyword') or '').strip();dbdir=str(p.get('dbDir') or '').strip();src=str(p.get('source') or '').strip();media=str(p.get('media') or '').strip();roaming=bool(p.get('roaming',False))
  if mode=='direct' and platform=='QQ':
   index=p.get('session')
   with self.lock:
    if type(index) is not int or not 0<=index<len(self.sessions):raise ValueError('请先连接QQ并选择好友或群聊')
    peer=dict(self.sessions[index])
   client=QCE(p.get('address') or 'http://127.0.0.1:40653',p.get('token') or self.token)
   if roaming and (int(peer['chatType'])!=1 or len(filters)!=2):raise ValueError('私聊漫游需要填写完整日期范围')
   identity=[platform,peer['chatType'],peer['peerUid'],filters]
  elif mode=='direct':
   require_wechat_support()
   if not keyword:raise ValueError('请填写微信好友准确备注、昵称或群名')
   if dbdir and not pathlib.Path(dbdir).is_dir():raise ValueError('微信数据目录不存在')
   if not self.snapshot()['wechatReady']:raise ValueError('请先安装微信组件；Mac 还需要点击初始化连接并在终端完成登录')
   identity=[platform,keyword,dbdir,filters]
  else:
   if not src or not pathlib.Path(src).exists():raise ValueError('请选择消息导出文件或目录')
   if platform=='QQ' and not pathlib.Path(media).is_file():raise ValueError('请选择同一批消息的QQ媒体ZIP')
   identity=[platform,str(pathlib.Path(src).resolve()),str(pathlib.Path(media).resolve()) if platform=='QQ' else '']
  target=dest/('chat-'+hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:12])
  def job():
   if platform=='WeChat':
    source=export_wechat(keyword,target,dbdir,self.log,self.stop,filters) if mode=='direct' else src
    summary=bundle_wechat(source,target,model,transcribe,self.log,self.stop,filters)
   else:
    a,b=client.export(peer,target,filters,self.log,self.stop,roaming) if client else (src,media)
    summary=bundle(a,b,target,model,transcribe,self.log,self.stop)
   with self.lock:
    self.last=target;self.analysis_preview=None;self.state.update(status='complete',stage='聊天档案已保存。现在可以选择关系类型，回顾你们的互动。',progress=100,messageCount=summary['messageCount'],voiceCount=summary['voiceTranscription'].get('完成',0),result=True,summary=summary,analysisArchive=str(target))
   self.log('档案已保存：'+str(target))
  self.launch('import' if mode=='import' else 'export',job)
 def inspect_analysis(self,p):
  with self.lock:
   if self.state['busy']:raise ValueError('当前任务正在运行，请等待完成后加载档案')
   source=str(p.get('archive') or self.state['analysisArchive'] or '').strip()
  if not source:raise ValueError('请先导出聊天记录，或选择已有档案文件夹')
  inspected=inspect_archive(source)
  quality=inspected['quality'];warnings=[]
  if quality.get('unresolvedSenders'):warnings.append(f"有 {quality['unresolvedSenders']} 条消息身份未确认，需要修复导出映射后分析")
  if quality.get('invalidTimes'):warnings.append(f"{quality['invalidTimes']} 条消息时间无效，将从统计中排除")
  if quality.get('isGroup') or len(inspected['participants'])!=2:warnings.append('初版仅支持两位可识别参与者的私聊')
  if any(person.get('identityFromName') for person in inspected['participants']):warnings.append('部分身份依据显示名区分，请留意改名或重名')
  quality['warnings']=warnings
  return inspected
 def prepare_analysis(self,p):
  with self.lock:
   if self.state['busy']:raise ValueError('当前任务正在运行，请等待完成后预览分析')
   source=str(p.get('archive') or self.state['analysisArchive'] or '').strip()
  if not source:raise ValueError('请选择聊天档案')
  options={key:p[key] for key in ('selfId','begin','end','customPrompt','batchChars') if key in p}
  prepared=prepare_analysis(source,p.get('relationship','friend'),options)
  preview_id=secrets.token_urlsafe(24)
  with self.lock:
   if self.state['busy']:raise ValueError('当前任务正在运行，请稍后重新预览')
   self.analysis_preview={'id':preview_id,'created':time.monotonic(),'prepared':prepared}
  return {'previewId':preview_id,'preview':prepared['preview']}
 def start_analysis(self,p):
  mode=p.get('mode','local')
  if mode not in ('local','ai'):raise ValueError('请选择本地统计或 AI 分析')
  config=None
  if mode=='ai':
   if p.get('consent') is not True:raise ValueError('请查看发送预览，并勾选允许向指定 AI 服务发送这些内容')
   from relationship import validate_api_config
   config=validate_api_config({'endpoint':p.get('endpoint',''),'model':p.get('model',''),'apiKey':p.get('apiKey','')})
  with self.lock:
   if self.state['busy']:raise ValueError('已有任务正在运行，请稍后开始分析')
   preview=self.analysis_preview
   if not preview or not secrets.compare_digest(str(p.get('previewId','')),preview['id']):raise ValueError('请先预览本次分析内容')
   if time.monotonic()-preview['created']>900:raise ValueError('预览已过期，请重新生成预览')
   prepared=preview['prepared']
   # Output is always rooted in the inspected archive, never a browser-supplied output path.
   source=pathlib.Path(prepared['_sourcePath'])
   parent=source.parent if source.is_file() else source
   target=parent/'relationship-reports'/(datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3))
   def job():
    self.log('开始关系分析：'+prepared['preview']['relationshipLabel'])
    report=analyze_prepared(prepared,config,self.log,self.stop)
    if self.stop.is_set():raise Cancelled('关系分析已停止，没有发布新报告')
    self.log('正在绘制图表与生成关系报告')
    path=pathlib.Path(write_report(report,target))
    if self.stop.is_set():raise Cancelled('关系分析已停止，新报告未设为当前结果')
    with self.lock:
     self.analysis_last=path.parent
     failed_ai=report.get('aiStatus',{}).get('state')=='failed'
     stage='AI 分析未完成，已生成本地统计报告。详情见报告与处理记录。' if failed_ai else '关系报告已生成。打开报告查看互动分析、双方形象与聊天证据。'
     self.state.update(status='complete',stage=stage,progress=100,analysisResult=True,analysisReportUrl='/analysis/report.html',analysisSummary={'relationshipLabel':report['relationshipLabel'],'mode':'local_fallback' if failed_ai else report['mode'],'messageCount':report['stats'].get('messageCount',0),'coverage':report.get('coverage',{})})
    self.log('关系报告已保存：'+str(path))
   self.launch('analyze',job)
   self.analysis_preview=None
 def install(self):
  require_wechat_support()
  if sys.platform=='darwin':
   self.component_action('install-wechat');return
  def job():
   from setup_wechat import install
   def log(s):
    if self.stop.is_set():raise Cancelled('安装已停止，可重新安装继续')
    self.log(s)
   install(data_root(ROOT)/'.wechat-packages',log)
   with self.lock:self.state.update(wechatReady=True,status='installed',stage='微信组件已就绪，可以开始导出。',progress=100)
  self.launch('install',job)
 def component_action(self,action):
  if action not in ('install-qq','start-qq','install-wechat','init-wechat','check-wechat'):raise ValueError('未知组件操作')
  def job():
   if action=='install-qq':
    desktop_exporters.install_component('qce',self.log,self.stop)
    stage='QQ 组件已安装。请先退出桌面 QQ，再点击启动服务，在终端扫码后点击连接 QQ。'
   elif action=='start-qq':
    desktop_exporters.start_qce()
    stage='已打开 QQ 导出终端；请按提示扫码登录，完成后点击连接 QQ。'
   elif action=='install-wechat':
    desktop_exporters.install_component('wxvault',self.log,self.stop)
    stage='微信 Mac 组件已安装，请点击初始化微信连接，并在终端完成授权与登录。'
   elif action=='init-wechat':
    desktop_exporters.initialize_wechat()
    stage='微信初始化已在终端打开；完成授权与登录后，返回这里检查连接。'
   else:
    desktop_exporters.run_wxvault(['sessions','--limit','1','--json'],self.stop)
    stage='微信本地读取连接已验证，请填写联系人或群名并开始导出。'
   self.log(stage)
   with self.lock:self.state.update(status='ready',stage=stage,progress=None)
  self.launch('component',job)
 def cancel(self):
  with self.lock:
   if not self.state['busy']:return
   if self.state['operation']=='connect':raise ValueError('会话读取中，请稍候')
   self.stop.set();self.state.update(status='stopping',stage='正在结束当前阶段，请稍候。已完成的档案会保留。')

class LocalHTTPServer(ThreadingHTTPServer):
 def server_bind(self):
  # HTTPServer otherwise performs reverse DNS on 127.0.0.1 during startup.
  # This local-only application never needs a network-resolved hostname.
  TCPServer.server_bind(self)
  self.server_name='localhost'
  self.server_port=self.socket.getsockname()[1]

def make_server(controller=None,port=0):
 controller=controller or Controller();auth=secrets.token_urlsafe(32)
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def send(self,code,data,typ='application/json; charset=utf-8',cookie=False,archive=False):
   if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False).encode('utf-8')
   self.send_response(code);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; media-src 'self'; frame-ancestors 'none'" if archive else "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; media-src 'self'; frame-ancestors 'none'")
   if cookie:self.send_header('Set-Cookie','archive_session='+auth+'; HttpOnly; SameSite=Strict; Path=/')
   self.end_headers();self.wfile.write(data)
  def allowed_host(self):return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
  def authenticated(self):return secrets.compare_digest(self.headers.get('X-Archive-Token',''),auth)
  def do_GET(self):
   if not self.allowed_host():self.send(403,{'error':'非法访问地址'});return
   path=urllib.parse.urlsplit(self.path).path
   if path=='/':
    template=(ROOT/'web/index.html').read_text(encoding='utf-8').replace('__ARCHIVE_TOKEN__',auth);self.send(200,template.encode(),'text/html; charset=utf-8',cookie=True)
   elif path in ('/style.css','/app.js'):
    f=ROOT/'web'/path[1:];self.send(200,f.read_bytes(),'text/css; charset=utf-8' if path.endswith('css') else 'text/javascript; charset=utf-8')
   elif path=='/api/state' and self.authenticated():self.send(200,controller.snapshot())
   elif path=='/api/config' and self.authenticated():self.send(200,{'output':str(data_root(ROOT)/'exports'),**desktop_exporters.status(),'wechatSupported':wechat_supported(),'voiceAvailable':voice_available(),'model':model_path(),'address':'http://127.0.0.1:40653','tokenDetected':bool(controller.token),'wechatReady':controller.state['wechatReady']})
   elif path.startswith('/archive/') or path.startswith('/analysis/'):
    cookie=self.headers.get('Cookie','')
    analysis_route=path.startswith('/analysis/')
    root=controller.analysis_last if analysis_route else controller.last
    if ('archive_session='+auth) not in cookie or root is None:self.send(403,{'error':'档案或报告不可用'});return
    try:
     prefix='/analysis/' if analysis_route else '/archive/'
     f=safe_child(root,urllib.parse.unquote(path[len(prefix):]))
     if not f.is_file():raise ValueError('文件不存在')
     self.send(200,f.read_bytes(),mimetypes.guess_type(f.name)[0] or 'application/octet-stream',archive=True)
    except (ValueError,OSError):self.send(404,{'error':'文件不存在'})
   else:self.send(404,{'error':'未找到请求'})
  def do_POST(self):
   origin=self.headers.get('Origin');expected=f'http://{self.headers.get("Host")}'
   if not self.allowed_host() or not self.authenticated() or (origin and origin!=expected):self.send(403,{'error':'请求验证失败'});return
   try:
    length=int(self.headers.get('Content-Length',0))
    if not 0<length<=65536 or self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('请求格式不正确')
    p=json.loads(self.rfile.read(length));path=urllib.parse.urlsplit(self.path).path
    if not isinstance(p,dict):raise ValueError('请求格式不正确')
    if path=='/api/connect':controller.connect(p)
    elif path=='/api/start':controller.start(p)
    elif path=='/api/analysis/inspect':self.send(200,controller.inspect_analysis(p));return
    elif path=='/api/analysis/prepare':self.send(200,controller.prepare_analysis(p));return
    elif path=='/api/analysis/start':controller.start_analysis(p)
    elif path=='/api/stop':controller.cancel()
    elif path=='/api/install':controller.install()
    elif path=='/api/component':controller.component_action(p.get('action'))
    elif path=='/api/browse':
     kind=p.get('kind');category=p.get('category','messages')
     if kind not in ('folder','file') or category not in ('messages','zip','model','output','db'):raise ValueError('选择器类型不正确')
     result=subprocess.run(child_command('filepicker',kind,category),capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONIOENCODING':'utf-8'},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=300)
     if result.returncode:raise ValueError('文件选择器未能打开，请在输入框中填写路径')
     self.send(200,{'path':json.loads(result.stdout)});return
    elif path=='/api/open-folder':
     if controller.last is None:raise ValueError('还没有完成的档案')
     open_folder(controller.last)
    elif path=='/api/shutdown':
     controller.stop.set()
     def close():
      while controller.snapshot()['busy']:time.sleep(.2)
      self.server.shutdown()
     threading.Thread(target=close,daemon=True).start()
    else:self.send(404,{'error':'未找到请求'});return
    self.send(200,{'ok':True})
   except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as e:self.send(400,{'error':str(e)})
 server=LocalHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True;server.controller=controller;server.auth=auth;return server

def browser_candidates():
 # Prefer a known installed browser instead of relying solely on URL association.
 if sys.platform != 'win32':return []
 bases=[pathlib.Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)')),pathlib.Path(os.environ.get('PROGRAMFILES','C:/Program Files')),pathlib.Path(os.environ.get('LOCALAPPDATA',str(pathlib.Path.home()/'AppData/Local')))]
 return [p for base in bases for suffix in ('Microsoft/Edge/Application/msedge.exe','Google/Chrome/Application/chrome.exe') if (p:=base/suffix).is_file()]

def open_browser_window(url):
 for browser in browser_candidates():
  try:
   process=subprocess.Popen([str(browser),'--app='+url,'--new-window','--window-size=1280,880'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   try:
    code=process.wait(timeout=.75)
   except subprocess.TimeoutExpired:
    return True
   # A zero exit can mean the existing browser accepted the new window.
   # A fast nonzero exit means this candidate failed; try the next one.
   if code==0:return True
  except OSError:continue
 try:return bool(webbrowser.open(url))
 except (OSError,webbrowser.Error):return False

def run(open_browser=True):
 server=make_server();url=f'http://127.0.0.1:{server.server_port}/'
 print('ChatArchive: '+url,flush=True)
 try:
  writable=data_root(ROOT)
  (writable/'logs').mkdir(parents=True,exist_ok=True)
  (writable/'logs/current-url.txt').write_text(url+'\n',encoding='utf-8')
  (writable/'打开界面.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url='+url+'"><title>打开 ChatArchive</title><p>请保持启动窗口运行。<a href="'+url+'">打开聊天工具</a></p></html>',encoding='utf-8')
 except OSError:pass
 print('Keep this window open. If no browser opens, paste the address above into a browser.',flush=True)
 def launch_browser():
  try:
   opened=open_browser_window(url)
  except Exception:
   opened=False
  if not opened:print('Browser did not open. Use the local address above or 打开界面.html.',flush=True)
 try:
  # URL associations can block while opening a browser. The local server must
  # still become available for the manual URL/HTML entry in that case.
  if open_browser:threading.Thread(target=launch_browser,daemon=True).start()
  server.serve_forever(poll_interval=.2)
 except KeyboardInterrupt:
  server.controller.stop.set()
  while server.controller.snapshot()['busy']:time.sleep(.2)
 finally:server.server_close()

if __name__=='__main__':run()
