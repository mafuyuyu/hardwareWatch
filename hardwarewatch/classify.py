# -*- coding: utf-8 -*-
"""Normalize raw event-log records into the journal event schema."""
from __future__ import annotations

import datetime

KIND_LABELS = {
    "arrival": "硬件接入",
    "removal": "硬件移除",
    "device_config": "设备配置",
    "device_start": "设备启动",
    "device_problem": "设备异常",
    "device_migrate": "设备迁移",
    "device_phantom": "幽灵设备清理",
    "device_pnp": "PnP 事件",
    "driver_install": "驱动安装",
    "driver_service": "驱动服务",
    "driver_change": "驱动变更",
    "driver_remove": "驱动卸载",
    "driver_error": "驱动加载失败",
    "windows_update": "Windows 更新",
    "system_sleep": "系统睡眠",
    "system_wake": "系统唤醒",
    "marker": "声音标记",
    "alert": "疑似异常",
    "system": "系统",
    "unknown": "未知",
}

KIND_ORDER = list(KIND_LABELS.keys())


def label(kind):
    return KIND_LABELS.get(kind, kind)


PREFIX_NAMES = {
    "VHF": "VHF 虚拟设备",
    "SWD": "软件设备",
    "ROOT": "根设备",
    "BTH": "蓝牙设备",
    "BTHENUM": "蓝牙设备",
    "BTHLEDEVICE": "蓝牙设备",
    "HID": "HID 设备",
    "USB": "USB 设备",
    "PCI": "PCI 设备",
    "ACPI": "ACPI 设备",
    "DISPLAY": "显示设备",
    "STORAGE": "存储设备",
}


def generic_name(instance):
    head = (instance or "").split("\\")[0].upper()
    return PREFIX_NAMES.get(head, "未知设备")


def _pick(data, *names):
    for name in names:
        value = data.get(name)
        if value:
            return value
    return ""


def _hex(value):
    try:
        number = int(value)
        return "0x%08X" % number
    except (TypeError, ValueError):
        return str(value or "")


def from_eventlog(row):
    channel = row.get("channel", "")
    event_id = int(row.get("event_id") or 0)
    data = row.get("data") or {}
    instance = _pick(data, "DeviceInstanceID", "DeviceInstanceId", "DeviceInstanceId ")
    detail = {"channel": channel, "event_id": event_id, "data": data}
    if row.get("pid"):
        detail["execution_pid"] = int(row["pid"])
    kind = "device_pnp"
    severity = 0
    driver = ""
    version = ""
    name = ""

    if channel.endswith("Kernel-PnP/Configuration"):
        if event_id in (400, 410):
            kind = "device_config"
            driver = _pick(data, "DriverName")
            version = _pick(data, "DriverVersion")
            detail["driver_package"] = _pick(data, "DriverPackageId")
            detail["driver_provider"] = _pick(data, "DriverProvider")
            detail["driver_date"] = _pick(data, "DriverDate")
            detail["updated"] = _pick(data, "DeviceUpdated")
            detail["problem"] = _pick(data, "Problem")
            if _pick(data, "Problem") not in ("", "0x0", "0"):
                kind = "device_problem"
                severity = 2
        elif event_id == 420:
            problem = str(_pick(data, "Problem")).lower()
            detail["problem"] = problem
            if problem in ("0x2d", "45"):
                kind = "device_phantom"
                severity = 0
                detail["note"] = "幽灵设备记录清理（设备已移除，不是故障）"
            else:
                kind = "device_problem"
                severity = 2
        elif event_id == 442:
            kind = "device_migrate"
            severity = 1
        else:
            kind = "device_pnp"
    elif channel == "System" and row.get("provider", "").endswith("Kernel-Power"):
        kind = "system_sleep" if event_id == 42 else "system_wake"
        name = "系统睡眠" if event_id == 42 else "系统唤醒"
        detail["power"] = True
    elif channel == "System" and "Power-Troubleshooter" in row.get("provider", ""):
        kind = "system_wake"
        name = "系统唤醒"
        detail["power"] = True
    elif channel == "System":
        if event_id == 219:
            kind = "driver_error"
            severity = 3
            name = _pick(data, "DriverName")
            detail["failure"] = _pick(data, "FailureName")
            detail["status"] = _hex(_pick(data, "Status"))
            instance = ""
        elif event_id == 20003:
            kind = "driver_service"
            severity = 1
            driver = _pick(data, "DriverFileName")
            name = _pick(data, "ServiceName")
        elif event_id == 20001:
            kind = "driver_install"
            severity = 1
            driver = _pick(data, "DriverName", "DriverFileName")
            version = _pick(data, "DriverVersion")
        elif event_id == 20004:
            kind = "driver_remove"
            severity = 1
            driver = _pick(data, "DriverName", "DriverFileName")
    elif "WindowsUpdateClient" in channel:
        kind = "windows_update"
        severity = 1 if event_id in (19, 20) else 2
        detail["update_id"] = _pick(data, "updateId", "UpdateID")
    elif "UserPnp" in channel:
        kind = "driver_install"
        severity = 1

    ts = float(row.get("ts") or 0)
    record_id = int(row.get("record_id") or 0)
    return {
        "ts": ts,
        "kind": kind,
        "source": channel or "eventlog",
        "instance_id": instance,
        "name": name,
        "class_name": "",
        "driver": driver,
        "driver_version": version,
        "vid": "",
        "pid": "",
        "serial": "",
        "detail": detail,
        "clues": [],
        "severity": severity,
        "ext_key": "%s:%d" % (channel, record_id) if record_id else None,
        "record_id": record_id,
        "event_id": event_id,
    }


def from_snapshot(ev):
    """Add text fields to a pnp.Snapshot event."""
    out = dict(ev)
    out.setdefault("ts", datetime.datetime.now().timestamp())
    out.setdefault("source", "device-tree")
    out.setdefault("driver_version", "")
    out.setdefault("severity", 0)
    return out
