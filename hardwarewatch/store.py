# -*- coding: utf-8 -*-
"""SQLite event journal with dedupe and burst coalescing."""
from __future__ import annotations

import datetime
import json
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    ts_text TEXT NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    instance_id TEXT DEFAULT '',
    name TEXT DEFAULT '',
    class_name TEXT DEFAULT '',
    driver TEXT DEFAULT '',
    driver_version TEXT DEFAULT '',
    vid TEXT DEFAULT '',
    pid TEXT DEFAULT '',
    serial TEXT DEFAULT '',
    detail TEXT DEFAULT '{}',
    clues TEXT DEFAULT '[]',
    severity INTEGER DEFAULT 0,
    merged_count INTEGER DEFAULT 1,
    note TEXT DEFAULT '',
    ext_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_inst ON events(instance_id, ts);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_ext ON events(ext_key) WHERE ext_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

MERGEABLE = {
    "arrival", "removal", "device_config", "device_problem",
    "driver_install", "driver_service", "driver_change",
}
PAIR_OK = {"arrival", "device_config", "driver_change"}

COLUMNS = [
    "ts", "ts_text", "kind", "source", "instance_id", "name", "class_name",
    "driver", "driver_version", "vid", "pid", "serial", "detail", "clues",
    "severity", "merged_count", "note", "ext_key",
]


def ts_text(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path):
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.commit()
            self._migrate()

    def _migrate(self):
        """Reclassify historical rows that were stored before a rule change."""
        with self._lock:
            self.conn.execute(
                "UPDATE events SET kind='device_phantom', severity=0, "
                "note='幽灵设备（非故障）' "
                "WHERE kind='device_problem' AND detail LIKE ?",
                ('%"problem": "0x2d"%',),
            )
            self.conn.commit()

    # -- meta --------------------------------------------------------------
    def get_meta(self, key, default=None):
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_meta(self, key, value):
        with self._lock:
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
            self.conn.commit()

    # -- writes ------------------------------------------------------------
    def insert(self, event, merge_window=3.0):
        """Insert one normalized event; returns (id, merged)."""
        ts = float(event.get("ts") or datetime.datetime.now().timestamp())
        kind = event.get("kind") or "unknown"
        instance = event.get("instance_id") or ""
        detail = event.get("detail") or {}
        clues = event.get("clues") or []
        with self._lock:
            if instance and kind in MERGEABLE:
                row = self.conn.execute(
                    "SELECT * FROM events WHERE instance_id=? AND kind IN (?,?) "
                    "AND ts>=? AND ts<=? ORDER BY id DESC LIMIT 1",
                    (
                        instance, kind, "device_config",
                        ts - merge_window, ts + merge_window,
                    ),
                ).fetchone()
                if row is None:
                    row = self.conn.execute(
                        "SELECT * FROM events WHERE instance_id=? AND kind=? "
                        "AND ts>=? AND ts<=? ORDER BY id DESC LIMIT 1",
                        (instance, kind, ts - merge_window, ts + merge_window),
                    ).fetchone()
                if row is not None and (
                    row["kind"] == kind
                    or (row["kind"] in PAIR_OK and kind in PAIR_OK)
                ):
                    old_detail = {}
                    try:
                        old_detail = json.loads(row["detail"] or "{}")
                    except ValueError:
                        old_detail = {}
                    old_detail.setdefault("merged", []).append(
                        {"kind": kind, "source": event.get("source", "")}
                    )
                    old_clues = []
                    try:
                        old_clues = json.loads(row["clues"] or "[]")
                    except ValueError:
                        old_clues = []
                    self.conn.execute(
                        "UPDATE events SET merged_count=merged_count+1, "
                        "detail=?, clues=?, driver=CASE WHEN driver='' THEN ? ELSE driver END, "
                        "driver_version=CASE WHEN driver_version='' THEN ? ELSE driver_version END, "
                        "severity=MAX(severity, ?) WHERE id=?",
                        (
                            json.dumps(old_detail, ensure_ascii=False),
                            json.dumps(old_clues + clues, ensure_ascii=False),
                            event.get("driver", ""),
                            event.get("driver_version", ""),
                            int(event.get("severity") or 0),
                            row["id"],
                        ),
                    )
                    self.conn.commit()
                    return int(row["id"]), True

            values = {
                "ts": ts,
                "ts_text": ts_text(ts),
                "kind": kind,
                "source": event.get("source", ""),
                "instance_id": instance,
                "name": event.get("name", ""),
                "class_name": event.get("class_name", ""),
                "driver": event.get("driver", ""),
                "driver_version": event.get("driver_version", ""),
                "vid": event.get("vid", ""),
                "pid": event.get("pid", ""),
                "serial": event.get("serial", ""),
                "detail": json.dumps(detail, ensure_ascii=False),
                "clues": json.dumps(clues, ensure_ascii=False),
                "severity": int(event.get("severity") or 0),
                "merged_count": 1,
                "note": event.get("note", ""),
                "ext_key": event.get("ext_key"),
            }
            placeholders = ",".join("?" for _ in COLUMNS)
            try:
                cur = self.conn.execute(
                    "INSERT INTO events (%s) VALUES (%s)"
                    % (",".join(COLUMNS), placeholders),
                    [values[c] for c in COLUMNS],
                )
                self.conn.commit()
                return int(cur.lastrowid), False
            except sqlite3.IntegrityError:
                row = self.conn.execute(
                    "SELECT id FROM events WHERE ext_key=?",
                    (values["ext_key"],),
                ).fetchone()
                return (int(row["id"]) if row else 0), True

    def add_note(self, event_id, note):
        with self._lock:
            self.conn.execute(
                "UPDATE events SET note=note || ? WHERE id=?",
                (("; " if note else "") + note, event_id),
            )
            self.conn.commit()

    # -- reads -------------------------------------------------------------
    def after(self, last_id, limit=400):
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE id>? ORDER BY id ASC LIMIT ?",
                (last_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def query(self, text="", kind="", since=0.0, only_problem=False,
              limit=3000, ascending=False):
        sql = "SELECT * FROM events WHERE ts>=?"
        args = [float(since)]
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        if only_problem:
            sql += " AND severity>=2"
        if text:
            like = "%" + text + "%"
            sql += (
                " AND (name LIKE ? OR instance_id LIKE ? OR driver LIKE ? "
                "OR note LIKE ? OR clues LIKE ?)"
            )
            args.extend([like, like, like, like, like])
        sql += " ORDER BY ts " + ("ASC" if ascending else "DESC") + " LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def get(self, event_id):
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM events WHERE id=?", (event_id,)
            ).fetchone()
        return dict(row) if row else None

    def stats(self):
        with self._lock:
            total = self.conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
            today = datetime.datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            ).timestamp()
            today_count = self.conn.execute(
                "SELECT COUNT(*) c FROM events WHERE ts>=?", (today,)
            ).fetchone()["c"]
            last = self.conn.execute(
                "SELECT ts FROM events ORDER BY ts DESC LIMIT 1"
            ).fetchone()
        return {
            "total": int(total),
            "today": int(today_count),
            "last_ts": float(last["ts"]) if last else 0.0,
        }

    def flapping(self, window=900, min_events=5):
        since = datetime.datetime.now().timestamp() - window
        with self._lock:
            rows = self.conn.execute(
                "SELECT instance_id, name, COUNT(*) c, SUM(merged_count) m, "
                "MIN(ts) a, MAX(ts) b FROM events WHERE ts>=? AND kind IN "
                "('arrival','removal','device_config') AND instance_id<>'' "
                "GROUP BY instance_id HAVING c>=? ORDER BY c DESC LIMIT 20",
                (since, min_events),
            ).fetchall()
        return [dict(r) for r in rows]

    def since(self, seconds):
        cutoff = datetime.datetime.now().timestamp() - seconds
        return self.query(since=cutoff, limit=5000, ascending=True)

    def export_rows(self, since=0.0):
        return self.query(since=since, limit=100000)

    def close(self):
        with self._lock:
            try:
                self.conn.close()
            except Exception:
                pass
