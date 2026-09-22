"""Draw a temporary highlight rectangle over a screen region (ctypes GDI)."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PS_SOLID = 0
NULL_BRUSH = 5
RDW_INVALIDATE = 0x0001
RDW_ALLCHILDREN = 0x0080
RDW_UPDATENOW = 0x0100

COLORS = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "orange": (255, 165, 0),
    "white": (255, 255, 255),
    "magenta": (255, 0, 255),
}

gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
gdi32.CreatePen.restype = wintypes.HPEN
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.GetStockObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.Rectangle.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]


def _colorref(color) -> int:
    if isinstance(color, (tuple, list)) and len(color) == 3:
        red, green, blue = color
        return int(red) | (int(green) << 8) | (int(blue) << 16)
    red, green, blue = COLORS.get(str(color).lower(), (255, 0, 0))
    return red | (green << 8) | (blue << 16)


def highlight(left: int, top: int, right: int, bottom: int, duration: float = 1.0, color="red", width: int = 3) -> None:
    hdc = user32.GetDC(0)
    pen = gdi32.CreatePen(PS_SOLID, max(1, int(width)), _colorref(color))
    old_pen = gdi32.SelectObject(hdc, pen)
    old_brush = gdi32.SelectObject(hdc, gdi32.GetStockObject(NULL_BRUSH))
    try:
        for offset in range(max(1, int(width))):
            gdi32.Rectangle(hdc, left - offset, top - offset, right + offset, bottom + offset)
        time.sleep(max(0.0, float(duration)))
    finally:
        gdi32.SelectObject(hdc, old_pen)
        gdi32.SelectObject(hdc, old_brush)
        gdi32.DeleteObject(pen)
        user32.ReleaseDC(0, hdc)
        user32.InvalidateRect(0, None, True)
        user32.RedrawWindow(0, None, 0, RDW_INVALIDATE | RDW_ALLCHILDREN | RDW_UPDATENOW)
