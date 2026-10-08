import json
import pathlib
import shutil
import unittest
import uuid
import zipfile

from analysis_input import iter_analysis_input, normalize_analysis_message


class InputAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = pathlib.Path(__file__).resolve().parents[1] / ".test-work"
        self.temp_root.mkdir(exist_ok=True)
        self.folder = self.temp_root / uuid.uuid4().hex
        self.folder.mkdir(mode=0o777)

    def tearDown(self):
        target = self.folder.resolve()
        target.relative_to(self.temp_root.resolve())
        shutil.rmtree(target)

    def raw(self, mid="one", elements=None, **extra):
        return {"id": mid, "timestamp": 1790820000000,
                "time": "2026-10-01T10:00:00+08:00", "type": "text",
                "sender": {"uid": "sender-a", "uin": "account-a", "name": "合成人物甲",
                           "nickname": "昵称甲", "avatar": "PRIVATE_AVATAR", "extra": "PRIVATE_EXTRA"},
                "content": {"text": "PRIVATE_SYNTHETIC_LABEL", "html": "PRIVATE_HTML",
                            "elements": elements if elements is not None else [{"type": "text", "data": {"text": "明天一起吃饭？"}}],
                            "resources": [{"url": "PRIVATE_RESOURCE"}]},
                "system": False, "original": {"secret": "PRIVATE_ORIGINAL"}, **extra}

    def jsonl(self, relative, messages):
        path = self.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\ufeff" + "\n".join(json.dumps(message, ensure_ascii=False) for message in messages) + "\n", encoding="utf-8")
        return path

    def manifest(self, chunks, total, **extra):
        document = {"chatInfo": {"type": "private", "selfUid": "sender-a", "selfUin": "account-a", "name": "PRIVATE_CONTACT"},
                    "statistics": {"totalMessages": total},
                    "chunked": {"format": "jsonl", "chunks": chunks}, **extra}
        path = self.folder / "manifest.json"
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return path

    def load(self, path):
        source, iterator, meta = iter_analysis_input(path)
        return source, list(iterator), meta

    def test_raw_text_and_completed_voice_only_no_resource_or_reply_leak(self):
        message = self.raw(elements=[
            {"type": "text", "data": {"text": "你好，"}},
            {"type": "text", "data": {"text": "辛苦了。"}},
            {"type": "reply", "data": {"content": "PRIVATE_QUOTED_TEXT", "senderName": "PRIVATE_QUOTED_NAME"}},
            {"type": "image", "data": {"url": "PRIVATE_URL", "filename": "PRIVATE_FILENAME"}},
            {"type": "audio", "data": {"filename": "PRIVATE_AUDIO"}},
        ], voiceTranscription={"text": "我需要你帮个忙。", "status": "完成", "machineGenerated": True})
        result = normalize_analysis_message(message, {"selfUid": "sender-a"})
        self.assertEqual(result["text"], "你好，辛苦了。")
        self.assertEqual(result["voiceText"], "我需要你帮个忙。")
        self.assertEqual(result["analysisText"], "你好，辛苦了。\n我需要你帮个忙。")
        self.assertTrue(result["sender"]["isSelf"])
        self.assertEqual(result["timestamp"], 1790820000000)
        self.assertEqual(set(result), {"id", "time", "timestamp", "sender", "system", "analysisText", "text", "voiceText", "parts"})
        self.assertNotIn("PRIVATE_", json.dumps(result))
        self.assertTrue(all(set(part) == {"type"} for part in result["parts"]))

    def test_unified_archive_and_manifest_count_are_preserved(self):
        message = {"id": "one", "sender": {"id": "alpha", "name": "甲", "resolutionStatus": "resolved"},
                   "text": "原始正文", "voiceText": "转写正文", "analysisText": "已合并正文",
                   "time": "2026-10-01T10:00:00+08:00", "parts": [{"type": "image", "path": "PRIVATE_PATH"}],
                   "original": {"secret": "PRIVATE_ORIGINAL"}}
        self.jsonl("messages.jsonl", [message])
        (self.folder / "manifest.json").write_text(json.dumps({"format": "chatarchive/1", "platform": "WeChat", "messageCount": 1,
                                                              "chat": {"type": "group"}, "historyCompleteness": "partial"}), encoding="utf-8")
        source, records, meta = self.load(self.folder)
        self.assertEqual(source, self.folder / "messages.jsonl")
        self.assertEqual(records[0]["analysisText"], "已合并正文")
        self.assertEqual(meta["platform"], "WeChat")
        self.assertEqual(meta["sourceFormat"], "chatarchive/1")
        self.assertEqual(meta["historyCompleteness"], "partial")
        self.assertEqual(meta["chat"]["type"], "group")
        self.assertNotIn("PRIVATE_", json.dumps(records))

    def test_chunks_read_index_order_and_source_files_unchanged(self):
        paths = [self.jsonl("chunks/second.jsonl", [self.raw("second")]),
                 self.jsonl("chunks/first.jsonl", [self.raw("first")])]
        manifest = self.manifest([
            {"index": 2, "relativePath": "chunks/second.jsonl", "count": 1},
            {"index": 1, "relativePath": "chunks/first.jsonl", "count": 1},
        ], 2)
        before = {path: path.read_bytes() for path in [manifest, *paths]}
        source, records, meta = self.load(self.folder)
        self.assertEqual(source, manifest)
        self.assertEqual([message["id"] for message in records], ["first", "second"])
        self.assertEqual(meta["fileCount"], 2)
        self.assertEqual(meta["sourceFormat"], "qce-chunked-jsonl")
        self.assertTrue(all(record["sender"].get("isSelf") for record in records))
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertEqual(len(list(self.folder.rglob("*"))), 4)

    def test_chunk_list_order_without_indices(self):
        self.jsonl("chunks/z.jsonl", [self.raw("first")])
        self.jsonl("chunks/a.jsonl", [self.raw("second")])
        self.manifest([{"relativePath": "chunks/z.jsonl", "count": 1}, {"relativePath": "chunks/a.jsonl", "count": 1}], 2)
        _, records, _ = self.load(self.folder)
        self.assertEqual([record["id"] for record in records], ["first", "second"])

    def test_single_raw_json_and_jsonl(self):
        jsonl = self.jsonl("raw.jsonl", [self.raw()])
        _, records, meta = self.load(jsonl)
        self.assertEqual(meta["sourceFormat"], "qce-jsonl")
        self.assertEqual(records[0]["analysisText"], "明天一起吃饭？")
        path = self.folder / "raw.json"
        path.write_text(json.dumps({"messages": [self.raw()], "statistics": {"totalMessages": 1},
                                   "chatInfo": {"type": "group", "selfUid": "sender-a"}}), encoding="utf-8")
        _, records, meta = self.load(path)
        self.assertEqual(meta["sourceFormat"], "qce-json")
        self.assertEqual(meta["chat"]["type"], "group")
        self.assertTrue(records[0]["sender"]["isSelf"])

    def test_media_face_reply_and_card_labels_are_not_plain_text(self):
        for kind in ("image", "audio", "video", "file", "face", "market_face", "reply", "json", "forward", "av_record"):
            with self.subTest(kind=kind):
                result = normalize_analysis_message(self.raw(elements=[{"type": kind, "data": {"text": "PRIVATE_LABEL", "content": "PRIVATE_PREVIEW"}}]))
                self.assertEqual(result["analysisText"], "")
                self.assertEqual(len(result["parts"]), 1)
        result = normalize_analysis_message(self.raw(elements=[{"type": "image", "data": {"subType": "sticker"}}]))
        self.assertEqual(result["parts"], [{"type": "sticker"}])

    def test_transcript_sources_deduplicated_and_failed_status_ignored(self):
        message = self.raw(elements=[{"type": "audio", "data": {"transcript": "实际转写"}}],
                           voiceTranscription={"text": "实际转写", "status": "完成"})
        message["content"]["voiceTranscript"] = "实际转写"
        self.assertEqual(normalize_analysis_message(message)["voiceText"], "实际转写")
        message = self.raw(elements=[{"type": "audio", "data": {}}], voiceTranscription={"text": "错误文字", "status": "失败"})
        self.assertEqual(normalize_analysis_message(message)["voiceText"], "")

    def test_system_messages_remain_system(self):
        message = self.raw(type="system", system=False)
        self.assertTrue(normalize_analysis_message(message)["system"])

    def test_manifest_traversal_and_absolute_paths_rejected(self):
        for name in ("../outside.jsonl", "chunks/../../outside.jsonl", "C:/outside.jsonl", "/outside.jsonl", "\\\\server\\outside.jsonl"):
            with self.subTest(name=name):
                self.manifest([{"relativePath": name, "count": 1}], 1)
                with self.assertRaisesRegex(ValueError, "非法文件路径"):
                    iter_analysis_input(self.folder)

    def test_missing_chunk_rejected_before_iterator(self):
        self.manifest([{"relativePath": "chunks/missing.jsonl", "count": 1}], 1)
        with self.assertRaisesRegex(ValueError, "缺少"):
            iter_analysis_input(self.folder)

    def test_duplicate_chunks_and_duplicate_message_ids_rejected(self):
        self.jsonl("chunks/one.jsonl", [self.raw()])
        self.manifest([{"relativePath": "chunks/one.jsonl"}, {"relativePath": "chunks/one.jsonl"}], 2)
        with self.assertRaisesRegex(ValueError, "重复文件"):
            iter_analysis_input(self.folder)
        path = self.jsonl("raw.jsonl", [self.raw(), self.raw(system=True)])
        with self.assertRaisesRegex(ValueError, "重复消息 ID"):
            self.load(path)

    def test_chunk_count_and_total_count_mismatch(self):
        self.jsonl("chunks/one.jsonl", [self.raw()])
        self.manifest([{"relativePath": "chunks/one.jsonl", "count": 2}], 2)
        with self.assertRaisesRegex(ValueError, "分块消息数量"):
            self.load(self.folder)
        self.manifest([{"relativePath": "chunks/one.jsonl", "count": 1}], 2)
        with self.assertRaisesRegex(ValueError, "消息数量"):
            self.load(self.folder)

    def test_unknown_content_does_not_silently_become_empty_archive(self):
        for content in (123, {"unknownPayload": {"text": "忽略"}}, {"elements": "wrong"}):
            with self.subTest(content=type(content).__name__):
                with self.assertRaises(ValueError):
                    normalize_analysis_message(self.raw(content=content))
        with self.assertRaisesRegex(ValueError, "应为文字"):
            normalize_analysis_message(self.raw(elements=[{"type": "text", "data": {"text": {"x": "忽略"}}}]))

    def test_legacy_plain_text_accepted_without_elements_only(self):
        message = self.raw(content={"text": "老格式正文"})
        self.assertEqual(normalize_analysis_message(message)["analysisText"], "老格式正文")
        message = self.raw(content={"text": "合成标签", "elements": []})
        self.assertEqual(normalize_analysis_message(message)["analysisText"], "")

    def test_chunk_zip_reads_nested_archive_without_extraction(self):
        archive_path = self.folder / "input.zip"
        document = {"statistics": {"totalMessages": 1}, "chatInfo": {"type": "private"},
                    "chunked": {"format": "jsonl", "chunks": [{"index": 1, "relativePath": "chunks/one.jsonl", "count": 1}]}}
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("export/manifest.json", json.dumps(document))
            archive.writestr("export/chunks/one.jsonl", json.dumps(self.raw(), ensure_ascii=False))
        source, records, meta = self.load(archive_path)
        self.assertEqual(source, archive_path)
        self.assertEqual(records[0]["text"], "明天一起吃饭？")
        self.assertEqual(meta["sourceFormat"], "qce-zip")
        self.assertEqual(list(self.folder.iterdir()), [archive_path])

    def test_zip_traversal_missing_chunk_and_ambiguous_manifests_rejected(self):
        archive_path = self.folder / "input.zip"
        document = {"chunked": {"chunks": [{"relativePath": "chunks/one.jsonl"}]}}
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("../unsafe.txt", "no")
        with self.assertRaisesRegex(ValueError, "非法文件路径"):
            iter_analysis_input(archive_path)
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(document))
        with self.assertRaisesRegex(ValueError, "缺少"):
            iter_analysis_input(archive_path)
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("a/manifest.json", json.dumps(document))
            archive.writestr("b/manifest.json", json.dumps(document))
        with self.assertRaisesRegex(ValueError, "且仅包含一个"):
            iter_analysis_input(archive_path)

    def test_index_and_manifest_schema_errors_are_actionable(self):
        for chunks in ([{"index": 1, "relativePath": "a.jsonl"}, {"relativePath": "b.jsonl"}],
                       [{"index": 1, "relativePath": "a.jsonl"}, {"index": 1, "relativePath": "b.jsonl"}]):
            self.manifest(chunks, 2)
            with self.assertRaises(ValueError):
                iter_analysis_input(self.folder)
        path = self.folder / "invalid.json"
        path.write_text('{"messages": "wrong"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "messages"):
            iter_analysis_input(path)


if __name__ == "__main__":
    unittest.main()
