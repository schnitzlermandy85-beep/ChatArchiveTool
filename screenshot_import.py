"""User-selected screenshot OCR and reviewed export. Never inspect client processes."""
import base64
from collections import Counter
import datetime as dt
import io
import json
import math
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import warnings
from PIL import Image, ImageOps
from core import ROOT, save_archive, write_json

MAX_IMAGES = 30
MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 25_000_000

def helper_path():
    if getattr(sys, 'frozen', False):
        return ROOT / 'screenshot-ocr'
    return ROOT / 'build/screenshot-ocr/screenshot-ocr'

def capability():
    return sys.platform == 'darwin' and helper_path().is_file()

def box(value):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError('截图区域不正确，请重新框选')
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise ValueError('截图区域不正确')
    x,y,w,h = value
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > 1.001 or y+h > 1.001:
        raise ValueError('框选区域超出截图')
    return [x,y,min(w,1-x),min(h,1-y)]

class ScreenshotImport:
    def __init__(self):
        self.lock = threading.Lock()
        self.temp = None
        self.images = {}
        self.generation = ''
    def reset(self):
        with self.lock:
            if self.temp: self.temp.cleanup()
            self.temp = tempfile.TemporaryDirectory(prefix='chatarchive-screenshots-')
            self.images = {}
            self.generation = secrets.token_hex(16)
            return {'generation': self.generation}
    def upload(self, p):
        if not capability(): raise ValueError('本地截图识别目前仅支持包含识别组件的 Mac 版本')
        with self.lock:
            self.require_generation(p)
            if len(self.images) >= MAX_IMAGES: raise ValueError('每批最多 30 张截图，请先导出这一批')
            encoded = p.get('data','')
            if not isinstance(encoded,str) or len(encoded) > MAX_BYTES*4//3+4: raise ValueError('每张截图请控制在 8 MB 以内')
            try: raw=base64.b64decode(encoded,validate=True)
            except ValueError: raise ValueError('截图数据不完整') from None
            if not raw or len(raw)>MAX_BYTES: raise ValueError('截图大小不正确')
            image_id=secrets.token_hex(12); root=Path(self.temp.name)
            normalized=root/(image_id+'.png')
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(raw)) as im:
                        if im.format not in ('PNG','JPEG') or im.width*im.height>MAX_PIXELS: raise ValueError('请选择不超过 2500 万像素的 PNG 或 JPEG 图片')
                        extension='png' if im.format=='PNG' else 'jpg'
                        im=ImageOps.exif_transpose(im).convert('RGB')
                        width,height=im.size
                        im.save(normalized)
            except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                raise ValueError('图片无法读取或尺寸过大，请重新截图') from None
            try:
                result=subprocess.run([str(helper_path()),str(normalized)],capture_output=True,timeout=90)
                if result.returncode: raise ValueError('系统识别组件未完成处理。请重新打开 App 后重试；仍失败可尝试较小的 PNG 截图。')
                lines=json.loads(result.stdout)
                lines.sort(key=lambda r:(round(r['box'][1],3),r['box'][0]))
                rows=[]
                for line in lines[:1000]:
                    b=box(line['box'])
                    # Alignment is only a suggestion. Export requires explicit human review.
                    sender='self' if b[0]>.5 else 'other' if b[0]+b[2]<.5 else 'unknown'
                    rows.append({'text':str(line['text']), 'confidence':float(line['confidence']),
                                 'box':b,'sender':sender,'kind':'text','time':''})
            except Exception:
                normalized.unlink(missing_ok=True)
                raise
            preview=io.BytesIO()
            with Image.open(normalized) as thumb:
                thumb.thumbnail((1200,2400))
                thumb.save(preview,format='PNG')
            original=root/(image_id+'.original.'+extension);original.write_bytes(raw)
            self.images[image_id]={'normalized':normalized,'original':original,'extension':extension,'width':width,'height':height}
            return {'id':image_id,'rows':rows,'width':width,'height':height,
                    'preview':base64.b64encode(preview.getvalue()).decode('ascii')}
    def require_generation(self,p):
        if not self.temp or p.get('generation')!=self.generation: raise ValueError('截图工作区已失效，请重新选择截图')
    def export(self,p):
        with self.lock:
            self.require_generation(p)
            if p.get('reviewed') is not True: raise ValueError('请先核对文字、发送者、时间和重复消息，再确认导出')
            rows=p.get('rows'); order=p.get('order')
            if not isinstance(rows,list) or not 1<=len(rows)<=5000: raise ValueError('请保留 1 至 5000 条记录')
            if not isinstance(order,list) or not order or len(set(order))!=len(order) or any(i not in self.images for i in order): raise ValueError('截图顺序不正确')
            names={key:str(p.get(key+'Name') or default).strip()[:80] for key,default in [('self','我'),('other','对方')]}
            records=[];attachments=[];stats=Counter();crops=[]
            for i,row in enumerate(rows):
                if not isinstance(row,dict) or row.get('image') not in order: raise ValueError('消息来源截图无效')
                sender=row.get('sender');kind=row.get('kind');text=row.get('text','')
                if sender not in ('self','other','unknown','system') or kind not in ('text','image','sticker'): raise ValueError('消息类型或发送者不正确')
                if not isinstance(text,str) or len(text)>20000: raise ValueError('单条文字过长')
                if kind=='text' and not text.strip(): raise ValueError('空白文字请删除或补充后导出')
                b=box(row.get('box')); time=row.get('time') or ''; stamp=None
                if time:
                    try:
                        parsed=dt.datetime.fromisoformat(time)
                        if parsed.tzinfo is None: raise ValueError()
                        stamp=int(parsed.timestamp()*1000)
                        if not 0<=stamp<=4102444800000: raise ValueError()
                    except (ValueError,TypeError,OverflowError): raise ValueError('日期需要完整年份、日期、时间和时区') from None
                mid=f'screenshot-{i+1:05d}'
                parts=[{'type':'text','text':text}] if text else []
                if kind!='text':
                    rel=f'media/{mid}.png'
                    part={'type':kind,'filename':mid+'.png','path':rel,'available':True,'isScreenshotCrop':True}
                    parts.append(part);attachments.append({'messageId':mid,**part});stats[kind]+=1
                    crops.append((row['image'],b,rel))
                records.append({'id':mid,'timestamp':stamp,'time':time or '时间未知',
                    'sender':{'uid':'screenshot:'+sender if sender in names else None,
                              'name':names.get(sender,'系统' if sender=='system' else '未知发送者'),
                              'isSelf':sender=='self' if sender in names else None,
                              'resolutionStatus':'resolved' if sender in names else 'unresolved_screenshot',
                              'identitySource':'user_confirmed_screenshot_role'},
                    'system':sender=='system','text':text,'voiceText':'','analysisText':text,'emoji':[], 'parts':parts,
                    'original':{'source':'screenshot-ocr','image':row['image'],'box':b,'reviewed':True,
                                'timestampSource':'user_confirmed' if stamp is not None else 'unknown'}})
            output=str(p.get('output') or '').strip()
            if not output: raise ValueError('请选择保存位置')
            parent=Path(output).expanduser().resolve();parent.mkdir(parents=True,exist_ok=True)
            target=parent/('screenshot-chat-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3))
            stage=Path(tempfile.mkdtemp(prefix='.screenshot-export-',dir=parent))
            try:
                (stage/'media').mkdir();(stage/'source-screenshots').mkdir()
                sources=[]
                for i,image_id in enumerate(order):
                    entry=self.images[image_id];rel=f'source-screenshots/{i+1:03d}.{entry["extension"]}'
                    shutil.copyfile(entry['original'],stage/rel)
                    sources.append({'id':image_id,'path':rel,'width':entry['width'],'height':entry['height']})
                paths={s['id']:s['path'] for s in sources}
                for r in records:r['original']['path']=paths[r['original']['image']]
                for image_id,b,rel in crops:
                    with Image.open(self.images[image_id]['normalized']) as im:
                        x,y,w,h=b
                        im.crop((int(x*im.width),int(y*im.height),max(int(x*im.width)+1,round((x+w)*im.width)),max(int(y*im.height)+1,round((y+h)*im.height)))).save(stage/rel)
                unknown_time=sum(r['timestamp'] is None for r in records)
                unknown_sender=sum(not r['sender']['uid'] and not r['system'] for r in records)
                summary=save_archive(records,attachments,{'chatInfo':{'name':str(p.get('name') or '截图聊天')[:100],'type':'private'}},stage,dict(stats),{},platform='WeChat',exporter='Apple Vision + human review',log=lambda _:None)
                summary.update(historyCompleteness='screenshots_only',analysisEligible=not unknown_time and not unknown_sender,
                    unknownTimeCount=unknown_time,unresolvedSenderCount=unknown_sender,
                    warnings=['仅覆盖所选截图；OCR 经人工核对仍可能有误。','图片和表情为截图裁片，未恢复原始媒体；语音与视频未导出。',f'{unknown_time} 条时间未知，{unknown_sender} 条发送者未知。'],sources=sources)
                write_json(stage/'manifest.json',summary)
                write_json(stage/'review.json',{'rows':rows,'order':order,'selfName':names['self'],'otherName':names['other']})
                stage.rename(target)
            except Exception:
                shutil.rmtree(stage);raise
            return target,summary
