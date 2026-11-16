# -*- coding: utf-8 -*-
"""Deep attribution via Windows process-creation auditing (Security 4688).

Windows does not record which process drives a PnP/driver installation. The
reliable detector is the Security log: with "Audit Process Creation" enabled
every process start is logged with its command line, so we can correlate the
installer (pnputil, Device Manager, an app calling SetupAPI...) to the device
event seconds later.

This module only changes the *audit policy*, never file/registry ACLs, and it
keeps a full auditpol backup so the previous policy can be restored.
"""
from __future__ import annotations

import ctypes
import json
import subprocess
import threading
import time

from . import config, evtlog, winapi

# Locale-independent GUID for the "Process Creation" audit subcategory.
PROCESS_CREATION_GUID = "{0CCE922B-69AE-11D9-BED3-505054503030}"
POLICY_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit"
POLICY_VALUE = "ProcessCreationIncludeCmdLine_Enabled"

INSTALLER_IMAGES = {
    "pnputil.exe", "devcon.exe", "drvinst.exe", "rundll32.exe", "mmc.exe",
    "devmgmt.msc", "trustedinstaller.exe", "tiworker.exe", "usoclient.exe",
    "setup.exe", "install.exe", "dpinst.exe", "dpinst64.exe",
}

HINT_WORDS = (
    "add-driver", "delete-driver", "pnputil", "devcon", "setupapi",
    ".inf", "difx", "dpinst",
)


def _run(args, timeout=30):
    try:
        result = subprocess.run(
            args, capture_output=True, timeout=timeout,
            encoding="mbcs", errors="replace",
        )
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except Exception as exc:  # pragma: no cover - defensive
        return -1, repr(exc)


def parse_4688(row):
    """Normalize one Security 4688 record."""
    data = row.get("data") or {}
    raw_pid = str(data.get("NewProcessId") or "0").strip()
    try:
        pid = int(raw_pid, 16) if raw_pid.lower().startswith("0x") else int(raw_pid)
    except ValueError:
        pid = 0
    return {
        "ts": float(row.get("ts") or 0),
        "pid": pid,
        "image": (data.get("NewProcessName") or "").strip(),
        "cmdline": (data.get("CommandLine") or "").strip(),
        "parent": (data.get("ParentProcessName") or "").strip(),
        "user": (data.get("SubjectUserName") or "").strip(),
        "record_id": int(row.get("record_id") or 0),
    }


class ProcessAudit:
    def __init__(self, store, log=None):
        self.store = store
        self._log = log or (lambda *a, **k: None)
        self.active = False
        self._events = []
        self._lock = threading.Lock()
        self._last_record = 0
        self._backup_path = config.data_dir() / "auditpol_backup.csv"

    # -- state -------------------------------------------------------------
    def status(self):
        return {
            "admin": winapi.is_admin(),
            "active": self.active,
            "wanted": self.store.get_meta("deep_audit", "0") == "1",
        }

    def _save_reg_state(self):
        import winreg

        state = {"exists": False, "value": 0}
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, POLICY_KEY, 0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as key:
                try:
                    state["value"] = int(
                        winreg.QueryValueEx(key, POLICY_VALUE)[0]
                    )
                    state["exists"] = True
                except OSError:
                    pass
        except OSError:
            pass
        self.store.set_meta("deep_audit_reg_backup", json.dumps(state))
        return state

    def _set_cmdline_policy(self, enabled):
        import winreg

        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_LOCAL_MACHINE, POLICY_KEY, 0,
                winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
            ) as key:
                if enabled:
                    winreg.SetValueEx(key, POLICY_VALUE, 0, winreg.REG_DWORD, 1)
                else:
                    try:
                        winreg.DeleteValue(key, POLICY_VALUE)
                    except OSError:
                        pass
        except OSError as exc:
            self._log("cmdline policy change failed: %r" % (exc,))

    def _restore_cmdline_policy(self):
        try:
            raw = self.store.get_meta("deep_audit_reg_backup", "")
            state = json.loads(raw) if raw else {}
        except ValueError:
            state = {}
        if state.get("exists"):
            import winreg

            try:
                with winreg.CreateKeyEx(
                    winreg.HKEY_LOCAL_MACHINE, POLICY_KEY, 0,
                    winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
                ) as key:
                    winreg.SetValueEx(
                        key, POLICY_VALUE, 0, winreg.REG_DWORD,
                        int(state.get("value", 1)),
                    )
            except OSError:
                pass
        else:
            self._set_cmdline_policy(False)

    # -- enable / disable --------------------------------------------------
    def enable(self):
        if self.active:
            return True
        if not winapi.is_admin():
            raise PermissionError("深度归因需要以管理员身份运行")
        self._save_reg_state()
        code, output = _run([
            "auditpol", "/backup", "/file:%s" % self._backup_path,
        ])
        if code != 0:
            self._log("auditpol backup failed: " + output[:300])
        code, output = _run([
            "auditpol", "/set",
            "/subcategory:%s" % PROCESS_CREATION_GUID,
            "/success:enable",
        ])
        if code != 0:
            raise RuntimeError("开启进程审计失败: " + output.strip()[:300])
        self._set_cmdline_policy(True)
        self.store.set_meta("deep_audit", "1")
        self.active = True
        self._last_record = 0
        self._log("deep audit enabled")
        return True

    def disable(self):
        if not winapi.is_admin():
            return False
        code, output = _run([
            "auditpol", "/set",
            "/subcategory:%s" % PROCESS_CREATION_GUID,
            "/success:disable",
        ])
        backup = str(self._backup_path)
        if self._backup_path.exists():
            code2, output2 = _run(["auditpol", "/restore", "/file:%s" % backup])
            if code2 != 0:
                self._log("auditpol restore failed: " + output2[:300])
        self._restore_cmdline_policy()
        self.store.set_meta("deep_audit", "0")
        self.active = False
        self._log("deep audit disabled: " + output.strip()[:200])
        return True

    # -- capture -----------------------------------------------------------
    def poll(self):
        if not self.active:
            return
        try:
            rows = evtlog.read_recent("Security", (4688,), seconds=120, max_events=300)
        except Exception as exc:
            self._log("security log read failed: %r" % (exc,))
            return
        fresh = []
        for row in rows:
            rid = int(row.get("record_id") or 0)
            if rid and rid <= self._last_record:
                continue
            if rid:
                self._last_record = max(self._last_record, rid)
            fresh.append(parse_4688(row))
        if not fresh:
            return
        now = time.time()
        with self._lock:
            self._events.extend(fresh)
            self._events = [
                e for e in self._events if now - e["ts"] <= 3600
            ][-800:]

    # -- attribution -------------------------------------------------------
    def clues(self, instance, ts, window=20.0):
        if not self.active:
            return []
        with self._lock:
            candidates = [
                e for e in self._events if abs(e["ts"] - ts) <= window
            ]
        if not candidates:
            return []
        best = None
        best_score = 0
        for entry in candidates:
            image = entry["image"].lower()
            cmd = entry["cmdline"].lower()
            score = 0
            if instance and instance.lower() in cmd:
                score += 4
            if any(word in cmd for word in HINT_WORDS):
                score += 3
            if image in INSTALLER_IMAGES:
                score += 2
            if score > best_score:
                best, best_score = entry, score
        if best is None:
            return []
        delta = best["ts"] - ts
        command = best["cmdline"] or best["image"]
        if len(command) > 150:
            command = command[:147] + "..."
        confidence = "high" if best_score >= 3 else ("medium" if best_score >= 1 else "low")
        return [{
            "type": "deep_process",
            "text": "审计捕获进程: %s (%+ds) · %s" % (
                best["image"] or "?", int(delta), command
            ),
            "confidence": confidence,
        }]
