# -*- coding: utf-8 -*-
"""One-off forensic review: virtual display / WUDFRd / phantom devices.

Produces a self-contained HTML report that ranks hypotheses and proposes
falsifiable experiments, instead of guessing.
"""
from __future__ import annotations

import datetime
import glob
import html
import json
import os
import subprocess
import winreg

from . import config, evtlog, winapi

KEYWORDS_SOFTWARE = (
    "remote", "stream", "display", "virtual", "uu", "todesk", "sunlogin",
    "向日葵", "parsec", "sunshine", "gameviewer", "1remote", "rustdesk",
    "teamviewer", "anydesk", "串流", "远程", "虚拟",
)


def _fmt(ts):
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return ""


def _esc(value):
    return html.escape(str(value or ""))


def _detail(row):
    try:
        return json.loads(row.get("detail") or "{}")
    except ValueError:
        return {}


def collect(store, days=30):
    since = datetime.datetime.now().timestamp() - days * 86400
    return store.query(since=since, limit=200000, ascending=True)


def focus_events(rows):
    xvdd, wudf, phantom, display, usb = [], [], [], [], []
    for row in rows:
        instance = row.get("instance_id") or ""
        name = row.get("name") or ""
        detail = _detail(row)
        text = (name + " " + instance + " " + row.get("driver", "")).lower()
        if "xvdd" in text:
            xvdd.append(row)
        if row.get("kind") == "driver_error" and "wudf" in str(detail.get("failure", "")).lower():
            wudf.append(row)
        if row.get("kind") == "device_phantom":
            phantom.append(row)
        if "DISPLAY" in instance.upper() or "MMDEVAPI" in instance.upper():
            display.append(row)
        if instance.upper().startswith("USB") and row.get("kind") in ("arrival", "removal"):
            usb.append(row)
    return {
        "xvdd": xvdd, "wudf": wudf, "phantom": phantom,
        "display": display, "usb": usb,
    }


def boot_times(days=30):
    try:
        rows = evtlog.read_recent("System", (6005,), seconds=days * 86400, max_events=200)
    except Exception:
        return []
    return [row["ts"] for row in rows]


def display_audio_changes(days=7):
    try:
        rows = evtlog.read_recent(
            "Microsoft-Windows-Kernel-PnP/Device Management",
            (1010,), seconds=days * 86400, max_events=500,
        )
    except Exception:
        return []
    hits = []
    for row in rows:
        instance = (row.get("data", {}) or {}).get("DeviceInstanceId", "")
        if "DISPLAY" in instance.upper() or "MMDEVAPI" in instance.upper():
            hits.append({"ts": row["ts"], "instance": instance})
    return hits


def _read_text(path, limit=2 * 1024 * 1024):
    try:
        with open(path, "rb") as fh:
            return fh.read(limit).decode("utf-8", "ignore")
    except OSError:
        return ""


def _inf_value(text, key):
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(key.lower()) and "=" in stripped:
            value = stripped.split("=", 1)[1].strip()
            if value.startswith("%") and value.endswith("%"):
                token = value.strip("%")
                strings = text.split("[Strings]", 1)
                if len(strings) == 2:
                    for entry in strings[1].splitlines():
                        if entry.strip().lower().startswith(token.lower() + " ") or entry.strip().lower().startswith(token.lower() + "="):
                            if "=" in entry:
                                return entry.split("=", 1)[1].strip().strip('"')
            return value.strip('"')
    return ""


def find_driver_infs(keyword="xvdd"):
    found = []
    for path in glob.glob("C:/Windows/INF/*.inf"):
        text = _read_text(path, 512 * 1024)
        if keyword.lower() in text.lower():
            found.append({
                "path": path,
                "provider": _inf_value(text, "Provider"),
                "class": _inf_value(text, "Class"),
                "driverver": _inf_value(text, "DriverVer"),
                "catalog": _inf_value(text, "CatalogFile"),
            })
    return found


def registry_services(keyword="xvdd"):
    hits = []
    base = r"SYSTEM\CurrentControlSet\Services"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                low = name.lower()
                try:
                    with winreg.OpenKey(root, name) as svc:
                        image = str(winreg.QueryValueEx(svc, "ImagePath")[0])
                        display = str(winreg.QueryValueEx(svc, "DisplayName")[0])
                except OSError:
                    continue
                blob = (low + " " + image.lower() + " " + display.lower())
                if keyword.lower() in blob or "virtual display" in blob:
                    hits.append({"name": name, "image": image, "display": display})
    except OSError:
        pass
    return hits


def installed_programs():
    hits = []
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, path in roots:
        try:
            with winreg.OpenKey(hive, path) as root:
                index = 0
                while True:
                    try:
                        sub = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(root, sub) as key:
                            name = str(winreg.QueryValueEx(key, "DisplayName")[0])
                            version = str(winreg.QueryValueEx(key, "DisplayVersion")[0])
                    except OSError:
                        continue
                    low = name.lower()
                    if any(word in low for word in KEYWORDS_SOFTWARE):
                        hits.append({"name": name, "version": version})
        except OSError:
            continue
    unique = []
    seen = set()
    for item in hits:
        if item["name"] not in seen:
            seen.add(item["name"])
            unique.append(item)
    return unique


def running_processes():
    processes = winapi.list_processes()
    hits = []
    for pid, name in processes.items():
        low = name.lower()
        if any(word in low for word in KEYWORDS_SOFTWARE):
            hits.append({"pid": pid, "name": name})
    return hits


def scheduled_tasks():
    script = (
        "Get-ScheduledTask | Where-Object {$_.State -ne 'Disabled'} | "
        "Select-Object TaskName,TaskPath,State,"
        "@{n='Triggers';e={$_.Triggers | ForEach-Object { [pscustomobject]@{"
        "Start=$_.StartBoundary; Interval=$_.Repetition.Interval; Enabled=$_.Enabled} }}},"
        "@{n='Actions';e={$_.Actions | ForEach-Object { ($_.Execute + ' ' + $_.Arguments) }}} | "
        "ConvertTo-Json -Depth 6 -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, timeout=60, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        data = json.loads(result.stdout)
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception:
        return []


def setupapi_hits(keywords=("xvdd", "wudf", "virtual display"), max_lines=40):
    path = "C:/Windows/INF/setupapi.dev.log"
    text = _read_text(path, 8 * 1024 * 1024)
    hits = []
    for line in text.splitlines():
        low = line.lower()
        if any(word in low for word in keywords):
            hits.append(line.strip())
    return hits[-max_lines:]


def nearest_boot(ts, boots):
    """Seconds since the last boot, tolerating events a few seconds before 6005."""
    before = [b for b in boots if b - 180 <= ts]
    return (ts - before[-1]) if before else None


def current_problem_devices():
    from . import pnp

    hits = []
    try:
        for instance, info in pnp.enumerate_present().items():
            if info.get("problem"):
                hits.append({
                    "name": info.get("name") or instance,
                    "instance": instance,
                    "problem": info.get("problem_text") or str(info.get("problem")),
                })
    except Exception:
        pass
    return hits


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2430;--muted:#66707d;--line:#e3e7ec;
--blue:#2563eb;--red:#dc2626;--amber:#d97706;--green:#059669;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.65 "Microsoft YaHei UI","Segoe UI",sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:23px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-bottom:18px}
.card h2{font-size:16px;margin:0 0 12px}
.hyp{border-left:4px solid var(--blue);padding:10px 14px;margin:10px 0;background:#f8fafc;border-radius:0 8px 8px 0}
.hyp b{display:block;margin-bottom:4px}
.high{border-left-color:var(--red)}.mid{border-left-color:var(--amber)}.low{border-left-color:var(--green)}
.conf{font-size:12px;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top;word-break:break-word}
th{color:var(--muted);background:#fafbfc}
.mono{font-family:Consolas,monospace;font-size:12px}
.note{color:var(--muted);font-size:12px}
ol li{margin:6px 0}
.tag{display:inline-block;padding:1px 8px;border-radius:20px;font-size:12px;border:1px solid var(--line);margin-right:4px}
"""


def analyze(store, days=30):
    rows = collect(store, days)
    focus = focus_events(rows)
    boots = boot_times(days)
    xvdd = focus["xvdd"]
    wudf = focus["wudf"]
    phantom = focus["phantom"]
    display = focus["display"]
    usb = focus["usb"]
    changes = display_audio_changes(7)
    xvdd_deltas = [nearest_boot(r["ts"], boots) for r in xvdd]
    wudf_deltas = [nearest_boot(r["ts"], boots) for r in wudf]
    phantom_deltas = [nearest_boot(r["ts"], boots) for r in phantom]
    xvdd_boot = [d for d in xvdd_deltas if d is not None and -180 <= d <= 300]
    wudf_boot = [d for d in wudf_deltas if d is not None and -180 <= d <= 300]
    phantom_boot = [d for d in phantom_deltas if d is not None and -180 <= d <= 300]
    infs = find_driver_infs("xvdd")
    services = registry_services("xvdd")
    programs = installed_programs()
    procs = running_processes()
    tasks = scheduled_tasks()
    event_times = set()
    for row in xvdd + wudf + phantom:
        event_times.add(datetime.datetime.fromtimestamp(row["ts"]).strftime("%H:%M"))
    matched_tasks = []
    for task in tasks:
        triggers = task.get("Triggers") or []
        if isinstance(triggers, dict):
            triggers = [triggers]
        for trigger in triggers:
            start = str(trigger.get("Start") or "")
            if len(start) >= 16 and "T" in start:
                hhmm = start.split("T")[1][:5]
                for et in event_times:
                    try:
                        em = int(et[:2]) * 60 + int(et[3:])
                        tm = int(hhmm[:2]) * 60 + int(hhmm[3:])
                    except ValueError:
                        continue
                    diff = abs(em - tm)
                    blob = ((task.get("TaskName") or "") + " " + "; ".join(task.get("Actions") or [])).lower()
                    relevant = any(word in blob for word in (
                        "display", "driver", "remote", "stream", "virtual",
                        "xvdd", "usb", "pnp",
                    ))
                    if diff <= 3 or (diff <= 10 and relevant):
                        matched_tasks.append({
                            "task": (task.get("TaskPath") or "") + (task.get("TaskName") or ""),
                            "trigger": hhmm,
                            "action": "; ".join(task.get("Actions") or [])[:160],
                            "diff": diff,
                            "relevant": relevant,
                        })
                        break
    problems = current_problem_devices()
    result = {
        "rows": rows,
        "focus": focus,
        "boots": boots,
        "xvdd": xvdd,
        "xvdd_boot": xvdd_boot,
        "wudf": wudf,
        "wudf_boot": wudf_boot,
        "phantom": phantom,
        "phantom_boot": phantom_boot,
        "display": display,
        "usb": usb,
        "changes": changes,
        "infs": infs,
        "services": services,
        "programs": programs,
        "procs": procs,
        "tasks": matched_tasks,
        "problems": problems,
        "days": days,
    }
    result["hypotheses"] = build_hypotheses(result)
    return result


def build_hypotheses(result):
    xvdd, wudf, phantom = result["xvdd"], result["wudf"], result["phantom"]
    hyps = []
    if xvdd:
        boot = len(result["xvdd_boot"])
        total = len(xvdd)
        if boot == total:
            hyps.append({
                "level": "low",
                "title": "虚拟显示器驱动 Xvdd 的配置全部发生在开机后 5 分钟内",
                "confidence": "中（时间相关性）",
                "text": "%d 次 Xvdd 配置，%d 次距最近一次开机 ≤300 秒。开机枚举本身是正常行为；"
                        "如果提示音出现在开机后很久，Xvdd 不是主因。" % (total, boot),
            })
        else:
            hyps.append({
                "level": "mid",
                "title": "Xvdd 在非开机时间也发生重新配置",
                "confidence": "较高（时间相关性）",
                "text": "%d 次 Xvdd 配置中 %d 次不在开机 5 分钟内，这类重新枚举更容易触发系统提示音。"
                        % (total, total - boot),
            })
    if wudf:
        boot = len(result["wudf_boot"])
        hyps.append({
            "level": "low" if boot == len(wudf) else "mid",
            "title": "WUDFRd 驱动加载失败事件",
            "confidence": "低（多为启动期噪音）",
            "text": "%d 次 \Driver\WUDFRd 加载失败，其中 %d 次在开机 5 分钟内。"
                    "WUDFRd 是用户模式驱动框架，虚拟显示器/虚拟 HID 常常出现这种失败，通常不致命，"
                    "但会伴随设备重新枚举。" % (len(wudf), boot),
        })
    if phantom:
        boot = len(result["phantom_boot"])
        hyps.append({
            "level": "mid" if boot < len(phantom) else "low",
            "title": "VHF 虚拟 HID 的幽灵设备清理发生在运行期",
            "confidence": "中（时间分布）",
            "text": "%d 条 0x2D 记录是 CM_PROB_PHANTOM（幽灵设备清理，不是故障），其中 %d 条在开机 5 分钟内，"
                    "说明其余发生在运行期间。虚拟手柄/HID 被创建后移除时会出现，若与提示音同时发生，"
                    "应优先检查对应外设软件（飞智、Steam、串流工具等）。" % (len(phantom), boot),
        })
    if result["changes"]:
        hyps.append({
            "level": "mid",
            "title": "显示器/音频端点发生过变化",
            "confidence": "中（7 天内 %d 次）" % len(result["changes"]),
            "text": "PnP 设备管理日志记录了 DISPLAY/MMDEVAPI 端点变化。显示器、默认音频设备切换"
                    "会触发设备接口到达事件，是“硬件插入”提示音的常见来源之一。",
        })
    if result["usb"]:
        hyps.append({
            "level": "high",
            "title": "运行期间检测到 USB 设备接入/移除",
            "confidence": "高（程序实测）",
            "text": "共 %d 条运行时 USB 变化记录，最近 10 条见时间线。" % len(result["usb"]),
        })
    if result["problems"]:
        names = "、".join(p["name"] for p in result["problems"][:4])
        hyps.append({
            "level": "mid",
            "title": "当前存在异常设备",
            "confidence": "高（设备状态实测）",
            "text": "当前状态非正常的设备：%s。若问题描述为“已禁用”，通常表示该功能被关闭，"
                    "不是硬件故障；蓝牙 PAN 反复加载时才会伴随设备事件。" % names,
        })
    streaming = [p["name"] for p in result["programs"] if any(
        word in p["name"].lower() for word in (
            "sunshine", "virtual desktop", "ps remote", "uu", "todesk",
            "向日葵", "sunlogin", "parsec", "virtual audio", "remote play",
            "1remote", "rustdesk", "teamviewer", "anydesk",
        )
    )]
    if streaming:
        hyps.append({
            "level": "mid",
            "title": "机器上有多款串流/远程桌面软件，会按需创建虚拟显示器与虚拟音频",
            "confidence": "中高（已安装证据）",
            "text": "检测到：%s。这类软件启动会话时会创建虚拟显示/音频端点，退出时清理，"
                    "系统会把它当成“设备接入/移除”，正好会播放提示音，而且不一定每次都伴随窗口提示。"
                    % "、".join(streaming[:8]),
        })
    matched = result["tasks"]
    if matched:
        hyps.append({
            "level": "mid",
            "title": "计划任务时间与设备事件时间重合",
            "confidence": "中（时间重合，需逐项验证）",
            "text": "发现 %d 个非禁用计划任务的触发时间与设备事件相差 ≤10 分钟，见“计划任务”表。" % len(matched),
        })
    if not hyps:
        hyps.append({
            "level": "low", "title": "当前数据不足以定位",
            "confidence": "低", "text": "日志范围内没有足够事件，建议开启管理员模式观察 24-48 小时。",
        })
    return hyps


def _table(headers, rows, widths=None):
    out = ["<table>"]
    if widths:
        out.append("<colgroup>" + "".join(
            "<col style='width:%s'>" % w for w in widths
        ) + "</colgroup>")
    out.append("<tr>" + "".join("<th>%s</th>" % _esc(h) for h in headers) + "</tr>")
    for row in rows:
        out.append("<tr>" + "".join("<td>%s</td>" % cell for cell in row) + "</tr>")
    out.append("</table>")
    return "".join(out)


def render_report(result, path):
    rows = result["rows"]
    days = result["days"]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = ["<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width, initial-scale=1'>",
             "<title>HwWatch 专项复盘</title><style>", CSS, "</style></head><body><div class='wrap'>"]
    parts.append("<h1>硬件“叮咚”声专项复盘</h1>")
    parts.append("<div class='sub'>生成时间 %s · 分析范围 %d 天 / %d 条事件 · 由 HwWatch 自动生成</div>"
                 % (now, days, len(rows)))
    parts.append("<div class='card'><h2>结论排序</h2>")
    for hyp in result["hypotheses"]:
        parts.append("<div class='hyp %s'><b>%s</b><span class='conf'>置信度：%s</span><div>%s</div></div>"
                     % (hyp["level"], _esc(hyp["title"]), _esc(hyp["confidence"]), _esc(hyp["text"])))
    parts.append("</div>")

    xvdd_rows = []
    for row in result["xvdd"][-15:]:
        delta = nearest_boot(row["ts"], result["boots"])
        xvdd_rows.append([
            _esc(_fmt(row["ts"])),
            _esc(row.get("kind")),
            _esc(row.get("name")),
            _esc(("开机后 %d 秒" % int(delta)) if delta is not None and delta >= 0
                 else ("启动阶段（早 %d 秒）" % int(-delta) if delta is not None else "-")),
        ])
    parts.append("<div class='card'><h2>Xvdd 虚拟显示器事件</h2>")
    parts.append(_table(["时间", "类型", "设备", "距开机"], xvdd_rows, ["150px", "110px", "300px", "140px"]))
    parts.append("</div>")

    change_rows = []
    for item in result["changes"][-15:]:
        delta = nearest_boot(item["ts"], result["boots"])
        change_rows.append([
            _esc(_fmt(item["ts"])),
            _esc(item["instance"]),
            _esc(("开机后 %d 秒" % int(delta)) if delta is not None and delta >= 0
                 else ("启动阶段（早 %d 秒）" % int(-delta) if delta is not None else "非开机时段")),
        ])
    parts.append("<div class='card'><h2>显示器 / 音频端点变化（近 7 天）</h2>")
    parts.append(_table(["时间", "设备实例", "距开机"], change_rows,
                        ["150px", "480px", "140px"]))
    parts.append("<div class='note'>显示器、电视或默认音频端点切换会触发设备接口到达事件，"
                 "是“硬件插入”提示音最容易被忽略的来源。</div></div>")

    boot_rows = [[_esc(_fmt(ts)), _esc("开机/事件日志启动")] for ts in result["boots"][-12:]]
    parts.append("<div class='card'><h2>开机时间（System 6005）</h2>")
    parts.append(_table(["时间", "说明"], boot_rows, ["220px", "300px"]))
    parts.append("<div class='note'>用它判断 Xvdd / WUDFRd 事件是否只是开机初始化。</div></div>")

    parts.append("<div class='card'><h2>驱动与软件画像</h2>")
    inf_rows = [[_esc(i["path"]), _esc(i["provider"]), _esc(i["class"]), _esc(i["driverver"])]
                for i in result["infs"]]
    parts.append("<p class='note'>匹配到 %d 个包含 xvdd 的 INF。</p>" % len(inf_rows))
    parts.append(_table(["INF", "Provider", "Class", "DriverVer"], inf_rows,
                        ["300px", "160px", "120px", "200px"]))
    svc_rows = [[_esc(s["name"]), _esc(s["display"]), _esc(s["image"])] for s in result["services"]]
    parts.append("<p class='note'>相关服务：</p>")
    parts.append(_table(["服务名", "显示名", "ImagePath"], svc_rows, ["160px", "220px", "360px"]))
    parts.append("</div>")

    parts.append("<div class='card'><h2>可能相关的软件</h2>")
    parts.append("<p class='note'>已安装：</p>")
    parts.append(_table(["程序", "版本"],
                        [[_esc(p["name"]), _esc(p["version"])] for p in result["programs"][:20]],
                        ["500px", "120px"]))
    parts.append("<p class='note'>当前运行：</p>")
    parts.append(_table(["PID", "进程"],
                        [[str(p["pid"]), _esc(p["name"])] for p in result["procs"][:20]],
                        ["100px", "300px"]))
    parts.append("</div>")

    task_rows = [[_esc(t["task"]), _esc(t["trigger"]),
                  _esc("相关" if t.get("relevant") else "例行任务"),
                  _esc(t["action"])] for t in result["tasks"][:20]]
    parts.append("<div class='card'><h2>时间重合的计划任务</h2>")
    parts.append(_table(["任务", "每日触发", "相关性", "动作"], task_rows,
                        ["280px", "90px", "90px", "380px"]))
    parts.append("<div class='note'>只列出非禁用任务；时间重合不代表因果，需要逐项禁用验证。</div></div>")

    problem_rows = [[_esc(p["name"]), _esc(p["instance"]), _esc(p["problem"])] for p in result["problems"]]
    parts.append("<div class='card'><h2>当前异常设备</h2>")
    parts.append(_table(["设备", "实例 ID", "问题"], problem_rows, ["220px", "400px", "150px"]))
    parts.append("</div>")

    parts.append("<div class='card'><h2>建议的验证实验（按性价比排序）</h2><ol>")
    parts.append("<li><b>48 小时基线观察</b>：以管理员启动 HwWatch，开启深度归因；每次听到提示音按 Ctrl+Alt+M。"
                 "两三天后导出 HTML，看“标记附近”是否有设备事件。</li>")
    parts.append("<li><b>排除 USB Hub/无线接收器</b>：拔掉外接 USB3 Hub（05E3:0626），罗技接收器直插主板后置口，观察 24 小时。</li>")
    parts.append("<li><b>Xvdd 对照实验</b>：设备管理器里禁用 “Xvdd SCSI Miniport”（或停用它对应的虚拟显示服务），"
                 "观察 24 小时；若提示音消失，再恢复并确认。</li>")
    parts.append("<li><b>蓝牙 PAN 修复</b>：卸载异常设备 “Bluetooth Device (Personal Area Network)” 后重新扫描硬件。</li>")
    parts.append("<li><b>空记录判据</b>：若某次提示音时 HwWatch 完全无新记录，把系统“设备连接/断开”声音设为“无”，"
                 "若声音随之消失，则说明是某个程序在调用系统音效。</li>")
    parts.append("</ol></div>")

    parts.append("<div class='card'><h2>附录：setupapi 关键词命中</h2><div class='mono'>")
    for line in setupapi_hits():
        parts.append(_esc(line) + "<br>")
    parts.append("</div></div>")

    parts.append("</div></body></html>")
    data = "".join(parts)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(data)
    return path


def run(store, out_path=None, days=30):
    result = analyze(store, days)
    if out_path is None:
        out_path = str(config.export_dir() / (
            "forensics_%s.html" % datetime.datetime.now().strftime("%Y%m%d_%H%M")
        ))
    render_report(result, out_path)
    return result, out_path
