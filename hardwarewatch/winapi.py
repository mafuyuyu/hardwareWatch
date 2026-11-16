# -*- coding: utf-8 -*-
"""Thin ctypes layer over the Win32 pieces this tool needs.

No third-party dependencies: ctypes + stdlib only.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import threading

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
shlwapi = ctypes.WinDLL("shlwapi", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

# ---- window messages -------------------------------------------------------
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_APP = 0x8000
WM_APP_SHOW = WM_APP + 1
WM_APP_NOTIFY = WM_APP + 2
WM_APP_REFRESH = WM_APP + 3
WM_HOTKEY = 0x0312
WM_DEVICECHANGE = 0x0219
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B

DBT_DEVNODES_CHANGED = 0x0007
DBT_DEVICEARRIVAL = 0x8000
DBT_DEVICEREMOVECOMPLETE = 0x8004
DBT_DEVTYP_VOLUME = 0x0002

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_M = 0x4D

NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIM_SETVERSION = 4
NOTIFYICON_VERSION_4 = 4

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010
NIF_SHOWTIP = 0x00000080

NIIF_INFO = 0x00000001
NIIF_NOSOUND = 0x00000010
NIIF_RESPECT_QUIET_TIME = 0x00000080

TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_GRAYED = 0x00000001
MF_CHECKED = 0x00000008

IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wt.DWORD),
        ("Data2", wt.WORD),
        ("Data3", wt.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __str__(self) -> str:
        d4 = "".join("%02x" % b for b in self.Data4)
        return "{%08x-%04x-%04x-%s-%s}" % (
            self.Data1, self.Data2, self.Data3, d4[:4], d4[4:]
        )


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HICON),
        ("szTip", wt.WCHAR * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", wt.WCHAR * 256),
        ("uTimeoutOrVersion", wt.UINT),
        ("szInfoTitle", wt.WCHAR * 64),
        ("dwInfoFlags", wt.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wt.HICON),
    ]


class DEV_BROADCAST_HDR(ctypes.Structure):
    _fields_ = [
        ("dbch_size", wt.DWORD),
        ("dbch_devicetype", wt.DWORD),
        ("dbch_reserved", wt.DWORD),
    ]


class DEV_BROADCAST_VOLUME(ctypes.Structure):
    _fields_ = [
        ("dbcv_size", wt.DWORD),
        ("dbcv_devicetype", wt.DWORD),
        ("dbcv_reserved", wt.DWORD),
        ("dbcv_unitmask", wt.DWORD),
        ("dbcv_flags", wt.WORD),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


# ---- function signatures ---------------------------------------------------
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wt.ATOM
user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p,
]
user32.CreateWindowExW.restype = wt.HWND
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.DestroyWindow.argtypes = [wt.HWND]
user32.DestroyWindow.restype = wt.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.GetMessageW.restype = wt.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL
user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.SendMessageW.restype = LRESULT
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetForegroundWindow.restype = wt.BOOL
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
user32.RegisterHotKey.restype = wt.BOOL
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wt.BOOL
user32.CreatePopupMenu.restype = wt.HMENU
user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.AppendMenuW.restype = wt.BOOL
user32.TrackPopupMenu.argtypes = [
    wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, ctypes.c_void_p
]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.DestroyMenu.argtypes = [wt.HMENU]
user32.DestroyMenu.restype = wt.BOOL
user32.LoadImageW.argtypes = [
    wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT
]
user32.LoadImageW.restype = wt.HANDLE
user32.LoadIconW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
user32.LoadIconW.restype = wt.HICON
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowW.restype = wt.HWND
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.ShowWindow.restype = wt.BOOL
user32.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
user32.MessageBoxW.restype = ctypes.c_int

shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wt.BOOL
shell32.IsUserAnAdmin.argtypes = []
shell32.IsUserAnAdmin.restype = wt.BOOL

kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HINSTANCE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.GetLastError.restype = wt.DWORD
kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wt.BOOL
kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wt.BOOL
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL

shlwapi.SHLoadIndirectString.argtypes = [
    wt.LPCWSTR, wt.LPWSTR, wt.UINT, ctypes.c_void_p
]
shlwapi.SHLoadIndirectString.restype = ctypes.c_long


def is_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def get_module_handle():
    return kernel32.GetModuleHandleW(None)


def last_error() -> int:
    return ctypes.get_last_error()


def err_text(code: int) -> str:
    try:
        return ctypes.FormatError(code).strip()
    except Exception:
        return "error %s" % code


def load_string(desc: str) -> str:
    """Resolve an INF/resource string such as '@usbhub3.inf,%x%;USB Hub'."""
    if not desc:
        return ""
    if desc.startswith("@"):
        buf = ctypes.create_unicode_buffer(1024)
        try:
            if shlwapi.SHLoadIndirectString(desc, buf, 1024, None) == 0 and buf.value:
                return buf.value.strip()
        except Exception:
            pass
        if ";" in desc:
            return desc.rsplit(";", 1)[1].strip()
    return desc.strip()


kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)
]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
kernel32.LoadLibraryW.argtypes = [wt.LPCWSTR]
kernel32.LoadLibraryW.restype = wt.HMODULE
kernel32.FormatMessageW.argtypes = [
    wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.LPWSTR, wt.DWORD, ctypes.c_void_p
]
kernel32.FormatMessageW.restype = wt.DWORD


def process_name(pid):
    """Return the executable file name for a pid, or an empty string."""
    if not pid:
        return ""
    handle = kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(handle)
    return ""


def ntstatus_text(code):
    """Best-effort NTSTATUS text via ntdll message table."""
    try:
        module = kernel32.LoadLibraryW("ntdll.dll")
        if not module:
            return "0x%08X" % code
        buf = ctypes.create_unicode_buffer(1024)
        flags = 0x00000800 | 0x00000200 | 0x00001000  # FROM_HMODULE|IGNORE_INSERTS|FROM_SYSTEM
        length = kernel32.FormatMessageW(
            flags, module, int(code), 0, buf, 1024, None
        )
        if length:
            return buf.value.strip()
    except Exception:
        pass
    return "0x%08X" % code


def list_processes():
    """Return {pid: exe_name} for the current process table."""
    out = {}
    snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value:
        return out
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out[int(entry.th32ProcessID)] = entry.szExeFile
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return out


class MessageWindow(threading.Thread):
    """Hidden top-level window hosting device broadcasts, hotkey and tray icon.

    Runs its own Win32 message loop on a dedicated thread; every callback is
    delivered through dispatch() so the caller decides which thread does work.
    """

    CLASS_NAME = "hardwareWatchMessageWindow"

    def __init__(self, dispatch, log=None):
        super().__init__(name="hwwatch-msgwnd", daemon=True)
        self._dispatch = dispatch
        self._log = log or (lambda *a, **k: None)
        self._hwnd = None
        self._ready = threading.Event()
        self._proc = WNDPROC(self._wndproc)
        self._icon = None

    # -- lifecycle ---------------------------------------------------------
    def run(self):
        try:
            self._create()
            self._tray_add(self._icon_path, "hardwareWatch 硬件监控")
            self._ready.set()
            self._loop()
        except Exception as exc:  # pragma: no cover - defensive
            self._log("message window failed: %r" % (exc,))
            self._ready.set()
        finally:
            self._cleanup()

    _icon_path = ""

    def start_tray(self, icon_path=""):
        self._icon_path = icon_path

    @property
    def hwnd(self):
        self._ready.wait(5)
        return self._hwnd

    def _create(self):
        hinst = get_module_handle()
        wc = WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = self._proc
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinst
        wc.hIcon = None
        wc.hCursor = None
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = self.CLASS_NAME
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom and last_error() != 1410:  # ERROR_CLASS_ALREADY_EXISTS
            raise OSError("RegisterClassW failed: " + err_text(last_error()))
        hwnd = user32.CreateWindowExW(
            0, self.CLASS_NAME, "hardwareWatch", 0, 0, 0, 0, 0, None, None, hinst, None
        )
        if not hwnd:
            raise OSError("CreateWindowExW failed: " + err_text(last_error()))
        self._hwnd = hwnd
        user32.RegisterHotKey(hwnd, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_M)

    def _loop(self):
        msg = wt.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _cleanup(self):
        if self._hwnd:
            try:
                self._tray_remove()
            except Exception:
                pass
            try:
                user32.UnregisterHotKey(self._hwnd, 1)
            except Exception:
                pass
            user32.DestroyWindow(self._hwnd)
        self._hwnd = None

    def stop(self):
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)

    # -- tray --------------------------------------------------------------
    def _nid(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        return nid

    def _tray_add(self, icon_path, tip):
        hicon = None
        if icon_path and os.path.exists(icon_path):
            hicon = user32.LoadImageW(
                None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
            )
        if not hicon:
            hicon = user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
        self._icon = hicon
        nid = self._nid()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        nid.uCallbackMessage = WM_APP + 10
        nid.hIcon = hicon
        nid.szTip = (tip or "hardwareWatch")[:127]
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            raise OSError("Shell_NotifyIcon failed: " + err_text(last_error()))
        nid.uTimeoutOrVersion = NOTIFYICON_VERSION_4
        shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))

    def _tray_remove(self):
        if self._hwnd:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid()))

    def notify(self, title, text, sound=False):
        if not self._hwnd:
            return
        nid = self._nid()
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = (title or "")[:63]
        nid.szInfo = (text or "")[:255]
        nid.uTimeoutOrVersion = 6000
        flags = NIIF_INFO | NIIF_RESPECT_QUIET_TIME
        if not sound:
            flags |= NIIF_NOSOUND
        nid.dwInfoFlags = flags
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def show_menu(self, items):
        """items: list of (id, text, enabled) or (None, separator, None)."""
        menu = user32.CreatePopupMenu()
        if not menu:
            return 0
        try:
            for item_id, text, enabled in items:
                if item_id is None:
                    user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                    continue
                flags = MF_STRING | (0 if enabled else MF_GRAYED)
                user32.AppendMenuW(menu, flags, item_id, text)
            pt = wt.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            user32.SetForegroundWindow(self._hwnd)
            cmd = user32.TrackPopupMenu(
                menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                pt.x, pt.y, 0, self._hwnd, None,
            )
            user32.PostMessageW(self._hwnd, 0, 0, 0)
            return int(cmd)
        finally:
            user32.DestroyMenu(menu)

    def set_tip(self, tip):
        if not self._hwnd:
            return
        nid = self._nid()
        nid.uFlags = NIF_TIP | NIF_SHOWTIP
        nid.szTip = (tip or "")[:127]
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    # -- window proc -------------------------------------------------------
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_DEVICECHANGE:
                if wparam == DBT_DEVNODES_CHANGED:
                    self._dispatch(("nodes_changed",))
                elif wparam in (DBT_DEVICEARRIVAL, DBT_DEVICEREMOVECOMPLETE) and lparam:
                    kind = "arrival" if wparam == DBT_DEVICEARRIVAL else "removal"
                    self._dispatch(("volume", kind, self._volume_letters(lparam)))
                return 1
            if msg == WM_HOTKEY:
                self._dispatch(("hotkey",))
                return 0
            if msg == WM_APP + 10:  # tray callback
                event = lparam & 0xFFFF
                if event == WM_LBUTTONUP:
                    self._dispatch(("tray_left",))
                elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._dispatch(("tray_right",))
                return 0
            if msg == WM_COMMAND:
                self._dispatch(("menu", int(wparam) & 0xFFFF))
                return 0
            if msg == WM_APP_SHOW:
                self._dispatch(("show",))
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                user32.PostQuitMessage(0)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception as exc:  # pragma: no cover - defensive
            self._log("wndproc error: %r" % (exc,))
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    @staticmethod
    def _volume_letters(lparam):
        hdr = ctypes.cast(lparam, ctypes.POINTER(DEV_BROADCAST_HDR)).contents
        if hdr.dbch_devicetype != DBT_DEVTYP_VOLUME:
            return []
        vol = ctypes.cast(lparam, ctypes.POINTER(DEV_BROADCAST_VOLUME)).contents
        letters = []
        mask = int(vol.dbcv_unitmask)
        for i in range(26):
            if mask & (1 << i):
                letters.append(chr(ord("A") + i) + ":")
        return letters
