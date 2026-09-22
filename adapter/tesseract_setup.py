"""Automatic Tesseract OCR setup for Windows.

Resolves an existing Tesseract binary, or installs one into a per-user managed
directory by downloading the official UB-Mannheim installer and extracting it
with 7-Zip (no admin required). Language data is fetched from tessdata_fast.

Disable the automatic install with MCP_WINACCESS_AUTO_TESSERACT=0.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import urllib.request

INSTALLER_URL = (
    "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/"
    "tesseract-ocr-w64-setup-5.4.0.20240606.exe"
)
TESSDATA_BASE = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/"
LANGUAGES = ("eng", "rus")

MANAGED_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "mcp-winaccess", "tesseract"
)

STD_LOCATIONS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

SEVEN_ZIP_CANDIDATES = (
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
)

_lock = threading.Lock()
_resolved: str | None = None
_install_failed = False


def _existing(path: str | None) -> str | None:
    return path if path and os.path.exists(path) else None


def _find_seven_zip() -> str | None:
    for name in ("7z", "7za"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in SEVEN_ZIP_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return None


def _candidates() -> list[str]:
    values = [
        os.environ.get("TESSERACT_CMD"),
        shutil.which("tesseract"),
        *STD_LOCATIONS,
        os.path.join(MANAGED_DIR, "tesseract.exe"),
    ]
    return [value for value in values if value]


def find_tesseract() -> str | None:
    """Return the first existing Tesseract executable, without installing."""
    for value in _candidates():
        if os.path.exists(value):
            return value
    return None


def _auto_install_enabled() -> bool:
    return os.environ.get("MCP_WINACCESS_AUTO_TESSERACT", "1").strip().lower() not in ("0", "false", "no", "off")


def _download(url: str, dest: str, timeout: float = 300.0) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "mcp-winaccess-win"})
    part = dest + ".part"
    with urllib.request.urlopen(request, timeout=timeout) as response, open(part, "wb") as handle:
        shutil.copyfileobj(response, handle, length=1024 * 256)
    os.replace(part, dest)


def _extract_installer(installer: str, target: str) -> bool:
    seven = _find_seven_zip()
    if seven:
        os.makedirs(target, exist_ok=True)
        result = subprocess.run(
            [seven, "x", "-y", f"-o{target}", installer],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0 and _locate_exe(target):
            return True
    # Fallback: NSIS silent install into the managed directory (may need admin).
    try:
        subprocess.run([installer, "/S", f"/D={target}"], capture_output=True, timeout=300)
    except Exception:
        return False
    return _locate_exe(target) is not None


def _locate_exe(root: str) -> str | None:
    direct = os.path.join(root, "tesseract.exe")
    if os.path.exists(direct):
        return direct
    for current, _dirs, files in os.walk(root):
        if "tesseract.exe" in files:
            return os.path.join(current, "tesseract.exe")
    return None


def _ensure_languages(exe: str) -> None:
    tessdata = os.path.join(os.path.dirname(exe), "tessdata")
    os.makedirs(tessdata, exist_ok=True)
    for lang in LANGUAGES:
        dest = os.path.join(tessdata, f"{lang}.traineddata")
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            continue
        try:
            _download(TESSDATA_BASE + f"{lang}.traineddata", dest, timeout=180)
        except Exception:
            pass


def install() -> str | None:
    """Download and extract Tesseract into MANAGED_DIR. Returns the exe path."""
    with tempfile.TemporaryDirectory(prefix="mcp_tess_") as work:
        installer = os.path.join(work, "tesseract-setup.exe")
        try:
            _download(INSTALLER_URL, installer)
        except Exception:
            return None
        os.makedirs(MANAGED_DIR, exist_ok=True)
        if not _extract_installer(installer, MANAGED_DIR):
            return None
    exe = _locate_exe(MANAGED_DIR)
    if exe:
        _ensure_languages(exe)
    return exe


def ensure_tesseract(allow_install: bool = True) -> str | None:
    """Return a usable Tesseract executable, installing it once if necessary."""
    global _resolved, _install_failed
    with _lock:
        found = _existing(_resolved) or find_tesseract()
        if found:
            _resolved = found
            return found
        if _install_failed or not allow_install or not _auto_install_enabled():
            return None
        exe = install()
        if exe:
            _resolved = exe
            return exe
        _install_failed = True
        return None


def main() -> int:  # pragma: no cover - manual helper
    import sys

    exe = ensure_tesseract()
    if exe:
        print(f"Tesseract: {exe}")
        return 0
    print("Tesseract could not be installed automatically. Set TESSERACT_CMD manually.", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
