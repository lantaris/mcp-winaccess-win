#!/usr/bin/env python3
"""mcp-winaccess-win: Windows desktop automation MCP server.

Tools are registered only when the adapter advertises the matching capability,
so unsupported actions never appear in the agent's tool list.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from typing import Annotated, Literal

from mcp.server.mcpserver import Image, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_winaccess_win.adapter import get_adapter, tesseract_setup

if sys.platform != "win32":
    raise RuntimeError(f"mcp-winaccess-win is Windows-only (detected platform: {sys.platform}).")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-winaccess-win",
        description="Windows-only desktop automation MCP server (ctypes + UI Automation).",
    )
    parser.add_argument(
        "--transport",
        choices=["local", "remote"],
        default="local",
        help="'local' uses stdio; 'remote' serves streamable-http on --listen/--port (default: local).",
    )
    parser.add_argument(
        "--listen",
        default="0.0.0.0",
        help="HTTP bind address for --transport remote (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="HTTP port for --transport remote (default: 8765).",
    )
    parser.add_argument(
        "--tesseract_cmd",
        default="auto",
        help="'auto' resolves Tesseract automatically, or an explicit path to tesseract.exe (default: auto).",
    )
    parser.add_argument(
        "--auto-tesseract",
        dest="auto_tesseract",
        action="store_true",
        default=True,
        help="enable automatic Tesseract install/download (default).",
    )
    parser.add_argument(
        "--no-auto-tesseract",
        dest="auto_tesseract",
        action="store_false",
        help="disable automatic Tesseract install.",
    )
    parser.add_argument(
        "--token",
        default="",
        help="Bearer token required for --transport remote (via the 'Authorization' header).",
    )
    return parser


_args = _build_parser().parse_args()
tesseract_setup.configure(tesseract_cmd=_args.tesseract_cmd, auto_tesseract=_args.auto_tesseract)

adapter = get_adapter()

INSTRUCTIONS = """\
mcp-winaccess drives a live Windows desktop (mouse, keyboard, clipboard, windows, UI Automation).

Conventions (apply to every tool unless stated otherwise):
- Coordinates are ABSOLUTE screen pixels in the virtual desktop (all monitors, DPI-aware). (0, 0) is the
  top-left of the primary monitor; a monitor to the left/top of it has negative coordinates.
- `value` identifies a window. Accepted forms: a partial title or class substring (str), a window
  handle (int or numeric string), or a prefix: 'title:', 'class:', 'pid:N', 'exe:name.exe'.
- `control_identifier` is either an 'element_N' ID returned by get_all_controls, or a control
  Name/AutoID. 'element_N' is the index in the FULL descendant walk of the window: query/control_type
  in get_all_controls only filter the printed rows, they do NOT renumber the IDs. IDs are not stable
  if the UI changes between calls.
- Return contract: a human-readable string on success; on failure a string starting with 'ERROR:'.
  Screenshot tools return an image (JPEG) instead of a string.
- Tools are registered by capability: some tools are ABSENT from the list when the platform/feature
  is unavailable (UI tree needs comtypes; vision needs opencv-python; OCR needs pytesseract - the
  Tesseract binary is downloaded and installed automatically on first OCR use).
- Many tools have SIDE EFFECTS: moving the cursor, changing focus, typing, replacing the clipboard,
  closing windows, switching virtual desktops, or holding keys/mouse buttons. Prefer read-only tools
  (screenshots, list_*, get_*) to inspect state first.
- Process tools: run_app launches an application detached; kill_process force-kills a process tree
  and is IRREVERSIBLE. Prefer close_window for a graceful close.
- Call switch_to_window before typing/clicking if the target may not be focused.
- Tool annotations (readOnlyHint/destructiveHint/idempotentHint) mark which tools only observe state
  and which change it; clients may use them to decide whether to ask for confirmation.
"""

mcp = MCPServer("mcp-winaccess", version="1.6.0", instructions=INSTRUCTIONS)

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True)
READ_ONLY_ONCE = ToolAnnotations(read_only_hint=True)
WRITE = ToolAnnotations(read_only_hint=False)
WRITE_IDEMPOTENT = ToolAnnotations(read_only_hint=False, idempotent_hint=True)
WRITE_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True)

VALUE = "window identifier (see server instructions)"
CTRL = "control identifier from get_all_controls (see server instructions)"
COORD = "absolute screen pixels on the virtual desktop"


def _image(img):
    if img is None:
        return "ERROR: screenshot failed."
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=85)
    return Image(data=buf.getvalue(), format="jpeg")


def tool(
    description: str,
    capability: str | None = None,
    title: str | None = None,
    annotations: ToolAnnotations | None = None,
):
    def deco(fn):
        if capability is None or adapter.supports(capability):
            mcp.add_tool(
                fn,
                name=fn.__name__,
                title=title,
                description=description,
                annotations=annotations,
                structured_output=False,
            )
        return fn

    return deco


# ---------------------------------------------------------------------------
# Screenshots and display
# ---------------------------------------------------------------------------


@tool(
    "screenshot: Full-desktop screenshot (all monitors) returned as an image. grid=True overlays labeled "
    "lines every 100 px with absolute coordinates; include_cursor=True draws the mouse pointer. "
    "Returns an image, or 'ERROR: screenshot failed.'",
    capability="screenshot",
    title="Screenshot (full desktop)",
    annotations=READ_ONLY,
)
def screenshot(
    grid: Annotated[bool, Field(description="overlay labeled coordinate lines every 100 px")] = False,
    include_cursor: Annotated[bool, Field(description="draw the mouse pointer on the image")] = False,
):
    return _image(adapter.screenshot(grid=grid, include_cursor=include_cursor))


@tool(
    "screenshot_jpg: Saves a full-desktop screenshot (all monitors) as a JPEG file and returns its path. "
    "An empty path uses a temp file. No grid/cursor options; overwrites an existing file.",
    capability="screenshot",
    title="Screenshot to JPEG file",
    annotations=WRITE_IDEMPOTENT,
)
def screenshot_jpg(
    path: Annotated[str, Field(description="output .jpg path; empty = a temp file")] = "",
) -> str:
    return adapter.screenshot_jpg(path)


@tool(
    "screenshot_region: Screenshot of an absolute screen rectangle (left, top, width, height in px). "
    "grid=True overlays labeled coordinate lines. width/height must be > 0 and inside the virtual desktop. "
    "Returns an image.",
    capability="screenshot_region",
    title="Screenshot (region)",
    annotations=READ_ONLY,
)
def screenshot_region(
    left: Annotated[int, Field(description="absolute left X")],
    top: Annotated[int, Field(description="absolute top Y")],
    width: Annotated[int, Field(description="region width in px (> 0)")],
    height: Annotated[int, Field(description="region height in px (> 0)")],
    grid: Annotated[bool, Field(description="overlay labeled coordinate lines")] = False,
):
    return _image(adapter.screenshot_region(left, top, width, height, grid=grid))


@tool(
    "screenshot_window: Screenshot of one window (value). Captures the window itself even if partially "
    "covered. grid=True adds labeled lines using the window's absolute origin. On failure (e.g. window "
    "not found) returns 'ERROR: screenshot failed.'",
    capability="screenshot_window",
    title="Screenshot (window)",
    annotations=READ_ONLY,
)
def screenshot_window(
    value: Annotated[str, Field(description=VALUE)],
    grid: Annotated[bool, Field(description="overlay labeled coordinate lines")] = False,
):
    return _image(adapter.screenshot_window(value, grid=grid))


@tool(
    "screenshot_monitor: Screenshot of one monitor by 0-based index (see list_monitors). An out-of-range "
    "index is clamped to the nearest monitor. grid=True adds labeled coordinate lines.",
    capability="screenshot_monitor",
    title="Screenshot (monitor)",
    annotations=READ_ONLY,
)
def screenshot_monitor(
    index: Annotated[int, Field(description="0-based monitor index (see list_monitors)")] = 0,
    grid: Annotated[bool, Field(description="overlay labeled coordinate lines")] = False,
):
    return _image(adapter.screenshot_monitor(index, grid=grid))


@tool(
    "list_monitors: Lists monitors as 'Monitor N [primary]: left, top, width, height, scale'. index is "
    "0-based; scale is the DPI multiplier. Use index with screenshot_monitor / image_to_screen_coords.",
    title="List monitors",
    annotations=READ_ONLY,
)
def list_monitors() -> str:
    return adapter.list_monitors()


@tool(
    "image_to_screen_coords: Converts a pixel (x, y) from a monitor screenshot into absolute "
    "virtual-desktop coordinates. monitor_index is 0-based and clamped. Use before clicking a point "
    "found on a monitor screenshot.",
    title="Image pixel to screen coordinates",
    annotations=READ_ONLY,
)
def image_to_screen_coords(
    x: Annotated[int, Field(description="X within the monitor screenshot")],
    y: Annotated[int, Field(description="Y within the monitor screenshot")],
    monitor_index: Annotated[int, Field(description="0-based monitor index (see list_monitors)")] = 0,
) -> str:
    return adapter.image_to_screen_coords(x, y, monitor_index)


@tool("get_mouse_position: Current cursor position in absolute pixels.", title="Get mouse position", annotations=READ_ONLY)
def get_mouse_position() -> str:
    return adapter.get_mouse_position()


# ---------------------------------------------------------------------------
# Mouse and keyboard
# ---------------------------------------------------------------------------


@tool("move_mouse: Moves the cursor to absolute (x, y) without clicking.", title="Move mouse", annotations=WRITE_IDEMPOTENT)
def move_mouse(
    x: Annotated[int, Field(description="absolute X")],
    y: Annotated[int, Field(description="absolute Y")],
) -> str:
    return adapter.move_mouse(x, y)


@tool(
    "click: Clicks at absolute (x, y). button: 'left'|'right'|'middle' (an unknown value falls back to "
    "'left'); clicks: number of clicks (>=1). Omit x/y (or pass null) to click at the current cursor "
    "position. Use clicks=2 for a double-click, button='right' for a right-click.",
    title="Click",
    annotations=WRITE,
)
def click(
    x: Annotated[int | None, Field(description="absolute X; null = current cursor X")] = None,
    y: Annotated[int | None, Field(description="absolute Y; null = current cursor Y")] = None,
    button: Annotated[str, Field(description="'left' | 'right' | 'middle' (unknown -> 'left')")] = "left",
    clicks: Annotated[int, Field(description="number of clicks (>= 1); 2 = double-click")] = 1,
) -> str:
    return adapter.click(x, y, button, clicks)


@tool(
    "drag: Press-move-release with the LEFT button from (x_from, y_from) to (x_to, y_to) over duration "
    "seconds (interpolated in ~20 ms steps).",
    title="Drag",
    annotations=WRITE,
)
def drag(
    x_from: Annotated[int, Field(description="start absolute X")],
    y_from: Annotated[int, Field(description="start absolute Y")],
    x_to: Annotated[int, Field(description="end absolute X")],
    y_to: Annotated[int, Field(description="end absolute Y")],
    duration: Annotated[float, Field(description="drag duration in seconds")] = 0.5,
) -> str:
    return adapter.drag(x_from, y_from, x_to, y_to, duration)


@tool(
    "scroll: Mouse-wheel scroll at absolute (x, y); (0, 0) scrolls at the current cursor position. "
    "direction: 'up'|'down'|'left'|'right'. amount = number of wheel steps.",
    title="Scroll",
    annotations=WRITE,
)
def scroll(
    direction: Literal["up", "down", "left", "right"] = "down",
    amount: Annotated[int, Field(description="number of wheel steps")] = 3,
    x: Annotated[int, Field(description="absolute X; 0 = current cursor X")] = 0,
    y: Annotated[int, Field(description="absolute Y; 0 = current cursor Y")] = 0,
) -> str:
    return adapter.scroll(direction, amount, x, y)


@tool(
    "type_text: Types text at the current keyboard focus via Unicode SendInput. '\\n' presses Enter, "
    "'\\t' presses Tab. It does NOT replace existing content (inserts at the caret). Only BMP characters "
    "are supported: emoji / non-BMP code points (U+10000+) are corrupted. Focus the target first.",
    title="Type text",
    annotations=WRITE,
)
def type_text(text: Annotated[str, Field(description="text to type (BMP only; \\n=Enter, \\t=Tab)")]) -> str:
    return adapter.type_text(text)


@tool(
    "press_key: Presses one key: a letter/digit, 'enter', 'tab', 'esc', 'f5', etc., or a system key "
    "('win', 'volumeup', 'volumedown', 'volumemute', 'playpause', 'nexttrack', 'prevtrack', 'printscreen'). "
    "An unknown name returns 'ERROR: unknown key'. System keys change system state.",
    title="Press key",
    annotations=WRITE,
)
def press_key(key: Annotated[str, Field(description="key name, e.g. 'enter', 'esc', 'f5', 'volumeup'")]) -> str:
    return adapter.press_key(key)


@tool(
    "hotkey: Presses a key combination, e.g. 'ctrl+c', 'ctrl+shift+s', 'win+ctrl+right'. Modifiers "
    "(ctrl/shift/alt/win) are held down, the main key is pressed and released, then modifiers are released. "
    "Spaces are treated as '+'.",
    title="Hotkey",
    annotations=WRITE,
)
def hotkey(keys: Annotated[str, Field(description="combination, e.g. 'ctrl+shift+s'")]) -> str:
    return adapter.hotkey(keys)


@tool(
    "key_down: Presses and HOLDS a key (pair with key_up). Use for Shift/Ctrl range selections. Always "
    "release it with key_up to avoid a stuck key.",
    title="Key down (hold)",
    annotations=WRITE,
)
def key_down(key: Annotated[str, Field(description="key name to hold, e.g. 'shift'")]) -> str:
    return adapter.key_down(key)


@tool("key_up: Releases a key previously held by key_down.", title="Key up (release)", annotations=WRITE)
def key_up(key: Annotated[str, Field(description="key name to release")]) -> str:
    return adapter.key_up(key)


@tool(
    "mouse_down: Presses and HOLDS a mouse button at (x, y). NOTE: (0, 0) moves the cursor to (0, 0) "
    "(not 'current position'); to press at the current position pass the coordinates from get_mouse_position. "
    "Pair with mouse_up.",
    title="Mouse down (hold)",
    annotations=WRITE,
)
def mouse_down(
    x: Annotated[int, Field(description="absolute X (0,0 = screen origin)")] = 0,
    y: Annotated[int, Field(description="absolute Y (0,0 = screen origin)")] = 0,
    button: Annotated[str, Field(description="'left' | 'right' | 'middle'")] = "left",
) -> str:
    return adapter.mouse_down(x, y, button)


@tool("mouse_up: Releases a mouse button previously held by mouse_down.", title="Mouse up (release)", annotations=WRITE)
def mouse_up(button: Annotated[str, Field(description="'left' | 'right' | 'middle'")] = "left") -> str:
    return adapter.mouse_up(button)


@tool(
    "mouse_move_relative: Moves the cursor by (dx, dy) relative to its current position.",
    title="Move mouse (relative)",
    annotations=WRITE,
)
def mouse_move_relative(
    dx: Annotated[int, Field(description="horizontal delta in px")],
    dy: Annotated[int, Field(description="vertical delta in px")],
) -> str:
    return adapter.mouse_move_relative(dx, dy)


# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------


@tool(
    "clipboard_get: Returns the current clipboard text (CF_UNICODETEXT), or an empty string if none.",
    capability="clipboard",
    title="Get clipboard text",
    annotations=READ_ONLY_ONCE,
)
def clipboard_get() -> str:
    return adapter.clipboard_get()


@tool(
    "clipboard_set: Replaces the ENTIRE clipboard with the given text.",
    capability="clipboard",
    title="Set clipboard text",
    annotations=WRITE_DESTRUCTIVE,
)
def clipboard_set(text: Annotated[str, Field(description="text to place on the clipboard")]) -> str:
    return adapter.clipboard_set(text)


@tool(
    "clipboard_clear: Empties the clipboard (all formats).",
    capability="clipboard",
    title="Clear clipboard",
    annotations=WRITE_DESTRUCTIVE,
)
def clipboard_clear() -> str:
    return adapter.clipboard_clear()


@tool(
    "get_pixel_color: RGB color at absolute (x, y). Read-only way to verify UI state without a screenshot.",
    title="Get pixel color",
    annotations=READ_ONLY,
)
def get_pixel_color(
    x: Annotated[int, Field(description="absolute X")],
    y: Annotated[int, Field(description="absolute Y")],
) -> str:
    return adapter.get_pixel_color(x, y)


# ---------------------------------------------------------------------------
# Vision / OCR
# ---------------------------------------------------------------------------


@tool(
    "locate_image_on_screen: Finds a template image file on screen via OpenCV template matching. "
    "confidence is 0-1. Returns its region and center, or 'ERROR: ... not found (score=...)'. "
    "Requires the 'vision' extra (opencv-python).",
    capability="vision",
    title="Locate image on screen",
    annotations=READ_ONLY,
)
def locate_image_on_screen(
    image_path: Annotated[str, Field(description="path to the template image file")],
    confidence: Annotated[float, Field(description="match threshold 0-1")] = 0.9,
) -> str:
    return adapter.locate_image_on_screen(image_path, confidence)


@tool(
    "wait_for_image: Polls locate_image_on_screen every ~0.4 s until the template appears or timeout "
    "(seconds) elapses. Requires the 'vision' extra.",
    capability="vision",
    title="Wait for image",
    annotations=READ_ONLY,
)
def wait_for_image(
    image_path: Annotated[str, Field(description="path to the template image file")],
    confidence: Annotated[float, Field(description="match threshold 0-1")] = 0.9,
    timeout: Annotated[float, Field(description="max wait in seconds")] = 10.0,
) -> str:
    return adapter.wait_for_image(image_path, confidence, timeout)


@tool(
    "click_image: Waits for a template image and clicks its center. Requires the 'vision' extra.",
    capability="vision",
    title="Click image",
    annotations=WRITE,
)
def click_image(
    image_path: Annotated[str, Field(description="path to the template image file")],
    confidence: Annotated[float, Field(description="match threshold 0-1")] = 0.9,
    timeout: Annotated[float, Field(description="max wait in seconds")] = 10.0,
) -> str:
    return adapter.click_image(image_path, confidence, timeout)


@tool(
    "ocr_screen: OCR text over the screen or a region (left, top, width, height; width/height 0 = full "
    "screen). lang e.g. 'eng' or 'rus+eng'. The Tesseract binary is downloaded and installed automatically "
    "on first use (disable with --no-auto-tesseract; override with --tesseract_cmd). "
    "Empty result -> '(no text found)'.",
    capability="ocr",
    title="OCR screen",
    annotations=READ_ONLY,
)
def ocr_screen(
    left: Annotated[int, Field(description="region left; 0 with width=0 = full screen")] = 0,
    top: Annotated[int, Field(description="region top")] = 0,
    width: Annotated[int, Field(description="region width; 0 = full screen")] = 0,
    height: Annotated[int, Field(description="region height; 0 = full screen")] = 0,
    lang: Annotated[str, Field(description="Tesseract language, e.g. 'eng' or 'rus+eng'")] = "",
) -> str:
    return adapter.ocr_screen(left, top, width, height, lang)


@tool(
    "find_text_on_screen: OCR-searches text (case-insensitive substring) and returns the CENTER "
    "coordinates of the matching word. confidence is 0-100 (note: different scale from vision's 0-1). "
    "lang e.g. 'eng'. Uses the auto-installed Tesseract binary.",
    capability="ocr",
    title="Find text on screen",
    annotations=READ_ONLY,
)
def find_text_on_screen(
    text: Annotated[str, Field(description="substring to search for")],
    confidence: Annotated[int, Field(description="minimum confidence 0-100")] = 60,
    lang: Annotated[str, Field(description="Tesseract language, e.g. 'eng'")] = "",
) -> str:
    return adapter.find_text_on_screen(text, confidence, lang)


@tool(
    "click_text: OCR-finds text on screen and clicks its center. confidence is 0-100. Uses the "
    "auto-installed Tesseract binary.",
    capability="ocr",
    title="Click text on screen",
    annotations=WRITE,
)
def click_text(
    text: Annotated[str, Field(description="substring to find and click")],
    confidence: Annotated[int, Field(description="minimum confidence 0-100")] = 60,
    lang: Annotated[str, Field(description="Tesseract language, e.g. 'eng'")] = "",
) -> str:
    return adapter.click_text(text, confidence, lang)


@tool(
    "wait_for_text: Polls OCR every ~0.5 s until the text is found or timeout (seconds) elapses (for "
    "canvas/custom UI without an accessibility tree). confidence is 0-100. Uses the auto-installed "
    "Tesseract binary.",
    capability="ocr",
    title="Wait for text",
    annotations=READ_ONLY,
)
def wait_for_text(
    text: Annotated[str, Field(description="substring to wait for")],
    timeout: Annotated[float, Field(description="max wait in seconds")] = 10.0,
    lang: Annotated[str, Field(description="Tesseract language, e.g. 'eng'")] = "",
    confidence: Annotated[int, Field(description="minimum confidence 0-100")] = 60,
) -> str:
    return adapter.wait_for_text(text, timeout, lang, confidence)


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------


@tool(
    "list_windows: Lists VISIBLE top-level windows (title, class, handle, PID, exe, rect). Optional "
    "process filter: a substring of the exe name or an exact PID. Windows with an empty title are skipped.",
    capability="window_list",
    title="List windows",
    annotations=READ_ONLY,
)
def list_windows(
    process: Annotated[str, Field(description="exe-name substring or exact PID; empty = all")] = "",
) -> str:
    return adapter.list_windows(process)


@tool(
    "find_window: Returns matching windows each prefixed with an index '[0]', '[1]'. value: a partial "
    "title/class substring (str), a handle (int/digits), or a prefix 'title:', 'class:', 'pid:N', 'exe:name.exe'.",
    capability="window_list",
    title="Find window",
    annotations=READ_ONLY,
)
def find_window(value: Annotated[str, Field(description=VALUE)]) -> str:
    return adapter.find_window(value)


@tool(
    "get_active_window: Returns the currently focused window, or 'ERROR' if there is none.",
    capability="window_list",
    title="Get active window",
    annotations=READ_ONLY,
)
def get_active_window() -> str:
    return adapter.get_active_window()


@tool(
    "switch_to_window: Restores and brings a window (value) to the foreground (Alt-unlock + "
    "SetForegroundWindow, with an AttachThreadInput fallback). Some always-on-top/system windows may "
    "refuse focus. Call before typing/clicking.",
    capability="window_activate",
    title="Activate window",
    annotations=WRITE_IDEMPOTENT,
)
def switch_to_window(value: Annotated[str, Field(description=VALUE)]) -> str:
    return adapter.switch_to_window(value)


@tool("minimize_window: Minimizes a window (value) via ShowWindow.", capability="window_minimize", title="Minimize window", annotations=WRITE_IDEMPOTENT)
def minimize_window(value: Annotated[str, Field(description=VALUE)]) -> str:
    return adapter.minimize_window(value)


@tool("maximize_window: Maximizes a window (value) via ShowWindow.", capability="window_maximize", title="Maximize window", annotations=WRITE_IDEMPOTENT)
def maximize_window(value: Annotated[str, Field(description=VALUE)]) -> str:
    return adapter.maximize_window(value)


@tool(
    "restore_window: Restores a minimized/maximized window (value) to its normal state.",
    capability="window_maximize",
    title="Restore window",
    annotations=WRITE_IDEMPOTENT,
)
def restore_window(value: Annotated[str, Field(description=VALUE)]) -> str:
    return adapter.restore_window(value)


@tool(
    "move_window: Moves a window's top-left to absolute (x, y), keeping its current size.",
    capability="window_move",
    title="Move window",
    annotations=WRITE_IDEMPOTENT,
)
def move_window(
    value: Annotated[str, Field(description=VALUE)],
    x: Annotated[int, Field(description="absolute X for the top-left corner")],
    y: Annotated[int, Field(description="absolute Y for the top-left corner")],
) -> str:
    return adapter.move_window(value, x, y)


@tool(
    "resize_window: Moves and resizes a window (value) to absolute (x, y, width, height).",
    capability="window_resize",
    title="Resize window",
    annotations=WRITE_IDEMPOTENT,
)
def resize_window(
    value: Annotated[str, Field(description=VALUE)],
    x: Annotated[int, Field(description="absolute X")],
    y: Annotated[int, Field(description="absolute Y")],
    width: Annotated[int, Field(description="new width in px")],
    height: Annotated[int, Field(description="new height in px")],
) -> str:
    return adapter.resize_window(value, x, y, width, height)


@tool(
    "snap_window: Tiles a window (value) on the PRIMARY monitor. position: 'left'|'right'|'top'|'bottom'|'maximize'.",
    capability="window_snap",
    title="Snap window",
    annotations=WRITE_IDEMPOTENT,
)
def snap_window(
    value: Annotated[str, Field(description=VALUE)],
    position: Literal["left", "right", "top", "bottom", "maximize"] = "left",
) -> str:
    return adapter.snap_window(value, position)


@tool(
    "set_always_on_top: Enables/disables always-on-top for a window (value) via SetWindowPos TOPMOST/NOTOPMOST.",
    capability="window_topmost",
    title="Set window always-on-top",
    annotations=WRITE_IDEMPOTENT,
)
def set_always_on_top(
    value: Annotated[str, Field(description=VALUE)],
    enabled: Annotated[bool, Field(description="True = always-on-top, False = normal")] = True,
) -> str:
    return adapter.set_always_on_top(value, enabled)


@tool(
    "wait_for_window: Polls every ~0.3 s until a window matching value appears or timeout (seconds) "
    "elapses. require_ready=True additionally waits until the window is VISIBLE and RESPONSIVE (not hung) "
    "- use it instead of a fixed sleep after launching an app.",
    capability="window_activate",
    title="Wait for window",
    annotations=READ_ONLY,
)
def wait_for_window(
    value: Annotated[str, Field(description=VALUE)],
    timeout: Annotated[float, Field(description="max wait in seconds")] = 10.0,
    require_ready: Annotated[bool, Field(description="also wait until visible and responsive")] = False,
) -> str:
    return adapter.wait_for_window(value, timeout, require_ready)


@tool(
    "get_window_state: Returns a window's rect, handle, PID, exe, state (normal/minimized/maximized) and "
    "monitor index (by the window's top-left corner).",
    capability="window_list",
    title="Get window state",
    annotations=READ_ONLY,
)
def get_window_state(value: Annotated[str, Field(description=VALUE)]) -> str:
    return adapter.get_window_state(value)


@tool(
    "close_window: Gracefully closes a window (value) with WM_CLOSE; does NOT kill the process. A save "
    "prompt may block the close.",
    capability="window_close",
    title="Close window",
    annotations=WRITE_DESTRUCTIVE,
)
def close_window(value: Annotated[str, Field(description=VALUE)]) -> str:
    return adapter.close_window(value)


@tool(
    "wait_for_window_gone: Polls every ~0.3 s until NO window matches value (partial title/class, handle, "
    "or prefix 'pid:'/'exe:') or timeout (seconds) elapses.",
    capability="window_list",
    title="Wait for window gone",
    annotations=READ_ONLY,
)
def wait_for_window_gone(
    value: Annotated[str, Field(description=VALUE)],
    timeout: Annotated[float, Field(description="max wait in seconds")] = 10.0,
) -> str:
    return adapter.wait_for_window_gone(value, timeout)


# ---------------------------------------------------------------------------
# Menus, dialogs, tray
# ---------------------------------------------------------------------------


@tool(
    "list_dialogs: Lists modal/dialog windows (class #32770 or owned windows with a title). Check after "
    "actions that may open a modal (file dialogs, confirmations).",
    capability="dialogs",
    title="List dialogs",
    annotations=READ_ONLY,
)
def list_dialogs() -> str:
    return adapter.list_dialogs()


@tool(
    "handle_dialog: Clicks a dialog button whose name CONTAINS button_text (case-insensitive), searching "
    "dialogs (optionally filtered by title) and the active window. Returns 'ERROR' if not found. Example: "
    "button_text='OK' or 'Не сохранять'.",
    capability="dialogs",
    title="Click dialog button",
    annotations=WRITE,
)
def handle_dialog(
    button_text: Annotated[str, Field(description="button label substring, e.g. 'OK' or 'Save'")],
    title: Annotated[str, Field(description="optional dialog-title filter")] = "",
) -> str:
    return adapter.handle_dialog(button_text, title)


@tool(
    "file_dialog_set_path: Sets the path in an open/save file dialog (targets FileNameControlHost / "
    "ComboBox / Edit). title optionally selects the dialog by its title.",
    capability="dialogs",
    title="Set file dialog path",
    annotations=WRITE,
)
def file_dialog_set_path(
    path: Annotated[str, Field(description="absolute file path to enter")],
    title: Annotated[str, Field(description="optional dialog-title filter")] = "",
) -> str:
    return adapter.file_dialog_set_path(path, title)


@tool(
    "file_dialog_confirm: Clicks the confirm button of a file dialog. Button priority: Сохранить/Save/"
    "Открыть/Open/OK; may press Enter afterward. title optionally selects the dialog.",
    capability="dialogs",
    title="Confirm file dialog",
    annotations=WRITE,
)
def file_dialog_confirm(title: Annotated[str, Field(description="optional dialog-title filter")] = "") -> str:
    return adapter.file_dialog_confirm(title)


@tool(
    "menu_select: Selects a menu item by path, e.g. 'File->Save As'. Item names may include accelerator "
    "text (e.g. 'Время и дата\\tF5'); intermediate items are clicked to open submenus. May not work for "
    "some Win32 popups.",
    capability="menus",
    title="Select menu item",
    annotations=WRITE,
)
def menu_select(
    value: Annotated[str, Field(description=VALUE)],
    path: Annotated[str, Field(description="menu path with '->' separators, e.g. 'File->Save As'")],
) -> str:
    return adapter.menu_select(value, path)


@tool(
    "context_menu_click: Right-clicks at absolute (x, y), then clicks the context-menu item. Searches "
    "popup windows (#32768/PopupMenu/ContextMenu) for up to ~4 s. item is a (partial) menu label.",
    capability="menus",
    title="Click context-menu item",
    annotations=WRITE,
)
def context_menu_click(
    x: Annotated[int, Field(description="absolute X to right-click")],
    y: Annotated[int, Field(description="absolute Y to right-click")],
    item: Annotated[str, Field(description="context-menu label (partial)")],
) -> str:
    return adapter.context_menu_click(x, y, item)


@tool(
    "tray_icon_click: Clicks a system-tray icon by (partial) name. action: 'left'|'right'. LIMITATION: on "
    "Windows 11 hidden/overflow icons live in a separate XAML window and are NOT reachable, so the icon "
    "may not be found.",
    capability="tray",
    title="Click tray icon",
    annotations=WRITE,
)
def tray_icon_click(
    name: Annotated[str, Field(description="tray icon tooltip name (partial)")],
    action: Literal["left", "right"] = "left",
) -> str:
    return adapter.tray_icon_click(name, action)


# ---------------------------------------------------------------------------
# UI tree (semantic controls)
# ---------------------------------------------------------------------------


@tool(
    "get_all_controls: Lists a window's descendant controls, bounded by limit and filtered by query "
    "(substring of Name+Text) / control_type. Each row includes Rect and Center (clickable coordinates). "
    "IMPORTANT: the returned 'element_N' is the index in the FULL descendant walk; query/control_type only "
    "filter the printed rows and do NOT renumber IDs. When the limit is hit a '... truncated at N controls.' "
    "line is appended. Use the ID or Name/AutoID as control_identifier in element tools.",
    capability="ui_tree",
    title="List window controls",
    annotations=READ_ONLY,
)
def get_all_controls(
    value: Annotated[str, Field(description=VALUE)],
    limit: Annotated[int, Field(description="max rows to print")] = 150,
    query: Annotated[str, Field(description="filter: substring of Name+Text")] = "",
    control_type: Annotated[str, Field(description="filter: control type, e.g. 'Button'")] = "",
) -> str:
    return adapter.get_all_controls(value, limit, query, control_type)


@tool(
    "click_element: Clicks a control (value, control_identifier). Prefers the Invoke pattern; falls back "
    "to a coordinate click at the control's center.",
    capability="ui_tree",
    title="Click UI control",
    annotations=WRITE,
)
def click_element(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
) -> str:
    return adapter.click_element(value, control_identifier)


@tool(
    "double_click_element: Double-clicks a control at its center (coordinate click). Params: value, control_identifier.",
    capability="ui_tree",
    title="Double-click UI control",
    annotations=WRITE,
)
def double_click_element(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
) -> str:
    return adapter.double_click_element(value, control_identifier)


@tool(
    "get_text: Reads a control's text: Value pattern, else Text pattern, else its Name. Params: value, control_identifier.",
    capability="ui_tree",
    title="Get control text",
    annotations=READ_ONLY,
)
def get_text(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
) -> str:
    return adapter.get_text(value, control_identifier)


@tool(
    "set_text: Sets a control's text. mode='value' (default) uses the Value pattern (instant, no focus) "
    "and falls back to focus + typing; mode='type' always focuses the control and types via SendInput. "
    "It does NOT clear the field first. Params: value, control_identifier, text, mode.",
    capability="ui_tree",
    title="Set control text",
    annotations=WRITE,
)
def set_text(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
    text: Annotated[str, Field(description="text to set")],
    mode: Literal["value", "type"] = "value",
) -> str:
    return adapter.set_text(value, control_identifier, text, mode)


@tool(
    "select_item: Selects an item by name in a combo/list/tree control. Tries expand+select, then a "
    "click, then keyboard. NOTE: success is verified through the Value pattern, which WPF ComboBox does "
    "not implement, so a successful selection may still report 'ERROR'. Params: value, control_identifier, item.",
    capability="ui_tree",
    title="Select list/combo item",
    annotations=WRITE,
)
def select_item(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
    item: Annotated[str, Field(description="item name to select")],
) -> str:
    return adapter.select_item(value, control_identifier, item)


@tool(
    "toggle_checkbox: Sets a CheckBox/RadioButton. state: 'check'|'uncheck'|'toggle'. Params: value, control_identifier, state.",
    capability="ui_tree",
    title="Toggle checkbox",
    annotations=WRITE,
)
def toggle_checkbox(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
    state: Literal["check", "uncheck", "toggle"] = "toggle",
) -> str:
    return adapter.toggle_checkbox(value, control_identifier, state)


@tool(
    "get_control_state: Returns enabled/offscreen/checked/value of a control. 'checked' is only present "
    "for toggle/legacy controls. Params: value, control_identifier.",
    capability="ui_tree",
    title="Get control state",
    annotations=READ_ONLY,
)
def get_control_state(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
) -> str:
    return adapter.get_control_state(value, control_identifier)


@tool(
    "set_slider: Sets a slider/range to an absolute value; requires the RangeValue pattern. Params: value, control_identifier, amount.",
    capability="ui_tree",
    title="Set slider value",
    annotations=WRITE,
)
def set_slider(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
    amount: Annotated[float, Field(description="absolute value within the slider range")],
) -> str:
    return adapter.set_slider(value, control_identifier, amount)


@tool(
    "get_selected_text: Returns the selected text of a control (Text pattern, else EM_GETSEL + control text). Params: value, control_identifier.",
    capability="ui_tree",
    title="Get selected text",
    annotations=READ_ONLY,
)
def get_selected_text(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
) -> str:
    return adapter.get_selected_text(value, control_identifier)


@tool(
    "scroll_into_view: Scrolls a control into view (ScrollItem pattern, else a mouse-wheel scroll). Params: value, control_identifier.",
    capability="ui_tree",
    title="Scroll control into view",
    annotations=WRITE,
)
def scroll_into_view(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
) -> str:
    return adapter.scroll_into_view(value, control_identifier)


@tool(
    "wait_for_element: Polls every ~0.3 s until the control appears or timeout (seconds) elapses. Params: value, control_identifier, timeout.",
    capability="ui_tree",
    title="Wait for element",
    annotations=READ_ONLY,
)
def wait_for_element(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
    timeout: Annotated[float, Field(description="max wait in seconds")] = 10.0,
) -> str:
    return adapter.wait_for_element(value, control_identifier, timeout)


@tool(
    "drag_element: Drags a control's center to absolute (x_to, y_to) over duration seconds. Params: value, control_identifier, x_to, y_to, duration.",
    capability="ui_tree",
    title="Drag UI control",
    annotations=WRITE,
)
def drag_element(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
    x_to: Annotated[int, Field(description="target absolute X")],
    y_to: Annotated[int, Field(description="target absolute Y")],
    duration: Annotated[float, Field(description="drag duration in seconds")] = 0.5,
) -> str:
    return adapter.drag_element(value, control_identifier, x_to, y_to, duration)


@tool(
    "screenshot_element: Screenshot of a single UI control's bounding rectangle. Params: value, control_identifier, grid.",
    capability="screenshot_element",
    title="Screenshot (UI control)",
    annotations=READ_ONLY,
)
def screenshot_element(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
    grid: Annotated[bool, Field(description="overlay labeled coordinate lines")] = False,
):
    return _image(adapter.screenshot_element(value, control_identifier, grid=grid))


@tool(
    "highlight_element: Draws a temporary rectangle around a control for visual confirmation. color: "
    "red/green/blue/yellow/orange/white/magenta. The call BLOCKS for duration seconds. Params: value, "
    "control_identifier, duration, color, width.",
    capability="ui_tree",
    title="Highlight UI control",
    annotations=WRITE_IDEMPOTENT,
)
def highlight_element(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
    duration: Annotated[float, Field(description="how long to show the rectangle, in seconds")] = 1.0,
    color: Annotated[str, Field(description="red|green|blue|yellow|orange|white|magenta")] = "red",
    width: Annotated[int, Field(description="rectangle border width in px")] = 3,
) -> str:
    return adapter.highlight_element(value, control_identifier, duration, color, width)


@tool(
    "get_element_at_point: Returns the UI element under absolute (x, y); use to discover what is at a location.",
    capability="ui_tree",
    title="Get element at point",
    annotations=READ_ONLY,
)
def get_element_at_point(
    x: Annotated[int, Field(description="absolute X")],
    y: Annotated[int, Field(description="absolute Y")],
) -> str:
    return adapter.get_element_at_point(x, y)


@tool(
    "get_active_element: Returns the currently focused UI control (name/type/rect), or 'ERROR' if none.",
    capability="ui_tree",
    title="Get active element",
    annotations=READ_ONLY,
)
def get_active_element() -> str:
    return adapter.get_active_element()


@tool(
    "wait_for_element_gone: Polls every ~0.3 s until the control disappears (e.g. a dialog closes) or "
    "timeout (seconds) elapses. Params: value, control_identifier, timeout.",
    capability="ui_tree",
    title="Wait for element gone",
    annotations=READ_ONLY,
)
def wait_for_element_gone(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
    timeout: Annotated[float, Field(description="max wait in seconds")] = 10.0,
) -> str:
    return adapter.wait_for_element_gone(value, control_identifier, timeout)


@tool(
    "scroll_element: Scrolls the mouse wheel with the pointer over a control's center. "
    "direction: 'up'|'down'|'left'|'right'. Params: value, control_identifier, direction, amount.",
    capability="ui_tree",
    title="Scroll over control",
    annotations=WRITE,
)
def scroll_element(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
    direction: Literal["up", "down", "left", "right"] = "down",
    amount: Annotated[int, Field(description="number of wheel steps")] = 3,
) -> str:
    return adapter.scroll_element(value, control_identifier, direction, amount)


@tool(
    "drag_element_to_element: Drag-and-drop from one control to another (both centers). Params: from_value, "
    "from_control, to_value, to_control, duration.",
    capability="ui_tree",
    title="Drag control to control",
    annotations=WRITE,
)
def drag_element_to_element(
    from_value: Annotated[str, Field(description="source " + VALUE)],
    from_control: Annotated[str, Field(description="source " + CTRL)],
    to_value: Annotated[str, Field(description="target " + VALUE)],
    to_control: Annotated[str, Field(description="target " + CTRL)],
    duration: Annotated[float, Field(description="drag duration in seconds")] = 0.5,
) -> str:
    return adapter.drag_element_to_element(from_value, from_control, to_value, to_control, duration)


@tool(
    "get_list_items: Lists item names (ListItem/DataItem/TreeItem) of a list/tree control. Params: value, control_identifier, limit.",
    capability="ui_tree",
    title="Get list items",
    annotations=READ_ONLY,
)
def get_list_items(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
    limit: Annotated[int, Field(description="max items")] = 200,
) -> str:
    return adapter.get_list_items(value, control_identifier, limit)


@tool(
    "get_table_data: Reads a table/grid/list as rows (cells joined by ' | '). Rows are grouped heuristically "
    "by Y position and ordered by X, so irregular layouts may be inaccurate. Params: value, control_identifier, limit.",
    capability="ui_tree",
    title="Get table data",
    annotations=READ_ONLY,
)
def get_table_data(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
    limit: Annotated[int, Field(description="max rows")] = 200,
) -> str:
    return adapter.get_table_data(value, control_identifier, limit)


@tool(
    "expand_element: Expands a tree/expander control (ExpandCollapse pattern). Params: value, control_identifier.",
    capability="ui_tree",
    title="Expand control",
    annotations=WRITE,
)
def expand_element(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
) -> str:
    return adapter.expand_element(value, control_identifier)


@tool(
    "collapse_element: Collapses a tree/expander control (ExpandCollapse pattern). Params: value, control_identifier.",
    capability="ui_tree",
    title="Collapse control",
    annotations=WRITE,
)
def collapse_element(
    value: Annotated[str, Field(description=VALUE)],
    control_identifier: Annotated[str, Field(description=CTRL)],
) -> str:
    return adapter.collapse_element(value, control_identifier)


# ---------------------------------------------------------------------------
# Clipboard files / images
# ---------------------------------------------------------------------------


@tool(
    "clipboard_set_files: Puts file paths on the clipboard (CF_HDROP) for pasting into Explorer. paths is "
    "a single ';'-separated string (a JSON array is NOT accepted by the schema). Relative paths are made absolute.",
    capability="clipboard",
    title="Set clipboard files",
    annotations=WRITE_DESTRUCTIVE,
)
def clipboard_set_files(
    paths: Annotated[str, Field(description="';'-separated file paths")],
) -> str:
    return adapter.clipboard_set_files(paths)


@tool(
    "clipboard_get_files: Returns the file paths currently on the clipboard (CF_HDROP), or 'No files in clipboard.'",
    capability="clipboard",
    title="Get clipboard files",
    annotations=READ_ONLY_ONCE,
)
def clipboard_get_files() -> str:
    return adapter.clipboard_get_files()


@tool(
    "clipboard_set_image: Copies an image file to the clipboard (converted to CF_DIB). Param: path.",
    capability="clipboard",
    title="Set clipboard image",
    annotations=WRITE_DESTRUCTIVE,
)
def clipboard_set_image(path: Annotated[str, Field(description="path to the image file")]) -> str:
    return adapter.clipboard_set_image(path)


@tool(
    "clipboard_get_image: Reads the clipboard image. Without save_path it returns only the size; with "
    "save_path it saves the image (format chosen by the file extension).",
    capability="clipboard",
    title="Get clipboard image",
    annotations=WRITE,
)
def clipboard_get_image(
    save_path: Annotated[str, Field(description="output file path; empty = report size only")] = "",
) -> str:
    return adapter.clipboard_get_image(save_path)


@tool(
    "compare_screenshots: Compares two image files pixel-wise (per-channel threshold 16) and returns "
    "differing pixels/percentage. Different sizes -> 'ERROR: image sizes differ.'. save_diff writes a "
    "black/white difference mask.",
    capability="screenshot",
    title="Compare screenshots",
    annotations=WRITE,
)
def compare_screenshots(
    image_a: Annotated[str, Field(description="path to the first image")],
    image_b: Annotated[str, Field(description="path to the second image")],
    save_diff: Annotated[str, Field(description="optional output path for the diff mask")] = "",
) -> str:
    return adapter.compare_screenshots(image_a, image_b, save_diff)


# ---------------------------------------------------------------------------
# Notifications and virtual desktops
# ---------------------------------------------------------------------------


@tool(
    "list_notifications: Lists current Windows notifications via the WinRT UserNotificationListener (no UI "
    "opened; may require user permission). NOTE: non-ASCII text may be garbled because the PowerShell "
    "output is decoded with the wrong encoding.",
    capability="notifications",
    title="List notifications",
    annotations=READ_ONLY,
)
def list_notifications() -> str:
    return adapter.list_notifications()


@tool(
    "dismiss_notifications: Clears all Windows notifications. The WinRT clear API is unavailable to "
    "desktop apps, so it uses the notification-center 'Clear all' button (best-effort).",
    capability="notifications",
    title="Dismiss notifications",
    annotations=WRITE_DESTRUCTIVE,
)
def dismiss_notifications() -> str:
    return adapter.dismiss_notifications()


@tool(
    "switch_desktop: Switches to the adjacent virtual desktop via the Win+Ctrl+Arrow shortcut. direction: 'left'|'right'.",
    capability="desktop",
    title="Switch virtual desktop",
    annotations=WRITE,
)
def switch_desktop(direction: Literal["left", "right"] = "right") -> str:
    return adapter.switch_desktop(direction)


@tool(
    "move_window_to_desktop: Activates a window (value), then moves it to the adjacent virtual desktop via "
    "Win+Ctrl+Shift+Arrow. direction: 'left'|'right'.",
    capability="desktop",
    title="Move window to desktop",
    annotations=WRITE,
)
def move_window_to_desktop(
    value: Annotated[str, Field(description=VALUE)],
    direction: Literal["left", "right"] = "right",
) -> str:
    return adapter.move_window_to_desktop(value, direction)


@tool(
    "wait_for_pixel_color: Polls get_pixel_color every ~0.2 s until the pixel at absolute (x, y) matches "
    "color (within tolerance) or timeout (seconds) elapses. color: 'r,g,b' (0-255) or '#rrggbb'. Use for "
    "canvas/indicator state checks without OCR.",
    title="Wait for pixel color",
    annotations=READ_ONLY,
)
def wait_for_pixel_color(
    x: Annotated[int, Field(description="absolute X")],
    y: Annotated[int, Field(description="absolute Y")],
    color: Annotated[str, Field(description="'r,g,b' (0-255) or '#rrggbb'")],
    timeout: Annotated[float, Field(description="max wait in seconds")] = 10.0,
    tolerance: Annotated[int, Field(description="allowed per-channel difference 0-255")] = 0,
) -> str:
    return adapter.wait_for_pixel_color(x, y, color, timeout, tolerance)


# ---------------------------------------------------------------------------
# Process control
# ---------------------------------------------------------------------------


@tool(
    "run_app: Launches an application at an absolute path (detached, so it does not block or inherit the "
    "server's stdio). args and cwd are optional. Returns the new PID. Pair with wait_for_window("
    "require_ready=True) before interacting.",
    capability="process",
    title="Launch application",
    annotations=WRITE,
)
def run_app(
    path: Annotated[str, Field(description="absolute path to the executable")],
    args: Annotated[str, Field(description="optional command-line arguments")] = "",
    cwd: Annotated[str, Field(description="optional working directory")] = "",
) -> str:
    return adapter.run_app(path, args, cwd)


@tool(
    "kill_process: Force-kills a process tree by PID (digits) or exact image name (e.g. 'notepad.exe'). "
    "IRREVERSIBLE; prefer close_window for a graceful close. Param: pid_or_name.",
    capability="process",
    title="Kill process",
    annotations=WRITE_DESTRUCTIVE,
)
def kill_process(
    pid_or_name: Annotated[str, Field(description="numeric PID or exact image name, e.g. 'notepad.exe'")],
) -> str:
    return adapter.kill_process(pid_or_name)


@tool(
    "list_processes: Lists running processes as 'PID N | name.exe', optionally filtered by a substring of "
    "the image name. Use to resolve a PID/exe before kill_process.",
    capability="process",
    title="List processes",
    annotations=READ_ONLY,
)
def list_processes(filter: Annotated[str, Field(description="image-name substring; empty = all")] = "") -> str:
    return adapter.list_processes(filter)


class _BearerAuthMiddleware:
    """Require 'Authorization: Bearer <token>' on every HTTP request."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            if headers.get("authorization") != f"Bearer {self.token}":
                body = b'{"error": "unauthorized"}'
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def _is_loopback(host: str) -> bool:
    value = (host or "").strip().lower()
    return value in ("localhost", "127.0.0.1", "::1") or value.startswith("127.")


def _build_remote_app():
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.routing import Mount

    @contextlib.asynccontextmanager
    async def _lifespan(app):
        async with mcp.session_manager.run():
            yield

    middleware = [Middleware(_BearerAuthMiddleware, token=_args.token)] if _args.token else None
    return Starlette(
        routes=[Mount("/", app=mcp.streamable_http_app(host=_args.listen))],
        middleware=middleware,
        lifespan=_lifespan,
    )


def main() -> int:
    if _args.transport == "remote":
        if not _args.token and not _is_loopback(_args.listen):
            print(
                "ERROR: --token is required when --listen is not loopback "
                "(refusing to expose the desktop unauthenticated).",
                file=sys.stderr,
            )
            return 1
        import uvicorn

        uvicorn.run(_build_remote_app(), host=_args.listen, port=_args.port, log_level="warning")
        return 0
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
