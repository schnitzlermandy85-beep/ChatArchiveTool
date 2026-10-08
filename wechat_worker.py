"""Isolated upstream adapter. Cancellation unwinds through upstream cleanup."""
import sys,pathlib,json,hashlib,re,xml.etree.ElementTree as ET,shutil
ROOT=pathlib.Path(__file__).resolve().parent

def run(request):
 cfg=json.loads(pathlib.Path(request).read_text(encoding='utf-8'));sys.path.insert(0,cfg['runtime']);sys.path.insert(0,str(ROOT/'vendor/wechat_export'))
 # pywin32 wheels use these directories for importable native modules.
 for n in ['win32','win32/lib','pywin32_system32','pythonwin']:sys.path.insert(0,str(pathlib.Path(cfg['runtime'])/n))
 import os
 dll=pathlib.Path(cfg['runtime'])/'pywin32_system32'
 handle=os.add_dll_directory(str(dll)) if dll.exists() and hasattr(os,'add_dll_directory') else None
 import exporter_core as upstream
 decoder=pathlib.Path(cfg["runtime"])/"rust-silk.exe"
 if decoder.exists():upstream._find_rust_silk=lambda:decoder
 if cfg.get("check_only"):
  print("CHATARCHIVE_RESULT:"+json.dumps({"ready":True,"decoder":decoder.exists()}),flush=True);return
 def progress(s):
  if pathlib.Path(cfg['cancel']).exists():raise InterruptedError('用户停止导出')
  print(s,flush=True)
 captured=[];account=None;real_load=upstream.load_rows
 def load(db,username):
  nonlocal account
  account=pathlib.Path(db.account_dir);rows=real_load(db,username)
  filters=cfg.get('filters',{});rows=[r for r in rows if filters.get('startTime',0)<=int(r.get('create_time') or 0)<=filters.get('endTime',2**63)]
  captured.extend(rows);return rows
 upstream.load_rows=load
 def exact_contact(db,keyword):
  matches=db.search_contact(keyword);exact=[m for m in matches if keyword in (m.get('username'),m.get('remark'),m.get('nick_name'))]
  if len(exact)!=1:raise ValueError('联系人未唯一匹配，请填写准确备注、昵称、群名或wxid；不自动选择模糊搜索的第一项')
  return exact[0]
 upstream.find_contact=exact_contact
 result=upstream.export_chat(cfg['keyword'],cfg['out'],progress=progress,export_images=True,export_files=True,export_voices=True,export_videos=True,transcribe_voices=False,db_dir=cfg.get('db_dir'))
 progress('正在关联微信本地表情缓存…')
 source=pathlib.Path(result['json']);meta=json.loads(source.read_text(encoding='utf-8-sig'))
 if len(captured)!=len(meta['messages']):raise ValueError('上游消息数量变化，无法关联表情缓存')
 wanted={}
 for row,msg in zip(captured,meta['messages']):
  if row.get('local_id')!=msg.get('local_id') or row.get('_db_rel')!=msg.get('source_db'):raise ValueError('上游消息身份变化')
  msg['timestamp']=int(row.get('create_time') or 0)*1000
  if upstream.low_type(row.get('local_type'))!=47:continue
  raw=upstream.decode_blob(row.get('message_content')) or upstream.decode_blob(row.get('compress_content'));msg['sticker_xml']=raw
  xml=upstream.xml_root(raw);emoji=xml.find('.//emoji') if xml is not None else None
  if xml is not None and xml.tag=='emoji':emoji=xml
  md5=emoji.get('md5','').lower() if emoji is not None else ''
  msg['media']={'kind':'sticker','available':False,'path':None,'md5':md5,'reason':'本机未找到可验证的表情缓存'}
  if re.fullmatch('[0-9a-f]{32}',md5):wanted.setdefault(md5,[]).append(msg)
 if wanted and account and account.is_dir():
  for f in account.rglob('*'):
   if pathlib.Path(cfg['cancel']).exists():raise InterruptedError('用户停止导出')
   if not f.is_file():continue
   candidates=set(re.findall('[0-9a-fA-F]{32}',f.name))
   for md5 in candidates:
    md5=md5.lower()
    if md5 not in wanted:continue
    try:
     if f.stat().st_size>32*1024*1024:continue
     data=f.read_bytes()
     if hashlib.md5(data).hexdigest()!=md5:continue
     from PIL import Image
     with Image.open(f) as image:ext={'GIF':'.gif','PNG':'.png','JPEG':'.jpg','WEBP':'.webp'}.get(image.format)
     if not ext:continue
     out=source.parent/'media/stickers'/(md5+ext);out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(data)
     for msg in wanted[md5]:msg['media'].update(available=True,path=out.relative_to(source.parent).as_posix(),reason=None)
    except (OSError,ValueError):continue
 with source.open('w',encoding='utf-8') as f:json.dump(meta,f,ensure_ascii=False,indent=2)
 print('CHATARCHIVE_RESULT:'+json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':
 try:run(sys.argv[1])
 except Exception as e:
  print('CHATARCHIVE_ERROR:'+str(e),flush=True);sys.exit(1)
