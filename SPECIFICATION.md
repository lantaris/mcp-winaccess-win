# Specification — mcp-winaccess-win v1.8.0

## Platform
- **Windows only** (10/11, x64). The package imports Windows-specific ctypes modules and does not
  run on other operating systems.
- Must run in an **interactive desktop session** (logged-in user); `SendInput` and UI Automation
  cannot drive the desktop from a non-interactive/service session.

## Protocol
- MCP via the `mcp` Python SDK v2 (`MCPServer` from `mcp.server.mcpserver`).
- Transports: `local` (stdio, default) and `remote` (streamable-http), selected by `--transport`.
  - `--listen` (default `0.0.0.0`), `--port` (default `8765`).
  - `--token` enables Bearer authentication on the HTTP endpoint and is **required** when
    `--listen` is not loopback.
- Tools are registered by capability (`adapter.supports(capability)`); unsupported tools are
  absent from `tools/list`. 94 tools are exposed on Windows.

## Command-line arguments
| Argument | Default | Meaning |
|---|---|---|
| `--transport` | `local` | `local` (stdio) or `remote` (streamable-http) |
| `--listen` | `0.0.0.0` | HTTP bind address (remote only) |
| `--port` | `8765` | HTTP port (remote only) |
| `--token` | *(none)* | Bearer token required for HTTP (remote only) |
| `--tesseract_cmd` | `auto` | `auto`, or an explicit path to `tesseract.exe` |
| `--auto-tesseract` / `--no-auto-tesseract` | on | automatic Tesseract install |
| `--no-shell` | off | disables the `run_command` tool (shell execution); enabled by default |

## Architecture
- `mcp_winaccess_win/server.py` — thin `@tool(description, capability)` wrappers gated by `adapter.supports(capability)`.
- `mcp_winaccess_win/adapter/__init__.py` — `get_adapter()` returns `WindowsAdapter` (fallback to `BaseAdapter`).
- `mcp_winaccess_win/adapter/base.py` — interface, capability flags, shared helpers, vision/OCR, JPEG encoding, grid drawing.
- `mcp_winaccess_win/adapter/win32_input.py` — ctypes `SendInput`: mouse (absolute/relative), keyboard, Unicode text
  (`KEYEVENTF_UNICODE`), scroll (v/h), drag, key/mouse hold; per-monitor-v2 DPI awareness.
- `mcp_winaccess_win/adapter/win32_screen.py` — Pillow `ImageGrab` (`bbox`, `all_screens`, window handle),
  `EnumDisplayMonitors`/`GetMonitorInfoW` (+ DPI scale), `GetPixel`, cursor drawing, image comparison.
- `mcp_winaccess_win/adapter/win32_clipboard.py` — Win32 clipboard via ctypes: text, files (CF_HDROP), image (CF_DIB),
  clear; `OpenClipboard` retries for transient contention.
- `mcp_winaccess_win/adapter/win32_window.py` — window enumeration/management, foreground activation, process exe
  name, visibility/hung checks, `EM_GETSEL`/`WM_GETTEXT` helpers.
- `mcp_winaccess_win/adapter/win32_overlay.py` — temporary highlight rectangle (GDI).
- `mcp_winaccess_win/adapter/win32_notifications.py` — notification listing via WinRT `UserNotificationListener`.
- `mcp_winaccess_win/adapter/win32_process.py` — process launch (detached, `DETACHED_PROCESS` + `DEVNULL`),
  force-kill (`taskkill /F /T`), enumeration (Toolhelp32 snapshot), and `run_command` (console command
  execution via `cmd.exe /c` or PowerShell, with captured output decoded as UTF-8 → OEM).
- `mcp_winaccess_win/adapter/tesseract_setup.py` — resolves the Tesseract binary or auto-installs it (downloads the
  UB-Mannheim installer, extracts it with 7-Zip into `%LOCALAPPDATA%\mcp-winaccess\tesseract`, and
  fetches `eng`/`rus` language data from tessdata_fast).
- `mcp_winaccess_win/adapter/uia.py` — UI Automation (COM) via `comtypes`: search, patterns, element-at-point,
  list/table extraction, menu state.
- `mcp_winaccess_win/adapter/windows.py` — `WindowsAdapter` composing the modules above.

## Capabilities
`screenshot`, `screenshot_region`, `screenshot_monitor`, `screenshot_window`, `screenshot_element`,
`input`, `monitors`, `clipboard`, `vision`, `ocr`, `window_list`, `window_activate`, `window_close`,
`window_minimize`, `window_maximize`, `window_move`, `window_resize`, `window_snap`, `window_topmost`,
`tray`, `ui_tree`, `menus`, `dialogs`, `notifications`, `desktop`, `process`, `shell`.

## Return conventions
- Every tool returns a human-readable string; failures start with `ERROR: `.
- Screenshot tools return a native MCP `Image` (JPEG) or an `ERROR:` string.

## Dependencies
- `mcp>=2.0.0`, `Pillow>=11.2.1` (needed for `ImageGrab(window=...)`), `comtypes>=1.4.0`,
  `pytesseract>=0.3.10` (OCR is installed by default), `starlette` + `uvicorn` (for the
  `remote`/streamable-http transport and Bearer middleware).
- Extras: `vision` (`opencv-python`).
- The Tesseract **binary** is auto-installed on first OCR use (UB-Mannheim installer extracted with
  7-Zip into `%LOCALAPPDATA%\mcp-winaccess\tesseract`); `--tesseract_cmd <path>` overrides it and
  `--no-auto-tesseract` disables the automatic install.
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

## Changes in 1.8.0
- Added `run_command` (capability `shell`): runs a console command via `cmd.exe /c` (default) or
  PowerShell and returns the exit code and captured output (decoded UTF-8 → OEM). Controlled by the
  `--no-shell` flag (enabled by default).

## Changes in 1.7.0
- Added utility tools for agents: `sleep` (fixed delay), `get_menu_items` (discover menu bar / menu
  items), `get_window_text` (flat text dump of a window), `highlight_region` (highlight an arbitrary
  screen rectangle).
- `click_element` gained a `clicks` parameter (merging `double_click_element`, which was removed);
  `set_text` gained a `clear` parameter (select-all before typing).

## Changes in 1.6.0
- Configuration moved from environment variables to command-line arguments: `--transport
  {local,remote}`, `--listen`, `--port`, `--tesseract_cmd`, `--auto-tesseract`/`--no-auto-tesseract`.
- Added HTTP Bearer authentication (`--token`) for the `remote` transport; a token is required when
  `--listen` is not loopback.
- Repackaged under the `mcp_winaccess_win` namespace (was a bare `server.py` + `adapter`), so the
  installed tool no longer depends on the current working directory or collides with other packages
  named `adapter`. Console script: `mcp-winaccess-win = "mcp_winaccess_win.server:main"`.

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
- `pyproject.toml` (hatchling), `only-include = ["mcp_winaccess_win"]`.
- Console script: `mcp-winaccess-win = "mcp_winaccess_win.server:main"`.
