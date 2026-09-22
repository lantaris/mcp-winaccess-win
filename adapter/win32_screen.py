"""Windows screen capture, monitors and pixel access (Pillow + ctypes)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PIL import ImageChops, ImageDraw, ImageGrab

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
shcore = getattr(ctypes.windll, "shcore", None)

MONITORINFOF_PRIMARY = 0x00000001


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def grab(bbox: tuple[int, int, int, int] | None = None):
    return ImageGrab.grab(bbox=bbox, all_screens=True)


def grab_window(hwnd: int):
    try:
        return ImageGrab.grab(window=hwnd)
    except TypeError:
        return ImageGrab.grab(all_screens=True)


def get_monitors() -> list[dict]:
    monitors: list[dict] = []
    monitor_enum = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(RECT),
        ctypes.c_double,
    )

    def _callback(hmonitor, hdc, rect, data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            r = info.rcMonitor
            scale = 1.0
            if shcore is not None:
                try:
                    dpi_x = wintypes.UINT()
                    dpi_y = wintypes.UINT()
                    if shcore.GetDpiForMonitor(hmonitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
                        scale = round(dpi_x.value / 96.0, 2)
                except Exception:
                    scale = 1.0
            monitors.append(
                {
                    "index": len(monitors),
                    "left": r.left,
                    "top": r.top,
                    "width": r.right - r.left,
                    "height": r.bottom - r.top,
                    "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                    "scale": scale,
                }
            )
        return 1

    try:
        user32.EnumDisplayMonitors(0, 0, monitor_enum(_callback), 0)
    except Exception:
        monitors = []
    if not monitors:
        width = user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(1)
        monitors = [{"index": 0, "left": 0, "top": 0, "width": width, "height": height, "primary": True}]
    return monitors


def get_pixel(x: int, y: int) -> tuple[int, int, int]:
    hdc = user32.GetDC(0)
    try:
        color = gdi32.GetPixel(hdc, x, y)
    finally:
        user32.ReleaseDC(0, hdc)
    if color == 0xFFFFFFFF:
        raise OSError("GetPixel failed")
    return color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF


def cursor_position() -> tuple[int, int]:
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def draw_cursor(image):
    x, y = cursor_position()
    draw = ImageDraw.Draw(image)
    draw.polygon(
        [(x, y), (x, y + 18), (x + 5, y + 13), (x + 9, y + 20), (x + 12, y + 18), (x + 8, y + 11), (x + 14, y + 11)],
        fill=(255, 0, 0),
        outline=(0, 0, 0),
    )
    return image


def compare(image_a, image_b, threshold: int = 16, save_diff: str = ""):
    if image_a.size != image_b.size:
        return None
    diff = ImageChops.difference(image_a.convert("RGB"), image_b.convert("RGB")).convert("L")
    histogram = diff.histogram()
    changed = sum(histogram[threshold + 1 :]) if threshold else sum(histogram[1:])
    total = image_a.size[0] * image_a.size[1]
    percent = (changed / total * 100.0) if total else 0.0
    if save_diff:
        diff.point(lambda value: 255 if value > threshold else 0).save(save_diff)
    return changed, total, percent
