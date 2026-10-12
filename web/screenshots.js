'use strict';
// Separate local draft: no OCR text or image is sent to the analysis API.
(()=>{
 const draft={generation:'',pages:[],active:0,busy:false,selection:null,picture:null,drag:null,available:false};
 const e=id=>document.getElementById('shot-'+id);
 function changed(){e('confirm').checked=false;e('result-actions').hidden=true;e('result').textContent='';}
 function current(){return draft.pages[draft.active];}
 function button(text,fn){const b=document.createElement('button');b.type='button';b.className='button secondary small';b.textContent=text;b.onclick=fn;return b;}
 function busy(value){draft.busy=value;screenshotPending=value;refreshReadiness();document.querySelectorAll('#screenshots-view button,#screenshots-view input,#screenshots-view select,#screenshots-view textarea').forEach(n=>n.disabled=value);e('recognize').disabled=value||!draft.available||!e('files').files.length;}
 function fail(error){e('status').textContent=error.message;toast(error.message);}
 function draw(){const c=e('canvas'),ctx=c.getContext('2d');if(!draft.picture)return;ctx.clearRect(0,0,c.width,c.height);ctx.drawImage(draft.picture,0,0,c.width,c.height);if(draft.selection){const [x,y,w,h]=draft.selection;ctx.strokeStyle='#dd5a37';ctx.lineWidth=Math.max(2,c.width/250);ctx.strokeRect(x*c.width,y*c.height,w*c.width,h*c.height);}}
 function preview(){draft.selection=null;const image=new Image();draft.picture=null;image.onload=()=>{draft.picture=image;e('canvas').width=image.width;e('canvas').height=image.height;draw();};image.src='data:image/png;base64,'+current().preview;}
 function pages(){e('page').replaceChildren();draft.pages.forEach((p,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`${i+1}. ${p.name}`;e('page').append(o);});e('page').value=draft.active;e('earlier').disabled=draft.active===0;e('later').disabled=draft.active===draft.pages.length-1;}
 function inputLabel(label,control){const el=document.createElement('label');el.textContent=label;el.append(control);return el;}
 function select(options,value,fn){const s=document.createElement('select');for(const [v,t] of options){const o=document.createElement('option');o.value=v;o.textContent=t;s.append(o);}s.value=value;s.onchange=()=>{fn(s.value);changed();};return s;}
 function renderRows(){const holder=e('rows');holder.replaceChildren();const page=current();if(!page)return;page.rows.forEach((row,i)=>{
  const card=document.createElement('article');card.className='shot-row';
  const check=document.createElement('input');check.type='checkbox';check.checked=!!row.checked;check.onchange=()=>row.checked=check.checked;
  const title=inputLabel(`第 ${i+1} 条`,check);title.className='shot-check';card.append(title,button('定位原图',()=>{draft.selection=row.box;draw();}));
  if(row.duplicate){const n=document.createElement('p');n.className='shot-warning';n.textContent='与上一张截图连续内容重叠，请核对后决定是否删除。';card.append(n);}
  if(row.confidence!=null&&row.confidence<.7){const n=document.createElement('p');n.className='shot-warning';n.textContent='识别把握较低，请仔细核对原图。';card.append(n);}
  const text=document.createElement('textarea');text.value=row.text;text.rows=2;text.maxLength=20000;text.oninput=()=>{row.text=text.value;changed();};card.append(inputLabel('文字（可修改）',text));
  const controls=document.createElement('div');controls.className='shot-row-controls';
  controls.append(inputLabel('发送者',select([['unknown','待确认'],['other','对方'],['self','我'],['system','系统 / 时间提示']],row.sender,v=>row.sender=v)),inputLabel('内容类型',select([['text','文字'],['image','图片裁片'],['sticker','表情裁片']],row.kind,v=>row.kind=v)));
  const date=document.createElement('input');date.type='datetime-local';date.value=row.time;date.onchange=()=>{row.time=date.value;changed();};controls.append(inputLabel('完整时间（可留空）',date));card.append(controls);
  const actions=document.createElement('div');actions.className='help-actions';actions.append(button('上移',()=>moveRow(i,-1)),button('下移',()=>moveRow(i,1)),button('删除',()=>{page.rows.splice(i,1);changed();renderRows();}));card.append(actions);holder.append(card);
 });if(!page.rows.length){const p=document.createElement('p');p.textContent='这张截图没有文字。可以框选图片 / 表情，或手动补充文字。';holder.append(p);}}
 function moveRow(i,d){const rows=current().rows,j=i+d;if(j<0||j>=rows.length)return;[rows[i],rows[j]]=[rows[j],rows[i]];changed();renderRows();}
 function movePage(d){const j=draft.active+d;if(j<0||j>=draft.pages.length)return;[draft.pages[j],draft.pages[draft.active]]=[draft.pages[draft.active],draft.pages[j]];draft.active=j;changed();pages();renderRows();}
 function base64(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('截图读取失败'));reader.readAsDataURL(file);});}
 ['nav-screenshots','tab-screenshots'].forEach(id=>document.getElementById(id).addEventListener('click',()=>showView('screenshots')));
 e('help').onclick=()=>openHelp('screenshots');
 e('files').onchange=()=>{e('recognize').disabled=!draft.available||!e('files').files.length;e('status').textContent=`已选择 ${e('files').files.length} 张；点击识别后替换上一批未保存结果。`;};
 ['name','self','other','output'].forEach(id=>e(id).oninput=changed);
 e('recognize').onclick=async()=>{
  if(draft.busy)return;
  const files=[...e('files').files].sort((a,b)=>a.name.localeCompare(b.name,'zh-CN',{numeric:true}));
  if(!files.length||files.length>30){fail(new Error('每批请选择 1 至 30 张截图'));return;}
  if(files.some(f=>f.size>8*1024*1024||!['image/png','image/jpeg'].includes(f.type))){fail(new Error('请选择每张不超过 8 MB 的 PNG / JPEG 图片'));return;}
  if(draft.pages.length&&!confirm('重新识别会替换当前未保存的核对结果。继续吗？'))return;
  busy(true);changed();
  try{
   const reset=await api('screenshots/reset',{});draft.generation=reset.generation;draft.pages=[];e('review').hidden=true;
   for(let i=0;i<files.length;i++){
    e('status').textContent=`正在本机识别第 ${i+1} / ${files.length} 张…`;
    const result=await api('screenshots/upload',{generation:draft.generation,data:await base64(files[i])});
    draft.pages.push({...result,name:files[i].name});
   }
   e('status').textContent=`已识别 ${draft.pages.length} 张，请核对下方记录。内容尚未保存为档案。`;
  }catch(error){fail(error);}finally{
   busy(false);if(draft.pages.length){draft.active=0;e('review').hidden=false;pages();preview();renderRows();}
  }
 };
 e('page').onchange=()=>{draft.active=Number(e('page').value);pages();preview();renderRows();};
 e('earlier').onclick=()=>movePage(-1);e('later').onclick=()=>movePage(1);
 function point(event){const rect=e('canvas').getBoundingClientRect();return [Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))];}
 e('canvas').onpointerdown=event=>{if(draft.busy)return;draft.drag=point(event);e('canvas').setPointerCapture(event.pointerId);};
 e('canvas').onpointermove=event=>{if(!draft.drag)return;const p=point(event),a=draft.drag;draft.selection=[Math.min(a[0],p[0]),Math.min(a[1],p[1]),Math.abs(a[0]-p[0]),Math.abs(a[1]-p[1])];draw();};
 e('canvas').onpointerup=()=>{draft.drag=null;};e('canvas').onpointercancel=()=>{draft.drag=null;};
 function append(kind){const page=current();if(!page)return;let b=draft.selection;if(kind!=='text'&&(!b||b[2]<.005||b[3]<.005)){toast('请先在左侧原图上拖动框选区域');return;}
  page.rows.push({text:'',time:'',sender:'unknown',kind,box:b?[...b]:[0,0,1,1]});changed();renderRows();}
 e('crop-image').onclick=()=>append('image');e('crop-sticker').onclick=()=>append('sticker');e('add').onclick=()=>append('text');
 e('remove').onclick=()=>{current().rows=current().rows.filter(r=>!r.checked);changed();renderRows();};
 e('merge').onclick=()=>{
  const page=current(),selected=page.rows.map((r,i)=>r.checked?i:-1).filter(i=>i>=0);
  if(selected.length<2||selected.some((v,i)=>i&&v!==selected[i-1]+1)||selected.some(i=>page.rows[i].kind!=='text')){toast('请勾选同一气泡连续的至少两条文字');return;}
  const rows=selected.map(i=>page.rows[i]),first=rows[0];
  if(rows.some(r=>r.sender!==first.sender||r.time!==first.time)){toast('请先将这些行的发送者和时间核对为一致');return;}
  const x=Math.min(...rows.map(r=>r.box[0])),y=Math.min(...rows.map(r=>r.box[1]));
  page.rows.splice(selected[0],rows.length,{...first,text:rows.map(r=>r.text).join('\n'),checked:false,box:[x,y,Math.max(...rows.map(r=>r.box[0]+r.box[2]))-x,Math.max(...rows.map(r=>r.box[1]+r.box[3]))-y]});changed();renderRows();
 };
 e('duplicates').onclick=()=>{
  let count=0;draft.pages.forEach(p=>p.rows.forEach(r=>r.duplicate=false));
  const signature=r=>JSON.stringify([r.sender,r.kind,r.text.trim()]);
  for(let i=1;i<draft.pages.length;i++){
   const a=draft.pages[i-1].rows,b=draft.pages[i].rows;
   for(let n=Math.min(a.length,b.length,80);n>=2;n--){if(b.slice(0,n).every((r,j)=>r.text.trim()&&signature(r)===signature(a[a.length-n+j]))){b.slice(0,n).forEach(r=>r.duplicate=true);count+=n;break;}}
  }
  renderRows();e('status').textContent=count?`标出了 ${count} 条疑似重叠消息，未自动删除。切换截图查看并核对。`:'未发现连续重叠文字；这不代表没有重复，请继续人工核对。';
 };
 e('browse').onclick=async()=>{try{const r=await api('browse',{kind:'folder',category:'output'});if(r.path){e('output').value=r.path;changed();}}catch(err){fail(err);}};
 e('export').onclick=async()=>{
  if(draft.busy)return;if(!e('confirm').checked){toast('请先完成核对，再勾选确认');return;}
  busy(true);e('result').textContent='正在保存…';
  try{
   const rows=draft.pages.flatMap(p=>p.rows.map(r=>({image:p.id,text:r.text,sender:r.sender,kind:r.kind,box:r.box,time:r.time?new Date(r.time).toISOString():''})));
   const result=await api('screenshots/export',{generation:draft.generation,order:draft.pages.map(p=>p.id),rows,reviewed:true,output:e('output').value,name:e('name').value,selfName:e('self').value,otherName:e('other').value});
   e('result').textContent=`已保存 ${result.summary.messageCount} 条记录。${result.summary.unknownTimeCount} 条时间未知，${result.summary.unresolvedSenderCount} 条发送者未知。位置：${result.path}`;
   renderState(await api('state'));
   e('result-actions').hidden=false;
  }catch(err){e('result').textContent='未保存：'+err.message;}finally{busy(false);pages();}
 };
 e('open').onclick=openArchive;e('folder').onclick=()=>action('open-folder');
 window.addEventListener('beforeunload',event=>{if(draft.busy){event.preventDefault();event.returnValue='';}});
 api('config').then(c=>{draft.available=!!c.screenshotAvailable;e('capability').textContent=draft.available?'Apple Vision 已就绪，无需下载模型或填写 API。':'此版本没有可用的 Mac 本地识别组件，请使用包含截图识别的 Mac 安装包。';e('output').value=c.output;e('recognize').disabled=!draft.available||!e('files').files.length;}).catch(fail);
})();
