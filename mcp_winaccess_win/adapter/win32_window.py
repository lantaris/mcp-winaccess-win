"""Windows window management via ctypes (no pywin32)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

GW_OWNER = 4
SW_MAXIMIZE = 3
SW_MINIMIZE = 6
SW_RESTORE = 9
WM_CLOSE = 0x0010
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
EM_GETSEL = 0x00B0
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]


def window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def process_id(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def process_exe_name(pid: int) -> str:
    if not pid:
        return ""
    import os

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(260)
        buffer = ctypes.create_unicode_buffer(260)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return os.path.basename(buffer.value)
    finally:
        kernel32.CloseHandle(handle)
    return ""


def owner(hwnd: int) -> int:
    return user32.GetWindow(hwnd, GW_OWNER) or 0


def foreground_window() -> int:
    return user32.GetForegroundWindow() or 0


def is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(hwnd))


def is_visible(hwnd: int) -> bool:
    return bool(user32.IsWindowVisible(hwnd))


def is_maximized(hwnd: int) -> bool:
    return bool(user32.IsZoomed(hwnd))


user32.IsHungAppWindow.argtypes = [wintypes.HWND]
user32.IsHungAppWindow.restype = wintypes.BOOL


def is_hung(hwnd: int) -> bool:
    return bool(user32.IsHungAppWindow(hwnd))


def enum_windows() -> list[dict]:
    results: list[dict] = []

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        try:
            left, top, right, bottom = window_rect(hwnd)
            results.append(
                {
                    "handle": hwnd,
                    "title": window_text(hwnd),
                    "class": class_name(hwnd),
                    "rect": (left, top, right, bottom),
                    "pid": process_id(hwnd),
                }
            )
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(WNDENUMPROC(callback), 0)
    except Exception:
        return []
    return results


def move_window(hwnd: int, x: int, y: int, width: int, height: int) -> None:
    user32.MoveWindow(hwnd, x, y, width, height, True)


def set_foreground(hwnd: int) -> bool:
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.BringWindowToTop(hwnd)
    if user32.GetForegroundWindow() == hwnd:
        return True
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(hwnd)
    if user32.GetForegroundWindow() == hwnd:
        return True
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    current_thread = kernel32.GetCurrentThreadId()
    foreground = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    attached = []
    for thread in (foreground_thread, target_thread):
        if thread and thread != current_thread and thread not in attached:
            user32.AttachThreadInput(current_thread, thread, True)
            attached.append(thread)
    try:
        user32.SetForegroundWindow(hwnd)
    finally:
        for thread in attached:
            user32.AttachThreadInput(current_thread, thread, False)
    return user32.GetForegroundWindow() == hwnd


def show_window(hwnd: int, command: int) -> None:
    user32.ShowWindow(hwnd, command)


def close_window(hwnd: int) -> None:
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def set_topmost(hwnd: int, enabled: bool) -> None:
    flag = HWND_TOPMOST if enabled else HWND_NOTOPMOST
    user32.SetWindowPos(hwnd, flag, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


user32.SendMessageW.restype = ctypes.c_ssize_t


def get_selection(hwnd: int) -> tuple[int, int]:
    start = wintypes.DWORD()
    end = wintypes.DWORD()
    user32.SendMessageW(hwnd, EM_GETSEL, ctypes.byref(start), ctypes.byref(end))
    return start.value, end.value


def get_text_content(hwnd: int) -> str:
    length = int(user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0))
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.SendMessageW(hwnd, WM_GETTEXT, length + 1, buffer)
    return buffer.value
