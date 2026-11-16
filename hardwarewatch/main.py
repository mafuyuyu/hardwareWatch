# -*- coding: utf-8 -*-
"""Process entry point: single instance, logging, app bootstrap."""
from __future__ import annotations

import ctypes
import logging
import logging.handlers
import os
import sys
import tkinter as tk

from . import app as appmod
from . import config, store as storemod, ui, winapi

MUTEX_NAME = "Local\\hardwareWatch_SingleInstance_v1"
_mutex_handle = None


def setup_logging():
    logger = logging.getLogger("hardwarewatch")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    handler = logging.handlers.RotatingFileHandler(
        str(config.log_dir() / "hardwarewatch.log"),
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    return logger


def _acquire_single_instance():
    global _mutex_handle
    _mutex_handle = winapi.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    already = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    return not already


def _focus_existing():
    hwnd = winapi.user32.FindWindowW(winapi.MessageWindow.CLASS_NAME, "hardwareWatch")
    if hwnd:
        winapi.user32.PostMessageW(hwnd, winapi.WM_APP_SHOW, 0, 0)
        return True
    return False


def _set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            winapi.user32.SetProcessDPIAware()
        except Exception:
            pass


def main(argv=None):
    _set_dpi_aware()
    logger = setup_logging()
    if not _acquire_single_instance():
        _focus_existing()
        return 0
    settings = config.load_settings()
    db = storemod.Store(config.db_path())
    application = appmod.App(
        db, settings, on_log=lambda message: logger.info(message)
    )
    icon = str(config.resource_path("assets", "hw.ico"))
    application.start(icon)
    logger.info("data dir %s", config.data_dir())
    root = tk.Tk()
    window = ui.MainWindow(root, application, icon)
    root.after(200, lambda: root.report_callback_exception(
        lambda *a: logger.exception("tk callback failed", exc_info=a[1])
    ))
    if settings.get("start_minimized"):
        root.withdraw()
        window._shown = False
    try:
        root.mainloop()
    finally:
        try:
            application.stop()
        except Exception:
            pass
        db.close()
        logger.info("exit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
