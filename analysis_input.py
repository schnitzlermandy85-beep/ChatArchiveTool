"""Read chatarchive/1 and QQChatExporter records without changing their source.

The public iterator emits an explicit allowlist of analysis fields.  Original
records, attachment locations, reply previews and resource metadata never leave
this module.  All archives are read in place; ZIP files are never extracted.
"""
from __future__ import annotations

import io
import json
import pathlib
import zipfile
from collections.abc import Iterator


MAX_ARCHIVE_BYTES = 150 * 1024 * 1024
MAX_MANIFEST_BYTES = 2_000_000
MAX_LINE_CHARS = 2_000_000


def _read_json(path: pathlib.Path, limit=MAX_ARCHIVE_BYTES):
    if path.stat().st_size > limit:
        raise ValueError("消息档案或导出清单过大，请缩小导出日期范围")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, ValueError):
        raise ValueError("所选文件不是有效的 UTF-8 JSON") from None


def _count(value, label):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(label + "必须是非负整数")
    return value


def _expected_count(manifest):
    stats = manifest.get("statistics")
    if isinstance(stats, dict) and "totalMessages" in stats:
        return _count(stats["totalMessages"], "导出清单消息数量")
    return _count(manifest.get("messageCount"), "导出清单消息数量")


def _meta(manifest, source, source_format):
    chat = manifest.get("chat") or manifest.get("chatInfo") or {}
    if not isinstance(chat, dict):
        raise ValueError("导出清单的会话信息格式无效")
    # Keep identity hints on the local input boundary; do not expose a complete
    # manifest containing contact lists, resource URLs or arbitrary payloads.
    chat = {key: chat[key] for key in ("type", "chatType", "selfUid", "selfUin") if key in chat}
    result = {"sourceFormat": source_format,
              "platform": str(manifest.get("platform") or "QQ"),
              "sourceName": "聊天统一档案" if source_format == "chatarchive/1" else "QQChatExporter",
              "sourcePath": str(source), "archivePath": str(source.parent),
              "expectedMessageCount": _expected_count(manifest),
              "chat": chat, "fileCount": 1}
    completeness = manifest.get("historyCompleteness")
    if completeness in ("unknown", "complete", "partial", "unverified"):
        result["historyCompleteness"] = completeness
    return result


def _relative_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("分块清单缺少文件路径")
    # Reject Windows drives, UNC paths, traversal and non-file entries before
    # resolution, including when a ZIP is opened on a different OS.
    value = value.replace("\\", "/")
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or ":" in value or "\x00" in value or ".." in path.parts:
        raise ValueError("分块清单包含非法文件路径")
    if not path.parts or value.endswith("/"):
        raise ValueError("分块清单包含非法文件路径")
    return path.as_posix()


def _chunks(manifest):
    chunked = manifest.get("chunked")
    if not isinstance(chunked, dict) or not isinstance(chunked.get("chunks"), list):
        raise ValueError("所选文件夹缺少有效的 QQChatExporter 分块清单")
    if str(chunked.get("format") or "jsonl").lower() != "jsonl":
        raise ValueError("当前关系分析支持 QQChatExporter 的 JSONL 分块格式")
    chunks = chunked["chunks"]
    if not chunks:
        raise ValueError("导出分块清单为空")
    if not all(isinstance(chunk, dict) for chunk in chunks):
        raise ValueError("导出分块清单格式无效")
    indexed = ["index" in chunk for chunk in chunks]
    if any(indexed) and not all(indexed):
        raise ValueError("导出分块清单的顺序索引不完整")
    if all(indexed):
        indices = [_count(chunk["index"], "分块顺序索引") for chunk in chunks]
        if any(index is None for index in indices):
            raise ValueError("导出分块清单的顺序索引无效")
        if len(set(indices)) != len(indices):
            raise ValueError("导出分块清单存在重复顺序索引")
        chunks = sorted(chunks, key=lambda chunk: chunk["index"])
    result, seen = [], set()
    for chunk in chunks:
        name = _relative_name(chunk.get("relativePath"))
        if pathlib.PurePosixPath(name).suffix.lower() != ".jsonl":
            raise ValueError("分块清单需要指向 JSONL 消息文件")
        if name.casefold() in seen:
            raise ValueError("导出分块清单包含重复文件")
        seen.add(name.casefold())
        result.append((name, _count(chunk.get("count"), "分块消息数量")))
    return result


def _sender(raw, chat):
    original = raw.get("sender")
    if original is None:
        original = {}
    if not isinstance(original, dict):
        raise ValueError("消息发送者字段格式无效")
    result = {key: original[key] for key in
              ("id", "uid", "userId", "wxid", "uin", "qq", "resolutionStatus")
              if key in original and isinstance(original[key], (str, int)) and not isinstance(original[key], bool)}
    name = original.get("name") or original.get("nickName") or original.get("nickname") or original.get("remark")
    if isinstance(name, str):
        result["name"] = name
    if isinstance(original.get("isSelf"), bool):
        result["isSelf"] = original["isSelf"]
    # Exported selfUid/selfUin are stronger identity hints than display names.
    if any(chat.get(hint) is not None and str(chat[hint]).strip() and
           original.get(field) is not None and str(chat[hint]) == str(original[field])
           for hint, field in (("selfUid", "uid"), ("selfUin", "uin"))):
        result["isSelf"] = True
    return result


def _string(value, label):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(label + "应为文字，不能直接分析未知结构化内容")
    return value


def _transcript(raw, content, elements):
    candidates = []
    if "voiceText" in raw:
        candidates.append(_string(raw.get("voiceText"), "语音转写"))
    prior = raw.get("voiceTranscription")
    if isinstance(prior, dict):
        # A failed or pending transcription must not become a quoted utterance.
        status = str(prior.get("status") or "").strip().lower()
        if status not in ("失败", "未转写", "处理中", "缺失音频", "failed", "error", "pending"):
            candidates.append(_string(prior.get("text"), "语音转写"))
    elif isinstance(prior, str):
        candidates.append(prior)
    elif prior is not None:
        raise ValueError("导出的语音转写格式无效")
    if isinstance(content, dict) and "voiceTranscript" in content:
        candidates.append(_string(content.get("voiceTranscript"), "语音转写"))
    for element in elements:
        if element.get("type") not in ("audio", "voice"):
            continue
        data = element.get("data") or {}
        for key in ("voiceTranscript", "transcript"):
            if key in data:
                value = data[key]
                if isinstance(value, dict):
                    value = value.get("text")
                candidates.append(_string(value, "语音转写"))
    unique = []
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and candidate not in unique:
            unique.append(candidate)
    return "\n".join(unique)


def normalize_analysis_message(raw, chat=None):
    """Normalize one record without treating quoted or media labels as speech."""
    if not isinstance(raw, dict) or raw.get("id") is None:
        raise ValueError("消息记录缺少消息 ID，请选择结构化 JSON／JSONL 档案")
    if not isinstance(raw["id"], (str, int)) or isinstance(raw["id"], bool):
        raise ValueError("消息 ID 格式无效")
    content = raw.get("content")
    parts, elements = [], []
    if content is not None and not isinstance(content, (dict, str)):
        raise ValueError("未知的消息内容格式，请选择 QQChatExporter 的 JSON／JSONL 导出")
    if isinstance(content, dict) and "elements" in content:
        elements = content["elements"]
        if not isinstance(elements, list):
            raise ValueError("消息 content.elements 必须是列表")
        for element in elements:
            if not isinstance(element, dict) or not isinstance(element.get("type"), str):
                raise ValueError("消息内容元素格式无效")
            if element.get("data") is not None and not isinstance(element.get("data"), dict):
                raise ValueError("消息内容元素 data 格式无效")
            kind = element["type"]
            if kind == "image" and (element.get("data") or {}).get("subType") == "sticker":
                kind = "sticker"
            if kind in ("face", "emoji", "marketface", "market_face"):
                kind = "qqemoji"
            parts.append({"type": kind})
    elif isinstance(raw.get("parts"), list):
        parts = [{"type": part["type"] if isinstance(part.get("type"), str) and part["type"] else "other"}
                 for part in raw["parts"] if isinstance(part, dict)]

    normalized = any(key in raw for key in ("analysisText", "text", "voiceText"))
    if normalized:
        text = _string(raw.get("text"), "消息正文")
        voice = _transcript(raw, content, elements)
        analysis = raw.get("analysisText")
        analysis = _string(analysis, "分析正文") if analysis is not None else "\n".join(value for value in (text, voice) if value).strip()
    else:
        utterances = []
        for element in elements:
            if element["type"] == "text":
                data = element.get("data") or {}
                utterances.append(_string(data.get("text", data.get("content")), "消息正文"))
        text = "".join(utterances)
        # Older QCE JSON may omit elements for a known plain-text message.
        # Existing elements (even []) are authoritative: content.text may be a
        # synthetic '[图片]' label, a quoted message or a resource description.
        if isinstance(content, dict) and "elements" not in content:
            if content and "text" not in content:
                raise ValueError("未知的结构化消息内容，请选择含 content.elements 的导出")
            if raw.get("type") == "text":
                text = _string(content.get("text"), "消息正文")
                if text:
                    parts.append({"type": "text"})
        elif isinstance(content, str):
            if raw.get("type") != "text":
                raise ValueError("无法判断文字内容来源，请使用 QQChatExporter 的结构化导出")
            text = content
            parts.append({"type": "text"})
        elif content is None:
            raise ValueError("消息缺少统一分析正文或 QQChatExporter 内容字段")
        voice = _transcript(raw, content, elements)
        analysis = "\n".join(value for value in (text, voice) if value).strip()
    return {"id": str(raw["id"]), "time": raw.get("time"),
            "timestamp": raw.get("timestamp"), "sender": _sender(raw, chat or {}),
            "system": raw.get("system") is True or raw.get("type") == "system",
            "analysisText": analysis, "text": text, "voiceText": voice, "parts": parts}


def _jsonl(stream):
    for number, line in enumerate(stream, 1):
        if not line.strip():
            continue
        if len(line) > MAX_LINE_CHARS:
            raise ValueError(f"消息文件第 {number} 行过长，请检查档案格式")
        try:
            yield json.loads(line)
        except (UnicodeError, ValueError):
            raise ValueError(f"消息文件第 {number} 行不是有效 JSON") from None


def _validated(records, meta):
    count, seen = 0, set()
    for raw in records:
        message = normalize_analysis_message(raw, meta.get("chat"))
        if not message["id"] or message["id"] in seen:
            raise ValueError("档案存在空消息 ID 或重复消息 ID，无法可靠关联证据")
        seen.add(message["id"])
        count += 1
        if count > 500_000:
            raise ValueError("初级版本支持最多 50 万条消息，请缩小导出日期范围")
        yield message
    expected = meta.get("expectedMessageCount")
    if expected is not None and count != expected:
        raise ValueError("消息数量与导出清单不一致，请重新选择完整导出")


def _folder_records(paths):
    for path, expected in paths:
        count = 0
        with path.open("r", encoding="utf-8-sig") as stream:
            for raw in _jsonl(stream):
                count += 1
                yield raw
        if expected is not None and count != expected:
            raise ValueError("分块消息数量与导出清单不一致，请重新选择完整导出")


def _zip_records(source, chunks):
    with zipfile.ZipFile(source) as archive:
        for name, expected in chunks:
            count = 0
            with archive.open(name) as binary:
                with io.TextIOWrapper(binary, encoding="utf-8-sig") as stream:
                    for raw in _jsonl(stream):
                        count += 1
                        yield raw
            if expected is not None and count != expected:
                raise ValueError("压缩包分块消息数量与导出清单不一致")


def _zip_input(source):
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(set(names)) != len(names):
                raise ValueError("压缩包存在重复文件路径")
            # Reject suspicious members even though extraction is never used.
            for entry in entries:
                _relative_name(entry.filename.rstrip("/"))
            candidates = []
            for entry in entries:
                if not entry.filename.endswith("manifest.json") or entry.is_dir():
                    continue
                if entry.file_size > MAX_MANIFEST_BYTES:
                    raise ValueError("压缩包导出清单过大")
                try:
                    manifest = json.loads(archive.read(entry).decode("utf-8-sig"))
                except (UnicodeError, ValueError):
                    raise ValueError("压缩包导出清单不是有效 JSON") from None
                if isinstance(manifest, dict) and ("chunked" in manifest or manifest.get("format") == "chatarchive/1"):
                    candidates.append((entry.filename, manifest))
            if len(candidates) != 1:
                raise ValueError("压缩包应包含且仅包含一个聊天档案清单，请选择具体会话")
            manifest_name, manifest = candidates[0]
            prefix = manifest_name[:-len("manifest.json")]
            source_format = "chatarchive/1" if manifest.get("format") == "chatarchive/1" else "qce-zip"
            chunks = [(prefix + name, count) for name, count in _chunks(manifest)] if "chunked" in manifest else [(prefix + "messages.jsonl", None)]
            size = 0
            for name, _ in chunks:
                if name not in names or archive.getinfo(name).is_dir():
                    raise ValueError("压缩包缺少清单指定的消息分块")
                size += archive.getinfo(name).file_size
            if size > MAX_ARCHIVE_BYTES:
                raise ValueError("初级版本支持不超过 150 MB 的消息档案")
    except zipfile.BadZipFile:
        raise ValueError("所选文件不是完整的 ZIP 压缩包") from None
    meta = _meta(manifest, source, source_format)
    meta["fileCount"] = len(chunks)
    return source, _validated(_zip_records(source, chunks), meta), meta


def iter_analysis_input(path: str | pathlib.Path) -> tuple[pathlib.Path, Iterator[dict], dict]:
    """Return canonical source file, normalized iterator and local source metadata.

    Manifest/chunk paths are checked immediately. Record schemas, duplicates and
    message counts are verified as the single-use iterator is consumed.
    """
    if not str(path or "").strip():
        raise ValueError("请选择统一档案或 QQChatExporter 的 JSON／JSONL／分块文件夹")
    selected = pathlib.Path(path).expanduser().resolve()
    if not selected.exists():
        raise ValueError("所选聊天档案不存在，请重新选择导出位置")
    source = selected
    if selected.is_dir():
        if (selected / "messages.jsonl").is_file():
            source = selected / "messages.jsonl"
        elif (selected / "manifest.json").is_file():
            source = selected / "manifest.json"
        else:
            raise ValueError("所选文件夹没有 messages.jsonl 或 QQChatExporter manifest.json")
    if not source.is_file():
        raise ValueError("请选择有效的聊天档案文件")
    if source.suffix.lower() == ".zip":
        return _zip_input(source)
    if source.suffix.lower() == ".jsonl":
        if source.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("初级版本支持不超过 150 MB 的消息档案")
        manifest = {}
        adjacent = source.parent / "manifest.json"
        if adjacent.is_file() and source.name.lower() == "messages.jsonl":
            manifest = _read_json(adjacent, MAX_MANIFEST_BYTES)
            if not isinstance(manifest, dict):
                raise ValueError("导出清单必须是 JSON 对象")
        source_format = "chatarchive/1" if manifest.get("format") == "chatarchive/1" or source.name.lower() == "messages.jsonl" else "qce-jsonl"
        meta = _meta(manifest, source, source_format)
        return source, _validated(_folder_records([(source, None)]), meta), meta
    if source.suffix.lower() != ".json":
        raise ValueError("请选择 JSON、JSONL、ZIP 或含 manifest.json 的聊天导出文件夹")
    document = _read_json(source, MAX_MANIFEST_BYTES if source.name.lower() == "manifest.json" else MAX_ARCHIVE_BYTES)
    if not isinstance(document, dict):
        raise ValueError("所选 JSON 必须是包含 messages 或 chunked 的导出对象")
    if "chunked" in document:
        chunks = _chunks(document)
        paths = []
        size = 0
        for name, count in chunks:
            chunk = (source.parent / pathlib.PurePosixPath(name)).resolve()
            if not chunk.is_relative_to(source.parent.resolve()):
                raise ValueError("导出清单包含越界文件路径")
            if not chunk.is_file():
                raise ValueError("导出文件夹缺少清单指定的消息分块，请选择完整导出")
            size += chunk.stat().st_size
            paths.append((chunk, count))
        if size > MAX_ARCHIVE_BYTES:
            raise ValueError("初级版本支持不超过 150 MB 的消息档案")
        meta = _meta(document, source, "qce-chunked-jsonl")
        meta["fileCount"] = len(paths)
        return source, _validated(_folder_records(paths), meta), meta
    messages = document.get("messages")
    if not isinstance(messages, list):
        raise ValueError("所选 JSON 没有 messages 消息列表，请选择 QQChatExporter 结构化导出")
    meta = _meta(document, source, "qce-json")
    return source, _validated(iter(messages), meta), meta
