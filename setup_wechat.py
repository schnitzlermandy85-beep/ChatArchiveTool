"""Install isolated wheel dependencies, pinned upstream reader, verified decoder."""
from __future__ import annotations
import pathlib,urllib.request,json,zipfile,io,hashlib,sys
try:
 from packaging.tags import sys_tags
 from packaging.requirements import Requirement
 from packaging.utils import parse_wheel_filename
 from packaging.version import Version
except ImportError:
 from pip._vendor.packaging.tags import sys_tags
 from pip._vendor.packaging.requirements import Requirement
 from pip._vendor.packaging.utils import parse_wheel_filename
 from pip._vendor.packaging.version import Version
ROOT=pathlib.Path(__file__).resolve().parent
COMMIT='04ef8cbde3862cff90b5f6b42c9ebfcea44ef48d'

def install(target=ROOT/'.wechat-packages',log=print):
 target=pathlib.Path(target).resolve();target.mkdir(parents=True,exist_ok=True);tags=set(sys_tags());done={}
 pending=[Requirement(n) for n in ['zstandard','Pillow>=9','psutil>=5.9','imageio-ffmpeg>=0.4.9','uiautomation>=2.0.18','pywin32>=305','pyperclip>=1.8.2','colorama>=0.4.6','cryptography>=41','winsdk>=1.0.0b10']]
 def fetch(url):
  with urllib.request.urlopen(url,timeout=90) as response:return response.read()
 while pending:
  req=pending.pop(0)
  if req.marker and not req.marker.evaluate({'extra':''}):continue
  key=req.name.lower().replace('_','-')
  if key in done:
   if done[key] not in req.specifier:raise RuntimeError('依赖版本冲突：'+str(req))
   continue
  log('安装微信依赖：'+req.name)
  info=json.loads(fetch('https://pypi.org/pypi/'+req.name+'/json'));selected=None
  versions=sorted((Version(v) for v in info['releases'] if req.specifier.contains(v,prereleases=None)),reverse=True)
  for version in versions:
   for f in info['releases'][str(version)]:
    if f.get('yanked') or not f['filename'].endswith('.whl'):continue
    try:_,_,_,wheel_tags=parse_wheel_filename(f['filename'])
    except ValueError:continue
    if tags & wheel_tags:selected=f;break
   if selected:break
  if not selected:raise RuntimeError('当前Python没有可用的Windows wheel：'+str(req)+'；建议Python 3.11或3.12 x64')
  data=fetch(selected['url'])
  if hashlib.sha256(data).hexdigest()!=selected['digests']['sha256']:raise RuntimeError('依赖下载校验失败：'+req.name)
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   for name in z.namelist():
    if name.endswith('/'):continue
    out=(target/name).resolve()
    if not out.is_relative_to(target):raise ValueError('非法依赖归档路径')
    if '.data/' in name:
     _,area,rel=name.split('/',2)
     if area not in ('purelib','platlib'):continue
     out=(target/rel).resolve()
     if not out.is_relative_to(target):raise ValueError('非法依赖归档路径')
    out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(z.read(name))
  done[key]=version
  release=json.loads(fetch('https://pypi.org/pypi/'+req.name+'/'+str(version)+'/json'))
  pending.extend(Requirement(r) for r in (release['info'].get('requires_dist') or []))
 log('安装固定版本微信读取组件')
 data=fetch('https://codeload.github.com/fanyuantaier/wechatauto-replica/zip/'+COMMIT)
 with zipfile.ZipFile(io.BytesIO(data)) as z:
  for n in z.namelist():
   if n.endswith('/'):continue
   parts=n.split('/');rel='/'.join(parts[1:])
   if not rel.startswith('wechatauto/') and not rel.upper().startswith('LICENSE'):continue
   out=(target/rel).resolve()
   if not out.is_relative_to(target):raise ValueError('非法读取组件路径')
   out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(z.read(n))
 log('安装语音SILK解码器')
 data=fetch('https://github.com/Wangnov/rust-silk/releases/download/v0.1.3/rust-silk-x86_64-pc-windows-msvc.zip')
 if hashlib.sha256(data).hexdigest()!='44a01bc0f3ec3ec6f6044b656869b0dd7c298329d12f07c7f7a846be72a89504':raise RuntimeError('SILK解码器SHA-256校验失败')
 with zipfile.ZipFile(io.BytesIO(data)) as z:
  member=next(n for n in z.namelist() if pathlib.Path(n).name.lower()=='rust-silk.exe');(target/'rust-silk.exe').write_bytes(z.read(member))
 (target/'chatarchive-runtime.json').write_text(json.dumps({'readerCommit':COMMIT,'packages':{k:str(v) for k,v in done.items()},'silkVersion':'0.1.3'},indent=2),encoding='utf-8')
 log('微信组件安装完成')

if __name__=='__main__':
 try:install(pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'.wechat-packages')
 except Exception as e:print('安装失败：'+str(e));sys.exit(1)
