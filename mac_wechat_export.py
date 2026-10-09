"""Mac WeChat 4.x reader using qwe11223's media formats and message parser.

Copies encrypted DB/WAL pairs before SQLCipher opens them. Requires every
message shard; never guesses media association from file ordering or mtime.
"""
from __future__ import annotations
from contextlib import closing
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import wave

from core import ROOT, Cancelled, write_json
from platform_support import data_root
from vendor.wechat_mac import image_dat, message_parser
from vendor.wechat_mac.models import Layout, Message

MAX_MEDIA = 1024 * 1024 * 1024
MAX_IMAGE = 64 * 1024 * 1024


def check_stop(stop):
    if stop and stop.is_set():
        raise Cancelled('已停止微信导出，临时数据库副本已清理')


def config_path():
    return data_root(ROOT) / 'components/wechat-mac/connection.json'


def private_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def layout_for(db_dir=''):
    root = Path.home() / 'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files'
    if db_dir:
        db = Path(db_dir).expanduser().resolve()
        if db.name != 'db_storage' or not db.is_relative_to(root.resolve()):
            raise ValueError('请选择当前用户微信账号内的 db_storage 文件夹')
    else:
        try:
            matches = [p / 'db_storage' for p in root.iterdir() if (p / 'db_storage/message').is_dir()]
        except PermissionError:
            raise ValueError('无法读取微信文件。请在“系统设置 → 隐私与安全性 → 完全磁盘访问”允许 ChatArchiveTool，然后重开本工具') from None
        except FileNotFoundError:
            matches = []
        if len(matches) != 1:
            raise ValueError('检测到多个微信账号，请在来源设置选择当前账号的 db_storage 文件夹' if matches else '未找到微信 4.x 本机记录。请登录电脑微信，打开目标聊天，等待同步后重试')
        db = matches[0]
    shards = sorted(p for p in (db / 'message').glob('message_*.db') if re.fullmatch(r'message_\d+\.db', p.name))
    if not shards or not (db / 'contact/contact.db').is_file():
        raise ValueError('未找到完整的微信 4.x 消息库和联系人库，请确认账号及本机同步状态')
    account = db.parent
    return Layout('v4', str(account), account.name, [str(p) for p in shards],
                  str(db / 'contact/contact.db'), media_root=str(account / 'msg'))


def load_connection(db_dir=''):
    try:
        cfg = json.loads(config_path().read_text(encoding='utf-8'))
        layout = layout_for(db_dir or cfg['dbDir'])
        if Path(cfg['dbDir']).resolve() != Path(layout.account_dir, 'db_storage').resolve():
            raise ValueError('所选账号与已连接账号不同，请重新连接所选账号')
        keys = cfg['keys']
        if not isinstance(keys, dict) or not keys:
            raise KeyError('keys')
        return layout, keys
    except (OSError, KeyError, json.JSONDecodeError):
        raise ValueError('请先点击“连接并检查”，完成本机微信读取授权') from None


def fingerprint(path):
    try:
        stat = path.stat()
        return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    except FileNotFoundError:
        return None


def copy_database(src, target, stop=None):
    """Copy a quiescent DB+WAL pair; never create sidecars beside WeChat data."""
    src, target = Path(src), Path(target)
    sources = [src, Path(str(src) + '-wal')]
    for _ in range(3):
        check_stop(stop)
        before = [fingerprint(p) for p in sources]
        if before[0] is None:
            raise ValueError('微信数据库已移动，请重新连接当前账号')
        for source, stamp, suffix in zip(sources, before, ('', '-wal')):
            dest = Path(str(target) + suffix)
            dest.unlink(missing_ok=True)
            if stamp:
                if source.is_symlink():
                    raise ValueError('微信数据库路径包含符号链接，已停止读取')
                shutil.copyfile(source, dest)
                dest.chmod(0o600)
        if before == [fingerprint(p) for p in sources]:
            return
        time.sleep(.1)
    raise ValueError('微信正在频繁更新数据库，请稍等同步完成，再重新导出')


def decrypt_database(src, keys, folder, stop=None):
    from sqlcipher3 import dbapi2
    src = Path(src)
    tag = hashlib.sha256(str(src).encode()).hexdigest()
    encrypted, plain = Path(folder) / (tag + '.enc'), Path(folder) / (tag + '.db')
    copy_database(src, encrypted, stop)
    with encrypted.open('rb') as stream:
        salt = stream.read(16).hex()
    key = keys.get(salt, '')
    if not re.fullmatch('[0-9a-fA-F]{64}', key):
        raise ValueError('部分微信数据库缺少有效密钥。请打开目标聊天，再点“连接并检查”；不会跳过该分片生成不完整档案')
    try:
        # This opens only our private copy. SQLCipher can replay its copied WAL.
        with closing(dbapi2.connect(str(encrypted))) as db:
            db.execute('PRAGMA key = "x\'' + key + salt + '\'"')
            db.execute('PRAGMA cipher_compatibility = 4')
            db.execute('SELECT count(*) FROM sqlite_master').fetchone()
            db.execute("ATTACH DATABASE ? AS plaintext KEY ''", (str(plain),))
            db.execute("SELECT sqlcipher_export('plaintext')").fetchone()
            db.execute('DETACH DATABASE plaintext')
        plain.chmod(0o600)
        return plain
    except dbapi2.Error:
        plain.unlink(missing_ok=True)
        raise ValueError('微信数据库校验失败，可能密钥已过期或版本不兼容。请重新连接；不会将读取失败当作导出成功') from None


def read_only(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db


def validate_keys(layout, keys, stop=None):
    with tempfile.TemporaryDirectory(prefix='chatarchive-check-') as tmp:
        for src in [layout.contact_db, *layout.message_dbs]:
            check_stop(stop)
            decrypt_database(src, keys, tmp, stop)


def decode_content(value):
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    data = bytes(value)
    if data.startswith(b'\x28\xb5\x2f\xfd'):
        import zstandard
        try:
            with zstandard.ZstdDecompressor().stream_reader(data) as stream:
                data = stream.read(32 * 1024 * 1024 + 1)
        except zstandard.ZstdError:
            raise ValueError('微信压缩正文损坏，已停止导出，避免保存乱码') from None
        if len(data) > 32 * 1024 * 1024:
            raise ValueError('单条微信消息过大，请缩小导出范围')
    return data.decode('utf-8', errors='replace')


@dataclass
class Record:
    message: Message
    shard: str
    raw: dict


def read_records(plain, shard, peer, filters, stop=None):
    table = 'Msg_' + hashlib.md5(peer.encode()).hexdigest()
    with closing(read_only(plain)) as db:
        if not db.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?', (table,)).fetchone():
            return
        columns = {r[1] for r in db.execute(f'PRAGMA table_info([{table}])')}
        required = {'local_id', 'local_type', 'create_time', 'real_sender_id', 'message_content'}
        if not required <= columns:
            raise ValueError('当前微信消息结构不兼容，已停止导出')
        names = {r[0]: r[1] for r in db.execute('SELECT rowid,user_name FROM Name2Id')}
        query = f'SELECT * FROM [{table}] WHERE create_time>=? AND create_time<=? ORDER BY create_time,local_id'
        for row in db.execute(query, (filters.get('startTime', 0), filters.get('endTime', int(time.time())))):
            check_stop(stop)
            raw = dict(row)
            content = decode_content(raw['message_content'])
            sender = names.get(raw['real_sender_id'], '')
            if peer.endswith('@chatroom') and (not sender or sender == peer):
                sender = message_parser.split_group_prefix(content)[0] or ''
            msg = Message(int(raw['local_id']), int(raw['create_time']), int(raw['local_type']),
                          content, server_id=str(raw.get('server_id') or ''), sender_username=sender)
            message_parser.parse(msg, is_group=peer.endswith('@chatroom'))
            yield Record(msg, shard, raw)


class Media:
    def __init__(self, layout, keys, tmp, peer, stop=None):
        self.layout, self.keys, self.tmp, self.peer, self.stop = layout, keys, tmp, peer, stop
        self.connections = {}
        self.image_key, self.xor = image_dat.derive_image_key(layout)
        self.root = Path(layout.media_root).resolve()

    def db(self, relative):
        if relative not in self.connections:
            src = Path(self.layout.account_dir) / 'db_storage' / relative
            try:
                self.connections[relative] = read_only(decrypt_database(src, self.keys, self.tmp, self.stop)) if src.is_file() else None
            except (ValueError, sqlite3.Error):
                self.connections[relative] = None
        return self.connections[relative]

    def close(self):
        for db in self.connections.values():
            if db is not None:
                db.close()

    def hashes(self, record):
        """Resource IDs are scoped to chat, local ID and type, never just local ID."""
        msg = record.message
        found = set()
        db = self.db('message/message_resource.db')
        if db is not None:
            try:
                columns = {r[1] for r in db.execute('PRAGMA table_info(MessageResourceInfo)')}
                if record.raw.get('_ambiguous_local') and not (
                    'create_time' in columns or ('message_svr_id' in columns and msg.server_id not in ('', '0'))
                ):
                    columns = set()  # XML hash remains usable below.
                for name_table in ('ChatName2Id', 'Name2Id'):
                    if not db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (name_table,)).fetchone():
                        continue
                    chat = db.execute(f'SELECT rowid FROM {name_table} WHERE user_name=?', (self.peer,)).fetchone()
                    if not chat or not {'chat_id', 'message_local_id', 'packed_info'} <= columns:
                        continue
                    query = 'SELECT packed_info FROM MessageResourceInfo WHERE chat_id=? AND message_local_id=?'
                    args = [chat[0], msg.local_id]
                    if 'message_local_type' in columns:
                        query += ' AND (message_local_type & 4294967295)=?'
                        args.append(msg.msg_type & 0xffffffff)
                    if 'create_time' in columns:
                        query += ' AND create_time=?'
                        args.append(msg.timestamp)
                    if 'message_svr_id' in columns and msg.server_id not in ('', '0'):
                        query += ' AND message_svr_id=?'
                        args.append(int(msg.server_id))
                    for row in db.execute(query, args):
                        blob = row[0].encode() if isinstance(row[0], str) else bytes(row[0] or b'')
                        found.update(x.decode().lower() for x in re.findall(rb'(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])', blob))
                    break
            except (sqlite3.Error, ValueError):
                pass
        # Exact message XML hash is an additional candidate, not a timestamp guess.
        md5 = msg.extra.get('md5', '').lower()
        if re.fullmatch('[0-9a-f]{32}', md5):
            found.add(md5)
        return found

    def valid_file(self, path, limit=MAX_MEDIA):
        path = Path(path)
        return path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(self.root) and 0 < path.stat().st_size <= limit

    def image(self, record):
        chat = hashlib.md5(self.peer.encode()).hexdigest()
        for suffix in ('.dat', '_h.dat', '_t.dat'):
            candidates = {p for h in self.hashes(record) for p in (self.root / 'attach' / chat).glob('*/Img/' + h + suffix)}
            if len(candidates) != 1:
                continue
            path = candidates.pop()
            if not self.valid_file(path, MAX_IMAGE):
                continue
            result = image_dat.decode_to_displayable(path.read_bytes(), self.image_key, self.xor)
            if result:
                data, ext = result
                # Verify the entire image, not merely its magic/header.
                from PIL import Image
                try:
                    with Image.open(io.BytesIO(data)) as image:
                        image.verify()
                except (OSError, ValueError):
                    continue
                return data, '.' + ext, 'thumbnail' if suffix == '_t.dat' else 'original'
        return None

    def video(self, record):
        paths = {p for h in self.hashes(record) for p in (self.root / 'video').glob('*/' + h + '.mp4') if self.valid_file(p)}
        if len(paths) != 1:
            return None
        path = paths.pop()
        with path.open('rb') as stream:
            header = stream.read(32)
        return path if b'ftyp' in header else None

    def audio(self, record):
        msg = record.message
        if not msg.server_id or msg.server_id == '0':
            return None  # Do not guess across shards with repeated local IDs.
        results = set()
        for source in Path(self.layout.account_dir, 'db_storage/message').glob('media_*.db'):
            db = self.db('message/' + source.name)
            if db is None:
                continue
            try:
                for row in db.execute('SELECT voice_data FROM VoiceInfo WHERE svr_id=?', (int(msg.server_id),)):
                    if row[0]:
                        results.add(bytes(row[0]))
            except (sqlite3.Error, ValueError):
                pass
        if len(results) != 1:
            return None
        silk = results.pop()
        try:
            import pysilk as decoder
            pcm = io.BytesIO()
            decoder.decode(io.BytesIO(silk[1:] if silk[:1] == b'\x02' else silk), pcm, 24000)
            output = io.BytesIO()
            with wave.open(output, 'wb') as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(24000)
                stream.writeframes(pcm.getvalue())
            return output.getvalue(), '.wav', 'original'
        except Exception:
            return (silk, '.silk', 'original') if b'#!SILK_V3' in silk[:12] else None


def export_wechat_mac(keyword, dest, db_dir='', log=print, stop=None, filters=None):
    layout, keys = load_connection(db_dir)
    dest = Path(dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='chatarchive-wechat-') as tmp:
        log('正在验证并复制本机微信数据库（包括尚未合并的最新消息）…')
        mapping = {}
        for src in [layout.contact_db, *layout.message_dbs]:
            check_stop(stop)
            mapping[src] = decrypt_database(src, keys, tmp, stop)
        with closing(read_only(mapping[layout.contact_db])) as db:
            people = [dict(r) for r in db.execute('SELECT username,nick_name,remark FROM contact')]
        exact = [p for p in people if p['username'] == keyword.strip()]
        matches = exact or [p for p in people if keyword.strip() in (p['nick_name'], p['remark'])]
        if len(matches) != 1:
            raise ValueError('未唯一匹配联系人，请填写准确备注、昵称或群名；同名时填写完整 wxid')
        peer = matches[0]['username']
        names = {p['username']: p['remark'] or p['nick_name'] or p['username'] for p in people}
        me = re.sub(r'_[0-9a-fA-F]{4}$', '', layout.account_id)
        # Distinct shards may repeat local_id; retain shard identity throughout.
        records = []
        for src in layout.message_dbs:
            for record in read_records(mapping[src], Path(src).name, peer, filters or {}, stop):
                records.append(record)
                if len(records) > 1_000_000:
                    raise ValueError('会话过大，请缩小日期范围')
        if not records:
            raise ValueError('所选日期范围没有本机微信消息；手机上的历史需要先迁移到电脑')
        records.sort(key=lambda r: (r.message.timestamp, r.shard, r.message.local_id))
        source = dest / 'source'
        source.mkdir(exist_ok=True)
        media = Media(layout, keys, tmp, peer, stop)
        messages = []
        # An ambiguous repeated local ID without timestamp/server fields must
        # not borrow another shard's image/video resource.
        from collections import Counter
        local_counts = Counter((r.message.local_id, r.message.msg_type & 0xffffffff) for r in records)
        try:
            for i, record in enumerate(records):
                check_stop(stop)
                msg = record.message
                record.raw['_ambiguous_local'] = local_counts[(msg.local_id, msg.msg_type & 0xffffffff)] > 1
                sender = msg.sender_username or None
                resolved = bool(sender and (sender != peer or not peer.endswith('@chatroom')))
                item = {'source_db': record.shard, 'local_id': msg.local_id, 'server_id': msg.server_id,
                        'timestamp': msg.timestamp, 'type_code': msg.msg_type & 0xffffffff,
                        'sender_username': sender, 'sender': names.get(sender, sender or '未知发送者'),
                        'sender_status': 'resolved' if resolved else 'unresolved',
                        'is_self': sender == me if resolved else None, 'content': msg.display_text}
                kind = {'voice': 'audio'}.get(msg.kind, msg.kind)
                if kind in ('image', 'video', 'audio', 'sticker', 'file'):
                    attachment = {'kind': kind, 'available': False, 'path': None,
                                  'reason': '本机原文件未下载、格式暂不支持或未能唯一关联；已保留消息位置'}
                    item['media'] = attachment
                    value = None
                    try:
                        if kind in ('image', 'video'):
                            value = getattr(media, kind)(record)
                        elif kind == 'audio':
                            value = media.audio(record)
                        if value:
                            if isinstance(value, Path):
                                with value.open('rb') as stream:
                                    hasher = hashlib.sha256()
                                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                                        hasher.update(chunk)
                                    digest = hasher.hexdigest()
                                out = source / 'media' / (digest + value.suffix.lower())
                                out.parent.mkdir(exist_ok=True)
                                shutil.copyfile(value, out)
                                quality = 'original'
                            else:
                                data, ext, quality = value
                                out = source / 'media' / (hashlib.sha256(data).hexdigest() + ext)
                                out.parent.mkdir(exist_ok=True)
                                out.write_bytes(data)
                            attachment.update(available=True, path=out.relative_to(source).as_posix(), reason=None, quality=quality)
                    except (OSError, ValueError):
                        attachment['reason'] = '媒体读取或解码失败，请先在微信中打开该图片或视频，下载完成后重试'
                messages.append(item)
                if i % 100 == 0:
                    log(f'读取微信文字与媒体 {i + 1}/{len(records)}')
        finally:
            media.close()
        output = source / 'chat_full_parsed.json'
        write_json(output, {'exporter_version': 'ChatArchiveTool/wechat-exporter-mac-231884e',
                           'chat_name': names[peer], 'chat_type': 'group' if peer.endswith('@chatroom') else 'private',
                           'message_count': len(messages), 'messages': messages,
                           'historyCompleteness': 'local_database_only'})
        log(f'已读取 {len(messages)} 条微信消息；整合时会显示未能保存的媒体数量')
        return output
