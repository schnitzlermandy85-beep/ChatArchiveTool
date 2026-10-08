"""macOS WeChat export via wxvault's validated, refreshed local SQLite snapshots.

Reference: with-yang/wxvault v0.1.0 (Apache-2.0), cache key layout and
WeChat 4.x Name2Id/Msg_* schema. CLI display strings are not sender identities.
"""
from __future__ import annotations
import base64
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import xml.etree.ElementTree as ET

from core import Cancelled, write_json
from desktop_exporters import run_wxvault, check_stop

MAX_MESSAGES = 1_000_000


def cache_root():
    return Path.home() / '.wxvault/cache'


def cache_file(relative):
    return cache_root() / (hashlib.md5(relative.encode()).hexdigest() + '.db')


def read_snapshot(path):
    path = Path(path).resolve()
    if not path.is_relative_to(cache_root().resolve()) or not path.is_file():
        raise ValueError('微信缓存路径无效，请重新初始化')
    # SQLite backup gives this query a stable view, including committed WAL data.
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
        snapshot = sqlite3.connect(':memory:')
        source.backup(snapshot)
    snapshot.row_factory = sqlite3.Row
    return snapshot


def contacts():
    with closing(read_snapshot(cache_file('contact/contact.db'))) as db:
        return [dict(row) for row in db.execute('SELECT username, nick_name, remark FROM contact')]


def exact_contact(rows, keyword):
    by_id = [r for r in rows if r['username'] == keyword]
    matches = by_id or [r for r in rows if keyword in (r.get('remark'), r.get('nick_name'))]
    if len(matches) != 1:
        raise ValueError('联系人未唯一匹配，请填写完整备注、昵称、群名或 wxid；同名时使用 wxid')
    return matches[0]


def decode_content(value):
    if isinstance(value, str):
        return value
    if value is None:
        return ''
    value = bytes(value)
    if value.startswith(b'\x28\xb5\x2f\xfd'):
        try:
            import zstandard
        except ImportError:
            raise ValueError('缺少微信正文解压依赖；源码版请先运行 python3 -m pip install zstandard') from None
        with zstandard.ZstdDecompressor().stream_reader(value) as reader:
            value = reader.read(32 * 1024 * 1024 + 1)
        if len(value) > 32 * 1024 * 1024:
            raise ValueError('微信单条消息正文过大，已停止导出')
    return value.decode('utf-8', errors='replace')


def message_content(raw, kind, group):
    if group and re.match(r'^[^\s<>:]+:\n', raw):
        raw = raw.split(':\n', 1)[1]
    if kind in (1, 10000):
        return raw
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return ''
    if kind == 49:
        title = root.findtext('.//appmsg/title') or root.findtext('.//title') or ''
        url = root.findtext('.//appmsg/url') or ''
        return '\n'.join(part for part in (title, url) if part)
    if kind == 48:
        node = root.find('.//location')
        return node.get('label', '') if node is not None else ''
    return ''


def own_username():
    try:
        config = json.loads((Path.home() / '.wxvault/config.json').read_text(encoding='utf-8'))
        name = Path(config['db_dir']).parent.name
        return re.sub(r'_[0-9a-fA-F]{4}$', '', name)
    except (OSError, KeyError, ValueError):
        return None


def rows_from_snapshot(path, relative, peer, names, filters, stop=None):
    group = peer.endswith('@chatroom')
    table = 'Msg_' + hashlib.md5(peer.encode()).hexdigest()
    with closing(read_snapshot(path)) as db:
        if not db.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?', (table,)).fetchone():
            raise ValueError('微信分片缺少目标会话表，未生成可能不完整的档案')
        mapping = {row[0]: row[1] for row in db.execute('SELECT rowid,user_name FROM Name2Id')}
        columns = {row[1] for row in db.execute(f'PRAGMA table_info([{table}])')}
        required = {'local_id', 'local_type', 'create_time', 'real_sender_id', 'message_content'}
        if not required <= columns:
            raise ValueError('当前微信数据库结构暂不兼容，未生成不完整的档案')
        begin = filters.get('startTime', 0)
        end = filters.get('endTime', int(time.time()))
        query = f'SELECT * FROM [{table}] WHERE create_time>=? AND create_time<=? ORDER BY create_time,local_id'
        for index, row in enumerate(db.execute(query, (begin, end))):
            check_stop(stop)
            if index >= MAX_MESSAGES:
                raise ValueError('会话超过导出条数限制，请缩小日期范围')
            item = dict(row)
            raw = decode_content(item['message_content'])
            sender = mapping.get(item['real_sender_id'])
            if group and (not sender or sender == peer):
                match = re.match(r'^([^\s<>:]+):\n', raw)
                sender = match[1] if match else None
            kind = int(item['local_type']) & 0xFFFFFFFF
            # Preserve native IDs with the source shard; local_id is not globally unique.
            yield {'source_db': relative, 'local_id': item['local_id'],
                   'server_id': item.get('server_id'), 'sort_seq': item.get('sort_seq') or item['create_time'],
                   'timestamp': int(item['create_time']), 'type_code': kind,
                   'sender_username': sender, 'sender': names.get(sender, sender or '未知发送者'),
                   'sender_status': 'resolved' if sender and sender != peer or (sender == peer and not group) else 'unresolved',
                   'content': message_content(raw, kind, group), '_raw_xml': raw}


def image_extension(path):
    with path.open('rb') as f:
        magic = f.read(16)
    if magic.startswith(b'\xff\xd8\xff'): return '.jpg'
    if magic.startswith(b'\x89PNG'): return '.png'
    if magic.startswith(b'GIF8'): return '.gif'
    if magic.startswith(b'RIFF') and magic[8:12] == b'WEBP': return '.webp'
    return '.bin'


def add_media(message, peer, folder, stop):
    kind = {3: 'image', 34: 'audio', 43: 'video', 47: 'sticker'}.get(message['type_code'])
    if message['type_code'] == 49:
        try:
            if ET.fromstring(message['_raw_xml']).findtext('.//appmsg/type') == '6':
                kind = 'file'
        except ET.ParseError:
            pass
    if not kind:
        return
    media = {'kind': kind, 'available': False, 'path': None,
             'reason': '当前 Mac 读取组件尚不支持导出此类媒体原文件；消息占位保留'}
    message['media'] = media
    if kind != 'image':
        return
    shard = re.fullmatch(r'message/message_(\d+)\.db', message['source_db'])
    payload = {'v': 1, 'chat': peer, 'local_id': message['local_id'],
               'create_time': message['timestamp'], 'kind': 'image'}
    if shard:
        payload['db'] = int(shard[1])
    attachment_id = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    target = folder / 'media' / (hashlib.sha256(attachment_id.encode()).hexdigest() + '.bin')
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_wxvault(['extract', attachment_id, '--output', str(target), '--overwrite', '--json'], stop, timeout=60)
        if not target.is_file():
            raise ValueError('No output')
        renamed = target.with_suffix(image_extension(target))
        if renamed != target:
            target.replace(renamed)
        media.update(available=True, path=renamed.relative_to(folder).as_posix(), reason=None)
    except (ValueError, OSError):
        target.unlink(missing_ok=True)
        media['reason'] = '本机图片提取失败或原图未下载；已保留消息占位'


def export_wechat_mac(keyword, dest, db_dir='', log=print, stop=None, filters=None):
    if db_dir:
        raise ValueError('Mac 版由初始化组件绑定当前账号，请清空 Windows 数据目录设置；换账号后重新初始化')
    # Refresh contacts and validate the configured account without dumping messages to logs.
    log('正在连接 Mac 微信本地读取组件…')
    run_wxvault(['sessions', '--limit', '1', '--json'], stop)
    people = contacts()
    selected = exact_contact(people, keyword.strip())
    peer = selected['username']
    names = {r['username']: r.get('remark') or r.get('nick_name') or r['username'] for r in people}
    # Refresh ALL shards, then read native rows from the per-shard snapshots. This
    # avoids the CLI's default 50/500-row limits and loss of private sender IDs.
    probe = run_wxvault(['--debug-source', 'history', peer, '--limit', '1', '--json'], stop)
    if probe.get('username') != peer:
        raise ValueError('微信组件返回了不同联系人，已停止导出')
    meta = probe.get('meta', {})
    if meta.get('unknown_shards') or meta.get('status') not in ('ok','windowed'):
        raise ValueError('微信存在未解锁或过期的消息分片，请重新初始化连接后再导出')
    shards = meta.get('shard_paths')
    if not isinstance(shards, dict) or not shards:
        raise ValueError('微信组件未返回完整分片清单，请重新初始化')
    filtered = dict(filters or {})
    filtered.setdefault('endTime', int(time.time()))
    messages = []
    me = own_username()
    folder = Path(dest).resolve() / 'source'
    folder.mkdir(parents=True, exist_ok=True)
    for relative, path in sorted(shards.items()):
        if not re.fullmatch(r'message/message_\d+\.db', relative):
            raise ValueError('微信组件返回未知分片结构')
        if Path(path).resolve() != cache_file(relative).resolve():
            raise ValueError('微信组件缓存路径与分片不匹配')
        log('正在读取微信消息分片…')
        for message in rows_from_snapshot(path, relative, peer, names, filtered, stop):
            if len(messages) >= MAX_MESSAGES:
                raise ValueError('会话超过导出条数限制，请缩小日期范围')
            sender = message['sender_username']
            message['is_self'] = sender == me if sender and me else None
            add_media(message, peer, folder, stop)
            message.pop('_raw_xml', None)
            messages.append(message)
    if not messages:
        raise ValueError('所选日期范围内没有微信消息')
    messages.sort(key=lambda m: (m['timestamp'], m['source_db'], m['local_id']))
    unavailable = Counter(m['media']['kind'] for m in messages if m.get('media') and not m['media']['available'])
    if unavailable:
        log('部分媒体未导出原文件：' + '、'.join(f'{k} {v} 条' for k, v in unavailable.items()) + '；档案保留占位及原因')
    output = folder / 'chat_full_parsed.json'
    write_json(output, {'exporter_version': 'ChatArchiveTool/wxvault-v0.1.0',
        'chat_name': names[peer], 'chat_type': 'group' if peer.endswith('@chatroom') else 'private',
        'message_count': len(messages), 'messages': messages})
    log(f'Mac 微信读取完成，共 {len(messages)} 条消息')
    return output
