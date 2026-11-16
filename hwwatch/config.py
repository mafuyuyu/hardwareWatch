# -*- coding: utf-8 -*-
"""Paths and persisted settings."""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "HwWatch"
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
    return Path(__file__).resolve().parent.parent


def is_portable():
    if os.environ.get("HWWATCH_PORTABLE") == "1":
        return True
    return (app_root() / "portable.txt").exists()


def data_dir():
    if is_portable():
        path = app_root() / "data"
    else:
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
    return data_dir() / "hwwatch.db"


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
