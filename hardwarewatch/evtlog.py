# -*- coding: utf-8 -*-
"""Read Windows event channels through wevtapi (no pywin32 needed)."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import datetime
import xml.etree.ElementTree as ET

wevtapi = ctypes.WinDLL("wevtapi", use_last_error=True)

EVT_HANDLE = ctypes.c_void_p
EvtQueryChannelPath = 0x1
EvtQueryFilePath = 0x2
EvtQueryReverseDirection = 0x100
EvtRenderEventXml = 1
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_NO_MORE_ITEMS = 259

wevtapi.EvtQuery.argtypes = [EVT_HANDLE, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD]
wevtapi.EvtQuery.restype = EVT_HANDLE
wevtapi.EvtNext.argtypes = [
    EVT_HANDLE, wt.DWORD, ctypes.POINTER(EVT_HANDLE), wt.DWORD, wt.DWORD,
    ctypes.POINTER(wt.DWORD),
]
wevtapi.EvtNext.restype = wt.BOOL
wevtapi.EvtRender.argtypes = [
    EVT_HANDLE, EVT_HANDLE, wt.DWORD, wt.DWORD, ctypes.c_void_p,
    ctypes.POINTER(wt.DWORD), ctypes.POINTER(wt.DWORD),
]
wevtapi.EvtRender.restype = wt.BOOL
wevtapi.EvtClose.argtypes = [EVT_HANDLE]
wevtapi.EvtClose.restype = wt.BOOL

NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}


def _render_xml(handle):
    used = wt.DWORD(0)
    props = wt.DWORD(0)
    wevtapi.EvtRender(None, handle, EvtRenderEventXml, 0, None,
                      ctypes.byref(used), ctypes.byref(props))
    if used.value <= 0:
        return ""
    chars = used.value // 2 + 1
    buf = ctypes.create_unicode_buffer(chars)
    if not wevtapi.EvtRender(None, handle, EvtRenderEventXml, used.value, buf,
                             ctypes.byref(used), ctypes.byref(props)):
        return ""
    return buf.value


def query_xml(channel, xpath, max_events=2000, newest_first=True):
    flags = EvtQueryChannelPath | (EvtQueryReverseDirection if newest_first else 0)
    handle = wevtapi.EvtQuery(None, channel, xpath, flags)
    if not handle:
        return []
    out = []
    try:
        while len(out) < max_events:
            buf = (EVT_HANDLE * 32)()
            got = wt.DWORD(0)
            ok = wevtapi.EvtNext(handle, 32, buf, 1000, 0, ctypes.byref(got))
            if not ok or got.value == 0:
                break
            for i in range(got.value):
                try:
                    xml = _render_xml(buf[i])
                finally:
                    wevtapi.EvtClose(buf[i])
                if xml:
                    out.append(xml)
    finally:
        wevtapi.EvtClose(handle)
    return out


def _parse_time(text):
    if not text:
        return 0.0
    # 2026-11-16T14:09:55.0203030Z
    body = text.rstrip("Z")
    if "." in body:
        head, frac = body.split(".", 1)
        body = head + "." + frac[:6]
    else:
        body = body
    try:
        dt = datetime.datetime.strptime(body, "%Y-%m-%dT%H:%M:%S.%f")
    except ValueError:
        try:
            dt = datetime.datetime.strptime(body, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return 0.0
    return dt.replace(tzinfo=datetime.timezone.utc).timestamp()


def parse_xml(xml):
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    system = root.find("e:System", NS)
    if system is None:
        return None
    provider = system.find("e:Provider", NS)
    event_id = system.findtext("e:EventID", default="", namespaces=NS)
    record_id = system.findtext("e:EventRecordID", default="", namespaces=NS)
    channel = system.findtext("e:Channel", default="", namespaces=NS)
    computer = system.findtext("e:Computer", default="", namespaces=NS)
    execution = system.find("e:Execution", NS)
    created = system.find("e:TimeCreated", NS)
    ts = _parse_time(created.get("SystemTime", "") if created is not None else "")
    data = {}
    event_data = root.find("e:EventData", NS)
    if event_data is not None:
        for node in event_data.findall("e:Data", NS):
            name = node.get("Name") or ("data%d" % len(data))
            data[name] = (node.text or "").strip()
    user_data = root.find("e:UserData", NS)
    if user_data is not None:
        for child in list(user_data):
            tag = child.tag.split("}")[-1]
            data["UserData_" + tag] = (child.text or "").strip()
            for sub in list(child):
                data[sub.tag.split("}")[-1]] = (sub.text or "").strip()
    return {
        "channel": channel or "",
        "provider": provider.get("Name", "") if provider is not None else "",
        "event_id": int(event_id) if event_id.isdigit() else 0,
        "record_id": int(record_id) if record_id.isdigit() else 0,
        "ts": ts,
        "computer": computer,
        "pid": int(execution.get("ProcessID", 0)) if execution is not None else 0,
        "tid": int(execution.get("ThreadID", 0)) if execution is not None else 0,
        "data": data,
        "xml": xml,
    }


# channel -> (event ids, label)
CHANNELS = {
    "Microsoft-Windows-Kernel-PnP/Configuration": {
        "ids": (400, 410, 420, 430, 441, 442, 443, 444, 445, 446),
        "label": "PnP 配置",
    },
    "Microsoft-Windows-UserPnp/DeviceInstall": {
        "ids": (20001, 20003, 20004, 20005, 20006),
        "label": "驱动安装",
    },
    "Microsoft-Windows-Kernel-PnP/Device Management": {
        "ids": (1000, 1010, 1011, 1012),
        "label": "PnP 管理",
    },
    "Microsoft-Windows-DeviceSetupManager/Admin": {
        "ids": (112, 190, 30, 101, 107),
        "label": "设备安装服务",
    },
    "System": {
        "ids": (219, 20001, 20003),
        "label": "系统",
    },
    "Microsoft-Windows-WindowsUpdateClient/Operational": {
        "ids": (19, 20, 43, 44),
        "label": "Windows 更新",
    },
}


def build_xpath(ids, seconds, provider=None):
    id_part = " or ".join("EventID=%d" % i for i in ids)
    clauses = ["(" + id_part + ")"]
    if provider:
        clauses.append("Provider[@Name='%s']" % provider)
    clauses.append("TimeCreated[timediff(@SystemTime) <= %d]" % int(seconds * 1000))
    return "*[System[" + " and ".join(clauses) + "]]"


def read_recent(channel, ids, seconds=300, max_events=2000, provider=None):
    xpath = build_xpath(ids, seconds, provider)
    rows = []
    for xml in query_xml(channel, xpath, max_events=max_events, newest_first=True):
        parsed = parse_xml(xml)
        if parsed:
            rows.append(parsed)
    rows.sort(key=lambda r: r["ts"])
    return rows
