"""Windows mouse and keyboard input via SendInput (ctypes, no pyautogui)."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
user32.VkKeyScanW.argtypes = [ctypes.c_wchar]
user32.VkKeyScanW.restype = ctypes.c_short

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

ULONG_PTR = wintypes.WPARAM


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


VK = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "win": 0x5B,
    "lwin": 0x5B,
    "super": 0x5B,
    "meta": 0x5B,
    "rwin": 0x5C,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "printscreen": 0x2C,
    "print_screen": 0x2C,
    "volumemute": 0xAD,
    "mute": 0xAD,
    "volumedown": 0xAE,
    "volumeup": 0xAF,
    "nexttrack": 0xB0,
    "prevtrack": 0xB1,
    "stop": 0xB2,
    "playpause": 0xB3,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}
for _i in range(10):
    VK[f"num{_i}"] = 0x60 + _i
    VK[f"numpad{_i}"] = 0x60 + _i

EXTENDED_KEYS = {
    0x21,
    0x22,
    0x23,
    0x24,
    0x25,
    0x26,
    0x27,
    0x28,
    0x2C,
    0x2D,
    0x2E,
    0x5B,
    0x5C,
    0x5D,
    0x6F,
    0x90,
    0xA3,
    0xA5,
}

MODIFIER_VK = {
    "ctrl": 0x11,
    "control": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "win": 0x5B,
    "super": 0x5B,
    "meta": 0x5B,
}


def _set_dpi_aware() -> None:
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


_set_dpi_aware()


def _send(*inputs: INPUT) -> None:
    count = len(inputs)
    array = (INPUT * count)(*inputs)
    user32.SendInput(count, array, ctypes.sizeof(INPUT))


def _mouse_input(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    return INPUT(type=INPUT_MOUSE, union=_INPUTUNION(mi=MOUSEINPUT(dx, dy, data, flags, 0, 0)))


def _key_input(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    if vk in EXTENDED_KEYS:
        flags |= KEYEVENTF_EXTENDEDKEY
    return INPUT(type=INPUT_KEYBOARD, union=_INPUTUNION(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))


def _virtual_screen() -> tuple[int, int, int, int]:
    left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return left, top, width, height


def _normalize(x: int, y: int) -> tuple[int, int]:
    left, top, width, height = _virtual_screen()
    width = max(width - 1, 1)
    height = max(height - 1, 1)
    nx = int(round((x - left) * 65535 / width))
    ny = int(round((y - top) * 65535 / height))
    return max(0, min(65535, nx)), max(0, min(65535, ny))


def get_cursor_position() -> tuple[int, int]:
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def screen_size() -> tuple[int, int]:
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def move_mouse(x: int, y: int) -> None:
    nx, ny = _normalize(x, y)
    _send(_mouse_input(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny))


def move_rel(dx: int, dy: int) -> None:
    _send(_mouse_input(MOUSEEVENTF_MOVE, int(dx), int(dy)))


def _button_flags(button: str) -> tuple[int, int]:
    button = (button or "left").lower()
    if button == "right":
        return MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    if button == "middle":
        return MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
    return MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP


def click(x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    move_mouse(x, y)
    down, up = _button_flags(button)
    for _ in range(max(1, clicks)):
        _send(_mouse_input(down), _mouse_input(up))
        time.sleep(0.02)


def double_click(x: int = 0, y: int = 0) -> None:
    if x == 0 and y == 0:
        x, y = get_cursor_position()
    click(x, y, "left", 2)


def right_click(x: int = 0, y: int = 0) -> None:
    if x == 0 and y == 0:
        x, y = get_cursor_position()
    click(x, y, "right", 1)


def mouse_down(x: int, y: int, button: str = "left") -> None:
    move_mouse(x, y)
    down, _ = _button_flags(button)
    _send(_mouse_input(down))


def mouse_up(button: str = "left") -> None:
    _, up = _button_flags(button)
    _send(_mouse_input(up))


def drag(x_from: int, y_from: int, x_to: int, y_to: int, duration: float = 0.5) -> None:
    move_mouse(x_from, y_from)
    mouse_down(x_from, y_from, "left")
    steps = max(1, int(duration / 0.02))
    for step in range(1, steps + 1):
        x = int(x_from + (x_to - x_from) * step / steps)
        y = int(y_from + (y_to - y_from) * step / steps)
        move_mouse(x, y)
        time.sleep(0.02)
    mouse_up("left")


def scroll(clicks: int, horizontal: bool = False) -> None:
    flag = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
    _send(_mouse_input(flag, data=int(clicks)))


def _vk_for_key(key: str) -> int:
    lowered = (key or "").lower().strip()
    if lowered in VK:
        return VK[lowered]
    if len(key) == 1:
        if "a" <= key.lower() <= "z":
            return 0x41 + (ord(key.lower()) - ord("a"))
        if "0" <= key <= "9":
            return 0x30 + (ord(key) - ord("0"))
        scan = user32.VkKeyScanW(ctypes.c_wchar(key))
        if scan != -1:
            return scan & 0xFF
    return 0


def key_down(key: str) -> None:
    vk = _vk_for_key(key)
    if vk:
        _send(_key_input(vk=vk))


def key_up(key: str) -> None:
    vk = _vk_for_key(key)
    if vk:
        _send(_key_input(vk=vk, flags=KEYEVENTF_KEYUP))


def press_key(key: str) -> bool:
    vk = _vk_for_key(key)
    if not vk:
        return False
    _send(_key_input(vk=vk), _key_input(vk=vk, flags=KEYEVENTF_KEYUP))
    return True


def hotkey(keys) -> None:
    if isinstance(keys, str):
        parts = [p for p in keys.replace(" ", "+").split("+") if p]
    else:
        parts = [str(k) for k in keys]
    if not parts:
        return
    modifiers = [p for p in parts if p.lower() in MODIFIER_VK]
    main = [p for p in parts if p.lower() not in MODIFIER_VK]
    inputs: list[INPUT] = []
    for modifier in modifiers:
        vk = _vk_for_key(modifier)
        if vk:
            inputs.append(_key_input(vk=vk))
    for key in main:
        vk = _vk_for_key(key)
        if vk:
            inputs.append(_key_input(vk=vk))
            inputs.append(_key_input(vk=vk, flags=KEYEVENTF_KEYUP))
    for modifier in reversed(modifiers):
        vk = _vk_for_key(modifier)
        if vk:
            inputs.append(_key_input(vk=vk, flags=KEYEVENTF_KEYUP))
    if inputs:
        _send(*inputs)


def type_text(text: str) -> None:
    for char in text:
        if char == "\n":
            press_key("enter")
            continue
        if char == "\t":
            press_key("tab")
            continue
        code = ord(char)
        _send(
            _key_input(scan=code, flags=KEYEVENTF_UNICODE),
            _key_input(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
        )
        time.sleep(0.002)
