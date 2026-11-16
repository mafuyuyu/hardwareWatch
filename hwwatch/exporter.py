# -*- coding: utf-8 -*-
"""CSV and self-contained HTML report export."""
from __future__ import annotations

import csv
import datetime
import html
import json
import os

from .classify import label

CSV_HEADERS = [
    "时间", "类型", "设备", "实例ID", "VID", "PID", "类别", "驱动",
    "驱动版本", "触发线索", "严重度", "合并次数", "备注", "来源",
]


def _clues_text(raw):
    try:
        clues = json.loads(raw or "[]")
    except ValueError:
        return raw or ""
    parts = []
    for clue in clues:
        if isinstance(clue, dict):
            text = clue.get("text", "")
            conf = clue.get("confidence", "")
            parts.append(text + ("[%s]" % conf if conf else ""))
        else:
            parts.append(str(clue))
    return " | ".join(parts)


def export_csv(rows, path):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADERS)
        for row in rows:
            writer.writerow([
                row.get("ts_text", ""),
                label(row.get("kind", "")),
                row.get("name", ""),
                row.get("instance_id", ""),
                row.get("vid", ""),
                row.get("pid", ""),
                row.get("class_name", ""),
                row.get("driver", ""),
                row.get("driver_version", ""),
                _clues_text(row.get("clues", "")),
                row.get("severity", 0),
                row.get("merged_count", 1),
                row.get("note", ""),
                row.get("source", ""),
            ])
    return path


def _fmt(ts):
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return ""


def _esc(text):
    return html.escape(str(text or ""))


def summarize(rows):
    counts = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    devices = {}
    for row in rows:
        inst = row.get("instance_id") or ""
        if not inst:
            continue
        item = devices.setdefault(inst, {
            "instance": inst,
            "name": row.get("name") or inst,
            "arrivals": 0,
            "removals": 0,
            "times": [],
        })
        if row["kind"] == "arrival":
            item["arrivals"] += 1
        elif row["kind"] == "removal":
            item["removals"] += 1
        item["times"].append(float(row["ts"]))
    suspicious = []
    for item in devices.values():
        total = item["arrivals"] + item["removals"]
        if total < 5:
            continue
        times = sorted(item["times"])
        burst = 1
        best_burst = 1
        start = 0
        for i in range(1, len(times)):
            while times[i] - times[start] > 120:
                start += 1
            burst = i - start + 1
            best_burst = max(best_burst, burst)
        suspicious.append({
            "name": item["name"],
            "instance": item["instance"],
            "total": total,
            "burst": best_burst,
            "last": _fmt(times[-1]),
        })
    suspicious.sort(key=lambda x: (-x["total"], -x["burst"]))
    drivers = [
        r for r in rows
        if r["kind"] in ("driver_install", "driver_service", "driver_change")
    ]
    problems = [r for r in rows if int(r.get("severity") or 0) >= 2]
    return {
        "counts": counts,
        "suspicious": suspicious[:20],
        "drivers": drivers,
        "problems": problems,
    }


HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HwWatch 硬件事件报告</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2430;--muted:#66707d;--line:#e3e7ec;
--blue:#2563eb;--red:#dc2626;--amber:#d97706;--green:#059669;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.6 "Microsoft YaHei UI","Segoe UI",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:22px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:24px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi b{display:block;font-size:24px;line-height:1.2}
.kpi span{color:var(--muted);font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-bottom:20px}
.card h2{font-size:16px;margin:0 0 12px}
table{width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed}
td,th{overflow:hidden;word-break:break-word}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;background:#fafbfc;position:sticky;top:0}
tr:hover td{background:#fafcff}
.badge{display:inline-block;padding:1px 8px;border-radius:20px;font-size:12px;border:1px solid var(--line)}
.b-arrival{color:var(--green);border-color:#a7e3cd;background:#ecfdf5}
.b-removal{color:var(--muted);background:#f3f4f6}
.b-driver{color:var(--blue);border-color:#bfdbfe;background:#eff6ff}
.b-problem{color:var(--red);border-color:#fecaca;background:#fef2f2}
.b-marker{color:var(--amber);border-color:#fde68a;background:#fffbeb}
.mono{font-family:Consolas,"Cascadia Mono",monospace;font-size:12px;color:#374151;word-break:break-all}
.note{color:var(--muted);font-size:12px}
.empty{color:var(--muted);text-align:center;padding:18px}
.search{width:100%;max-width:340px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;font-size:13px;margin-bottom:10px}
.hint{background:#eff6ff;border:1px solid #bfdbfe;color:#1e3a8a;border-radius:8px;padding:10px 12px;font-size:13px;margin-bottom:18px}
@media print{.search{display:none}body{background:#fff}}
</style></head><body><div class="wrap">
"""


def export_html(rows, path, title="HwWatch 硬件事件报告", admin=False):
    summary = summarize(rows)
    counts = summary["counts"]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if rows:
        span = "%s 至 %s" % (_fmt(min(r["ts"] for r in rows)), _fmt(max(r["ts"] for r in rows)))
    else:
        span = "无数据"
    parts = [HTML_HEAD]
    parts.append("<h1>%s</h1>" % _esc(title))
    parts.append(
        '<div class="sub">生成时间 %s · 记录区间 %s · 共 %d 条 · %s</div>'
        % (now, _esc(span), len(rows), "管理员模式" if admin else "普通权限（部分事件可能缺失）")
    )
    parts.append('<div class="hint">本报告由 HwWatch 自动生成。Windows 不公开驱动安装的“发起进程”，'
                 '因此“触发线索”标注了置信度，请结合时间和设备判断。</div>')
    kpi = [
        ("总事件", len(rows)),
        ("硬件接入", counts.get("arrival", 0)),
        ("硬件移除", counts.get("removal", 0)),
        ("驱动安装/变更", counts.get("driver_install", 0) + counts.get("driver_service", 0)
         + counts.get("driver_change", 0)),
        ("异常", len(summary["problems"])),
        ("声音标记", counts.get("marker", 0)),
    ]
    parts.append('<div class="kpis">')
    for name, value in kpi:
        parts.append('<div class="kpi"><b>%s</b><span>%s</span></div>' % (value, _esc(name)))
    parts.append("</div>")

    parts.append('<div class="card"><h2>重点结论</h2><ul>')
    if summary["suspicious"]:
        top = summary["suspicious"][0]
        parts.append(
            "<li><b>%s</b> 出现 %d 次接入/移除，最多 %d 次集中在 2 分钟内；"
            "若并非你亲手插拔，优先检查线材、接口或 USB Hub 供电。</li>"
            % (_esc(top["name"]), top["total"], top["burst"])
        )
    else:
        parts.append("<li>没有发现明显的反复重连设备。</li>")
    if summary["problems"]:
        parts.append("<li>存在 %d 条异常/错误事件，见下方“异常事件”。</li>" % len(summary["problems"]))
    if summary["drivers"]:
        parts.append("<li>本次区间内有 %d 条驱动安装/变更记录。</li>" % len(summary["drivers"]))
    if counts.get("marker"):
        parts.append("<li>你有 %d 次“听到提示音”的手动标记，可用于比对系统事件。</li>" % counts["marker"])
    if not counts.get("arrival") and not counts.get("removal"):
        parts.append("<li>本次区间没有接入/移除记录：历史回填只覆盖事件日志，"
                     "插拔统计从程序实际运行后开始。</li>")
    parts.append("</ul></div>")

    if summary["suspicious"]:
        parts.append('<div class="card"><h2>疑似反复重连的设备</h2><table>'
                     "<tr><th>设备</th><th>实例 ID</th><th>接入+移除</th><th>2 分钟内最多</th><th>最近一次</th></tr>")
        for item in summary["suspicious"]:
            parts.append(
                "<tr><td>%s</td><td class=mono>%s</td><td>%d</td><td>%d</td><td>%s</td></tr>"
                % (_esc(item["name"]), _esc(item["instance"]), item["total"], item["burst"], _esc(item["last"]))
            )
        parts.append("</table></div>")

    parts.append('<div class="card"><h2>驱动安装 / 变更</h2>')
    if summary["drivers"]:
        parts.append("<table><colgroup><col style='width:150px'><col style='width:100px'>"
                     "<col style='width:230px'><col style='width:320px'><col style='width:120px'>"
                     "</colgroup><tr><th>时间</th><th>类型</th><th>设备</th><th>驱动</th><th>版本</th></tr>")
        for row in summary["drivers"][:200]:
            parts.append(
                "<tr><td>%s</td><td>%s</td><td>%s</td><td class=mono>%s</td><td>%s</td></tr>"
                % (_fmt(row["ts"]), _esc(label(row["kind"])), _esc(row.get("name")),
                   _esc(row.get("driver")), _esc(row.get("driver_version")))
            )
        parts.append("</table>")
    else:
        parts.append('<div class="empty">区间内没有驱动安装/变更记录</div>')
    parts.append("</div>")

    parts.append('<div class="card"><h2>异常事件</h2>')
    if summary["problems"]:
        parts.append("<table><colgroup><col style='width:150px'><col style='width:100px'>"
                     "<col style='width:250px'><col style='width:300px'></colgroup>"
                     "<tr><th>时间</th><th>类型</th><th>设备</th><th>说明</th></tr>")
        for row in summary["problems"][:200]:
            detail = {}
            try:
                detail = json.loads(row.get("detail") or "{}")
            except ValueError:
                pass
            text = detail.get("data", {}).get("Problem") or detail.get("failure") or ""
            parts.append(
                "<tr><td>%s</td><td>%s</td><td>%s</td><td class=mono>%s</td></tr>"
                % (_fmt(row["ts"]), _esc(label(row["kind"])), _esc(row.get("name") or row.get("instance_id")), _esc(text))
            )
        parts.append("</table>")
    else:
        parts.append('<div class="empty">区间内没有异常事件</div>')
    parts.append("</div>")

    parts.append('<div class="card"><h2>完整时间线</h2>')
    parts.append('<input class="search" id="q" placeholder="输入设备名 / 实例 ID / 驱动过滤…" oninput="flt()">')
    parts.append("<table id='tl'><colgroup><col style='width:132px'><col style='width:92px'>"
                 "<col style='width:190px'><col style='width:300px'><col style='width:176px'>"
                 "<col style='width:180px'><col style='width:110px'></colgroup>"
                 "<thead><tr><th>时间</th><th>类型</th><th>设备</th><th>实例 ID</th>"
                 "<th>驱动</th><th>线索</th><th>备注</th></tr></thead><tbody>")
    for row in rows[:3000]:
        cls = "b-problem" if int(row.get("severity") or 0) >= 2 else {
            "arrival": "b-arrival", "removal": "b-removal", "marker": "b-marker",
        }.get(row["kind"], "b-driver")
        parts.append(
            "<tr><td>%s</td><td><span class='badge %s'>%s</span></td><td>%s</td>"
            "<td class=mono>%s</td><td class=mono>%s</td><td>%s</td><td>%s</td></tr>"
            % (_fmt(row["ts"]), cls, _esc(label(row["kind"])), _esc(row.get("name")),
               _esc(row.get("instance_id")), _esc(row.get("driver")),
               _esc(_clues_text(row.get("clues", ""))), _esc(row.get("note")))
        )
    if not rows:
        parts.append("<tr><td colspan=7 class=empty>没有记录</td></tr>")
    parts.append("</tbody></table></div>")
    parts.append("""<script>
function flt(){var q=document.getElementById('q').value.toLowerCase();
var rows=document.querySelectorAll('#tl tbody tr');
for(var i=0;i<rows.length;i++){rows[i].style.display=
rows[i].innerText.toLowerCase().indexOf(q)>=0?'':'none';}}
</script></div></body></html>""")
    data = "".join(parts)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(data)
    return path
