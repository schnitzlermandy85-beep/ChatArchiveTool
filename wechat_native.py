"""Import WeChat's own merged-forward ZIP/TXT without touching the live client.

TXT structure and attachment markers verified against qzz0518/Dukou (MIT),
commit 28f38d7ebb0f107d7bc8cc6ef367753c44250bef. Source bytes are preserved.
Display names are not account IDs; native TXT times have minute precision and
no timezone. Interpret them in this computer's local timezone and disclose it.
"""
from collections import Counter
from contextlib import contextmanager
import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import threading
import unicodedata
import zipfile

from core import Cancelled, emojis, safe_child, save_archive, write_json

MAX_TOTAL = 1024 ** 3
MAX_TEXT = 16 * 1024 ** 2
HEADER = re.compile(r'^·([^\n]+)\n(\d{4}年\d{1,2}月\d{1,2}日 \d{2}:\d{2})\n', re.M)
MARKERS = {}
for kind, words in {
    'image': ('图片', '圖片', 'photo', 'image'),
    'video': ('视频', '小视频', '影片', '微影片', 'video'),
    'audio': ('语音', '語音', '录音', '錄音', '音频', '音訊', 'voice', 'audio', 'recording'),
    'sticker': ('表情', '动画表情', '動態貼圖', 'sticker'),
    'file': ('文件', '檔案', 'file'),
}.items():
    for word in words: MARKERS[word] = kind


def check(stop):
    if stop.is_set(): raise Cancelled('已停止整合微信导出文件')


def parse_transcript(body):
    body = body.lstrip('\ufeff').replace('\r\n', '\n')
    matches = list(HEADER.finditer(body))
    if not matches or matches[0].start() != 0:
        raise ValueError('无法识别微信聊天 TXT。请选择微信“多选 → 合并转发到其他应用”生成的 ZIP；不要选择普通附件或数据库。')
    records = []
    for i, match in enumerate(matches):
        try:
            date = datetime.datetime.strptime(match[2], '%Y年%m月%d日 %H:%M').astimezone()
        except ValueError:
            raise ValueError('微信 TXT 中的日期无效，原文件未修改') from None
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        records.append((match[1], date, body[match.end():end].strip('\n')))
    return records


def is_native(source):
    return source.suffix.lower() in ('.zip', '.txt') or (source.is_dir() and not (source / 'chat_full_parsed.json').exists())


def validated_entries(archive):
    entries = archive.infolist()
    if not entries or len(entries) > 10000 or sum(e.file_size for e in entries) > MAX_TOTAL:
        raise ValueError('微信 ZIP 太大，请分批导出（每批解压后不超过 1 GB）')
    seen, prefixes = set(), {}
    for entry in entries:
        name = entry.filename.rstrip('/')
        parts = name.split('/')
        mode = stat.S_IFMT(entry.external_attr >> 16)
        if (entry.orig_filename != entry.filename or not name or any(p in ('', '.', '..') for p in parts) or '\\' in name or ':' in name
                or any(ord(c) < 32 for c in name) or mode not in (0, stat.S_IFREG, stat.S_IFDIR)
                or entry.flag_bits & 1 or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise ValueError('微信 ZIP 含不安全路径、链接或不支持的压缩方式')
        if name in seen: raise ValueError('微信 ZIP 含重复路径')
        seen.add(name)
        for i in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:i]); key = unicodedata.normalize('NFC', prefix).casefold()
            if key in prefixes and prefixes[key] != prefix: raise ValueError('微信 ZIP 含大小写或 Unicode 冲突路径')
            prefixes[key] = prefix
    files = {e.filename for e in entries if not e.is_dir()}
    for name in files:
        if any(str(parent) in files for parent in PurePosixPath(name).parents if str(parent) != '.'):
            raise ValueError('微信 ZIP 中文件和目录冲突')
    return entries


@contextmanager
def unpack(source, stop):
    if source.suffix.lower() != '.zip':
        yield source.parent if source.is_file() else source
        return
    if source.stat().st_size > MAX_TOTAL: raise ValueError('微信 ZIP 超过 1 GB，请分批导出')
    with tempfile.TemporaryDirectory(prefix='chatarchive-wechat-') as tmp:
        root = Path(tmp)
        try:
            with zipfile.ZipFile(source) as archive:
                for entry in validated_entries(archive):
                    check(stop); target = safe_child(root, entry.filename)
                    if entry.is_dir(): target.mkdir(parents=True, exist_ok=True); continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as incoming, target.open('xb') as out:
                        remaining = entry.file_size
                        while block := incoming.read(1024 * 1024):
                            check(stop); remaining -= len(block)
                            if remaining < 0: raise ValueError('ZIP 解压大小与清单不符')
                            out.write(block)
                        if remaining: raise ValueError('ZIP 内容不完整')
                    target.chmod(0o600)
            yield root
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
            raise ValueError('微信 ZIP 已损坏或受密码保护，请重新从微信导出') from None


def transcripts(root, source):
    if source.suffix.lower() == '.txt': return [source]
    # Dukou merges use batches/0001/...; the root TXT is an index, not messages.
    batches = root / 'batches'
    candidates = sorted(batches.glob('*/聊天记录.txt')) if batches.is_dir() else []
    if not candidates:
        candidates = [root / '聊天记录.txt'] if (root / '聊天记录.txt').is_file() else sorted(root.glob('*/聊天记录.txt'))
    if not candidates:
        candidates = [p for p in root.glob('*.txt') if p.is_file()]
    if not candidates or (len(candidates) > 1 and not batches.is_dir()):
        raise ValueError('没有找到唯一的聊天记录.txt，请选择微信生成的 ZIP 或具体 TXT 文件')
    return candidates


def bundle_native(source, dest, model='', transcribe=False, log=print, stop=None, filters=None):
    stop = stop or threading.Event(); filters = filters or {}; source = Path(source).resolve(); dest = Path(dest).resolve()
    records, attachments, stats, voices = [], [], Counter(), Counter()
    warnings = ['仅包含在微信中选中的消息，不代表全部历史。',
                '来源只有显示昵称，无法确认微信账号 ID、同名者或哪一方是本人。',
                '来源时间精确到分钟且不含时区；按这台电脑的本地时区解释。']
    with unpack(source, stop) as root:
        root = root.resolve()
        texts = transcripts(root, source)
        if dest == root or root.is_relative_to(dest) or dest.is_relative_to(root):
            raise ValueError('档案保存目录不能位于微信原始导出目录内，请选择另一个保存位置')
        dest.mkdir(parents=True, exist_ok=True)
        for batch_index, text_file in enumerate(texts):
            check(stop)
            if text_file.is_symlink() or not text_file.resolve().is_relative_to(root) or text_file.stat().st_size > MAX_TEXT:
                raise ValueError('聊天 TXT 路径无效或超过 16 MB')
            raw = text_file.read_bytes()
            try: parsed = parse_transcript(raw.decode('utf-8-sig'))
            except UnicodeDecodeError: raise ValueError('聊天 TXT 不是 UTF-8，请重新从微信导出') from None
            digest = hashlib.sha256(raw).hexdigest()
            # Include batch position: repeated messages and equal TXT batches must not collapse.
            batch_root = text_file.parent
            files = []
            for file in batch_root.rglob('*'):
                check(stop)
                if file.is_symlink(): raise ValueError('微信导出目录中不能包含符号链接')
                if file.is_file(): files.append(file)
                if len(files) > 10000: raise ValueError('微信导出目录文件过多，请选择本次导出的具体目录')
            paths = {p.relative_to(batch_root).as_posix(): p for p in files if p != text_file}
            by_name = {}
            for name, p in paths.items(): by_name.setdefault(p.name, []).append(name)
            for i, (sender, date, body) in enumerate(parsed):
                check(stop); stamp = int(date.timestamp() * 1000)
                if stamp < filters.get('startTime', 0) * 1000 or stamp > filters.get('endTime', 2**63) * 1000: continue
                mid = 'wx-native-' + hashlib.sha256(f'{batch_index}:{digest}:{i}'.encode()).hexdigest()[:24]
                parts, text_lines = [], []
                for line in body.split('\n'):
                    match = re.fullmatch(r'\[([^\]]+)\]\s*(.*)', line.strip())
                    kind = MARKERS.get(match[1].lower()) if match else None
                    if not kind:
                        text_lines.append(line); parts.append({'type': 'text', 'text': line}); continue
                    reference = match[2].removeprefix('./')
                    relative = reference if reference in paths else None
                    if relative is None and '/' not in reference and len(by_name.get(reference, [])) == 1:
                        relative = by_name[reference][0]
                    candidate = paths.get(relative) if relative else None
                    output = None
                    if candidate:
                        if candidate.stat().st_size > MAX_TOTAL: raise ValueError('媒体文件超过 1 GB')
                        with candidate.open('rb') as media_file:
                            hasher = hashlib.sha256()
                            while block := media_file.read(1024 * 1024):
                                check(stop); hasher.update(block)
                            content_hash = hasher.hexdigest()
                        output = safe_child(dest, 'resources/' + kind + '/' + content_hash + candidate.suffix.lower())
                        output.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(candidate, output)
                    item = {'type': kind, 'filename': reference or '[' + match[1] + ']', 'available': bool(output),
                            'path': output.relative_to(dest).as_posix() if output else None,
                            'reason': None if output else '微信原生导出未提供可唯一匹配的附件，原文已保留'}
                    stats[kind] += 1
                    if not output: stats['missing_' + kind] += 1
                    if kind == 'audio':
                        item['transcription'] = {'status': '未转写' if output else '缺失音频', 'text': ''}
                        voices[item['transcription']['status']] += 1
                    parts.append(item); attachments.append({'messageId': mid, **item})
                text = '\n'.join(text_lines); emoji = emojis(text); stats['unicodeEmoji'] += len(emoji)
                records.append({'id': mid, 'timestamp': stamp, 'time': date.isoformat(),
                                'sender': {'uid': None, 'name': sender, 'isSelf': None, 'resolutionStatus': 'unresolved_display_name'},
                                'system': False, 'text': text, 'voiceText': '', 'analysisText': text, 'emoji': emoji,
                                'parts': parts, 'original': {'source': 'wechat-native', 'batch': batch_index,
                                'recordIndex': i, 'text': body, 'timestampPrecision': 'minute'}})
            # Retain original TXT, including unsupported cards and unmatched file references.
            original = dest / 'source-native' / str(batch_index)
            original.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(text_file, original / '聊天记录.txt')
            log(f'整合微信原生导出：第 {batch_index + 1} 批，{len(parsed)} 条消息')
        if source.suffix.lower() == '.zip':
            shutil.copyfile(source, dest / 'source-native/original.zip')
        if not records: raise ValueError('所选日期范围内没有微信消息')
        if voices: warnings.append('微信原生导出中的语音暂不自动转写；有原文件则保留，没有则标注缺失。')
        records.sort(key=lambda m: m['timestamp'])
        result = save_archive(records, attachments, {'chatInfo': {'name': source.stem, 'type': 'unknown'}},
                              dest, dict(stats), dict(voices), platform='WeChat', exporter='WeChat native merged-forward', log=log)
        result.update(historyCompleteness='selected_messages_only', analysisEligible=False, warnings=warnings,
                      senderResolutionCounts={'unresolved_display_name': len(records)}, filter=filters)
        write_json(dest / 'manifest.json', result)
        for warning in warnings: log(warning)
        return result
