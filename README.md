# mcp-winaccess-win

**Version 1.5.0** · Windows-only desktop automation MCP server. Built directly on the OS APIs —
**ctypes** (`SendInput`, `ImageGrab`, Win32 windows, clipboard) and **UI Automation** via
`comtypes` — with **no `pyautogui` / `pywinauto` / `pywin32`**.

## Requirements

- **Windows 10/11 (x64)** — this package only runs on Windows.
- Python 3.10+.
- The server must run **inside an interactive desktop session** (a logged-in user), not as a
  background service — otherwise `SendInput`/UI Automation cannot reach the desktop.
- No administrator rights are required for normal user applications (see Limitations).
- OCR auto-install needs network access and 7-Zip (or an existing Tesseract install; see Troubleshooting).

## Install

```
pip install mcp-winaccess-win              # OCR support (pytesseract) is included
pip install "mcp-winaccess-win[vision]"    # optional: OpenCV template matching
```

The **Tesseract binary** (a system program, not a Python package) is downloaded and installed
automatically on first OCR use into `%LOCALAPPDATA%\mcp-winaccess\tesseract` (with `eng` + `rus`
language data). Set `TESSERACT_CMD` to use an existing install, or `MCP_WINACCESS_AUTO_TESSERACT=0`
to disable the automatic install (see Troubleshooting).

## Run

```
python server.py
# or the console script
mcp-winaccess-win
```

Remote MCP (streamable-http):

```
set MCP_WINACCESS_TRANSPORT=streamable-http
set MCP_WINACCESS_HOST=127.0.0.1
set MCP_WINACCESS_PORT=8765
python server.py
```

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `MCP_WINACCESS_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `MCP_WINACCESS_HOST` | `127.0.0.1` | HTTP bind address |
| `MCP_WINACCESS_PORT` | `8765` | HTTP port |
| `TESSERACT_CMD` | auto | Path to `tesseract.exe` (overrides auto-install/`PATH`) |
| `MCP_WINACCESS_AUTO_TESSERACT` | `1` | set to `0` to disable automatic Tesseract install |

## OpenCode config (`opencode.jsonc`)

```jsonc
{
  "mcp": {
    "winaccess": {
      "type": "local",
      "command": ["uvx", "mcp-winaccess-win"],
      "enabled": true
    }
  }
}
```

## Architecture

| Layer | Implementation |
|---|---|
| Mouse / keyboard | `SendInput` (ctypes); text via `KEYEVENTF_UNICODE` (Unicode without the clipboard) |
| Screenshots | Pillow `ImageGrab` (`bbox`, `all_screens`, window handle) |
| Windows | ctypes `EnumWindows` / `MoveWindow` / `SetWindowPos` / `PostMessage` |
| Clipboard | Win32 clipboard via ctypes |
| UI tree, menus, dialogs | UI Automation COM via `comtypes` |
| Vision / OCR | OpenCV template matching / pytesseract with an auto-installed Tesseract binary |

Modules: `server.py` (tool wrappers), `adapter/windows.py` (adapter), `adapter/win32_input.py`,
`adapter/win32_screen.py`, `adapter/win32_window.py`, `adapter/win32_clipboard.py`,
`adapter/win32_overlay.py` (element highlight), `adapter/win32_notifications.py`,
`adapter/win32_process.py` (launch/kill/enumerate processes),
`adapter/tesseract_setup.py` (auto-install OCR engine), `adapter/uia.py` (UI Automation),
`adapter/base.py` (interface + shared helpers).

## Conventions

- `value` (window identifier): a partial title/class (`str`), a window handle (`int`), or a
  prefix `title:`, `class:`, `pid:N`, `exe:name.exe`.
- `control_identifier`: the `ID` returned by `get_all_controls` (`element_N`) or a control
  `Name`/`AutoID`.
- All coordinates are **absolute screen pixels** (virtual-desktop space).
- Any failure returns a string starting with `ERROR:`; success messages are human-readable.
- Tool schemas carry per-parameter descriptions, `Literal` enums for fixed choices, a human-readable
  `title`, and behavioural hints (`readOnlyHint`/`destructiveHint`/`idempotentHint`) so agents can tell
  observing tools from state-changing ones.

## Tools

90 tools. They are registered only when the adapter advertises the matching **capability**;
unsupported tools are hidden.

### Screenshots and display — `screenshot`, `screenshot_region`, `screenshot_monitor`, `screenshot_window`, `screenshot_element`
- `screenshot(grid=False, include_cursor=False)` — the whole virtual desktop (all monitors); `grid=True` overlays labeled 100 px lines; `include_cursor=True` draws the mouse pointer.
- `screenshot_jpg(path="")` — save a JPEG (temp file when `path` is empty).
- `screenshot_region(left, top, width, height, grid=False)`.
- `screenshot_monitor(index=0, grid=False)` — a single monitor.
- `screenshot_window(value, grid=False)` — capture a window (even if partially occluded).
- `screenshot_element(value, control_identifier, grid=False)` — capture a single control.
- `compare_screenshots(image_a, image_b, save_diff="")` — differing pixels/percentage between two image files.
- `list_monitors()` (includes DPI `scale`), `image_to_screen_coords(x, y, monitor_index=0)`, `get_pixel_color(x, y)`, `wait_for_pixel_color(x, y, color, timeout=10, tolerance=0)`.

### Mouse and keyboard — `input`
- `get_mouse_position()`, `move_mouse(x, y)`, `mouse_move_relative(dx, dy)`.
- `click(x=None, y=None, button="left", clicks=1)` — omit `x`/`y` to click at the current position; `clicks=2` is a double-click, `button="right"` a right-click.
- `mouse_down(x=0, y=0, button="left")` / `mouse_up(button="left")` — hold/release for manual drags.
- `drag(x_from, y_from, x_to, y_to, duration=0.5)`, `scroll(direction="down", amount=3, x=0, y=0)`.
- `type_text(text)` (Unicode), `hotkey(keys)` (e.g. `"ctrl+shift+s"`).
- `press_key(key)` — a key (`enter`, `tab`, `esc`, `f5`, letters/digits) or a system key (`win`, `volumeup`, `volumedown`, `volumemute`, `playpause`, `nexttrack`, `prevtrack`, `printscreen`).
- `key_down(key)` / `key_up(key)` — hold/release keys (e.g. Shift range selection).

### Clipboard — `clipboard`
- `clipboard_get()`, `clipboard_set(text)`, `clipboard_clear()`.
- `clipboard_set_files(paths)` / `clipboard_get_files()` — file paths (CF_HDROP).
- `clipboard_set_image(path)` / `clipboard_get_image(save_path="")` — image (CF_DIB).

### Vision / OCR — `vision`, `ocr`
- `locate_image_on_screen(image_path, confidence=0.9)`, `wait_for_image(...)`, `click_image(...)` — require the `vision` extra.
- `ocr_screen(left, top, width, height, lang="")`, `find_text_on_screen(text, confidence, lang)`, `click_text(text, confidence, lang)` — `lang` e.g. `"eng"` or `"rus+eng"`; the Tesseract binary auto-installs on first use.
- `wait_for_text(text, timeout, lang, confidence)` — waits until OCR finds text (for canvas/custom UI).

### Windows — `window_list`, `window_activate`, `window_close`, `window_minimize`, `window_maximize`, `window_move`, `window_resize`, `window_snap`, `window_topmost`
- `list_windows(process="")`, `find_window(value)`, `get_active_window()`, `get_window_state(value)` (rect, handle, pid, exe, state, monitor).
- `switch_to_window(value)`, `wait_for_window(value, timeout, require_ready=False)` (`require_ready=True` waits until visible and responsive), `wait_for_window_gone(value, timeout)`.
- `minimize_window(value)`, `maximize_window(value)`, `restore_window(value)`, `close_window(value)`.
- `move_window(value, x, y)`, `resize_window(value, x, y, width, height)`, `snap_window(value, position)`.
- `set_always_on_top(value, enabled)`.

`value` accepts a partial window title (`str`), a window handle (`int`), or a prefix: `title:`, `class:`, `pid:N`, `exe:name.exe`. `list_windows(process=...)` filters by exe name or PID.

### Menus and dialogs — `menus`, `dialogs`, `tray`
- `menu_select(value, path)` (e.g. `"File->Save As"`), `context_menu_click(x, y, item)`.
- `list_dialogs()`, `handle_dialog(button_text, title="")`.
- `file_dialog_set_path(path, title="")`, `file_dialog_confirm(title="")`.
- `tray_icon_click(name, action="left")`.

### UI tree (semantic controls) — `ui_tree`
- `get_all_controls(value, limit=150, query="", control_type="")` — use the returned `ID` (`element_N`)
  or `Name`/`AutoID` as `control_identifier`; each row includes `Rect` and `Center`.
- `click_element`, `double_click_element`, `get_text`, `set_text(value, control_identifier, text, mode="value")`
  (`mode="type"` forces focus + typing), `select_item`,
  `toggle_checkbox`, `get_control_state`, `set_slider`, `get_selected_text`, `scroll_into_view`,
  `wait_for_element`, `drag_element`.

### Element inspection — `ui_tree`
- `get_element_at_point(x, y)` — element under a screen point.
- `get_active_element()` — the currently focused control.
- `highlight_element(value, control_identifier, duration=1.0, color="red", width=3)` — temporary rectangle (visual confirmation).
- `wait_for_element_gone(value, control_identifier, timeout=10)` — wait until a control disappears.
- `expand_element(value, control_identifier)` / `collapse_element(value, control_identifier)` — tree/expander controls.
- `get_control_state(value, control_identifier)` — enabled/offscreen/checked/value (works for checkboxes, menu items, sliders).
- `drag_element_to_element(from_value, from_control, to_value, to_control, duration=0.5)` — drag-and-drop between controls.
- `scroll_element(value, control_identifier, direction="down", amount=3)`.

### Lists and tables — `ui_tree`
- `get_list_items(value, control_identifier, limit=200)` — item names of a list/tree.
- `get_table_data(value, control_identifier, limit=200)` — table/grid rows (cells joined by ` | `).

### Notifications — `notifications`
- `list_notifications()` — current Windows notifications via the `UserNotificationListener` API (no UI opened).
- `dismiss_notifications()` — clears all notifications (UI clear-all button; the WinRT clear API is unavailable to desktop apps).

### Virtual desktops — `desktop`
- `switch_desktop(direction="right")` — switch to the adjacent desktop.
- `move_window_to_desktop(value, direction="right")` — move a window to the adjacent desktop.

### Processes — `process`
- `run_app(path, args="", cwd="")` — launch an application detached (returns its PID); pair with `wait_for_window(require_ready=True)`.
- `kill_process(pid_or_name)` — force-kill a process tree (irreversible; prefer `close_window`).
- `list_processes(filter="")` — list running processes as `PID N | name.exe`.

## Examples

```
# 12 + 34 in Calculator
click_element("Калькулятор", "clearButton")
click_element("Калькулятор", "num1Button")
click_element("Калькулятор", "num2Button")
click_element("Калькулятор", "plusButton")
click_element("Калькулятор", "num3Button")
click_element("Калькулятор", "num4Button")
click_element("Калькулятор", "equalButton")
get_text("Калькулятор", "CalculatorResults")   # -> 46

# Screenshot with a coordinate grid
screenshot(grid=True)
```

## Limitations

- **UIPI**: `SendInput` cannot drive windows with higher integrity (elevated apps) from a
  non-elevated process. Run the server elevated to automate those.
- **Foreground activation**: `switch_to_window` uses the Alt-unlock + `SetForegroundWindow`
  technique; some always-on-top/system windows may still refuse focus.
- **UWP apps** (e.g. Calculator) can expose two `ApplicationFrameWindow` instances (one minimized);
  the adapter prefers the visible/largest frame.
- **DPI**: the process is per-monitor-v2 DPI aware, so coordinates match physical pixels.

## Troubleshooting

- **OCR fails** — the Tesseract binary is auto-installed on first use (downloaded via the UB-Mannheim
  installer, extracted with 7-Zip, into `%LOCALAPPDATA%\mcp-winaccess\tesseract`). If that fails
  (no network / no 7-Zip), install Tesseract manually and set `TESSERACT_CMD`. Language data `eng`
  and `rus` are fetched automatically; add more by dropping `*.traineddata` into the managed `tessdata`.
- **Vision tools missing** — install the `vision` extra (`opencv-python`).
- **UI tree tools missing** — `comtypes` is required (installed with the package).

## Tests

The `tests/` suite was removed; verification is done manually, function by function, against a
live desktop session.
