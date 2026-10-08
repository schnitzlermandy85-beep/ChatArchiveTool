"""Offline two-column Chinese reports with native SVG figures.

Public artifacts contain aggregate results only. Original excerpts, request
previews and API credentials remain outside HTML and report-data.json.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import math
from pathlib import Path
from typing import Any
from psychology_frameworks import get_framework_profile
from psychology_references import get_references


RELATIONSHIP_LABELS = {
    "friend": "朋友", "family": "亲人", "partner": "恋人", "best_friend": "闺蜜 / 亲密朋友"
}
COLORS = ["#333333", "#737373", "#a3a3a3", "#c6c6c6", "#575757", "#8a8a8a", "#dedede"]
TYPE_LABELS = {"text": "文字", "audio": "语音", "image": "图片", "video": "视频", "sticker": "表情", "file": "文件", "other": "其他"}
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _n(value: Any) -> int:
    try:
        return max(0, int(value))
    except (ValueError, TypeError, OverflowError):
        return 0


def _number(value: Any) -> str:
    return f"{_n(value):,}"


def _date(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _duration(value: Any) -> str:
    if value is None:
        return "—"
    try:
        seconds = max(0, float(value))
    except (ValueError, TypeError):
        return "—"
    if not math.isfinite(seconds):
        return "—"
    if seconds < 60:
        return f"{seconds:.0f} 秒"
    if seconds < 3600:
        return f"{seconds / 60:.1f} 分钟"
    return f"{seconds / 3600:.1f} 小时"


def _paragraphs(value: Any) -> str:
    if isinstance(value, list):
        return "".join(f"<p>{_e(item)}</p>" for item in value if item)
    return "".join(f"<p>{_e(line)}</p>" for line in str(value or "").split("\n") if line.strip())


def _list(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "<p class=muted>暂无可确认内容。</p>"
    return "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in items) + "</ul>"


def _svg_open(width: int, height: int, label: str, extra: str = "") -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{_e(label)}" {extra}><title>{_e(label)}</title>'


def _empty_chart(text: str) -> str:
    return f'<div class="empty-chart">{_e(text)}</div>'


def _bar_chart(values: Any, labels: list[str], title: str) -> str:
    counts = [_n(value) for value in (values if isinstance(values, list) else [])]
    counts = (counts + [0] * len(labels))[:len(labels)]
    if not any(counts):
        return _empty_chart("没有可用于此图的有效时间记录。")
    width, height, left, right, top, bottom = 420, 230, 40, 410, 24, 184
    maximum = max(counts)
    step = (right - left) / len(labels)
    parts = [_svg_open(width, height, title)]
    for i in range(5):
        y = bottom - i / 4 * (bottom - top)
        parts.append(f'<line class="grid-line" x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}"/><text class="axis-label" x="{left-10}" y="{y+4:.1f}" text-anchor="end">{round(maximum*i/4)}</text>')
    for index, (label, count) in enumerate(zip(labels, counts)):
        x = left + index * step + step * .18
        h = count / maximum * (bottom - top)
        parts.append(f'<rect x="{x:.1f}" y="{bottom-h:.1f}" width="{step*.64:.1f}" height="{h:.1f}" fill="#666666" tabindex="0" aria-label="{_e(label)}：{count} 条消息"><title>{_e(label)}：{count} 条消息</title></rect>')
        if len(labels) <= 8 or index % 3 == 0:
            parts.append(f'<text class="axis-label" x="{left+(index+.5)*step:.1f}" y="{bottom+24}" text-anchor="middle">{_e(label)}</text>')
    parts.append(f'<text class="axis-label" x="{left}" y="12">消息条数</text><text class="axis-label" x="{right}" y="226" text-anchor="end">小时（UTC+08:00）</text></svg>')
    return "".join(parts)


def _donut(counts: dict, labels: dict, title: str) -> str:
    rows = [(str(key), _n(value)) for key, value in counts.items() if _n(value)]
    total = sum(count for _, count in rows)
    if not total:
        return _empty_chart("没有可用于此图的消息记录。")
    parts = ['<div class="media-chart">', _svg_open(260, 230, title)]
    radius, cx, cy = 66, 130, 115
    circumference = 2 * math.pi * radius
    offset = 0.0
    for index, (key, count) in enumerate(rows):
        length = count / total * circumference
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{COLORS[index%len(COLORS)]}" stroke-width="25" stroke-dasharray="{length:.3f} {circumference-length:.3f}" stroke-dashoffset="{-offset:.3f}" transform="rotate(-90 {cx} {cy})"><title>{_e(labels.get(key,key))}：{count} 条消息</title></circle>')
        offset += length
    parts.append(f'<text x="{cx}" y="{cy}" text-anchor="middle" class="donut-number">{_number(total)}</text><text x="{cx}" y="{cy+23}" text-anchor="middle" class="axis-label">条消息</text></svg>')
    parts.append('<ul class="chart-legend">')
    for index, (key, count) in enumerate(rows):
        parts.append(f'<li><i style="background:{COLORS[index%len(COLORS)]}"></i><span>{_e(labels.get(key,key))}</span><strong>{_number(count)}</strong></li>')
    parts.append("</ul></div>")
    return "".join(parts)


def _calendar_data(stats: dict) -> tuple[dict[dt.date, int], dt.date | None, dt.date | None]:
    daily = {}
    for item in stats.get("dailyCounts", []):
        if isinstance(item, dict) and (date := _date(item.get("date"))):
            daily[date] = _n(item.get("count"))
    date_range = stats.get("dateRange") or {}
    start = _date(date_range.get("start")) or (min(daily) if daily else None)
    end = _date(date_range.get("end")) or (max(daily) if daily else None)
    if start and end and start > end:
        return daily, None, None
    return daily, start, end


def _heat_level(count: int, maximum: int) -> int:
    if not count:
        return 0
    return min(4, max(1, math.ceil(count / max(1, maximum) * 4)))


def _year_calendar(year: int, daily: dict, start: dt.date, end: dt.date, maximum: int, three_d: bool = False) -> str:
    first = dt.date(year, 1, 1)
    last = dt.date(year, 12, 31)
    aligned = first - dt.timedelta(days=first.weekday())
    total_weeks = ((last - aligned).days // 7) + 1
    step = 13
    width = 62 + total_weeks * step + (45 if three_d else 0)
    height = 150 if three_d else 135
    parts = [_svg_open(width, height, f"{year} 年{'立体' if three_d else '日历'}消息热力图；无记录不代表没有联系", 'class="calendar-svg"')]
    for month in range(1, 13):
        date = dt.date(year, month, 1)
        week = (date - aligned).days // 7
        x = 49 + week * step
        parts.append(f'<text class="axis-label" x="{x}" y="15">{month}月</text>')
    for weekday in range(7):
        y = (52 + weekday * 10) if three_d else (37 + weekday * step)
        parts.append(f'<text class="axis-label" x="4" y="{y}">{WEEKDAYS[weekday]}</text>')
    for week in range(total_weeks):
        for weekday in range(7):
            date = aligned + dt.timedelta(days=week * 7 + weekday)
            if date.year != year:
                continue
            valid = start <= date <= end
            count = daily.get(date, 0) if valid else 0
            level = _heat_level(count, maximum)
            label = f"{date.isoformat()}：{count} 条消息" if count else f"{date.isoformat()}：无记录（不代表没有联系）"
            if not valid:
                label = f"{date.isoformat()}：不在本次记录日期范围内"
            attributes = f'tabindex="0" aria-label="{_e(label)}"' if valid else f'aria-label="{_e(label)}"'
            css = f"heat-{level}" if valid else "heat-outside"
            if not three_d:
                x, y = 49 + week * step, 28 + weekday * step
                parts.append(f'<rect x="{x}" y="{y}" width="10" height="10" rx="2" class="{css}" {attributes}><title>{_e(label)}</title></rect>')
            else:
                x, y = 49 + week * step + weekday * 4, 48 + weekday * 10
                h = (2 + 24 * math.sqrt(count / maximum)) if count and valid else 1
                parts.append(f'<g class="bar3d {css}" {attributes}><title>{_e(label)}</title><polygon class="face-left" points="{x},{y-h:.1f} {x+5},{y-h+3:.1f} {x+5},{y+3} {x},{y}"/><polygon class="face-right" points="{x+5},{y-h+3:.1f} {x+10},{y-h:.1f} {x+10},{y} {x+5},{y+3}"/><polygon class="face-top" points="{x},{y-h:.1f} {x+5},{y-h-3:.1f} {x+10},{y-h:.1f} {x+5},{y-h+3:.1f}"/></g>')
    parts.append("</svg>")
    return "".join(parts)


def _heatmaps(stats: dict) -> str:
    daily, start, end = _calendar_data(stats)
    if not start or not end:
        return _empty_chart("消息缺少有效日期，无法绘制日历热力图。")
    maximum = max(max(daily.values(), default=0), 1)
    chunks = []
    for year in range(start.year, end.year + 1):
        year_start, year_end = max(start, dt.date(year, 1, 1)), min(end, dt.date(year, 12, 31))
        year_count = sum(n for day, n in daily.items() if year_start <= day <= year_end)
        chunks.append(f'<div class="calendar-year"><div class="calendar-heading"><strong>{year}</strong><span>{_number(year_count)} 条消息</span></div><div class="calendar-scroll calendar-3d">{_year_calendar(year,daily,start,end,maximum,True)}</div><div class="calendar-scroll calendar-2d print-only" aria-hidden="true">{_year_calendar(year,daily,start,end,maximum)}</div></div>')
    chunks.append('<div class="heat-legend"><span>无记录</span>' + "".join(f'<i class="heat-{level}"></i>' for level in range(5)) + f'<span>较多 · 本次最高 {_number(maximum)} 条 / 日</span></div>')
    return "".join(chunks)


STYLE = r"""
:root{--ink:#171717;--serif:"Songti SC","Noto Serif CJK SC","SimSun","STSong",serif;--sans:"Noto Sans CJK SC","Microsoft YaHei","SimHei",sans-serif}
*{box-sizing:border-box}body{margin:0;color:var(--ink);background:#eee;font:15px/1.75 var(--serif)}button{font:12px var(--sans);color:#222;background:#fff;border:1px solid #888;padding:7px 13px;cursor:pointer}button:hover{background:#f4f4f4}button:focus-visible,[tabindex]:focus-visible{outline:2px solid #333;outline-offset:2px}svg [tabindex]:focus{stroke:#000;stroke-width:1.5}.toolbar{max-width:1080px;margin:20px auto 12px;padding:0 44px;display:flex;align-items:center;justify-content:space-between;font:11px var(--sans);color:#666}.paper{max-width:1080px;margin:0 auto 44px;background:#fff;padding:43px 58px 30px;box-shadow:0 2px 12px #00000009}.paper-header{text-align:center;padding:3px 0 20px;border-bottom:1px solid #333}.kicker{font:12px var(--sans);letter-spacing:3px;margin:0 0 12px;color:#555}.paper-header h1{font:700 30px/1.35 var(--sans);letter-spacing:1px;margin:0}.paper-subtitle{font:18px/1.5 var(--serif);margin:10px 0 0}.metadata{font:12px/1.7 var(--serif);margin:14px 0 0;color:#555}.abstract{padding:19px 32px 20px;border-bottom:1px solid #ccc;margin-bottom:24px;font-size:13px;line-height:1.75}.abstract h2{font:700 16px var(--sans);text-align:center;margin:0 0 8px}.abstract p{margin:5px 0;text-align:justify}.keywords{margin-top:11px!important}.keywords strong{font-family:var(--sans)}.analysis-state{font-size:12px;color:#555}.analysis-state.failed{border-left:2px solid #444;padding-left:10px;color:#222}.paper-body{column-count:2;column-gap:32px;text-align:justify}.section{margin:0 0 19px}.section h2{font:700 18px/1.5 var(--sans);margin:0 0 10px;break-after:avoid}.section h3{font:700 14px/1.5 var(--sans);margin:14px 0 7px;break-after:avoid}.section p{margin:5px 0 10px;overflow-wrap:anywhere}.section ul,.section ol{padding-left:21px;margin:7px 0 12px}.section li{margin:5px 0}.method-detail{font-size:13px}.wide{column-span:all}.figure{margin:17px 0 22px;break-inside:avoid;text-align:left}.figure svg{display:block;width:100%;height:auto}.figcaption{font:12px/1.7 var(--serif);margin-top:9px;text-align:justify}.figcaption strong{font-family:var(--sans)}.figure-row{display:grid;grid-template-columns:1fr 1fr;column-gap:30px;align-items:start}.figure-row .figure{margin-top:8px}.grid-line{stroke:#dedede;stroke-width:.7}.axis-label{fill:#555;font:12px var(--sans)}.calendar-year{margin:0 0 14px;break-inside:avoid}.calendar-heading{font:12px/1.5 var(--serif);display:flex;justify-content:space-between;padding:0 3px}.calendar-heading strong{font-family:var(--sans);font-weight:500}.calendar-scroll{overflow-x:auto;overflow-y:hidden}.calendar-svg{min-width:650px}.heat-0{fill:#eaeaea;background:#eaeaea}.heat-1{fill:#ccc;background:#ccc}.heat-2{fill:#a3a3a3;background:#a3a3a3}.heat-3{fill:#707070;background:#707070}.heat-4{fill:#303030;background:#303030}.heat-outside{fill:#fafafa}.face-left{filter:brightness(.86)}.face-right{filter:brightness(.70)}.heat-legend{display:flex;align-items:center;gap:4px;font:10px/1.5 var(--sans);color:#666;justify-content:flex-end;flex-wrap:wrap;margin:3px 0 7px}.heat-legend span{margin:0 4px}.heat-legend i{width:10px;height:10px;display:block}.media-chart{display:grid;grid-template-columns:1.5fr 1fr;align-items:center;min-height:230px}.chart-legend{list-style:none;padding:0;margin:0;font:11px/1.7 var(--sans)}.chart-legend li{display:flex;align-items:center;gap:6px;margin:4px 0}.chart-legend strong{margin-left:auto;font-weight:500}.chart-legend i{width:10px;height:10px;flex-shrink:0;border:1px solid #888}.donut-number{fill:#222;font:600 22px var(--serif)}.empty-chart{padding:35px 15px;text-align:center;color:#666;font-size:12px;border:1px solid #ddd;min-height:170px}.table-block{margin:2px 0 24px}.table-block figcaption{margin:0 0 7px;text-align:center}.table-scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font:12px/1.65 var(--serif);border-top:1.5px solid #333;border-bottom:1.5px solid #333}th{border-bottom:1px solid #777;font-weight:500;font-family:var(--sans)}th,td{padding:7px 8px;text-align:center}th:first-child,td:first-child{text-align:left}.table-note{font:11px/1.65 var(--serif);margin:7px 0 0;color:#555}.finding{break-inside:avoid}.finding p{font-size:14px}.alternative{font-size:12px!important;color:#555}.portrait{break-inside:avoid;margin-bottom:16px}.portrait .descriptor-label{font:11px/1.6 var(--sans);color:#666;margin:2px 0 7px}.portrait .sub-label{font-family:var(--sans);font-size:12px;font-weight:600;margin-top:8px}.portrait ul{font-size:13px;margin-top:3px}.footer{border-top:1px solid #ccc;margin-top:20px;padding-top:10px;display:flex;justify-content:space-between;gap:15px;font:10px/1.6 var(--sans);color:#666}.print-only{display:none}
@media(max-width:760px){body{background:#fff}.toolbar{margin:12px 0;padding:0 20px}.toolbar span{font-size:10px}.paper{margin:0;padding:20px;box-shadow:none}.paper-header h1{font-size:25px}.paper-subtitle{font-size:16px}.abstract{padding:16px 0}.paper-body{column-count:1}.figure-row{grid-template-columns:1fr;gap:3px}.media-chart{min-height:180px}.calendar-svg{min-width:650px}.footer{flex-direction:column;gap:0}.figure{margin-top:15px}}
@media print{@page{size:A4;margin:15mm 14mm}body{background:#fff;font-size:9.5pt;line-height:1.65}.no-print,.calendar-3d{display:none!important}.print-only{display:block!important}.paper{max-width:none;margin:0;padding:0;box-shadow:none}.paper-header{padding:0 0 5mm}.paper-header h1{font-size:20pt}.paper-subtitle{font-size:12pt}.metadata{font-size:8pt}.abstract{padding:4mm 8mm;margin-bottom:5mm;font-size:8.5pt}.paper-body{column-count:2;column-gap:6mm}.section{margin-bottom:4mm}.section h2{font-size:12pt}.section h3{font-size:10pt}.method-detail,.finding p{font-size:9pt}.figure-row{column-gap:6mm}.figure{margin:3mm 0 5mm}.figcaption{font-size:8pt}.calendar-svg{min-width:0}.calendar-scroll{overflow:visible}.calendar-year{margin-bottom:3mm}.calendar-heading{font-size:8pt}.media-chart{min-height:0}.chart-legend{font-size:7.5pt}.table-block{margin-bottom:5mm}table{font-size:8pt}th,td{padding:2mm 1.5mm}.table-note{font-size:7.5pt}.alternative,.portrait .sub-label{font-size:8pt!important}.portrait ul{font-size:8.5pt}.footer{font-size:7pt;margin-top:5mm}.figure,.calendar-year,.heat-legend{print-color-adjust:exact;-webkit-print-color-adjust:exact}p{orphans:3;widows:3}}
"""


def _safe_public_data(data: dict) -> dict:
    """Share aggregate results, never raw message material or request bodies."""
    allowed = {"schemaVersion", "relationship", "relationshipLabel", "mode", "generatedAt", "participants", "stats", "quality", "coverage", "summary", "findings", "portraits", "suggestions", "aiStatus", "analysisRequirements", "frameworkProfile"}
    public = {key: value for key, value in data.items() if key in allowed}
    if public.get("frameworkProfile"):
        # Theory names and links come from our verified registry, not prose or
        # metadata invented by an API provider or an archive.
        try:
            profile = get_framework_profile(public.get("relationship"))
            theories = [profile["primaryTheory"], *profile["auxiliaryTheories"]]
            profile["references"] = get_references(item["id"] for item in theories)
            public["frameworkProfile"] = profile
        except ValueError:
            public.pop("frameworkProfile", None)
    for field in ("findings", "portraits"):
        if isinstance(public.get(field), list):
            public[field] = [{key: value for key, value in item.items() if key not in ("evidenceIds", "evidence", "messages", "rawText")} for item in public[field] if isinstance(item, dict)]
    if not public.get("coverage") and isinstance(data.get("preview"), dict):
        coverage = data["preview"].get("coverage")
        if isinstance(coverage, dict):
            public["coverage"] = coverage
    return public


def _coverage_description(data: dict, stats: dict, ai_success: bool, failed: bool) -> str:
    coverage = data.get("coverage") or {}
    eligible = _n(coverage.get("validTextMessageCount", stats.get("textMessageCount")))
    if not coverage:
        return f"有效文字消息共 {_number(eligible)} 条。" + ("AI 已完成文本解释；本次输入覆盖信息未提供。" if ai_success else "当前报告未调用 AI。" if not failed else "AI 分析未完成，采用本地描述性统计。")
    batches = _n(coverage.get("batchCount"))
    completed = _n(coverage.get("completedBatchCount"))
    analyzed = _n(coverage.get("analyzedTextMessageCount"))
    sent = _n(coverage.get("sentMessageCount"))
    omitted = _n(coverage.get("omittedTextMessages"))
    full = (coverage.get("mode") == "full" and not omitted and sent == eligible
            and analyzed == eligible and completed == batches)
    if ai_success:
        lead = f"全部 {_number(eligible)} 条有效文字由 {_number(batches)} 个批次分析" if full else f"本次选取 {_number(sent)} / {_number(eligible)} 条有效文字进行分析"
        return lead + f"，已完成 {_number(completed)} 批，随后综合各批结果。" + (f"另有 {_number(omitted)} 条文字未参与 AI 分析。" if omitted else "")
    if failed:
        return f"AI 分析未完成：计划覆盖 {_number(eligible)} 条有效文字、{_number(batches)} 个批次；已完成 {_number(completed)} 批、{_number(analyzed)} 条文字。本报告采用本地统计结果。"
    return f"有效文字消息共 {_number(eligible)} 条；当前报告未调用 AI。本地行为统计覆盖所选日期范围的全部有效消息。"


def render_report(data: dict) -> str:
    """Render verified aggregate results in a two-column Chinese paper layout."""
    data = _safe_public_data(data)
    stats = data.get("stats") or {}
    people = [person for person in data.get("participants", []) if isinstance(person, dict)]
    aliases = {str(person.get("id")): str(person.get("name") or ("我" if person.get("isSelf") else "对方")) for person in people}
    relation = str(data.get("relationshipLabel") or RELATIONSHIP_LABELS.get(data.get("relationship"), "关系"))
    status = data.get("aiStatus") or {}
    ai_success = status.get("state") == "succeeded" and data.get("mode") == "ai"
    failed = status.get("state") == "failed"
    quality = data.get("quality") or {}
    date_range = stats.get("dateRange") or {}
    start, end = _date(date_range.get("start")), _date(date_range.get("end"))
    range_label = f"{start.isoformat()} 至 {end.isoformat()}" if start and end else "日期资料不足"
    names = "、".join(aliases.values()) or "我、对方"
    generated = str(data.get("generatedAt") or "")[:19].replace("T", " ")
    coverage_description = _coverage_description(data, stats, ai_success, failed)
    framework = data.get("frameworkProfile") or {}
    dimension_names = {item["id"]: item["name"] for item in framework.get("dimensionDefinitions", [])}
    theory_names = {item["id"]: item["name"] for item in ([framework["primaryTheory"]] + framework.get("auxiliaryTheories", []))} if framework.get("primaryTheory") else {}
    threshold = _n((stats.get("sessions") or {}).get("thresholdMinutes")) or 30
    sender_counts = stats.get("senderCounts") or {}
    sessions = stats.get("sessions") or {}
    title = f"双人聊天记录的关系互动分析：{relation}视角"
    parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>', _e(title), '</title><style>', STYLE, '</style></head><body>']
    parts.append('<div class="toolbar no-print"><span>中文分析报告 · 离线阅读</span><button type="button" id="print-report">打印 / 保存 PDF</button></div><article class="paper">')
    parts.append(f'<header class="paper-header"><p class="kicker">关系互动分析报告</p><h1>双人聊天记录的关系互动分析</h1><p class="paper-subtitle">——以{_e(relation)}关系为视角</p><p class="metadata">观察对象：{_e(names)}　｜　记录范围：{_e(range_label)}<br>生成时间：{_e(generated)}</p></header>')
    parts.append('<section class="abstract" id="abstract"><h2>摘　要</h2>')
    parts.append(_paragraphs(data.get("summary") or "本文以已导出的双人聊天记录为分析对象，统计互动的时间分布、消息媒介构成及发起与回应行为，并依据所选关系视角组织关系观察与双方交流形象。"))
    if failed:
        parts.append('<p class="analysis-state failed"><strong>AI 分析未完成。</strong> 以下关系观察与交流形象采用本地描述性统计，未展示未完成的 AI 综合结论。</p>')
    elif not ai_success:
        parts.append('<p class="analysis-state">分析方式：本地统计。当前报告未调用 AI，人物描述依据可观察的文字行为。</p>')
    else:
        model = f"（{_e(status.get('model'))}）" if status.get("model") else ""
        parts.append(f'<p class="analysis-state">分析方式：本地行为统计与 AI 文本分析{model}。实际文字覆盖与批次完成情况见第 1 节。</p>')
    parts.append(f'<p class="keywords"><strong>关键词：</strong>{_e(relation)}；聊天互动；时间分布；交流形象</p></section><div class="paper-body">')
    parts.append('<section class="section" id="methods"><h2>1　数据与分析方法</h2>')
    parts.append(f'<p>本次分析对象为{_e(names)}的双人聊天档案，关系类型由用户选定为{_e(relation)}。观察区间为{_e(range_label)}，包含 {_number(stats.get("messageCount"))} 条有效消息、{_number(stats.get("activeDays"))} 个有记录的日期。双方身份采用所选别名。</p>')
    parts.append(f'<p class="method-detail">消息数量、时间分布和媒介构成由本地程序计算。时间统一为 UTC+08:00；相邻消息间隔超过 {threshold} 分钟划为新会话。回复间隔统计同一会话内相邻发送者切换，使用中位数与第 90 百分位数描述。</p>')
    parts.append(f'<p class="method-detail">{_e(coverage_description)}媒体正文不参与文本分析；已有语音转写作为文字处理。关系观察分别呈现记录中的行为与文本解释，人物形象依据交流内容组织。</p>')
    if framework:
        auxiliary = "、".join(item["name"] for item in framework["auxiliaryTheories"])
        priorities = "、".join(dimension_names[key] for key in framework["priorityDimensions"][:4])
        applied = "AI 文本解释以" if ai_success else "配置的 AI 观察框架以"
        parts.append('<p class="method-detail"><strong>心理学观察框架：</strong>' + _e(applied + framework["primaryTheory"]["name"] + "为主，辅以" + auxiliary + "。重点观察" + priorities + "。理论用于组织具体互动的解释，不作心理量表评分或依恋类型判断。") + '</p>')
        references = framework.get("references", [])
        if references:
            links = [f'<a href="{_e(item["url"])}" target="_blank" rel="noopener noreferrer">{_e(item["title"])}</a>' for item in references]
            parts.append('<p class="method-detail">框架参考：' + '；'.join(links) + '。</p>')
    excluded = []
    for field, label in [("systemMessages", "系统消息"), ("invalidTimes", "无效时间消息"), ("rangeExcluded", "日期范围外消息")]:
        if _n(quality.get(field)):
            excluded.append(f"{_number(quality[field])} 条{label}")
    if excluded:
        parts.append('<p class="method-detail">数据检查中排除' + _e("、".join(excluded)) + '。</p>')
    if data.get("analysisRequirements"):
        parts.append('<p class="method-detail"><strong>本次补充分析要求：</strong>' + _e(data.get("analysisRequirements")) + '</p>')
    parts.append('</section><section class="section" id="behavior"><h2>2　互动行为统计</h2>')
    parts.append(f'<p>记录共划分为 {_number(sessions.get("count"))} 个会话段。图 1 描述互动在日期上的持续性，图 2 描述一天内的时段选择，图 3 描述交流使用的消息媒介。表 1 汇总双方的会话开启与回应行为。</p><p class="method-detail">各图采用日期、小时与媒介类型三个统计维度。无记录不代表无联系，消息数量与回应时间均按档案中的实际消息计算。</p></section>')
    parts.append('<figure class="figure wide" id="figure-1">' + _heatmaps(stats) + '<figcaption class="figcaption"><strong>图 1　日期层面的互动分布。</strong>每个单元代表一天；灰度与立体柱高表示消息量，柱高采用平方根缩放。悬停或键盘聚焦显示准确条数。打印版使用同一数据的平面投影，日期范围外单元不参与分析。</figcaption></figure>')
    parts.append('<div class="figure-row wide"><figure class="figure" id="figure-2">' + _bar_chart(stats.get("hourCounts"), [f"{hour:02d}" for hour in range(24)], "日内时段分布：各小时消息条数") + '<figcaption class="figcaption"><strong>图 2　日内时段分布。</strong>横轴为本地小时，纵轴为消息条数，用于观察聊天发生的作息时段。</figcaption></figure><figure class="figure" id="figure-3">' + _donut(stats.get("typeCounts") or {}, TYPE_LABELS, "消息媒介构成：各媒介消息条数") + '<figcaption class="figcaption"><strong>图 3　消息媒介构成。</strong>每条消息按一个主要媒介类别计数，用于描述文字、语音及其他媒介的使用结构。</figcaption></figure></div>')
    parts.append('<figure class="table-block wide" id="table-1"><figcaption class="figcaption"><strong>表 1　双方发起与回应行为统计。</strong></figcaption><div class="table-scroll"><table><thead><tr><th>人物</th><th>消息条数</th><th>会话开启数</th><th>回复样本数</th><th>间隔中位数</th><th>第 90 百分位</th></tr></thead><tbody>')
    for participant_id, name in aliases.items():
        response = (stats.get("responseDelays") or {}).get(participant_id) or {}
        initiated = (sessions.get("initiations") or {}).get(participant_id)
        parts.append(f'<tr><td>{_e(name)}</td><td>{_number(sender_counts.get(participant_id))}</td><td>{_number(initiated)}</td><td>{_number(response.get("count"))}</td><td>{_e(_duration(response.get("medianSeconds")))}</td><td>{_e(_duration(response.get("p90Seconds")))}</td></tr>')
    parts.append('</tbody></table></div><p class="table-note">会话开启指每段记录中的第一条消息；回复样本指同一会话内的发送者切换。“—”表示没有可计算样本。该表描述行为分布，不将消息量转换为关系评分。</p></figure>')
    parts.append('<section class="section" id="findings"><h2>3　关系互动模式</h2>')
    findings = [item for item in data.get("findings", []) if isinstance(item, dict)]
    if not findings:
        parts.append('<p>当前未生成关系互动解释，可依据第 2 节的行为统计进行回顾。</p>')
    for index, finding in enumerate(findings, 1):
        parts.append(f'<article class="finding"><h3>3.{index}　{_e(finding.get("title") or "互动观察")}</h3>')
        if (finding.get("dimensionId") in dimension_names and finding.get("theoryId") in theory_names
                and finding.get("supportLevel") in ("tentative", "contextual")):
            support = "暂时解释" if finding.get("supportLevel") == "tentative" else "多片段支持的解释"
            parts.append('<p class="method-detail">' + _e(dimension_names[finding["dimensionId"]] + " · " + theory_names[finding["theoryId"]] + " · " + support) + '</p>')
        if finding.get("observation"):
            parts.append('<p><strong>观察：</strong>' + _e(finding.get("observation")) + '</p>')
        if finding.get("interpretation"):
            parts.append('<p><strong>' + ('文本解释：' if ai_success else '回顾提示：') + '</strong>' + _e(finding.get("interpretation")) + '</p>')
        alternatives = finding.get("alternatives")
        if isinstance(alternatives, list) and alternatives:
            parts.append('<p class="alternative"><strong>其他解释：</strong>' + _e("；".join(str(item) for item in alternatives)) + '</p>')
        parts.append('</article>')
    parts.append('</section><section class="section" id="portraits"><h2>4　双方交流形象</h2>')
    portraits = {str(item.get("participantId")): item for item in data.get("portraits", []) if isinstance(item, dict)}
    for index, (participant_id, name) in enumerate(aliases.items(), 1):
        portrait = portraits.get(participant_id)
        parts.append(f'<article class="portrait"><h3>4.{index}　{_e(name)}</h3>')
        if ai_success and portrait:
            parts.append(_paragraphs(portrait.get("description")))
            if portrait.get("strengths"):
                parts.append('<p class="sub-label">表达特点</p>' + _list(portrait.get("strengths")))
            if portrait.get("communicationNeeds"):
                parts.append('<p class="sub-label">沟通需要</p>' + _list(portrait.get("communicationNeeds")))
        else:
            parts.append('<p class="descriptor-label">可观察的表达习惯 · 本地统计</p>')
            parts.append(_paragraphs(portrait.get("description")) if portrait and portrait.get("description") else f'<p>本次记录中发送了 {_number(sender_counts.get(participant_id))} 条消息。</p>')
        parts.append('</article>')
    parts.append('</section><section class="section" id="suggestions"><h2>5　沟通建议</h2>')
    suggestions = data.get("suggestions") or ["选取双方愿意讨论的互动情境，询问对方当时的感受，再说明自己的理解。", "对互动解释出现分歧时，结合双方说明调整理解与后续沟通方式。"]
    parts.append('<ol>' + ''.join(f'<li>{_e(item)}</li>' for item in suggestions) + '</ol></section></div><footer class="footer"><span>ChatArchiveTool · 自动生成的交流分析报告</span><span>可离线阅读与打印</span></footer></article>')
    js_path = Path(__file__).parent / "web" / "report.js"
    script = js_path.read_text(encoding="utf-8") if js_path.exists() else "document.getElementById('print-report').addEventListener('click',function(){window.print();});"
    parts.append('<script>' + script.replace("</script", "<\\/script") + '</script></body></html>')
    return "".join(parts)


def write_report(data: dict, dest: str | Path) -> str:
    """Write self-contained HTML and aggregate report JSON; return HTML path."""
    target = Path(dest).expanduser().resolve()
    if target.suffix.lower() == ".html":
        report_path, directory = target, target.parent
    else:
        directory, report_path = target, target / "report.html"
    directory.mkdir(parents=True, exist_ok=True)
    public = _safe_public_data(data)
    report_path.write_text(render_report(public), encoding="utf-8")
    (directory / "report-data.json").write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(report_path)
