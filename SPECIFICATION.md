# Specification — mcp-winaccess-win v1.5.0

## Platform
- **Windows only** (10/11, x64). The package imports Windows-specific ctypes modules and does not
  run on other operating systems.
- Must run in an **interactive desktop session** (logged-in user); `SendInput` and UI Automation
  cannot drive the desktop from a non-interactive/service session.

## Protocol
- MCP via the `mcp` Python SDK v2 (`MCPServer` from `mcp.server.mcpserver`).
- Transports: `stdio` (default) and `streamable-http`.
  - `MCP_WINACCESS_TRANSPORT=streamable-http`, `MCP_WINACCESS_HOST`, `MCP_WINACCESS_PORT`.
- Tools are registered by capability (`adapter.supports(capability)`); unsupported tools are
  absent from `tools/list`. 90 tools are exposed on Windows.

## Environment variables
| Variable | Default | Meaning |
|---|---|---|
| `MCP_WINACCESS_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `MCP_WINACCESS_HOST` | `127.0.0.1` | HTTP bind address |
| `MCP_WINACCESS_PORT` | `8765` | HTTP port |
| `TESSERACT_CMD` | auto | Path to `tesseract.exe` (overrides auto-install/`PATH`) |
| `MCP_WINACCESS_AUTO_TESSERACT` | `1` | set to `0` to disable automatic Tesseract install |

## Architecture
- `server.py` — thin `@tool(description, capability)` wrappers gated by `adapter.supports(capability)`.
- `adapter/__init__.py` — `get_adapter()` returns `WindowsAdapter` (fallback to `BaseAdapter`).
- `adapter/base.py` — interface, capability flags, shared helpers, vision/OCR, JPEG encoding, grid drawing.
- `adapter/win32_input.py` — ctypes `SendInput`: mouse (absolute/relative), keyboard, Unicode text
  (`KEYEVENTF_UNICODE`), scroll (v/h), drag, key/mouse hold; per-monitor-v2 DPI awareness.
- `adapter/win32_screen.py` — Pillow `ImageGrab` (`bbox`, `all_screens`, window handle),
  `EnumDisplayMonitors`/`GetMonitorInfoW` (+ DPI scale), `GetPixel`, cursor drawing, image comparison.
- `adapter/win32_clipboard.py` — Win32 clipboard via ctypes: text, files (CF_HDROP), image (CF_DIB),
  clear; `OpenClipboard` retries for transient contention.
- `adapter/win32_window.py` — window enumeration/management, foreground activation, process exe
  name, visibility/hung checks, `EM_GETSEL`/`WM_GETTEXT` helpers.
- `adapter/win32_overlay.py` — temporary highlight rectangle (GDI).
- `adapter/win32_notifications.py` — notification listing via WinRT `UserNotificationListener`.
- `adapter/win32_process.py` — process launch (detached, `DETACHED_PROCESS` + `DEVNULL`),
  force-kill (`taskkill /F /T`) and enumeration (Toolhelp32 snapshot).
- `adapter/tesseract_setup.py` — resolves the Tesseract binary or auto-installs it (downloads the
  UB-Mannheim installer, extracts it with 7-Zip into `%LOCALAPPDATA%\mcp-winaccess\tesseract`, and
  fetches `eng`/`rus` language data from tessdata_fast).
- `adapter/uia.py` — UI Automation (COM) via `comtypes`: search, patterns, element-at-point,
  list/table extraction, menu state.
- `adapter/windows.py` — `WindowsAdapter` composing the modules above.

## Capabilities
`screenshot`, `screenshot_region`, `screenshot_monitor`, `screenshot_window`, `screenshot_element`,
`input`, `monitors`, `clipboard`, `vision`, `ocr`, `window_list`, `window_activate`, `window_close`,
`window_minimize`, `window_maximize`, `window_move`, `window_resize`, `window_snap`, `window_topmost`,
`tray`, `ui_tree`, `menus`, `dialogs`, `notifications`, `desktop`, `process`.

## Return conventions
- Every tool returns a human-readable string; failures start with `ERROR: `.
- Screenshot tools return a native MCP `Image` (JPEG) or an `ERROR:` string.

## Dependencies
- `mcp>=2.0.0`, `Pillow>=11.2.1` (needed for `ImageGrab(window=...)`), `comtypes>=1.4.0`,
  `pytesseract>=0.3.10` (OCR is installed by default).
- Extras: `vision` (`opencv-python`).
- The Tesseract **binary** is auto-installed on first OCR use (UB-Mannheim installer extracted with
  7-Zip into `%LOCALAPPDATA%\mcp-winaccess\tesseract`); `TESSERACT_CMD` overrides it and
  `MCP_WINACCESS_AUTO_TESSERACT=0` disables the automatic install.
- WinRT notification APIs are accessed through `powershell` (no Python dependency).

## Robustness and performance
- DPI awareness is set to per-monitor v2 at import so screen coordinates match `SendInput`.
- Unicode text uses `KEYEVENTF_UNICODE` (no clipboard round-trip).
- Window enumeration uses Win32 (`EnumWindows`); UI Automation is initialized per thread and
  tree traversal is bounded.
- Foreground activation uses an Alt-key unlock plus `SetForegroundWindow`, with an
  `AttachThreadInput` fallback, and reports failure when activation does not take effect.
- Window targeting accepts `title:`, `class:`, `pid:`, `exe:` prefixes; UWP duplicate frames are
  resolved by preferring the visible/largest frame.

## Limitations
- `SendInput` respects UIPI: elevated windows cannot be driven from a non-elevated process.
- `UserNotificationListener.ClearNotifications()` returns `0x80070490` for desktop processes, so
  clearing falls back to the notification-center UI clear-all button (invoke only, no coordinate
  clicks).
- `switch_desktop` / `move_window_to_desktop` use the `Win+Ctrl(+Shift)+Arrow` shortcuts.
- Tesseract language data: `eng` and `rus` are downloaded automatically; add more by dropping
  `*.traineddata` into the managed `tessdata` directory.

## Changes in 1.5.0
- OCR no longer requires a manual Tesseract install: `adapter/tesseract_setup.py` resolves an existing
  binary (`TESSERACT_CMD` / `PATH` / `Program Files`) or downloads and extracts one into
  `%LOCALAPPDATA%\mcp-winaccess\tesseract` (7-Zip extraction, no admin), then fetches `eng` + `rus`
  language data. Controlled by `MCP_WINACCESS_AUTO_TESSERACT` (default on).

## Changes in 1.4.0
- Tool schemas are now self-describing for agents: every parameter carries a description
  (`Annotated[..., Field(description=...)]`), fixed-choice parameters use `Literal` (enums),
  every tool has a human-readable `title`, and every tool carries `ToolAnnotations`
  (`read_only_hint`, `destructive_hint`, `idempotent_hint`).
- Global conventions (`value`, `control_identifier`, coordinates, `ERROR:` contract) remain in the
  server `instructions` and are referenced from parameter descriptions instead of being duplicated.

## Changes in 1.3.0
- Added process tools: `run_app`, `kill_process`, `list_processes` (capability `process`) and
  `wait_for_pixel_color`.
- Merged duplicates: `double_click`/`right_click` into `click(x=None, y=None, button, clicks)`;
  `type_in_element` into `set_text(mode="value"|"type")`; `wait_for_app_ready` into
  `wait_for_window(require_ready=True)`.
- Removed: `get_screen_size` (use `list_monitors`), `find_element` (use `get_all_controls`, which
  now includes `Center`), `list_desktops` (unreliable on Windows 11).
- `get_all_controls` rows now include the control `Center` coordinates.

## Changes in 1.2.0
- OCR (`pytesseract`) is now a core dependency (installed automatically); only `vision` remains optional.
- Removed duplicates: `screenshot_all_monitors` (use `screenshot`), `send_system_key` (use
  `press_key` with a system-key name), `get_menu_item_state` (use `get_control_state`).
- `wait_for_app_ready` now waits until the window is visible and responsive (not just present).
- Added `get_active_element`, `wait_for_text` (OCR), `clipboard_clear`.
- `list_monitors` reports the DPI `scale`; `get_window_state` reports the process `exe`.
- `ocr_screen` / `find_text_on_screen` / `click_text` accept `lang`.

## Tests
- No automated suite is shipped; verification is performed manually, one function at a time,
  against a live interactive desktop session.

## Packaging
- `pyproject.toml` (hatchling), `only-include = ["server.py", "adapter"]`.
- Console script: `mcp-winaccess-win = "server:main"`.
