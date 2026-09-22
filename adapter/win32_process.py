"""Process launch, termination and enumeration via ctypes / taskkill (no pywin32)."""

from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes

kernel32 = ctypes.windll.kernel32

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_PATH = 260

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def run(path: str, args: str = "", cwd: str = "") -> int:
    """Launch an application detached from this process and return its PID.

    Detached with DEVNULL handles so the child never inherits (and thus never
    holds open) the MCP stdio pipe.
    """
    command = path
    if args:
        command = f'"{path}" {args}' if " " in path else f"{path} {args}"
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        command,
        cwd=cwd or None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
        shell=False,
    )
    return proc.pid


def kill(pid_or_name: str) -> tuple[bool, str]:
    """Force-kill a process (and its tree) by PID or exact image name."""
    target = (pid_or_name or "").strip()
    if not target:
        return False, "empty target"
    if target.isdigit():
        cmd = ["taskkill", "/F", "/T", "/PID", target]
    else:
        image = target if target.lower().endswith(".exe") else target + ".exe"
        cmd = ["taskkill", "/F", "/IM", image]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output.strip()


def list_processes(filter_text: str = "") -> list[tuple[int, str]]:
    """Return (pid, exe_name) for running processes, optionally filtered by substring."""
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return []
    needle = (filter_text or "").lower()
    results: list[tuple[int, str]] = []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            name = entry.szExeFile
            if not needle or needle in name.lower():
                results.append((int(entry.th32ProcessID), name))
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return results


def is_running(image_name: str) -> bool:
    name = image_name if image_name.lower().endswith(".exe") else image_name + ".exe"
    return any(exe.lower() == name.lower() for _pid, exe in list_processes())


def main() -> int:  # pragma: no cover - manual smoke helper
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        for pid, exe in list_processes(sys.argv[2] if len(sys.argv) > 2 else ""):
            print(pid, exe)
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        print(run(sys.argv[2], " ".join(sys.argv[3:])))
        return 0
    if len(sys.argv) > 2 and sys.argv[1] == "kill":
        ok, out = kill(sys.argv[2])
        print(ok, out)
        return 0
    print("usage: win32_process.py list [filter] | run <path> [args] | kill <pid|name>")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
