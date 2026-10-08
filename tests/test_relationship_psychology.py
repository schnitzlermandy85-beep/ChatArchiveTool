"""Psychology integration: transport rules, cautious labels and public output."""
import json
from pathlib import Path
import unittest
import uuid
from unittest import mock

import relationship as rel
from relationship_report import render_report, write_report


class PsychologyIntegrationTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / ".test-work"
        parent.mkdir(exist_ok=True)
        self.directory = parent / ("psychology-" + uuid.uuid4().hex)
        self.directory.mkdir()
        self.path = self.directory / "messages.jsonl"
        messages = [{"id": str(index), "time": f"2026-10-01T10:{index:02}:00+08:00",
                     "sender": {"uid": f"person{index % 2}", "name": f"person{index % 2}",
                                "isSelf": index % 2 == 1, "resolutionStatus": "resolved"},
                     "system": False, "analysisText": "明天一起吃饭？" if index % 2 else "好，明天见。",
                     "parts": [{"type": "text"}]} for index in range(1, 5)]
        self.path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in messages), encoding="utf-8")
        self.prepared = rel.prepare_analysis(self.path, "friend")

    def tearDown(self):
        self.directory.resolve().relative_to((Path(__file__).resolve().parents[1] / ".test-work").resolve())
        for name in ("messages.jsonl", "report.html", "report-data.json"):
            (self.directory / name).unlink(missing_ok=True)
        self.directory.rmdir()

    def result(self, prepared=None, support="tentative"):
        prepared = prepared or self.prepared
        sample = prepared["preview"]["sample"]
        return {"summary": "双方协商了见面安排。", "findings": [{
            "title": "共同安排", "observation": "一方提议吃饭，另一方作出回应。",
            "interpretation": "这可作为共同活动与协调的观察。",
            "alternatives": ["也可能只是一次临时安排，落实情况尚不明确。"],
            "evidenceIds": [sample[0]["id"], sample[1]["id"]],
            "dimensionId": "shared_activities", "theoryId": "social_exchange_theory", "supportLevel": support}],
            "portraits": [{"participantId": person["id"], "description": "在这段记录中参与了安排。",
                          "strengths": ["表达了具体安排。"], "communicationNeeds": ["可以询问合适的时间。"],
                          "evidenceIds": [next(item["id"] for item in sample if item["participantId"] == person["id"])]}
                         for person in prepared["preview"]["participants"]], "suggestions": ["进一步确认是否成行。"]}

    def test_four_lenses_in_all_planned_phases(self):
        primary_ids = {"family": "family_systems", "partner": "attachment_theory",
                       "friend": "social_exchange_theory", "best_friend": "social_penetration_theory"}
        for relation, primary_id in primary_ids.items():
            prepared = rel.prepare_analysis(self.path, relation, {"customPrompt": "重点看共同安排。"})
            preview = prepared["preview"]
            framework = preview["frameworkProfile"]
            self.assertEqual(framework["primaryTheory"]["id"], primary_id)
            self.assertEqual(len(framework["dimensionDefinitions"]), 8)
            prompts = [batch["systemPrompt"] for batch in preview["batches"]]
            prompts += [preview["synthesis"]["systemPrompt"], preview["synthesis"]["intermediateSystemPrompt"]]
            for prompt in prompts:
                self.assertIn(framework["primaryTheory"]["name"], prompt)
                self.assertIn("不诊断", prompt.replace("禁止诊断", "不诊断"))
                self.assertIn("可询问、可协商", prompt)
                self.assertIn("重点看共同安排。", prompt)
                for dimension in framework["dimensionDefinitions"]:
                    self.assertIn(dimension["name"], prompt)
            context = json.loads(preview["batches"][0]["payloadText"])["psychologyFramework"]
            self.assertEqual(context["primaryTheory"]["id"], primary_id)
            self.assertEqual({item["id"] for item in context["dimensions"]}, set(framework["priorityDimensions"]))
            self.assertTrue(context["references"])

    def test_actual_transport_equals_preview_with_framework(self):
        config = {"endpoint": "http://127.0.0.1:9999/v1", "model": "synthetic-model", "apiKey": ""}
        with mock.patch.object(rel, "_request_json", return_value=self.result()) as request:
            report = rel.analyze_prepared(self.prepared, config, log=lambda _: None)
        self.assertEqual(report["mode"], "ai")
        batch = self.prepared["preview"]["batches"][0]
        self.assertEqual(request.call_args.args[:2], (batch["systemPrompt"], batch["payloadText"]))
        self.assertEqual(report["frameworkProfile"]["primaryTheory"]["id"], "social_exchange_theory")
        self.assertEqual(report["findings"][0]["dimensionId"], "shared_activities")

    def test_unknown_or_other_lens_theory_is_rejected(self):
        for field, value in (("theoryId", "attachment_theory"), ("dimensionId", "trust_score"),
                             ("supportLevel", "certain"), ("theoryId", ["social_exchange_theory"])):
            result = self.result()
            result["findings"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "AI_INVALID_PSYCHOLOGY"):
                rel._validate_ai(result, self.prepared)

    def test_metadata_requires_complete_fields(self):
        for field in ("dimensionId", "theoryId", "supportLevel"):
            result = self.result()
            del result["findings"][0][field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "AI_INVALID_PSYCHOLOGY"):
                rel._validate_ai(result, self.prepared)

    def test_both_interpretation_levels_require_alternative(self):
        for level in ("tentative", "contextual"):
            result = self.result(support=level)
            result["findings"][0]["alternatives"] = []
            with self.subTest(level=level), self.assertRaisesRegex(ValueError, "AI_INVALID_PSYCHOLOGY"):
                rel._validate_ai(result, self.prepared)

    def test_contextual_requires_two_distinct_messages(self):
        result = self.result(support="contextual")
        ids = result["findings"][0]["evidenceIds"]
        result["findings"][0]["evidenceIds"] = [ids[0], ids[0]]
        with self.assertRaisesRegex(ValueError, "AI_INVALID_PSYCHOLOGY"):
            rel._validate_ai(result, self.prepared)
        result = self.result(support="contextual")
        self.assertEqual(rel._validate_ai(result, self.prepared)["findings"][0]["supportLevel"], "contextual")

    def test_synthesis_cannot_raise_tentative_interpretation(self):
        lower = rel._validate_ai(self.result(), self.prepared)
        upper = rel._validate_ai(self.result(support="contextual"), self.prepared, source_results=[lower])
        self.assertEqual(upper["findings"][0]["supportLevel"], "tentative")
        lower = rel._validate_ai(self.result(support="contextual"), self.prepared)
        self.assertEqual(rel._validate_ai(self.result(support="contextual"), self.prepared,
                                        source_results=[lower])["findings"][0]["supportLevel"], "contextual")

    def test_synthesis_cannot_attach_other_inherited_messages_to_theory(self):
        lower = rel._validate_ai(self.result(), self.prepared)
        upper = self.result()
        upper["findings"][0]["evidenceIds"] = [self.prepared["preview"]["sample"][-1]["id"]]
        with self.assertRaisesRegex(ValueError, "AI_INVALID_PSYCHOLOGY"):
            rel._validate_ai(upper, self.prepared, source_results=[lower])

    def test_common_labels_and_psychology_scores_fail(self):
        for text in ("对方是焦虑型依恋。", "对方表现出回避型依恋。", "P1就是安全型依恋。",
                     "判断为抑郁症。", "你们的亲密度为80分。", "信任程度：95。", "依恋强度80。",
                     "不能排除对方是回避型依恋。",
                     "不能判断P1是焦虑型依恋，但是P2是回避型依恋。"):
            result = self.result()
            result["summary"] = text
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "AI_UNSUPPORTED_DIAGNOSIS"):
                rel._validate_ai(result, self.prepared)

    def test_explicit_caution_is_not_a_diagnosis(self):
        for text in ("不能判断对方是焦虑型依恋。", "仅凭聊天不能诊断为抑郁症。",
                     "资料不足，不能判断为安全型依恋。", "想你不代表对方是安全型依恋。"):
            result = self.result()
            result["summary"] = text
            with self.subTest(text=text):
                self.assertEqual(rel._validate_ai(result, self.prepared)["summary"], text)

    def test_public_report_has_canonical_framework_and_no_raw_messages(self):
        report = rel.analyze_prepared(self.prepared, log=lambda _: None)
        report["frameworkProfile"]["primaryTheory"]["name"] = "FAKE_MODEL_THEORY"
        report["frameworkProfile"]["references"] = [{"title": "fake", "url": "javascript:alert(1)"}]
        html = render_report(report)
        self.assertIn("配置的 AI 观察框架以社会交换理论", html)
        self.assertNotIn("FAKE_MODEL_THEORY", html)
        self.assertNotIn("javascript:alert", html)
        write_report(report, self.directory)
        public = json.loads((self.directory / "report-data.json").read_text(encoding="utf-8"))
        self.assertNotIn("preview", public)
        self.assertNotIn("evidence", public)
        self.assertNotIn("limitations", public)
        self.assertNotIn("evidenceIds", json.dumps(public))
        self.assertNotIn("明天一起吃饭", json.dumps(public, ensure_ascii=False))
        self.assertEqual(public["frameworkProfile"]["primaryTheory"]["name"], "社会交换理论")
        for removed in ("原文证据", "局限与解释边界"):
            self.assertNotIn(removed, html)

    def test_ai_report_labels_interpretation_without_new_chart(self):
        config = {"endpoint": "http://127.0.0.1:9999", "model": "demo", "apiKey": ""}
        with mock.patch.object(rel, "_request_json", return_value=self.result()):
            report = rel.analyze_prepared(self.prepared, config, log=lambda _: None)
        html = render_report(report)
        self.assertIn("AI 文本解释以社会交换理论", html)
        self.assertIn("共同活动与协作 · 社会交换理论 · 暂时解释", html)
        self.assertEqual(html.count('id="figure-'), 3)
        self.assertNotIn("雷达", html)


if __name__ == "__main__":
    unittest.main()
