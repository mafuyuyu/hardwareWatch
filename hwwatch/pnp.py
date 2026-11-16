# -*- coding: utf-8 -*-
"""Enumerate present PnP devices and diff snapshots into arrival/removal events."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import re
import time

from . import winapi

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
cfgmgr = ctypes.WinDLL("cfgmgr32", use_last_error=True)

DIGCF_PRESENT = 0x00000002
DIGCF_ALLCLASSES = 0x00000004
CM_GETIDLIST_FILTER_PRESENT = 0x00000002

GUID = winapi.GUID


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("ClassGuid", GUID),
        ("DevInst", wt.DWORD),
        ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
    ]


setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(GUID), wt.LPCWSTR, wt.HWND, wt.DWORD
]
setupapi.SetupDiGetClassDevsW.restype = wt.HANDLE
setupapi.SetupDiEnumDeviceInfo.argtypes = [
    wt.HANDLE, wt.DWORD, ctypes.POINTER(SP_DEVINFO_DATA)
]
setupapi.SetupDiEnumDeviceInfo.restype = wt.BOOL
setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
    wt.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), wt.LPWSTR,
    wt.DWORD, ctypes.POINTER(wt.DWORD),
]
setupapi.SetupDiGetDeviceInstanceIdW.restype = wt.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wt.HANDLE]
setupapi.SetupDiDestroyDeviceInfoList.restype = wt.BOOL

cfgmgr.CM_Get_Parent.argtypes = [
    ctypes.POINTER(wt.DWORD), wt.DWORD, wt.DWORD
]
cfgmgr.CM_Get_Parent.restype = ctypes.c_ulong
cfgmgr.CM_Get_Device_IDW.argtypes = [
    wt.DWORD, wt.LPWSTR, wt.DWORD, wt.DWORD
]
cfgmgr.CM_Get_Device_IDW.restype = ctypes.c_ulong
cfgmgr.CM_Get_DevNode_Status.argtypes = [
    ctypes.POINTER(wt.DWORD), ctypes.POINTER(wt.DWORD), wt.DWORD, wt.DWORD
]
cfgmgr.CM_Get_DevNode_Status.restype = ctypes.c_ulong

PROBLEM_TEXT = {
    0: "正常",
    1: "未配置",
    2: "加载器失败",
    3: "内存不足",
    5: "资源仲裁失败",
    10: "无法启动",
    12: "资源冲突",
    14: "需要重启",
    18: "需要重新安装",
    19: "注册表损坏",
    21: "正在被移除",
    22: "已禁用",
    24: "设备不存在",
    28: "驱动未安装",
    31: "加载驱动失败",
    32: "服务已禁用",
    37: "驱动初始化失败",
    39: "驱动加载失败",
    43: "启动后失败",
    45: "幽灵设备",
    48: "驱动被阻止",
    52: "驱动未签名",
}

VID_RE = re.compile(r"VID_([0-9A-F]{4})", re.I)
PID_RE = re.compile(r"PID_([0-9A-F]{4})", re.I)


def _reg_values(path):
    import winreg

    values = {}
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            "SYSTEM\\CurrentControlSet\\Enum\\" + path,
            0,
            winreg.KEY_READ,
        ) as key:
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                values[name] = value
                index += 1
    except OSError:
        pass
    return values


_CLASS_NAMES = {}


def class_name_for(guid):
    if not guid:
        return ""
    guid = guid.strip()
    if guid in _CLASS_NAMES:
        return _CLASS_NAMES[guid]
    import winreg

    name = ""
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            "SYSTEM\\CurrentControlSet\\Control\\Class\\" + guid,
            0,
            winreg.KEY_READ,
        ) as key:
            name = str(winreg.QueryValueEx(key, "Class")[0])
    except OSError:
        pass
    _CLASS_NAMES[guid] = name
    return name


def parse_ids(instance_id):
    vid = PID_RE  # placeholder to keep linters quiet
    m = VID_RE.search(instance_id or "")
    v = m.group(1).upper() if m else ""
    m = _PID_RE.search(instance_id or "")
    p = m.group(1).upper() if m else ""
    serial = ""
    parts = (instance_id or "").split("\\")
    if len(parts) >= 3:
        serial = parts[-1]
    return v, p, serial


_PID_RE = PID_RE


def describe(instance_id, devinst=0):
    values = _reg_values(instance_id)
    friendly = winapi.load_string(values.get("FriendlyName", ""))
    desc = winapi.load_string(values.get("DeviceDesc", ""))
    name = friendly or desc or instance_id
    class_guid = values.get("ClassGUID", "")
    info = {
        "instance_id": instance_id,
        "name": name,
        "description": desc,
        "class_guid": class_guid,
        "class_name": class_name_for(class_guid) if class_guid else "",
        "driver": values.get("Driver", ""),
        "service": values.get("Service", ""),
        "mfg": winapi.load_string(values.get("Mfg", "")),
        "location": values.get("LocationInformation", ""),
        "vid": "",
        "pid": "",
        "serial": "",
        "problem": 0,
        "problem_text": "",
        "parent": "",
    }
    info["vid"], info["pid"], info["serial"] = parse_ids(instance_id)
    if devinst:
        status = wt.DWORD(0)
        problem = wt.DWORD(0)
        if cfgmgr.CM_Get_DevNode_Status(
            ctypes.byref(status), ctypes.byref(problem), devinst, 0
        ) == 0:
            info["problem"] = int(problem.value)
            info["problem_text"] = PROBLEM_TEXT.get(
                int(problem.value), "问题代码 %d" % int(problem.value)
            )
        parent = wt.DWORD(0)
        if cfgmgr.CM_Get_Parent(ctypes.byref(parent), devinst, 0) == 0:
            buf = ctypes.create_unicode_buffer(1024)
            if cfgmgr.CM_Get_Device_IDW(parent.value, buf, 1024, 0) == 0:
                info["parent"] = buf.value
    return info


def enumerate_present(deep=True):
    """Return {instance_id: info} for every present device."""
    devices = {}
    hdev = setupapi.SetupDiGetClassDevsW(
        None, None, None, DIGCF_PRESENT | DIGCF_ALLCLASSES
    )
    if hdev == wt.HANDLE(-1).value or not hdev:
        return devices
    try:
        index = 0
        while True:
            data = SP_DEVINFO_DATA()
            data.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
            if not setupapi.SetupDiEnumDeviceInfo(hdev, index, ctypes.byref(data)):
                break
            index += 1
            buf = ctypes.create_unicode_buffer(1024)
            need = wt.DWORD(0)
            if not setupapi.SetupDiGetDeviceInstanceIdW(
                hdev, ctypes.byref(data), buf, 1024, ctypes.byref(need)
            ):
                continue
            instance = buf.value
            if deep and instance in _DESCRIBE_CACHE:
                info, ts = _DESCRIBE_CACHE[instance]
                if time.time() - ts < 600:
                    # refresh dynamic problem state cheaply
                    info = dict(info)
                    devices[instance] = info
                    continue
            try:
                info = describe(instance, int(data.DevInst))
            except Exception:
                continue
            _DESCRIBE_CACHE[instance] = (info, time.time())
            devices[instance] = info
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return devices


_DESCRIBE_CACHE = {}


def invalidate(instance_id=None):
    if instance_id is None:
        _DESCRIBE_CACHE.clear()
    else:
        _DESCRIBE_CACHE.pop(instance_id, None)


def get_info(instance_id):
    """Describe a device instance with a short-lived cache."""
    cached = _DESCRIBE_CACHE.get(instance_id)
    if cached and time.time() - cached[1] < 600:
        return dict(cached[0])
    info = describe(instance_id)
    _DESCRIBE_CACHE[instance_id] = (info, time.time())
    return info


class Snapshot:
    """Holds the last device map and produces human diff events."""

    def __init__(self, log=None):
        self.current = {}
        self._first = True
        self.log = log or (lambda *a, **k: None)

    def refresh(self):
        new = enumerate_present()
        old = self.current
        events = []
        if not self._first:
            added = set(new) - set(old)
            removed = set(old) - set(new)
            for instance in sorted(added):
                info = new[instance]
                events.append(
                    {
                        "kind": "arrival",
                        "instance_id": instance,
                        "name": info.get("name") or instance,
                        "class_name": info.get("class_name", ""),
                        "driver": info.get("driver", ""),
                        "vid": info.get("vid", ""),
                        "pid": info.get("pid", ""),
                        "serial": info.get("serial", ""),
                        "detail": {"device": info},
                        "severity": 0 if not info.get("problem") else 2,
                    }
                )
            for instance in sorted(removed):
                info = old[instance]
                events.append(
                    {
                        "kind": "removal",
                        "instance_id": instance,
                        "name": info.get("name") or instance,
                        "class_name": info.get("class_name", ""),
                        "driver": info.get("driver", ""),
                        "vid": info.get("vid", ""),
                        "pid": info.get("pid", ""),
                        "serial": info.get("serial", ""),
                        "detail": {"device": info},
                        "severity": 0,
                    }
                )
            for instance in sorted(set(new) & set(old)):
                before = old[instance].get("driver", "")
                after = new[instance].get("driver", "")
                if before and after and before != after:
                    events.append(
                        {
                            "kind": "driver_change",
                            "instance_id": instance,
                            "name": new[instance].get("name") or instance,
                            "class_name": new[instance].get("class_name", ""),
                            "driver": after,
                            "vid": new[instance].get("vid", ""),
                            "pid": new[instance].get("pid", ""),
                            "serial": new[instance].get("serial", ""),
                            "detail": {"before": before, "after": after},
                            "severity": 1,
                        }
                    )
        self._first = False
        self.current = new
        return events
