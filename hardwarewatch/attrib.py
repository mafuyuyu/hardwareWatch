# -*- coding: utf-8 -*-
"""Best-effort attribution: install method, nearby processes, update activity.

Windows does not expose the originating process for a PnP driver install, so
this module gathers corroborating evidence and labels it by confidence instead
of pretending to know more than the OS reveals.
"""
from __future__ import annotations

import datetime
import os
import re

from . import winapi

SETUPAPI_LOG = "C:/Windows/INF/setupapi.dev.log"

HEADER_RE = re.compile(r"^>>>\s+\[(.+?)\]\s*$")
INSTANCE_RE = re.compile(r"\s-\s(.+)$")
SECTION_RE = re.compile(r"^>>>\s+Section start\s+(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d+)")

KNOWN_SOFTWARE = [
    ("lghub", "罗技 G HUB"),
    ("ghub", "罗技 G HUB"),
    ("logi", "罗技软件"),
    ("armoury", "华硕 Armoury Crate"),
    ("aura", "华硕 AURA / 灯控"),
    ("asus", "华硕相关软件"),
    ("flydigi", "飞智手柄软件"),
    ("razer", "雷蛇软件"),
    ("icue", "海盗船 iCUE"),
    ("msi", "微星相关软件"),
    ("mystic", "微星 Mystic Light"),
    ("gigabyte", "技嘉相关软件"),
    ("openrgb", "OpenRGB 灯控"),
    ("signalrgb", "SignalRGB 灯控"),
    ("steam", "Steam"),
    ("phoneexperiencehost", "手机连接 Phone Link"),
    ("yourphone", "手机连接 Phone Link"),
    ("nvcontainer", "NVIDIA 容器"),
    ("nvidia", "NVIDIA 软件"),
    ("vmware", "VMware"),
    ("virtualbox", "VirtualBox"),
    ("xvdd", "虚拟显示器驱动"),
    ("sunshine", "Sunshine 串流"),
    ("parsec", "Parsec 串流"),
    ("wallpaper", "Wallpaper Engine"),
]

DRIVER_SOFTWARE_HINT = re.compile(
    r"ghub|lghub|armoury|aura|flydigi|razer|icue|openrgb|signalrgb|"
    r"phoneexperiencehost|yourphone|nvcontainer|vmware|virtualbox|sunshine|parsec",
    re.I,
)


class ProcessTracker:
    """Remembers when each pid first appeared, so we can list new arrivals."""

    def __init__(self):
        self._seen = {}
        self._first_poll = True

    def poll(self):
        now = datetime.datetime.now().timestamp()
        current = winapi.list_processes()
        for pid, exe in current.items():
            if pid not in self._seen:
                self._seen[pid] = (exe, now)
        for pid in list(self._seen):
            if pid not in current:
                self._seen.pop(pid, None)
        if self._first_poll:
            self._first_poll = False

    def recent(self, seconds=90):
        cutoff = datetime.datetime.now().timestamp() - seconds
        rows = [
            (name, pid)
            for pid, (name, started) in self._seen.items()
            if started >= cutoff
        ]
        rows.sort()
        return rows[:12]


class SetupApiLog:
    """Incrementally tails setupapi.dev.log for device/driver install blocks."""

    def __init__(self, path=SETUPAPI_LOG, log=None):
        self.path = path
        self.offset = 0
        self.entries = []
        self._pending = None
        self._buffer = ""
        self._log = log or (lambda *a, **k: None)
        try:
            self.offset = os.path.getsize(path)
        except OSError:
            self.offset = 0
        self.entries = []

    def poll(self):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return
        if size < self.offset:
            self.offset = 0
            self._buffer = ""
        if size == self.offset:
            return
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                chunk = fh.read(2 * 1024 * 1024)
                self.offset = fh.tell()
        except OSError:
            return
        text = self._buffer + chunk.decode("utf-8", "ignore")
        lines = text.splitlines()
        self._buffer = ""
        if text and not text.endswith(("\n", "\r")):
            self._buffer = lines.pop() if lines else text
        for line in lines:
            self._feed(line)
        self._trim()

    def _feed(self, line):
        match = HEADER_RE.match(line.strip())
        if match:
            self._pending = match.group(1)
            return
        match = SECTION_RE.match(line.strip())
        if match and self._pending:
            try:
                when = datetime.datetime.strptime(
                    match.group(1), "%Y/%m/%d %H:%M:%S.%f"
                ).timestamp()
            except ValueError:
                self._pending = None
                return
            header = self._pending
            self._pending = None
            inst_match = INSTANCE_RE.search(header)
            instance = inst_match.group(1).strip() if inst_match else ""
            method = ""
            if "(" in header and ")" in header:
                method = header[header.find("(") + 1:header.rfind(")")].strip()
            kind = "device" if header.lower().startswith("device install") else "driver"
            self.entries.append(
                {
                    "ts": when,
                    "instance": instance,
                    "method": method,
                    "kind": kind,
                }
            )

    def _trim(self):
        cutoff = datetime.datetime.now().timestamp() - 3600
        self.entries = [e for e in self.entries if e["ts"] >= cutoff][-300:]

    def find(self, instance, ts, window=120.0):
        best = None
        for entry in self.entries:
            if not entry["instance"] or not instance:
                continue
            if entry["instance"].lower() != instance.lower():
                continue
            delta = abs(entry["ts"] - ts)
            if delta <= window and (best is None or delta < abs(best["ts"] - ts)):
                best = entry
        return best


def software_hints(processes):
    hints = []
    for name, pid in processes:
        low = (name or "").lower()
        for key, label in KNOWN_SOFTWARE:
            if key in low and label not in hints:
                hints.append(label)
                break
    return hints


SYSTEM_NOISE = {
    "svchost.exe", "conhost.exe", "dllhost.exe", "runtimebroker.exe",
    "backgroundtaskhost.exe", "wmiprvse.exe", "taskhostw.exe",
    "searchprotocolhost.exe", "smartscreen.exe", "ctfmon.exe",
    "lockapp.exe", "python.exe", "pythonw.exe", "textinputhost.exe",
    "startmenuexperiencehost.exe", "shellexperiencehost.exe",
}

SKIP_KINDS = {
    "marker", "alert", "arrival", "removal", "windows_update", "unknown",
    "driver_error", "device_migrate", "device_phantom",
}

DRIVER_KINDS = {
    "driver_install", "driver_service", "driver_change", "device_config",
    "device_problem",
}

PROCESS_LIST_KINDS = {"driver_install", "driver_service", "driver_change"}


def execution_clues(event):
    """Turn the event's Execution ProcessID into a human clue when meaningful."""
    detail = event.get("detail") or {}
    pid = int(detail.get("execution_pid") or 0)
    if not pid or pid in (0, 4):
        return []
    name = winapi.process_name(pid)
    if not name:
        return []
    return [{
        "type": "exec_pid",
        "text": "事件执行进程: %s (PID %d)" % (name, pid),
        "confidence": "medium",
    }]


def build_clues(event, tracker, setupapi, store, audit=None):
    if event.get("kind") in SKIP_KINDS:
        return []
    clues = []
    ts = float(event.get("ts") or datetime.datetime.now().timestamp())
    instance = event.get("instance_id") or ""
    methods = {
        "hardware initiated": "硬件插入触发安装",
        "update driver for plug and play devices": "驱动更新触发",
        "dif installdevice": "系统安装设备",
        "diinstalldevice": "系统安装设备",
    }
    if instance and setupapi is not None:
        entry = setupapi.find(instance, ts)
        if entry:
            method = (entry.get("method") or "").strip()
            human = methods.get(method.lower())
            if not human:
                human = "安装方式: " + (method or "未知")
            clues.append(
                {
                    "type": "install",
                    "text": human,
                    "confidence": "high",
                    "at": entry["ts"],
                }
            )
    fresh = (datetime.datetime.now().timestamp() - ts) <= 600
    recent = tracker.recent(120) if tracker is not None else []
    recent = [
        (name, pid) for name, pid in recent
        if (name or "").lower() not in SYSTEM_NOISE
    ]
    if recent and fresh and event.get("kind") in PROCESS_LIST_KINDS:
        listing = ", ".join("%s(%d)" % (n, p) for n, p in recent[:4])
        clues.append(
            {
                "type": "process",
                "text": "时间窗内新启动的进程: " + listing,
                "confidence": "low",
            }
        )
    hints = software_hints(recent) if fresh else []
    if hints:
        clues.append(
            {
                "type": "software",
                "text": "相关软件在运行: " + "、".join(hints[:4]),
                "confidence": "low",
            }
        )
    if store is not None and event.get("kind") not in ("windows_update",):
        cutoff = ts - 600
        try:
            rows = store.query(since=cutoff, limit=50, ascending=True)
        except Exception:
            rows = []
        for row in rows:
            if row["kind"] == "windows_update" and abs(row["ts"] - ts) <= 600:
                clues.append(
                    {
                        "type": "windows_update",
                        "text": "前后 10 分钟内有 Windows 更新活动",
                        "confidence": "medium",
                    }
                )
                break
    clues.extend(execution_clues(event))
    if audit is not None:
        try:
            clues.extend(audit.clues(event.get("instance_id") or "", ts))
        except Exception:
            pass
    return clues
