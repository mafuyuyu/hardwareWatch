# -*- coding: utf-8 -*-
"""Paths and persisted settings."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "hardwareWatch"
VERSION = "0.1.0"

DEFAULTS = {
    "notify_arrival": True,
    "notify_removal": True,
    "notify_driver": True,
    "notify_problem": True,
    "notify_sound": False,
    "notify_bursts": True,
    "poll_seconds": 3.0,
    "retention_days": 0,
    "start_minimized": False,
    "backfill_days": 7,
    "deep_audit": False,
    "hotkey": "Ctrl+Alt+M",
}


def app_root():
    """Directory that holds the launcher / exe (portable data lives beside it)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(*parts):
    """Bundled read-only resources (works both from source and onefile exe)."""
    base = Path(getattr(sys, "_MEIPASS", app_root()))
    return base.joinpath(*parts)


def is_portable():
    if os.environ.get("HWWATCH_PORTABLE") == "1":
        return True
    return (app_root() / "portable.txt").exists()


_MIGRATED = False


def _migrate_legacy():
    """Move data written under the old brand name, once."""
    global _MIGRATED
    if _MIGRATED:
        return
    _MIGRATED = True
    if is_portable():
        return
    base = Path(os.environ.get("LOCALAPPDATA") or str(Path.home()))
    new_dir = base / APP_NAME
    old_dir = base / "HwWatch"
    if not new_dir.exists() and old_dir.exists():
        try:
            os.rename(old_dir, new_dir)
        except OSError:
            return
    for suffix in ("", "-wal", "-shm"):
        old_db = new_dir / ("hwwatch.db" + suffix)
        new_db = new_dir / ("hardwarewatch.db" + suffix)
        if old_db.exists() and not new_db.exists():
            try:
                os.rename(old_db, new_db)
            except OSError:
                pass


def data_dir():
    if is_portable():
        path = app_root() / "data"
    else:
        _migrate_legacy()
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir():
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_dir():
    path = data_dir() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path():
    return data_dir() / "hardwarewatch.db"


def settings_path():
    return data_dir() / "settings.json"


def load_settings():
    data = dict(DEFAULTS)
    try:
        with open(settings_path(), "r", encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            data.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return data


def save_settings(settings):
    clean = {k: settings.get(k, v) for k, v in DEFAULTS.items()}
    try:
        with open(settings_path(), "w", encoding="utf-8") as fh:
            json.dump(clean, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass
