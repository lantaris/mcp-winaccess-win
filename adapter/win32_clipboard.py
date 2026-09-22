"""Windows clipboard access via ctypes (text, files, image)."""

from __future__ import annotations

import ctypes
import io
import os
import struct
import time
from ctypes import wintypes

from PIL import Image

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

CF_BITMAP = 2
CF_DIB = 8
CF_UNICODETEXT = 13
CF_HDROP = 15
GMEM_MOVEABLE = 0x0002

kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
shell32.DragQueryFileW.restype = wintypes.UINT


class DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    ]


def _open_clipboard(retries: int = 8, delay: float = 0.05) -> bool:
    for _ in range(retries):
        if user32.OpenClipboard(0):
            return True
        time.sleep(delay)
    return False


def _set_bytes(fmt: int, payload: bytes) -> None:
    if not _open_clipboard():
        raise OSError("OpenClipboard failed")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(payload))
        if not handle:
            raise OSError("GlobalAlloc failed")
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            raise OSError("GlobalLock failed")
        try:
            ctypes.memmove(pointer, payload, len(payload))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(fmt, handle):
            kernel32.GlobalFree(handle)
            raise OSError("SetClipboardData failed")
    finally:
        user32.CloseClipboard()


def _get_handle(fmt: int):
    if not _open_clipboard():
        raise OSError("OpenClipboard failed")
    return user32.GetClipboardData(fmt)


def get_text() -> str:
    handle = _get_handle(CF_UNICODETEXT)
    try:
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_text(text: str) -> None:
    _set_bytes(CF_UNICODETEXT, ((text or "") + "\0").encode("utf-16-le"))


def clear() -> None:
    if not _open_clipboard():
        raise OSError("OpenClipboard failed")
    try:
        user32.EmptyClipboard()
    finally:
        user32.CloseClipboard()


def set_files(paths: list[str]) -> int:
    files = [os.path.abspath(path) for path in paths if path]
    if not files:
        raise OSError("no files provided")
    header = DROPFILES()
    header.pFiles = ctypes.sizeof(DROPFILES)
    header.fWide = True
    payload = bytes(header) + ("\0".join(files) + "\0\0").encode("utf-16-le")
    _set_bytes(CF_HDROP, payload)
    return len(files)


def get_files() -> list[str]:
    handle = _get_handle(CF_HDROP)
    try:
        if not handle:
            return []
        count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
        files = []
        for index in range(count):
            length = shell32.DragQueryFileW(handle, index, None, 0)
            buffer = ctypes.create_unicode_buffer(length + 1)
            shell32.DragQueryFileW(handle, index, buffer, length + 1)
            files.append(buffer.value)
        return files
    finally:
        user32.CloseClipboard()


def set_image(path: str) -> None:
    with Image.open(path) as image:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, "BMP")
        data = buffer.getvalue()
    _set_bytes(CF_DIB, data[14:])


def get_image(save_path: str = ""):
    handle = _get_handle(CF_DIB)
    try:
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            size = kernel32.GlobalSize(handle)
            dib = ctypes.string_at(pointer, size)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
    header_size = struct.unpack_from("<I", dib, 0)[0]
    offset = 14 + header_size
    file_header = b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, offset)
    opened = Image.open(io.BytesIO(file_header + dib))
    opened.load()
    image = opened.convert("RGB")
    if save_path:
        image.save(save_path)
    return image
