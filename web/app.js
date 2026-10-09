'use strict';
const $=id=>document.getElementById(id);
const auth=document.querySelector('meta[name="archive-token"]').content;
let platform='QQ',mode='direct',selectedSession=null,sessionItems=[],state={},lastLog=0,toastTimer,closing=false,offlineNotified=false;
let activeView='export',lastWechatStep='';
let wechatSupported=true,voiceAvailable=true,wechatMac=false;
const analysis={inspection:null,sourcePath:'',previewId:null,preview:null,mode:'local',pending:false};
function workspaceBusy(){return !!state.busy||analysis.pending;}
async function api(path,body){
 const options={headers:{'X-Archive-Token':auth}};
 if(body!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}
 const response=await fetch('/api/'+path,options);let data;
 try{data=await response.json();}catch{throw new Error('工具连接已断开，请重新启动。');}
 if(!response.ok)throw new Error(data.error||'请求未完成，请重试。');
 return data;
}
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,5000);}
function closeMenu(){$('session-menu').hidden=true;$('session-button').setAttribute('aria-expanded','false');}
function selectSession(item){selectedSession=item.index;$('session-button').querySelector('span').textContent=item.kind+' · '+item.name;$('session-button').classList.add('has-value');closeMenu();refreshReadiness();$('session-button').focus();}
function renderSessions(){
 const query=$('session-search').value.trim().toLowerCase();const items=sessionItems.filter(c=>(c.name+' '+c.kind).toLowerCase().includes(query));
 $('session-options').replaceChildren();
 for(const item of items){const button=document.createElement('button');button.type='button';button.className='session-option';button.setAttribute('role','option');button.setAttribute('aria-selected',String(selectedSession===item.index));const kind=document.createElement('span');kind.className='session-kind';kind.textContent=item.kind;const name=document.createElement('span');name.className='session-name';name.textContent=item.name;button.append(kind,name);button.addEventListener('click',()=>selectSession(item));$('session-options').append(button);}
 if(!items.length){const p=document.createElement('p');p.className='menu-empty';p.textContent='没有匹配的好友或群聊';$('session-options').append(p);}
 $('session-total').textContent=items.length+' 个会话';
}
function updatePlatform(){
 if(platform==='WeChat'&&!wechatSupported&&mode==='direct'){mode='import';updateMode();}
 document.querySelectorAll('[data-platform]').forEach(button=>{const active=button.dataset.platform===platform;button.classList.toggle('selected',active);button.setAttribute('aria-pressed',String(active));});
 $('wechat-native-guide').hidden=platform!=='WeChat'||!wechatMac||mode!=='import';
 $('source-badge').textContent=platform==='QQ'?'QQ':'微信';$('source-badge').classList.toggle('wechat-badge',platform==='WeChat');
 $('qq-fields').hidden=platform!=='QQ';$('wechat-fields').hidden=platform!=='WeChat';$('qq-advanced').hidden=platform!=='QQ';$('wechat-advanced').hidden=platform!=='WeChat';$('media-field').hidden=platform!=='QQ';
 $('import-hint').textContent=platform==='QQ'?'消息文件与媒体 ZIP 需来自同一会话、同一日期范围。':'Mac 微信可导入已有原生 ZIP 或聊天记录.txt；也支持 wechat-chat-export 的 chat_full_parsed.json 与文件夹。';
 refreshReadiness();closeMenu();
}
function updateMode(){
 document.querySelectorAll('[data-mode]').forEach(button=>{const active=button.dataset.mode===mode;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});
 $('wechat-native-guide').hidden=platform!=='WeChat'||!wechatMac||mode!=='import';$('direct-fields').hidden=mode!=='direct';$('import-fields').hidden=mode!=='import';document.querySelector('.source-card>.advanced').hidden=mode!=='direct';refreshReadiness();closeMenu();
}
function ready(){
 if(!$('output').value.trim())return false;
 if(mode==='import')return !!$('source').value.trim()&&(platform!=='QQ'||!!$('media').value.trim());
 return platform==='QQ'?selectedSession!==null:!!$('keyword').value.trim()&&!!state.wechatReady;
}
function refreshReadiness(){
 const busy=workspaceBusy();$('start').disabled=busy||!ready();$('start').querySelector('span').textContent=busy?'正在处理…':mode==='import'?'开始整合':'开始导出';
 $('stop').hidden=!state.busy||['connect','analyze'].includes(state.operation);$('stop').disabled=state.status==='stopping';
 document.querySelectorAll('[data-platform],[data-mode]').forEach(b=>b.disabled=busy);
 document.querySelectorAll('#export-form input,#export-form .browse,#export-form .text-button,#install').forEach(el=>el.disabled=busy);
 $('install').disabled=wechatMac||busy||!wechatSupported||(wechatMac&&!!state.wechatPreflight?.blocked);
 document.querySelectorAll('[data-component]').forEach(b=>b.disabled=busy);
 $('install-qq').disabled=busy||state.qceInstallSupported===false;
 $('start-qq').disabled=busy||!state.qceInstalled;
 $('init-wechat').disabled=busy||!state.wechatInstalled||!$('wechat-consent').checked;
 $('install-wechat-mac').disabled=busy||!state.wechatInstalled||!$('wechat-consent').checked;
 $('restore-wechat').disabled=busy||!$('wechat-consent').checked;
 $('check-wechat').disabled=busy||!state.wechatReady;
 document.querySelector('[data-mode="direct"]').disabled=busy||(platform==='WeChat'&&!wechatSupported);
 $('enable-wechat-share').disabled=busy;
 $('transcribe').disabled=busy||!voiceAvailable;
 document.querySelectorAll('[data-help],#wechat-step-help').forEach(b=>b.disabled=false);
 $('connect').disabled=busy;$('connect').classList.toggle('spinning',busy&&state.operation==='connect');$('connect').querySelector('span').textContent=busy&&state.operation==='connect'?'连接中':sessionItems.length?'刷新':'准备并连接 QQ';$('session-button').disabled=busy||!sessionItems.length;
 $('ready-hint').textContent=busy?(state.status==='stopping'?'正在安全结束当前任务':state.operation==='analyze'||analysis.pending?'正在处理关系分析，请稍候':'正在创建档案，请稍候'):ready()?'设置已就绪，可以开始':mode==='import'?(platform==='WeChat'?'选择一个聊天 ZIP 即可开始':'选择消息文件与媒体后即可开始'):platform==='QQ'?'连接 QQ 并选择会话后即可开始':state.wechatReady?'填写好友或群名后即可开始':(wechatMac?('按步骤准备读取、登录微信，再连接并检查'):'在来源设置中安装微信组件');
 refreshAnalysisReadiness();
}
function renderLogs(logs){
 if(!logs.length)return;
 const last=logs[logs.length-1].id;if(last===lastLog)return;lastLog=last;
 const bottom=$('log-list').scrollTop+$('log-list').clientHeight>=$('log-list').scrollHeight-35;
 $('log-list').replaceChildren();for(const log of logs){const row=document.createElement('div');row.className='log-row';const time=document.createElement('time');time.textContent=log.time;const text=document.createElement('span');text.textContent=log.text;row.append(time,text);$('log-list').append(row);}
 $('log-count').textContent=logs.length;if(bottom)$('log-list').scrollTop=$('log-list').scrollHeight;
}
function renderComponents(data){
 if(data.wechatMac!==undefined)wechatMac=!!data.wechatMac;
 if(data.wechatSupported!==undefined)wechatSupported=!!data.wechatSupported;
 $('app-version').textContent=data.appVersion||'dev';
 $('wechat-mac-setup').hidden=!wechatMac;
 $('wechat-native-guide').hidden=platform!=='WeChat'||!wechatMac||mode!=='import';
 renderWechatStep(data.wechatPreflight?.blocked&&!data.wechatReady?data.wechatPreflight:(data.wechatConnection||{}));
 $('wechat-import-route').hidden=!wechatMac;
 $('wechat-experimental-note').hidden=!!data.wechatPreflight?.blocked;
 document.querySelectorAll('.mac-only').forEach(el=>el.hidden=!wechatMac);
 $('qq-component-status').textContent=data.qceInstalled?'QQ 导出组件已安装':'尚未安装内置 QQ 导出组件；也可连接已有本机服务';
 $('wechat-ready').textContent=data.wechatPreflight?.blocked&&!data.wechatReady?data.wechatPreflight.title:!wechatSupported?'此 Mac 暂支持导入；微信直读需要 Apple 芯片':data.wechatReady?'微信读取配置已就绪；可检查连接或开始导出':wechatMac?(data.wechatInstalled?'组件已安装，请连接已登录微信':'请先安装微信 Mac 导出组件'):'首次使用需要安装微信组件';
 $('wechat-platform-hint').textContent=wechatMac?'Mac 默认自动查找账号。多账号时可选择当前账号的 db_storage 文件夹，再连接。':'适配 Windows 微信 4.1.12+；手机记录需先迁移或同步到电脑。';
 if(data.desktopOS==='darwin')$('qq-setup-hint').textContent=data.qceInstallSupported?'先完全退出桌面 QQ（⌘Q），再点“准备并连接 QQ”并扫码，好友列表会自动加载。组件会创建独立运行副本并重新签名，与桌面 QQ 共享本机数据；导出期间不要同时打开桌面 QQ。':'Intel Mac 暂无 QCE 原生安装包；可连接自行部署并共享导出目录的本机 QCE 服务，或导入已有文件。';
}
function renderState(data){
 state=data;sessionItems=data.sessions||[];$('connection-label').textContent=data.connection||'未连接';$('connection-label').classList.toggle('connected',sessionItems.length>0);
 renderComponents(data);
 const status=data.operation==='analyze'?(data.result?'complete':'ready'):(data.status||'ready');const labels={ready:'待创建',running:'处理中',stopping:'正在停止',complete:'已完成',error:'未完成',stopped:'已停止',connected:'已连接',installed:'已就绪'};
 $('status-badge').textContent=labels[status]||'待创建';$('status-badge').className='status-badge '+status;
 const idle=['ready','connected','installed'].includes(status)&&!data.result;
 $('empty-art').hidden=!idle;$('result-symbol').hidden=idle;$('result-symbol').className='result-symbol '+status;
 $('status-title').textContent=status==='running'?(data.operation==='connect'?'正在连接 QQ':data.operation==='install'?'正在准备微信组件':data.operation==='component'?'正在处理导出组件':'正在创建聊天档案'):status==='complete'?'聊天档案已保存':status==='error'?'这次处理未完成':status==='stopping'?'正在结束当前任务':status==='stopped'?'任务已停止':data.result?'上次档案已保存':'从一段聊天开始';
 $('stage').textContent=data.operation==='analyze'?(data.result?'原始聊天档案已保存，可以随时回看。':'导出完成后，文字、图片和语音会一起保存在这里。'):status==='ready'&&data.operation!=='component'?'导出完成后，文字、图片和语音会一起保存在这里。':data.stage;
 const showProgress=data.operation!=='analyze'&&(!!data.busy||status==='complete');$('task-progress').hidden=!showProgress;
 if(data.progress===null||data.progress===undefined){$('progress').removeAttribute('value');$('progress-label').textContent='处理中';}else{$('progress').value=data.progress;$('progress-label').textContent=Math.round(data.progress)+'%';}
 $('message-count').textContent=data.messageCount===null||data.messageCount===undefined?'—':data.messageCount.toLocaleString();$('voice-count').textContent=data.voiceCount===null||data.voiceCount===undefined?'—':data.voiceCount.toLocaleString();
 for(const id of ['open-archive','open-folder','nav-archive'])$(id).disabled=!data.result;
 $('result-notes').hidden=true;
 if(status==='complete'&&data.summary){const voices=data.summary.voiceTranscription||{};const notes=Object.entries(voices).filter(([k,v])=>k!=='完成'&&v).map(([k,v])=>`${v} 条语音${k}`);const missing=Object.entries(data.summary.media||{}).filter(([k])=>k.startsWith('missing_')).reduce((n,[k,v])=>n+v,0);if(missing)notes.push(`${missing} 个媒体引用缺失`);notes.push(...(data.summary.warnings||[]));if(notes.length){$('result-notes').textContent=notes.join(' · ');$('result-notes').hidden=false;}}
 $('after-export-analysis').hidden=!data.result||data.summary?.analysisEligible===false;$('analyze-export').disabled=workspaceBusy();
 renderAnalysisState(data);renderLogs(data.logs||[]);refreshReadiness();
}
function payload(){return {platform,mode,session:selectedSession,address:$('address').value,token:$('token').value,keyword:$('keyword').value,dbDir:$('db-dir').value,source:$('source').value,media:$('media').value,begin:mode==='import'?'':$('begin').value,end:mode==='import'?'':$('end').value,output:$('output').value,model:$('model').value,roaming:$('roaming').checked,transcribe:$('transcribe').checked,allowResign:$('wechat-consent').checked};}
async function action(name,body={}){try{await api(name,body);renderState(await api('state'));return true;}catch(e){toast(e.message);return false;}}
function openArchive(){if(state.result)window.open('/archive/index.html','_blank','noopener');}
function showLogs(){if(!$('logs-dialog').open)$('logs-dialog').showModal();$('log-list').scrollTop=$('log-list').scrollHeight;}

function showView(view){
 if(!['export','analysis','help'].includes(view))return;
 activeView=view;
 for(const name of ['export','analysis','help']){const active=name===view;$(name+'-view').hidden=!active;$('nav-'+name).classList.toggle('selected',active);$('tab-'+name).classList.toggle('active',active);$('nav-'+name).setAttribute('aria-current',active?'page':'false');}
 const copy={export:['聊天导出','CHAT ARCHIVE','让每段聊天，都有归档。','把文字、图片和语音整理在一起，随时回看，方便分析。'],analysis:['关系分析','RELATIONSHIP REFLECTION','在对话里，看见彼此。','选择关系视角，回顾你们的互动，描绘聊天中的双方形象。'],help:['使用帮助','YOUR GUIDE','从连接到导出，每一步都有说明。','按主题找到下一步，无需先学会终端或 API。']}[view];
 document.querySelector('.breadcrumb span').textContent=copy[0];$('page-eyebrow').textContent=copy[1];$('page-title').textContent=copy[2];$('page-subtitle').textContent=copy[3];
 if(view==='analysis'&&!$('analysis-archive').value.trim()&&state.analysisArchive)$('analysis-archive').value=state.analysisArchive;
 refreshReadiness();
}
function filterHelp(){
 const query=$('help-search').value.trim().toLowerCase();let count=0;
 document.querySelectorAll('[data-help-topic]').forEach(topic=>{const visible=!query||topic.textContent.toLowerCase().includes(query);topic.hidden=!visible;if(visible)count++;});
 $('help-empty').hidden=count>0||!query;
}
function openHelp(topic='start'){
 $('help-search').value='';filterHelp();showView('help');
 const section=$('help-'+(['start','qq','wechat','permissions','terminal','api','files','trouble'].includes(topic)?topic:'start'));
 section.scrollIntoView({behavior:'smooth',block:'start'});section.focus({preventScroll:true});
}
function renderWechatStep(step){
 const signature=JSON.stringify(step);if(signature===lastWechatStep)return;lastWechatStep=signature;
 $('wechat-step-title').textContent=step.title||'先准备组件，再连接微信';
 $('wechat-step-detail').textContent=step.detail||'保持日常使用的微信登录。首次连接使用 macOS 系统授权弹窗。';
 $('cancel-wechat').hidden=!step.active;$('cancel-wechat').disabled=step.code==='cancelling';
 $('wechat-next-actions').replaceChildren();
 const actions={disk_permission:[['full-disk-access','打开完全磁盘访问']],tools_missing:[['install-tools','安装系统工具']],wechat_not_running:[['open-wechat','打开微信']],password:[['show-terminal','显示终端']],terminal_pending:[['show-terminal','显示终端']],cancelling:[['show-terminal','显示终端']]};
 for(const [actionName,label] of actions[step.code]||[]){const button=document.createElement('button');button.type='button';button.className='button secondary small';button.textContent=label;button.addEventListener('click',()=>action('setup',{action:actionName}));$('wechat-next-actions').append(button);}
}
async function connectQQ(){
 selectedSession=null;$('session-button').querySelector('span').textContent='连接后选择好友或群聊';$('session-button').classList.remove('has-value');
 // Existing/custom local services remain usable without an installed bundle.
 await action('component',{...payload(),action:'prepare-qq'});
}
function analysisError(message){$('analysis-error').textContent=message||'';$('analysis-error').hidden=!message;}
function invalidateAnalysisPreview(){analysis.previewId=null;analysis.preview=null;$('analysis-preview').hidden=true;$('analysis-payload').textContent='';$('analysis-consent').checked=false;analysisError('');refreshAnalysisReadiness();}
function invalidateAnalysisArchive(){analysis.inspection=null;analysis.sourcePath='';$('analysis-loaded').hidden=true;$('analysis-quality').hidden=true;$('analysis-self').replaceChildren(new Option('先读取档案，再选择你的身份',''));invalidateAnalysisPreview();}
function analysisReady(){return !!analysis.inspection&&analysis.sourcePath===$('analysis-archive').value.trim()&&!!$('analysis-self').value;}
function refreshAnalysisReadiness(){
 const busy=workspaceBusy();document.querySelectorAll('#analysis-form input,#analysis-form select,#analysis-form textarea,#analysis-form button').forEach(element=>element.disabled=busy);
 $('analysis-self').disabled=busy||!analysis.inspection;$('analysis-load').disabled=busy||!$('analysis-archive').value.trim();
 $('analysis-prepare').disabled=busy||!analysisReady();$('analysis-prepare').querySelector('span').textContent=busy?'正在处理…':analysis.mode==='ai'?'预览 AI 分析内容':'生成关系报告';
 $('analysis-stop').hidden=!state.busy||state.operation!=='analyze';$('analysis-stop').disabled=state.status==='stopping';
 $('analysis-ai-start').disabled=busy||!analysis.previewId||!$('analysis-consent').checked;
 $('analysis-ready-hint').textContent=busy?(state.operation==='analyze'?'正在生成报告，请稍候':'正在准备，请稍候'):!analysis.inspection?'读取档案并选择你的身份后即可开始':!$('analysis-self').value?'请选择哪位是你':analysis.mode==='ai'?'先查看发送内容，再授权本次 AI 调用':'已就绪，无需 API 即可生成报告';
}
function updateAnalysisMode(modeName){
 analysis.mode=modeName;document.querySelectorAll('[data-analysis-mode]').forEach(button=>{const active=button.dataset.analysisMode===modeName;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});
 $('analysis-ai-settings').hidden=modeName!=='ai';$('analysis-mode-hint').textContent=modeName==='ai'?'AI 按所选关系的心理学框架，分批读取日期范围内全部有效文字与已有转写，解释互动与表达特点，区分事实和推测。其他媒介只参与本地统计。':'无需 API。通过消息节奏与可观察的表达，生成基础关系回顾、双方画像与聊天图表。';
 invalidateAnalysisPreview();
}
async function inspectAnalysisArchive(){
 if(workspaceBusy()||!$('analysis-archive').value.trim())return false;
 const source=$('analysis-archive').value.trim();analysis.pending=true;analysisError('');refreshReadiness();
 try{
  const data=await api('analysis/inspect',{archive:source});analysis.inspection=data;analysis.sourcePath=source;invalidateAnalysisPreview();
  const participants=data.participants||[];$('analysis-self').replaceChildren(new Option('请选择你的身份',''));for(const person of participants)$('analysis-self').append(new Option(person.name+' · '+Number(person.count||0).toLocaleString()+' 条',String(person.id)));
  $('analysis-loaded').hidden=false;$('analysis-loaded-title').textContent=Number(data.messageCount||0).toLocaleString()+' 条消息 · '+participants.length+' 位参与者';
  const range=data.dateRange||{};const quality=data.quality||{};const formats={'qce-chunked-jsonl':'QQ 分块 JSONL','qce-jsonl':'QQ JSONL','qce-json':'QQ JSON','chatarchive/1':'统一档案','qce-zip':'QQ ZIP',qce_chunked_jsonl:'QQ 分块 JSONL',qce_jsonl:'QQ JSONL',qce_json:'QQ JSON',chatarchive:'统一档案',qce_zip:'QQ ZIP'};const format=data.sourceFormat||quality.sourceFormat||data.source?.rawFormat;const formatLabel=typeof format==='string'?(formats[format]||format):'';$('analysis-loaded-detail').textContent=(range.start&&range.end?String(range.start).slice(0,10)+' 至 '+String(range.end).slice(0,10):'已读取聊天记录')+' · '+participants.map(person=>person.name).join(' / ')+(formatLabel?' · '+formatLabel:'');
  const warnings=Array.isArray(quality.warnings)?quality.warnings:Array.isArray(data.warnings)?data.warnings:[];$('analysis-quality').textContent=warnings.join('；');$('analysis-quality').hidden=!warnings.length;
  $('analysis-self').focus();return true;
 }catch(error){invalidateAnalysisArchive();analysisError(error.message);return false;}finally{analysis.pending=false;refreshReadiness();}
}
function analysisPayload(){return {archive:$('analysis-archive').value.trim(),relationship:document.querySelector('input[name="relationship"]:checked').value,selfId:$('analysis-self').value,begin:$('analysis-begin').value,end:$('analysis-end').value,customPrompt:analysis.mode==='ai'?$('analysis-custom-prompt').value.trim():''};}
function normalizeAnalysisEndpoint(value){
 let url;try{url=new URL(value.trim());}catch{throw new Error('请填写有效的 API 服务地址，例如 https://api.example.com/v1。');}
 if(!['http:','https:'].includes(url.protocol)||!url.hostname)throw new Error('API 服务地址应使用 https://。');
 if(url.username||url.password||url.search||url.hash)throw new Error('API 服务地址不能包含账号密码、查询参数或片段；API Key 请单独填写。');
 const host=url.hostname.toLowerCase();if(url.protocol!=='https:'&&!['localhost','127.0.0.1','[::1]','::1'].includes(host))throw new Error('远程 API 服务必须使用 https://；本机服务可使用 http://。');
 const path=url.pathname.replace(/\/+$/,'');url.pathname=path.endsWith('/chat/completions')?path:path+'/chat/completions';return url.href;
}
function validateAnalysisSettings(requireKey=false){
 if($('analysis-begin').value&&$('analysis-end').value&&$('analysis-begin').value>$('analysis-end').value)throw new Error('开始日期不能晚于结束日期。');
 if(analysis.mode==='ai'){
  const endpoint=new URL(normalizeAnalysisEndpoint($('analysis-endpoint').value));const localService=['localhost','127.0.0.1','[::1]','::1'].includes(endpoint.hostname.toLowerCase());
  if(!$('analysis-model').value.trim())throw new Error('请填写模型名称。');
  if(requireKey&&!localService&&!$('analysis-key').value.trim())throw new Error('请在 API 密钥输入框填写所选服务商的密钥。');
  if($('analysis-custom-prompt').value.trim().length>2000)throw new Error('补充分析要求最多 2000 字。');
 }
}
function showAnalysisPreview(data){
 analysis.previewId=data.previewId;analysis.preview=data.preview;const preview=data.preview||{};const stats=preview.stats||{};const coverage=preview.coverage||{};
 const batches=Array.isArray(preview.batches)?preview.batches:[];const count=stats.messageCount??coverage.totalMessages??preview.messageCount??analysis.inspection?.messageCount??0;
 const validTextCount=coverage.validTextMessageCount??preview.validTextMessageCount??preview.sampleCount??0;const sentCount=coverage.sentMessageCount??batches.reduce((total,batch)=>total+Number(batch.messageCount||0),0);
 const batchCount=coverage.batchCount??batches.length;const fullCoverage=coverage.mode==='full'&&sentCount===validTextCount;
 const endpoint=normalizeAnalysisEndpoint($('analysis-endpoint').value);
 $('analysis-preview-meta').textContent=(preview.relationshipLabel||'关系')+'视角 · 范围内 '+Number(count).toLocaleString()+' 条消息 · '+(fullCoverage?'拟发送全部 '+Number(validTextCount).toLocaleString()+' 条有效文字 / 已有转写':'拟发送 '+Number(sentCount).toLocaleString()+' / '+Number(validTextCount).toLocaleString()+' 条有效文字 / 已有转写')+' · 分 '+Number(batchCount).toLocaleString()+' 批 · 调用地址：'+endpoint+' · 模型：'+$('analysis-model').value.trim();
 if(preview.frameworkProfile?.primaryTheory?.name){$('analysis-preview-meta').textContent+=' · 主框架：'+preview.frameworkProfile.primaryTheory.name;}
 const sections=batches.map((batch,index)=>'第 '+(batch.index??index+1)+' / '+batches.length+' 批 · '+Number(batch.messageCount||0).toLocaleString()+' 条文字\n\nSYSTEM\n'+(batch.systemPrompt??preview.systemPrompt??'')+'\n\nUSER\n'+(typeof batch.payloadText==='string'?batch.payloadText:JSON.stringify(batch.payload||{},null,2)));
 if(!batches.length){const userPayload=typeof preview.payloadText==='string'?preview.payloadText:JSON.stringify(preview.payload||preview,null,2);sections.push((preview.systemPrompt?'SYSTEM\n'+preview.systemPrompt+'\n\nUSER\n':'')+userPayload);}
 if(preview.synthesis?.required){const synthesis=preview.synthesis;sections.push('批次结果汇总\n'+(synthesis.description||'以下是固定汇总规则与请求模板。各批通过校验的结果返回后，程序再生成实际汇总请求；长结果可能分层汇总。')+'\n\n最终综合 SYSTEM\n'+(synthesis.systemPrompt||'')+(synthesis.intermediateSystemPrompt?'\n\n中间综合 SYSTEM（需要分层时使用）\n'+synthesis.intermediateSystemPrompt:'')+'\n\nUSER 请求模板（批次结果返回后动态填入）\n'+(typeof synthesis.payloadTemplate==='string'?synthesis.payloadTemplate:JSON.stringify(synthesis.payloadTemplate||{},null,2)));}
 $('analysis-payload').textContent=sections.join('\n\n'+'─'.repeat(32)+'\n\n');
 $('analysis-redaction').textContent='参与者以代号显示，常见联系方式已脱敏。正文仍可能包含可识别信息，请展开请求内容核对；不发送原始图片或音频。';
 if(preview.canUseAI===false||preview.planningError){analysis.previewId=null;analysisError(preview.planningError||'当前记录无法按接口限制完整发送，请调整日期范围。');}
 $('analysis-consent').checked=false;$('analysis-preview').hidden=false;$('analysis-preview').scrollIntoView({behavior:'smooth',block:'nearest'});
}
async function startPreparedAnalysis(){
 if(!analysis.previewId)return;const isAI=analysis.mode==='ai';if(isAI&&!$('analysis-consent').checked)return;
 const body={previewId:analysis.previewId,mode:analysis.mode};
 if(isAI){validateAnalysisSettings(true);body.endpoint=normalizeAnalysisEndpoint($('analysis-endpoint').value);body.model=$('analysis-model').value.trim();body.apiKey=$('analysis-key').value.trim();body.consent=true;}
 await api('analysis/start',body);if(isAI)$('analysis-key').value='';analysis.previewId=null;$('analysis-preview').hidden=true;$('analysis-consent').checked=false;renderState(await api('state'));
}
async function prepareAnalysis(){
 if(workspaceBusy()||!analysisReady())return;analysis.pending=true;analysisError('');refreshReadiness();
 try{validateAnalysisSettings();const data=await api('analysis/prepare',analysisPayload());if(analysis.mode==='ai')showAnalysisPreview(data);else{analysis.previewId=data.previewId;analysis.preview=data.preview;await startPreparedAnalysis();}}
 catch(error){analysisError(error.message);}finally{analysis.pending=false;refreshReadiness();}
}
function renderAnalysisState(data){
 if(data.analysisArchive&&!$('analysis-archive').value.trim())$('analysis-archive').value=data.analysisArchive;
 const analyzing=data.operation==='analyze';const busy=analyzing&&!!data.busy;const status=analyzing?data.status:'ready';const result=!!data.analysisResult;
 const labels={running:'分析中',stopping:'正在停止',complete:'已生成',error:'未完成',stopped:'已停止'};$('analysis-status-badge').textContent=analyzing?(labels[status]||'待分析'):result?'已生成':'待分析';$('analysis-status-badge').className='status-badge '+(analyzing?status:result?'complete':'ready');
 $('analysis-status-title').textContent=busy?'正在认识这段对话':analyzing&&status==='error'?'这次分析未完成':analyzing&&status==='stopped'?'分析已停止':result?'关系报告已生成':'从对话中认识彼此';
 $('analysis-stage').textContent=analyzing&&(busy||['error','stopped'].includes(status))?(data.stage||'正在处理聊天记录'):result?'报告包含互动观察、双方沟通画像与聊天图表，可以离线打开。':'观察互动模式、沟通风格与双方的表达形象，每个解释都回到聊天证据。';
 $('analysis-task-progress').hidden=!busy;if(data.progress===null||data.progress===undefined){$('analysis-progress').removeAttribute('value');$('analysis-progress-label').textContent='处理中';}else{$('analysis-progress').value=data.progress;$('analysis-progress-label').textContent=Math.round(data.progress)+'%';}
 $('analysis-open-report').disabled=!result;const summary=data.analysisSummary||{};$('analysis-report-meta').hidden=!result;const names={local:'本地基础分析',ai:'AI 分析',local_fallback:'本地报告（AI 调用失败）'};$('analysis-report-meta').textContent=result?'最近生成的报告 · '+(summary.relationshipLabel||'关系回顾')+' · '+(names[summary.mode]||summary.mode||'本地基础分析')+(summary.messageCount?' · '+Number(summary.messageCount).toLocaleString()+' 条消息':''):'';
 if(analyzing&&status==='error')analysisError(data.stage||'分析未完成，请查看处理记录。');
}
['nav-export','tab-export'].forEach(id=>$(id).addEventListener('click',()=>showView('export')));['nav-analysis','tab-analysis'].forEach(id=>$(id).addEventListener('click',()=>showView('analysis')));
$('analyze-export').addEventListener('click',async()=>{showView('analysis');if(state.analysisArchive&&$('analysis-archive').value.trim()!==state.analysisArchive){$('analysis-archive').value=state.analysisArchive;invalidateAnalysisArchive();}if(!analysis.inspection)await inspectAnalysisArchive();});
$('analysis-archive').addEventListener('input',()=>{invalidateAnalysisArchive();refreshReadiness();});
async function browseAnalysis(kind){if(workspaceBusy())return;analysis.pending=true;refreshReadiness();try{const data=await api('browse',{kind,category:'messages'});if(data.path){$('analysis-archive').value=data.path;invalidateAnalysisArchive();}}catch(error){analysisError(error.message);}finally{analysis.pending=false;refreshReadiness();}}
$('analysis-browse').addEventListener('click',()=>browseAnalysis('folder'));$('analysis-browse-file').addEventListener('click',()=>browseAnalysis('file'));$('analysis-load').addEventListener('click',inspectAnalysisArchive);
document.querySelectorAll('[data-analysis-mode]').forEach(button=>button.addEventListener('click',()=>updateAnalysisMode(button.dataset.analysisMode)));
['analysis-self','analysis-begin','analysis-end','analysis-endpoint','analysis-model','analysis-custom-prompt'].forEach(id=>$(id).addEventListener('input',invalidateAnalysisPreview));document.querySelectorAll('input[name="relationship"]').forEach(input=>input.addEventListener('change',invalidateAnalysisPreview));
$('analysis-deepseek').addEventListener('click',()=>{$('analysis-endpoint').value='https://api.deepseek.com';invalidateAnalysisPreview();$('analysis-endpoint').focus();});
$('analysis-consent').addEventListener('change',refreshAnalysisReadiness);$('analysis-form').addEventListener('submit',event=>{event.preventDefault();prepareAnalysis();});
$('analysis-ai-start').addEventListener('click',async()=>{if(workspaceBusy()||!$('analysis-consent').checked)return;analysis.pending=true;analysisError('');refreshReadiness();try{await startPreparedAnalysis();}catch(error){analysisError(error.message);}finally{analysis.pending=false;refreshReadiness();}});
$('analysis-open-report').addEventListener('click',()=>{if(state.analysisResult)window.open('/analysis/report.html','_blank','noopener');});
$('analysis-stop').addEventListener('click',()=>action('stop'));
document.querySelectorAll('[data-platform]').forEach(button=>button.addEventListener('click',()=>{platform=button.dataset.platform;updatePlatform();}));
document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>{mode=button.dataset.mode;updateMode();}));
$('session-button').addEventListener('click',()=>{const opening=$('session-menu').hidden;$('session-menu').hidden=!opening;$('session-button').setAttribute('aria-expanded',String(opening));if(opening){$('session-search').value='';renderSessions();$('session-search').focus();}});
$('session-search').addEventListener('input',renderSessions);
$('session-picker').addEventListener('keydown',event=>{if(event.key==='Escape'){closeMenu();$('session-button').focus();}if(['ArrowDown','ArrowUp'].includes(event.key)&&!$('session-menu').hidden){event.preventDefault();const buttons=[...$('session-options').querySelectorAll('button')];const current=buttons.indexOf(document.activeElement);const next=event.key==='ArrowDown'?current+1:current-1;(buttons[(next+buttons.length)%buttons.length])?.focus();}if(event.key==='Enter'&&document.activeElement===$('session-search')){$('session-options').querySelector('button')?.click();event.preventDefault();}});
document.addEventListener('click',event=>{if(!$('session-picker').contains(event.target))closeMenu();});
$('connect').addEventListener('click',connectQQ);
$('clear-dates').addEventListener('click',()=>{$('begin').value='';$('end').value='';});
['keyword','source','media','output'].forEach(id=>$(id).addEventListener('input',refreshReadiness));
document.querySelectorAll('[data-browse]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{const data=await api('browse',{kind:button.dataset.kind,category:button.dataset.category});if(data.path)$(button.dataset.browse).value=data.path;}catch(e){toast(e.message);}finally{button.disabled=workspaceBusy();refreshReadiness();}}));
$('export-form').addEventListener('submit',async event=>{event.preventDefault();if(!ready()||workspaceBusy())return;if($('begin').value&&$('end').value&&$('begin').value>$('end').value&&mode==='direct'){toast('开始日期不能晚于结束日期');$('begin').focus();return;}await action('start',payload());});
$('stop').addEventListener('click',()=>action('stop'));
$('install').addEventListener('click',()=>action('install'));
document.querySelectorAll('[data-component]').forEach(button=>button.addEventListener('click',()=>action('component',{...payload(),action:button.dataset.component})));
['open-archive','nav-archive'].forEach(id=>$(id).addEventListener('click',openArchive));$('open-folder').addEventListener('click',()=>action('open-folder'));
['nav-logs','show-logs','analysis-show-logs'].forEach(id=>$(id).addEventListener('click',showLogs));$('close-logs').addEventListener('click',()=>$('logs-dialog').close());$('logs-dialog').addEventListener('click',event=>{if(event.target===$('logs-dialog'))$('logs-dialog').close();});
$('exit').addEventListener('click',async()=>{if(state.busy&&!confirm('退出会停止当前任务，并等待临时缓存清理。确定退出？'))return;closing=true;try{await api('shutdown',{});$('closed-overlay').hidden=false;}catch(e){closing=false;toast(e.message);}});
async function poll(){if(closing)return;try{renderState(await api('state'));offlineNotified=false;}catch(e){if(!offlineNotified){toast('工具连接已断开，请重新打开 ChatArchiveTool。');offlineNotified=true;}$('start').disabled=true;$('status-badge').textContent='已断开';}finally{if(!closing)setTimeout(poll,700);}}
(async()=>{try{const config=await api('config');state={...state,...config};renderComponents(config);wechatSupported=config.wechatSupported!==false;voiceAvailable=config.voiceAvailable!==false;if(!voiceAvailable){$('transcribe').checked=false;$('voice-hint').textContent='已有转写自动复用，原始语音保留。新语音转写需使用源码版安装可选语音依赖。';}$('output').value=config.output;$('model').value=config.model;$('address').value=config.address;$('token').placeholder=config.tokenDetected?'已自动读取本机令牌；无需填写':'请输入 QCE 访问令牌';state.wechatReady=config.wechatReady;updatePlatform();updateMode();poll();}catch(e){toast(e.message);}})();

['nav-help','tab-help'].forEach(id=>$(id).addEventListener('click',()=>showView('help')));
$('help-search').addEventListener('input',filterHelp);
document.querySelectorAll('[data-help]').forEach(button=>button.addEventListener('click',()=>openHelp(button.dataset.help)));
document.querySelectorAll('[data-setup]').forEach(button=>button.addEventListener('click',()=>action('setup',{action:button.dataset.setup})));
$('wechat-step-help').addEventListener('click',()=>openHelp(state.wechatPreflight?.blocked?'wechat':state.wechatConnection?.topic||'wechat'));
$('wechat-import-route').addEventListener('click',()=>{mode='import';updateMode();toast('选择上游导出的 chat_full_parsed.json 或整个结果文件夹。');});
$('cancel-wechat').addEventListener('click',()=>action('wechat-cancel'));
$('help-to-export').addEventListener('click',()=>showView('export'));
$('help-to-analysis').addEventListener('click',()=>showView('analysis'));

$('qce-upstream-ui').addEventListener('click',()=>action('qce-ui',{address:$('address').value.trim(),token:$('token').value.trim()}));

$('enable-wechat-share').addEventListener('click',async()=>{const button=$('enable-wechat-share');button.disabled=true;try{const result=await api('wechat-share',{});$('wechat-share-status').textContent=result.message;}catch(e){$('wechat-share-status').textContent=e.message;}finally{button.disabled=false;}});

$('wechat-consent').addEventListener('change',refreshReadiness);
