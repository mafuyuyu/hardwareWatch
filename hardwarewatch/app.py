# -*- coding: utf-8 -*-
"""Orchestrator: collectors, coalescing, notifications and alerts."""
from __future__ import annotations

import datetime
import json
import os
import queue
import threading
import time

from . import attrib, classify, config, deepaudit, evtlog, pnp, winapi

CHANNELS = {
    "pnp-config": {
        "channel": "Microsoft-Windows-Kernel-PnP/Configuration",
        "ids": (400, 410, 420, 430, 441, 442, 443, 444, 445, 446),
    },
    "system-pnp": {"channel": "System", "ids": (219, 20001, 20003, 20004)},
    "system-power": {
        "channel": "System",
        "ids": (42, 107),
        "provider": "Microsoft-Windows-Kernel-Power",
    },
    "system-wake": {
        "channel": "System",
        "ids": (1,),
        "provider": "Microsoft-Windows-Power-Troubleshooter",
    },
    "windows-update": {
        "channel": "Microsoft-Windows-WindowsUpdateClient/Operational",
        "ids": (19, 20, 43, 44),
    },
}

NOTIFY_KINDS = {
    "arrival": ("notify_arrival", "硬件接入"),
    "removal": ("notify_removal", "硬件移除"),
    "driver_install": ("notify_driver", "驱动安装"),
    "driver_service": ("notify_driver", "驱动服务"),
    "driver_change": ("notify_driver", "驱动变更"),
    "driver_remove": ("notify_driver", "驱动卸载"),
    "driver_error": ("notify_problem", "驱动加载失败"),
    "device_problem": ("notify_problem", "设备异常"),
}


def fmt_ts(ts):
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return ""


class App:
    def __init__(self, store, settings, log=None, on_log=None):
        self.store = store
        self.settings = settings
        self._log = on_log or (lambda *a: None)
        self.log = log
        self.paused = False
        self.ui_queue = queue.Queue()
        self.snapshot = pnp.Snapshot()
        self.tracker = attrib.ProcessTracker()
        self.setupapi = attrib.SetupApiLog(log=self._log)
        self.audit = deepaudit.ProcessAudit(store, log=self._log)
        self.msg = winapi.MessageWindow(self._dispatch, log=self._log)
        self._stop = threading.Event()
        self._rescan = threading.Event()
        self._last_ids = {}
        self._threads = []
        self._notify_lock = threading.Lock()
        self._notify_ts = []
        self._suppressed = 0
        self._alert_at = {}
        self._started_at = time.time()
        self._last_ids = self._load_cursor()

    # -- lifecycle ---------------------------------------------------------
    @property
    def is_admin(self):
        return winapi.is_admin()

    def start(self, icon_path=""):
        self.snapshot.refresh()
        self.tracker.poll()
        self.setupapi.poll()
        self.msg.start_tray(icon_path)
        self.msg.start()
        if self.settings.get("deep_audit"):
            try:
                self.audit.enable()
            except Exception as exc:
                self._log("deep audit unavailable: %r" % (exc,))
        self._backfill()
        self._spawn(self._loop_snapshot, "snapshot")
        self._spawn(self._loop_eventlog, "eventlog")
        self._spawn(self._loop_context, "context")
        self._spawn(self._loop_alerts, "alerts")
        self._log("started admin=%s" % self.is_admin)

    def stop(self):
        self._stop.set()
        try:
            if self.audit.active:
                self.audit.disable()
        except Exception as exc:
            self._log("deep audit disable failed: %r" % (exc,))
        try:
            self.msg.stop()
        except Exception:
            pass
        self.store.set_meta("evtlog_cursor", json.dumps(self._last_ids))

    def _spawn(self, target, name):
        thread = threading.Thread(target=target, name="hwwatch-" + name, daemon=True)
        thread.start()
        self._threads.append(thread)

    # -- dispatch from the message window ---------------------------------
    def _dispatch(self, msg):
        kind = msg[0]
        try:
            if kind == "nodes_changed":
                self._rescan.set()
            elif kind == "volume":
                self._on_volume(msg[1], msg[2])
            elif kind == "hotkey":
                self.mark_sound("热键 Ctrl+Alt+M")
            elif kind == "tray_left":
                self.ui_queue.put(("show",))
            elif kind == "tray_right":
                self._menu(self.msg.show_menu(self._menu_items()))
            elif kind == "menu":
                self._menu(msg[1])
            elif kind == "show":
                self.ui_queue.put(("show",))
        except Exception as exc:
            self._log("dispatch error %r" % (exc,))

    def _menu_items(self):
        return [
            (1, "显示主窗口", True),
            (2, "标记「我听到了」", True),
            (3, "恢复提醒" if self.paused else "暂停提醒", True),
            (None, "", None),
            (4, "打开数据目录", True),
            (5, "导出 HTML 报告…", True),
            (7, "生成专项复盘报告…", True),
            (None, "", None),
            (6, "退出", True),
        ]

    def _menu(self, cmd):
        if cmd == 1:
            self.ui_queue.put(("show",))
        elif cmd == 2:
            self.mark_sound("托盘菜单")
        elif cmd == 3:
            self.toggle_pause()
        elif cmd == 4:
            try:
                os.startfile(str(config.data_dir()))
            except Exception:
                pass
        elif cmd == 5:
            self.ui_queue.put(("export",))
        elif cmd == 6:
            self.ui_queue.put(("quit",))
        elif cmd == 7:
            self.run_forensics()

    def run_forensics(self):
        def work():
            try:
                from . import forensics

                result, path = forensics.run(self.store)
                self.msg.notify("专项复盘报告已生成", path)
                self.ui_queue.put(("forensics_done", path))
            except Exception as exc:
                self._log("forensics failed %r" % (exc,))
                self.ui_queue.put(("forensics_failed", str(exc)))

        threading.Thread(
            target=work, name="hwwatch-forensics", daemon=True
        ).start()

    def set_deep_audit(self, enabled):
        if enabled:
            self.audit.enable()
        else:
            self.audit.disable()
        self.settings["deep_audit"] = bool(enabled)
        config.save_settings(self.settings)
        self.ui_queue.put(("deep_audit", self.audit.active))
        return self.audit.active

    def toggle_pause(self):
        self.paused = not self.paused
        self.ui_queue.put(("pause", self.paused))

    # -- collectors --------------------------------------------------------
    def _loop_snapshot(self):
        poll = max(1.0, float(self.settings.get("poll_seconds") or 3.0))
        while not self._stop.is_set():
            triggered = self._rescan.wait(poll)
            self._rescan.clear()
            if self._stop.is_set():
                break
            if triggered:
                time.sleep(0.35)
            try:
                events = self.snapshot.refresh()
            except Exception as exc:
                self._log("snapshot failed %r" % (exc,))
                continue
            for event in events:
                event["ts"] = event.get("ts") or time.time()
                self._ingest(classify.from_snapshot(event))

    def _loop_eventlog(self):
        while not self._stop.is_set():
            for key, spec in CHANNELS.items():
                try:
                    rows = evtlog.read_recent(
                        spec["channel"], spec["ids"], seconds=600,
                        max_events=400, provider=spec.get("provider"),
                    )
                except Exception as exc:
                    self._log("eventlog %s failed %r" % (key, exc))
                    continue
                for row in rows:
                    rid = int(row.get("record_id") or 0)
                    if rid and rid <= self._last_ids.get(key, 0):
                        continue
                    event = classify.from_eventlog(row)
                    self._ingest(event)
                    if rid:
                        self._last_ids[key] = max(self._last_ids.get(key, 0), rid)
            try:
                self.store.set_meta("evtlog_cursor", json.dumps(self._last_ids))
            except Exception:
                pass
            self._stop.wait(2.0)

    def _loop_context(self):
        while not self._stop.is_set():
            try:
                self.tracker.poll()
                self.setupapi.poll()
                self.audit.poll()
            except Exception as exc:
                self._log("context failed %r" % (exc,))
            self._stop.wait(3.0)

    def _loop_alerts(self):
        while not self._stop.is_set():
            if not self.paused:
                try:
                    rows = self.store.flapping(window=900, min_events=6)
                except Exception:
                    rows = []
                now = time.time()
                for row in rows:
                    inst = row["instance_id"]
                    if now - self._alert_at.get(inst, 0) < 1800:
                        continue
                    self._alert_at[inst] = now
                    self._insert_alert(row)
            self._stop.wait(60.0)

    # -- ingestion ---------------------------------------------------------
    def _load_cursor(self):
        raw = self.store.get_meta("evtlog_cursor", "")
        try:
            data = json.loads(raw) if raw else {}
            return {str(k): int(v) for k, v in data.items()}
        except (ValueError, TypeError):
            return {}

    def _backfill(self):
        days = int(self.settings.get("backfill_days") or 7)
        seconds = days * 86400
        added = 0
        for key, spec in CHANNELS.items():
            try:
                rows = evtlog.read_recent(
                    spec["channel"], spec["ids"], seconds=seconds,
                    max_events=5000, provider=spec.get("provider"),
                )
            except Exception as exc:
                self._log("backfill %s failed %r" % (key, exc))
                continue
            floor = self._last_ids.get(key, 0)
            for row in rows:
                rid = int(row.get("record_id") or 0)
                if rid and rid <= floor:
                    continue
                self._ingest(classify.from_eventlog(row), notify=False)
                if rid:
                    self._last_ids[key] = max(self._last_ids.get(key, 0), rid)
                added += 1
        self.store.set_meta("evtlog_cursor", json.dumps(self._last_ids))
        self._log("backfill %d events over %d days" % (added, days))

    def _enrich(self, event):
        instance = event.get("instance_id") or ""
        if not instance:
            return
        try:
            info = pnp.get_info(instance)
        except Exception:
            info = {}
        if not info:
            return
        if not event.get("name"):
            resolved = info.get("name") or ""
            event["name"] = (
                resolved
                if resolved and resolved != instance
                else classify.generic_name(instance)
            )
        event["class_name"] = event.get("class_name") or info.get("class_name", "")
        event["vid"] = event.get("vid") or info.get("vid", "")
        event["pid"] = event.get("pid") or info.get("pid", "")
        event["serial"] = event.get("serial") or info.get("serial", "")
        if not event.get("driver"):
            event["driver"] = info.get("driver", "")
        detail = event.setdefault("detail", {})
        detail.setdefault("device", info)

    def _ingest(self, event, notify=True):
        try:
            self._enrich(event)
            if not event.get("ts"):
                event["ts"] = time.time()
            clues = attrib.build_clues(
                event, self.tracker, self.setupapi, self.store, self.audit
            )
            event["clues"] = clues + list(event.get("clues") or [])
            event.pop("record_id", None)
            event.pop("event_id", None)
            event_id, merged = self.store.insert(event)
            if event_id and notify and not merged:
                self._maybe_notify(event)
            self.ui_queue.put(("event", event_id))
        except Exception as exc:
            self._log("ingest failed %r for %r" % (exc, event.get("kind")))

    def _maybe_notify(self, event):
        if self.paused:
            return
        kind = event.get("kind") or ""
        spec = NOTIFY_KINDS.get(kind)
        if not spec:
            return
        setting_key, title = spec
        if not self.settings.get(setting_key, True):
            return
        name = event.get("name") or event.get("instance_id") or "未知设备"
        ids = ""
        if event.get("vid") and event.get("pid"):
            ids = "VID %s / PID %s" % (event["vid"], event["pid"])
        parts = [name]
        if ids:
            parts.append(ids)
        if event.get("driver"):
            parts.append("驱动 " + event["driver"])
        parts.append(fmt_ts(event.get("ts")))
        body = " · ".join(parts)
        if event.get("class_name"):
            body = event["class_name"] + " · " + body
        self._notify(title, body)

    def _notify(self, title, body):
        with self._notify_lock:
            now = time.time()
            self._notify_ts = [t for t in self._notify_ts if now - t < 4]
            if len(self._notify_ts) >= 3:
                self._suppressed += 1
                return
            self._notify_ts.append(now)
            suppressed = self._suppressed
            self._suppressed = 0
        text = body
        if suppressed:
            text = "刚又发生 %d 个设备变化 · 详见记录窗口" % suppressed
        try:
            self.msg.notify(title, text, sound=bool(self.settings.get("notify_sound")))
        except Exception as exc:
            self._log("notify failed %r" % (exc,))

    # -- user actions ------------------------------------------------------
    def _on_volume(self, kind, letters):
        if not letters:
            return
        name = "驱动器 " + "、".join(letters)
        event = {
            "ts": time.time(),
            "kind": "arrival" if kind == "arrival" else "removal",
            "source": "volume-broadcast",
            "instance_id": "",
            "name": name,
            "detail": {"letters": letters},
            "severity": 0,
        }
        self._ingest(event)

    def mark_sound(self, source="手动"):
        now = time.time()
        nearby = []
        try:
            for row in self.store.query(since=now - 30, limit=30, ascending=True):
                if abs(row["ts"] - now) <= 30:
                    nearby.append(
                        {
                            "id": row["id"],
                            "ts": row["ts_text"],
                            "kind": row["kind"],
                            "name": row["name"],
                        }
                    )
        except Exception:
            pass
        event = {
            "ts": now,
            "kind": "marker",
            "source": source,
            "name": "用户听到提示音",
            "detail": {"source": source, "nearby": nearby},
            "severity": 1,
            "note": "手动标记",
        }
        self._ingest(event, notify=False)
        tail = ""
        if nearby:
            last = nearby[-1]
            tail = " · 最近事件: %s %s" % (last["name"], last["ts"][11:])
        self.msg.notify(
            "已记录声音标记",
            datetime.datetime.fromtimestamp(now).strftime("%H:%M:%S") + tail,
        )
        self.ui_queue.put(("marker",))

    def _insert_alert(self, row):
        event = {
            "ts": time.time(),
            "kind": "alert",
            "source": "flapping-detector",
            "instance_id": row.get("instance_id") or "",
            "name": row.get("name") or row.get("instance_id") or "",
            "detail": {
                "window_minutes": 15,
                "events": row.get("c"),
                "merged": row.get("m"),
                "first": fmt_ts(row.get("a")),
                "last": fmt_ts(row.get("b")),
            },
            "severity": 2,
            "note": "15 分钟内反复接入/移除 %s 次，疑似接触不良或供电不足"
            % row.get("c"),
        }
        self._ingest(event, notify=False)
        self.msg.notify(
            "疑似设备反复重连",
            "%s · 15 分钟内 %s 次，建议检查线材/接口"
            % (event["name"], row.get("c")),
        )

    def recent_for_ui(self, seconds=86400):
        return self.store.since(seconds)
