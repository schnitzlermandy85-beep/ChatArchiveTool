import copy
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relationship_report import render_report, write_report


@contextmanager
def report_test_directory():
    # Normal mkdir avoids TemporaryDirectory's restrictive ACL under the
    # Windows app sandbox. Only these two known files are ever removed.
    parent = Path(__file__).parent.resolve()
    directory = parent / ("report-test-" + uuid.uuid4().hex)
    assert directory.resolve().parent == parent
    directory.mkdir()
    try:
        yield directory
    finally:
        for filename in ("report.html", "report-data.json"):
            (directory / filename).unlink(missing_ok=True)
        directory.rmdir()


def sample_report():
    return {
        "schemaVersion": 1,
        "relationship": "friend",
        "relationshipLabel": "朋友",
        "mode": "ai",
        "generatedAt": "2026-10-03T17:00:00+08:00",
        "participants": [{"id": "P1", "name": "我", "isSelf": True, "count": 2}, {"id": "P2", "name": "对方", "isSelf": False, "count": 1}],
        "stats": {
            "messageCount": 3, "textMessageCount": 3, "activeDays": 2,
            "dateRange": {"start": "2025-12-31", "end": "2026-01-02"},
            "senderCounts": {"P1": 2, "P2": 1},
            "dailyCounts": [{"date": "2025-12-31", "count": 1}, {"date": "2026-01-02", "count": 2}],
            "monthlyCounts": [{"month": "2025-12", "count": 1}, {"month": "2026-01", "count": 2}],
            "hourCounts": [3] + [0] * 23, "weekdayCounts": [0, 0, 1, 0, 2, 0, 0],
            "typeCounts": {"text": 3},
            "sessions": {"count": 2, "initiations": {"P1": 2}, "thresholdMinutes": 30},
            "responseDelays": {"P2": {"count": 1, "medianSeconds": 40, "p90Seconds": 40}},
        },
        "summary": "短期互动回顾。",
        "findings": [{"title": "互相回应", "observation": "出现了直接回应。", "interpretation": "可以回顾支持表达。", "alternatives": ["记录范围较短。"], "evidenceIds": ["m1", "missing"]}],
        "portraits": [{"participantId": "P1", "description": "会直接表达需要。", "strengths": ["表达清晰"], "communicationNeeds": ["确认感受"], "evidenceIds": ["m1"]}],
        "suggestions": ["询问对方当时的感受。"],
        "evidence": [{"id": "m1", "time": "2025-12-31 00:00:00", "participantId": "P1", "text": "今天有点累。"}],
        "aiStatus": {"state": "succeeded", "model": "example-model", "error": ""},
        "coverage": {"mode": "full", "validMessageCount": 3, "validTextMessageCount": 3,
                     "sentMessageCount": 3, "omittedTextMessages": 0, "batchCount": 2,
                     "analyzedTextMessageCount": 3, "completedBatchCount": 2,
                     "mediaOnlyMessageCount": 0, "aiSucceeded": True, "status": "succeeded"},
        "limitations": ["聊天记录缺少线下互动。"],
    }


class RelationshipReportTests(unittest.TestCase):
    def test_supplemental_requirements_recorded_and_escaped(self):
        data = sample_report()
        data["analysisRequirements"] = '重点分析主动联系。<img src=x onerror="attack()">'
        with report_test_directory() as directory:
            path = Path(write_report(data, directory))
            html = path.read_text(encoding="utf-8")
            public = json.loads((directory / "report-data.json").read_text(encoding="utf-8"))
            self.assertIn('本次补充分析要求', html)
            self.assertIn('&lt;img', html)
            self.assertNotIn('<img src=x', html)
            self.assertEqual(public["analysisRequirements"], data["analysisRequirements"])

    def test_untrusted_text_cannot_create_html_or_script(self):
        data = sample_report()
        attack = '</script><img src=x onerror="alert(1)"><script>alert(2)</script>'
        data["evidence"][0]["text"] = attack
        data["participants"][0]["name"] = attack
        data["summary"] = attack
        data["findings"][0]["title"] = attack
        result = render_report(data)
        self.assertNotIn('<img src=x', result)
        self.assertNotIn('<script>alert(2)', result)
        self.assertIn('&lt;img src=x', result)
        self.assertEqual(result.count('<script>'), 1)
        self.assertEqual(result.count('</script>'), 1)

    def test_removed_sections_and_message_excerpts_are_not_exported(self):
        result = render_report(sample_report())
        self.assertNotIn('原文证据', result)
        self.assertNotIn('局限与解释边界', result)
        self.assertNotIn('href="#e-', result)
        self.assertNotIn('今天有点累。', result)
        self.assertNotIn('聊天记录缺少线下互动。', result)
        self.assertNotIn('evidenceIds', result)
        with report_test_directory() as directory:
            write_report(sample_report(), directory)
            public_text = (directory / 'report-data.json').read_text(encoding='utf-8')
            public = json.loads(public_text)
            self.assertNotIn('evidence', public)
            self.assertNotIn('limitations', public)
            self.assertNotIn('evidenceIds', public_text)
            self.assertNotIn('今天有点累。', public_text)

    def test_academic_layout_uses_three_independent_figures_and_one_table(self):
        result = render_report(sample_report())
        self.assertIn('column-count:2', result)
        self.assertIn('column-span:all', result)
        self.assertIn('SimSun', result)
        self.assertIn('关键词：', result)
        self.assertIn('3.1　互相回应', result)
        self.assertIn('4.1　我', result)
        self.assertEqual(result.count('<strong>图 '), 3)
        self.assertEqual(result.count('<table>'), 1)
        self.assertIn('viewBox="0 0 420 230"', result)
        self.assertIn('font:12px var(--sans)', result)
        self.assertNotIn('data-calendar-view', result)
        self.assertNotIn('月度消息量趋势', result)
        self.assertNotIn('双方消息量</', result)
        self.assertIn('calendar-2d print-only', result)

    def test_full_and_partial_coverage_descriptions_are_truthful(self):
        data = sample_report()
        result = render_report(data)
        self.assertIn('全部 3 条有效文字由 2 个批次分析，已完成 2 批', result)
        data['aiStatus']['state'] = 'failed'
        data['mode'] = 'local'
        data['coverage']['completedBatchCount'] = 1
        data['coverage']['analyzedTextMessageCount'] = 2
        result = render_report(data)
        self.assertIn('已完成 1 批、2 条文字', result)
        self.assertNotIn('全部 3 条有效文字由', result)
        self.assertIn('AI 分析未完成', result)
        data['aiStatus']['state'] = 'not_requested'
        result = render_report(data)
        self.assertIn('当前报告未调用 AI', result)
        self.assertNotIn('已完成 1 批', result)

    def test_local_and_failed_reports_do_not_present_ai_portraits(self):
        data = sample_report()
        data["mode"] = "local"
        data["aiStatus"] = {"state": "not_requested"}
        data["portraits"][0]["description"] = "本次记录中发送了 2 条消息，平均每条 5 字。"
        result = render_report(data)
        self.assertIn('当前报告未调用 AI', result)
        self.assertNotIn('会直接表达需要。', result)
        self.assertNotIn('表达清晰', result)
        self.assertIn('本次记录中发送了 2 条消息', result)
        self.assertIn('平均每条 5 字', result)
        self.assertIn('可观察的表达习惯 · 本地统计', result)
        data["aiStatus"] = {"state": "failed", "error": "SecretProviderDetail"}
        result = render_report(data)
        self.assertIn('AI 分析未完成', result)
        self.assertNotIn('SecretProviderDetail', result)
        self.assertNotIn('会直接表达需要。', result)

    def test_calendar_crosses_year_and_distinguishes_missing_record(self):
        result = render_report(sample_report())
        self.assertIn('<strong>2025</strong>', result)
        self.assertIn('<strong>2026</strong>', result)
        self.assertIn('2025-12-31：1 条消息', result)
        self.assertIn('2026-01-02：2 条消息', result)
        self.assertIn('2026-01-01：无记录（不代表没有联系）', result)
        self.assertIn('2026-01-03：不在本次记录日期范围内', result)
        self.assertIn('无记录不代表无联系', result)
        self.assertIn('1月', result)
        self.assertIn('周一', result)
        self.assertIn('calendar-3d', result)
        self.assertIn('face-top', result)

    def test_leap_day_and_no_dates(self):
        data = sample_report()
        data["stats"]["dateRange"] = {"start": "2024-02-28", "end": "2024-03-01"}
        data["stats"]["dailyCounts"] = [{"date": "2024-02-29", "count": 3}]
        result = render_report(data)
        self.assertIn('2024-02-29：3 条消息', result)
        data["stats"]["dateRange"] = {"start": None, "end": None}
        data["stats"]["dailyCounts"] = []
        result = render_report(data)
        self.assertIn('消息缺少有效日期', result)

    def test_offline_deliverables_exclude_private_config_and_preview(self):
        data = sample_report()
        data["apiKey"] = "SECRET_NEVER_SERIALIZE"
        data["archivePath"] = "PRIVATE_ARCHIVE_PATH"
        data["preview"] = {"apiKey": "SECRET_IN_PREVIEW"}
        original = copy.deepcopy(data)
        with report_test_directory() as directory:
            path = Path(write_report(data, directory))
            public = json.loads((path.parent / "report-data.json").read_text(encoding="utf-8"))
            html_content = path.read_text(encoding="utf-8")
            self.assertTrue(path.is_file())
            self.assertEqual(path.name, 'report.html')
            self.assertNotIn('apiKey', public)
            self.assertNotIn('preview', public)
            self.assertNotIn('archivePath', public)
            self.assertNotIn('SECRET_NEVER_SERIALIZE', html_content)
            self.assertNotIn('<script src=', html_content)
            self.assertNotIn('<link ', html_content)
            self.assertIn('离线', html_content)
            self.assertIn('关键词：', html_content)
        self.assertEqual(original, data)


if __name__ == '__main__':
    unittest.main()
