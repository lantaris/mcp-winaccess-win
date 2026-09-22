"""Windows adapter built on ctypes + UI Automation (no pyautogui/pywinauto)."""

from __future__ import annotations

import importlib.util
import re
import time
from typing import Any

from mcp_winaccess_win.adapter import win32_clipboard as clipboard
from mcp_winaccess_win.adapter import win32_input as input
from mcp_winaccess_win.adapter import win32_notifications
from mcp_winaccess_win.adapter import win32_process as process
from mcp_winaccess_win.adapter import win32_screen as screen
from mcp_winaccess_win.adapter import win32_window as win
from mcp_winaccess_win.adapter.base import SYSTEM_KEYS, BaseAdapter

_UIA_AVAILABLE = importlib.util.find_spec("comtypes") is not None


class WindowsAdapter(BaseAdapter):
    """Full Windows automation: SendInput, ImageGrab, ctypes windows, UIA tree."""

    name = "windows"

    def __init__(self):
        self.uia: Any = None
        if _UIA_AVAILABLE:
            try:
                from mcp_winaccess_win.adapter.uia import UiaClient

                self.uia = UiaClient()
            except Exception:
                self.uia = None

    def _platform_capabilities(self) -> set[str]:
        caps = {
            "screenshot_window",
            "screenshot_element",
            "tray",
            "notifications",
            "desktop",
            "process",
            "window_list",
            "window_activate",
            "window_close",
            "window_minimize",
            "window_maximize",
            "window_move",
            "window_resize",
            "window_snap",
            "window_topmost",
        }
        if self.uia is not None:
            caps |= {"ui_tree", "menus", "dialogs"}
        return caps

    def _clipboard_available(self) -> bool:
        return True

    # --- display ---

    def _screen_size(self) -> tuple[int, int]:
        return input.screen_size()

    def screenshot(self, grid: bool = False, include_cursor: bool = False):
        image = screen.grab()
        if include_cursor:
            image = screen.draw_cursor(image)
        return self._draw_grid(image, 0, 0) if grid else image

    def screenshot_region(self, left: int, top: int, width: int, height: int, grid: bool = False):
        image = screen.grab((left, top, left + width, top + height))
        return self._draw_grid(image, left, top) if grid else image

    def screenshot_window(self, value, grid: bool = False):
        handle = self._find_handle(value)
        if handle is None:
            return None
        image = screen.grab_window(handle)
        if image is None:
            left, top, right, bottom = win.window_rect(handle)
            image = screen.grab((left, top, right, bottom))
        if image is None:
            return None
        if grid:
            left, top, _, _ = win.window_rect(handle)
            image = self._draw_grid(image, left, top)
        return image

    def get_pixel_color(self, x: int, y: int) -> str:
        try:
            red, green, blue = screen.get_pixel(x, y)
        except Exception as exc:
            return f"ERROR: pixel read failed: {exc}"
        return f"Pixel ({x}, {y}) = RGB({red}, {green}, {blue})"

    def get_mouse_position(self) -> str:
        x, y = input.get_cursor_position()
        return f"Mouse position: ({x}, {y})"

    # --- input ---

    def move_mouse(self, x: int, y: int) -> str:
        input.move_mouse(x, y)
        return f"Mouse moved to ({x}, {y})"

    def click(self, x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1) -> str:
        if x is None or y is None:
            x, y = input.get_cursor_position()
            where = f"current position ({x}, {y})"
        else:
            where = f"({x}, {y})"
        input.click(x, y, button, clicks)
        return f"Clicked {button} x{clicks} at {where}"

    def drag(self, x_from: int, y_from: int, x_to: int, y_to: int, duration: float = 0.5) -> str:
        input.drag(x_from, y_from, x_to, y_to, duration)
        return f"DRAGGED from ({x_from}, {y_from}) to ({x_to}, {y_to})"

    def scroll(self, direction: str = "down", amount: int = 3, x: int = 0, y: int = 0) -> str:
        direction = (direction or "down").lower()
        if x or y:
            input.move_mouse(x, y)
        horizontal = direction in ("left", "right")
        if horizontal:
            clicks = 120 if direction == "right" else -120
        else:
            clicks = -120 if direction == "down" else 120
        for _ in range(max(1, amount)):
            input.scroll(clicks, horizontal=horizontal)
        where = "current position" if not (x or y) else f"({x}, {y})"
        return f"SCROLLED {direction} {amount} at {where}"

    def type_text(self, text: str) -> str:
        input.type_text(text)
        return f"Typed: {text}"

    def press_key(self, key: str) -> str:
        mapped = SYSTEM_KEYS.get((key or "").lower().strip(), key)
        if input.press_key(mapped):
            return f"Pressed key: {mapped}"
        return f"ERROR: unknown key '{mapped}'."

    def hotkey(self, keys) -> str:
        input.hotkey(keys)
        return f"Pressed hotkey: {keys}"

    # --- clipboard ---

    def clipboard_get(self) -> str:
        try:
            return f"Clipboard: {clipboard.get_text()}"
        except Exception as exc:
            return f"ERROR: clipboard read failed: {exc}"

    def clipboard_clear(self) -> str:
        try:
            clipboard.clear()
            return "Clipboard cleared."
        except Exception as exc:
            return f"ERROR: clipboard clear failed: {exc}"

    def clipboard_set(self, text: str) -> str:
        try:
            clipboard.set_text(text)
            return "Clipboard updated."
        except Exception as exc:
            return f"ERROR: clipboard write failed: {exc}"

    # --- window helpers ---

    def _window_matches(self, value, info: dict) -> bool:
        value = self._coerce(value)
        if isinstance(value, int):
            return info["handle"] == value
        text = str(value)
        prefix, separator, rest = text.partition(":")
        if separator:
            key = prefix.lower()
            rest = rest.strip().lower()
            if key == "pid":
                return str(info.get("pid")) == rest
            if key == "exe":
                return rest in win.process_exe_name(info.get("pid", 0)).lower()
            if key == "title":
                return rest in (info.get("title") or "").lower()
            if key == "class":
                return rest in (info.get("class") or "").lower()
        return self._match(value, info["title"], info["class"], info["handle"])

    def _find_handle(self, value):
        matches = [info for info in win.enum_windows() if self._window_matches(value, info)]
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]["handle"]

        def score(info: dict) -> int:
            points = 0
            if info["class"] == "ApplicationFrameWindow":
                points += 100000
            elif info["class"] == "Windows.UI.Core.CoreWindow":
                points -= 50000
            left, top, right, bottom = info["rect"]
            points += max(0, (right - left)) * max(0, (bottom - top)) // 1000
            return points

        return max(matches, key=score)["handle"]

    def _window_element(self, value):
        if self.uia is None:
            return None
        handle = self._find_handle(value)
        if handle is None:
            return None
        return self.uia.element_from_handle(handle)

    def window_rect(self, value):
        handle = self._find_handle(value)
        if handle is None:
            return None
        left, top, right, bottom = win.window_rect(handle)
        return left, top, right - left, bottom - top

    # --- windows ---

    def list_windows(self, process: str = "") -> str:
        lines = []
        needle = (process or "").lower()
        for info in win.enum_windows():
            if not info["title"].strip():
                continue
            if needle:
                exe = win.process_exe_name(info["pid"]).lower()
                if needle not in exe and needle != str(info["pid"]):
                    continue
            left, top, right, bottom = info["rect"]
            lines.append(
                f"Title: '{info['title']}' | Class: '{info['class']}' | Handle: {info['handle']} | "
                f"PID: {info['pid']} | Exe: {win.process_exe_name(info['pid'])} | Rect: ({left}, {top}, {right}, {bottom})"
            )
        return "\n".join(lines) if lines else "No visible windows found."

    def find_window(self, value) -> str:
        matches: list[str] = []
        for info in win.enum_windows():
            if self._window_matches(value, info):
                left, top, right, bottom = info["rect"]
                matches.append(
                    f"[{len(matches)}] Title: '{info['title']}' | Class: '{info['class']}' | "
                    f"Handle: {info['handle']} | PID: {info['pid']} | Rect: ({left}, {top}, {right}, {bottom})"
                )
        if not matches:
            return f"ERROR: Window '{value}' not found."
        return "\n".join(matches)

    def get_active_window(self) -> str:
        handle = win.foreground_window()
        if not handle:
            return "ERROR: no foreground window."
        for info in win.enum_windows():
            if info["handle"] == handle:
                left, top, right, bottom = info["rect"]
                return (
                    f"Active window: title='{info['title']}', class='{info['class']}', "
                    f"handle={info['handle']}, pid={info['pid']}, rect=({left}, {top}, {right}, {bottom})"
                )
        return "ERROR: could not resolve active window."

    def switch_to_window(self, value) -> str:
        handle = self._find_handle(value)
        if handle is None:
            return f"ERROR: Window '{value}' not found."
        if win.set_foreground(handle):
            return f"Activated window '{win.window_text(handle)}'"
        return f"ERROR: could not activate '{value}'."

    def manage_window(self, value, action: str = "restore", x: int = 0, y: int = 0) -> str:
        handle = self._find_handle(value)
        if handle is None:
            return f"ERROR: Window '{value}' not found."
        action = (action or "restore").lower()
        if action == "minimize":
            win.show_window(handle, win.SW_MINIMIZE)
        elif action == "maximize":
            win.show_window(handle, win.SW_MAXIMIZE)
        elif action == "restore":
            win.show_window(handle, win.SW_RESTORE)
        elif action == "close":
            win.close_window(handle)
        elif action == "move":
            left, top, right, bottom = win.window_rect(handle)
            win.move_window(handle, x, y, right - left, bottom - top)
        else:
            return f"ERROR: unknown action '{action}'."
        return f"{action.capitalize()}: {win.window_text(handle)}"

    def minimize_window(self, value) -> str:
        handle = self._find_handle(value)
        if handle is None:
            return f"ERROR: Window '{value}' not found."
        win.show_window(handle, win.SW_MINIMIZE)
        return f"Minimized: {win.window_text(handle)}"

    def maximize_window(self, value) -> str:
        handle = self._find_handle(value)
        if handle is None:
            return f"ERROR: Window '{value}' not found."
        win.show_window(handle, win.SW_MAXIMIZE)
        return f"Maximized: {win.window_text(handle)}"

    def restore_window(self, value) -> str:
        handle = self._find_handle(value)
        if handle is None:
            return f"ERROR: Window '{value}' not found."
        win.show_window(handle, win.SW_RESTORE)
        return f"Restored: {win.window_text(handle)}"

    def move_window(self, value, x: int, y: int) -> str:
        handle = self._find_handle(value)
        if handle is None:
            return f"ERROR: Window '{value}' not found."
        left, top, right, bottom = win.window_rect(handle)
        win.move_window(handle, x, y, right - left, bottom - top)
        return f"Moved: {win.window_text(handle)} to ({x}, {y})"

    def resize_window(self, value, x: int, y: int, width: int, height: int) -> str:
        handle = self._find_handle(value)
        if handle is None:
            return f"ERROR: Window '{value}' not found."
        win.move_window(handle, x, y, width, height)
        return f"Resized '{win.window_text(handle)}' to ({x}, {y}, {width}, {height})"

    def snap_window(self, value, position: str = "left") -> str:
        handle = self._find_handle(value)
        if handle is None:
            return f"ERROR: Window '{value}' not found."
        monitors = self._get_monitors()
        m = next((mm for mm in monitors if mm["primary"]), monitors[0])
        left, top, width, height = m["left"], m["top"], m["width"], m["height"]
        half = width // 2
        layout = {
            "left": (left, top, half, height),
            "right": (left + half, top, width - half, height),
            "top": (left, top, width, height // 2),
            "bottom": (left, top + height // 2, width, height - height // 2),
            "maximize": (left, top, width, height),
        }
        position = (position or "left").lower()
        if position not in layout:
            return f"ERROR: unknown position '{position}'."
        win.show_window(handle, win.SW_RESTORE)
        x, y, w, h = layout[position]
        win.move_window(handle, x, y, w, h)
        return f"Snapped '{win.window_text(handle)}' to {position}"

    def set_always_on_top(self, value, enabled: bool = True) -> str:
        handle = self._find_handle(value)
        if handle is None:
            return f"ERROR: Window '{value}' not found."
        win.set_topmost(handle, enabled)
        return f"Always-on-top {'enabled' if enabled else 'disabled'} for '{win.window_text(handle)}'"

    def wait_for_window(self, value, timeout: float = 10.0, require_ready: bool = False) -> str:
        start = time.time()
        while time.time() - start < timeout:
            handle = self._find_handle(value)
            if handle is not None and (not require_ready or (win.is_visible(handle) and not win.is_hung(handle))):
                state = "is ready (visible, responsive)" if require_ready else "found"
                return f"Window '{value}' {state} (title={win.window_text(handle)})."
            time.sleep(0.3)
        if require_ready:
            return f"ERROR: window '{value}' not ready within {timeout}s."
        return f"ERROR: timeout ({timeout}s) waiting for '{value}'."

    def get_window_state(self, value) -> str:
        handle = self._find_handle(value)
        if handle is None:
            return f"ERROR: Window '{value}' not found."
        left, top, right, bottom = win.window_rect(handle)
        state = "normal"
        if win.is_minimized(handle):
            state = "minimized"
        elif win.is_maximized(handle):
            state = "maximized"
        return (
            f"Window: title={win.window_text(handle)}, rect=({left}, {top}, {right}, {bottom}), "
            f"handle={handle}, pid={win.process_id(handle)}, exe={win.process_exe_name(win.process_id(handle))}, "
            f"state={state}, monitor={self._monitor_index_for(left, top)}"
        )

    def close_window(self, value) -> str:
        handle = self._find_handle(value)
        if handle is None:
            return f"ERROR: Window '{value}' not found."
        title = win.window_text(handle)
        win.close_window(handle)
        return f"Closed window '{title}'"

    def _monitor_index_for(self, x: int, y: int) -> int:
        for m in self._get_monitors():
            if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
                return m["index"]
        return 0

    def _get_monitors(self) -> list[dict]:
        return screen.get_monitors()

    # --- UI Automation helpers ---

    def _require_uia(self) -> str | None:
        if self.uia is None:
            return "ERROR: UI Automation is unavailable (install comtypes)."
        return None

    @staticmethod
    def _format_control(info: dict, index: int) -> str:
        rect = info.get("rect") or (0, 0, 0, 0)
        center = f"({(rect[0] + rect[2]) // 2}, {(rect[1] + rect[3]) // 2})"
        return (
            f"ID: 'element_{index}' | Name: '{info.get('name', '').strip()}' | "
            f"AutoID: '{info.get('automation_id', '').strip()}' | Type: {info.get('control_type', '')} | "
            f"Class: '{info.get('class_name', '').strip()}' | Text: '{info.get('text', '')}' | "
            f"Handle: {info.get('handle', 0)} | Rect: ({rect[0]}, {rect[1]}, {rect[2]}, {rect[3]}) | "
            f"Center: {center}"
        )

    def _window_controls(self, value):
        element = self._window_element(value)
        if element is None:
            return None
        return self.uia.descendants(element)

    def _find_control(self, value, control_identifier: str):
        element = self._window_element(value)
        if element is None:
            return None
        identifier = str(control_identifier)
        if identifier.startswith("element_"):
            try:
                index = int(identifier.split("_", 1)[1])
                controls = self.uia.descendants(element)
                if 0 <= index < len(controls):
                    return controls[index]
            except Exception:
                pass
        return self.uia.find(element, name=identifier) or self.uia.find(element, automation_id=identifier)

    # --- UI tree ---

    def get_all_controls(self, value, limit: int = 150, query: str = "", control_type: str = "") -> str:
        error = self._require_uia()
        if error:
            return error
        element = self._window_element(value)
        if element is None:
            return f"ERROR: Window '{value}' not found."
        lines = []
        needle = (query or "").lower()
        wanted = (control_type or "").lower()
        for index, control in enumerate(self.uia.descendants(element)):
            info = self.uia.info(control)
            if wanted and wanted not in info["control_type"].lower():
                continue
            if needle and needle not in f"{info['name']} {info['text']}".lower():
                continue
            lines.append(self._format_control(info, index))
            if len(lines) >= limit:
                lines.append(f"... truncated at {limit} controls.")
                break
        return "\n".join(lines) if lines else "No controls found."

    def click_element(self, value, control_identifier: str) -> str:
        error = self._require_uia()
        if error:
            return error
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        if self.uia.invoke(control) or self.uia.legacy_default_action(control):
            return f"Clicked control '{control_identifier}'"
        center = self.uia.center(control)
        if center is None:
            return f"ERROR: control '{control_identifier}' has no position."
        input.click(center[0], center[1])
        return f"Clicked control '{control_identifier}' at {center}"

    def double_click_element(self, value, control_identifier: str) -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        center = self.uia.center(control)
        if center is None:
            return f"ERROR: control '{control_identifier}' has no position."
        input.double_click(center[0], center[1])
        return f"Double clicked control '{control_identifier}' at {center}"

    def get_text(self, value, control_identifier: str) -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        text = self.uia.value_get(control) or self.uia.text(control) or self.uia.info(control)["name"]
        return f"Text: '{text}'"

    def set_text(self, value, control_identifier: str, text: str, mode: str = "value") -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        if mode == "type":
            self.uia.set_focus(control)
            input.type_text(text)
            return f"Typed text '{text}' into '{control_identifier}'"
        if self.uia.value_set(control, text):
            return f"Set text '{text}' into '{control_identifier}'"
        self.uia.set_focus(control)
        input.type_text(text)
        return f"Typed text '{text}' into '{control_identifier}'"

    def select_item(self, value, control_identifier: str, item: str) -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."

        def current() -> str:
            return str(self.uia.value_get(control) or "")

        self.uia.expand(control)
        time.sleep(0.2)
        target = self.uia.find(control, name=item) or self.uia.find(control, automation_id=item)
        if target is not None:
            self.uia.select(target)
            time.sleep(0.2)
            if item.lower() in current().lower():
                return f"Selected '{item}' in '{control_identifier}'"
            center = self.uia.center(target)
            if center:
                input.click(center[0], center[1])
                time.sleep(0.2)
                if item.lower() in current().lower():
                    return f"Selected '{item}' in '{control_identifier}'"
        self.uia.set_focus(control)
        input.hotkey("ctrl+a")
        input.type_text(item)
        input.press_key("tab")
        time.sleep(0.3)
        if item.lower() in current().lower():
            return f"Selected '{item}' in '{control_identifier}'"
        return f"ERROR: could not select '{item}' in '{control_identifier}'."

    def toggle_checkbox(self, value, control_identifier: str, state: str = "toggle") -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        control_type = self.uia.info(control)["control_type"].lower()
        if control_type not in ("checkbox", "radiobutton"):
            return f"ERROR: control '{control_identifier}' is not a checkbox/radio button."
        current = self.uia.toggle_state(control)
        desired = (state or "toggle").lower()
        want_on = desired in ("check", "on", "true", "1")
        want_off = desired in ("uncheck", "off", "false", "0")
        if (want_on and current == 1) or (want_off and current == 0):
            return f"Checkbox '{control_identifier}' already {desired}"
        if self.uia.toggle(control):
            return f"Checkbox '{control_identifier}' set to {desired}"
        center = self.uia.center(control)
        if center:
            input.click(center[0], center[1])
            return f"Checkbox '{control_identifier}' set to {desired}"
        return f"ERROR: could not toggle '{control_identifier}'."

    def get_control_state(self, value, control_identifier: str) -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        info = self.uia.info(control)
        parts = [f"enabled={info['enabled']}", f"offscreen={info['offscreen']}"]
        toggle = self.uia.menu_item_state(control)
        if toggle is not None:
            parts.append(f"checked={toggle}")
        value_text = self.uia.value_get(control)
        if value_text is not None:
            parts.append(f"value={value_text}")
        return f"State of '{control_identifier}': " + ", ".join(parts)

    def set_slider(self, value, control_identifier: str, amount: float) -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        if self.uia.range_set(control, amount):
            return f"Set slider '{control_identifier}' to {amount}"
        return f"ERROR: control '{control_identifier}' does not support range value."

    def get_selected_text(self, value, control_identifier: str) -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        text = self.uia.selection_text(control)
        if text:
            return f"Selected text: '{text}'"
        handle = self.uia.info(control).get("handle") or 0
        if handle:
            try:
                start, end = win.get_selection(handle)
                if end > start:
                    content = self.uia.value_get(control) or win.get_text_content(handle)
                    if content:
                        return f"Selected text: '{content[start:end]}'"
            except Exception:
                pass
        return "ERROR: no selected text available."

    def scroll_into_view(self, value, control_identifier: str) -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        if self.uia.scroll_into_view(control):
            return f"Scrolled '{control_identifier}' into view"
        center = self.uia.center(control)
        if center:
            input.move_mouse(center[0], center[1])
            input.scroll(-120)
            return f"Scrolled '{control_identifier}' into view"
        return f"ERROR: could not scroll '{control_identifier}'."

    def wait_for_element(self, value, control_identifier: str, timeout: float = 10.0) -> str:
        start = time.time()
        while time.time() - start < timeout:
            if self._find_control(value, control_identifier) is not None:
                return f"ELEMENT FOUND: '{control_identifier}'"
            time.sleep(0.3)
        return f"ERROR: timeout ({timeout}s) waiting for '{control_identifier}'."

    def drag_element(self, value, control_identifier: str, x_to: int, y_to: int, duration: float = 0.5) -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        center = self.uia.center(control)
        if center is None:
            return f"ERROR: control '{control_identifier}' has no position."
        input.drag(center[0], center[1], x_to, y_to, duration)
        return f"Dragged '{control_identifier}' to ({x_to}, {y_to})"

    # --- dialogs ---

    def _dialog_windows(self) -> list[dict]:
        result: list[dict] = []
        for info in win.enum_windows():
            if info["class"] in ("Button", "Shell_TrayWnd", "Progman"):
                continue
            if info["class"] == "#32770" or (win.owner(info["handle"]) and info["title"].strip()):
                result.append(info)
        return result

    def list_dialogs(self) -> str:
        lines = [f"Dialog: '{info['title']}' | Class: '{info['class']}' | Handle: {info['handle']}" for info in self._dialog_windows()]
        return "\n".join(lines) if lines else "No dialogs found."

    def _dialog_scopes(self, title: str = ""):
        if self.uia is None:
            return []
        scopes = []
        for info in self._dialog_windows():
            if not title or title.lower() in info["title"].lower():
                element = self.uia.element_from_handle(info["handle"])
                if element is not None:
                    scopes.append(element)
        handle = win.foreground_window()
        if handle:
            element = self.uia.element_from_handle(handle)
            if element is not None and element not in scopes:
                scopes.append(element)
        return scopes

    def handle_dialog(self, button_text: str, title: str = "") -> str:
        error = self._require_uia()
        if error:
            return error
        needle = button_text.lower()
        for scope in self._dialog_scopes(title):
            for control in self.uia.descendants(scope):
                info = self.uia.info(control)
                if "button" in info["control_type"].lower() and needle in info["name"].lower():
                    if self.uia.invoke(control) or self.uia.legacy_default_action(control):
                        return f"Clicked dialog button '{info['name']}'"
                    center = self.uia.center(control)
                    if center:
                        input.click(center[0], center[1])
                        return f"Clicked dialog button '{info['name']}'"
        return f"ERROR: button '{button_text}' not found."

    def file_dialog_set_path(self, path: str, title: str = "") -> str:
        error = self._require_uia()
        if error:
            return error
        for scope in self._dialog_scopes(title):
            field = self.uia.find(scope, automation_id="FileNameControlHost")
            if field is None:
                field = self.uia.find(scope, control_type="ComboBox")
            if field is None:
                field = self.uia.find(scope, control_type="Edit")
            if field is None:
                continue
            if self.uia.value_set(field, path):
                return f"Set file dialog path to '{path}'"
            self.uia.set_focus(field)
            input.hotkey("ctrl+a")
            input.type_text(path)
            return f"Set file dialog path to '{path}'"
        return "ERROR: no file dialog found."

    def file_dialog_confirm(self, title: str = "") -> str:
        error = self._require_uia()
        if error:
            return error
        priority = ["сохранить", "save", "открыть", "open", "ok"]
        for scope in self._dialog_scopes(title):
            controls = self.uia.descendants(scope)
            handle = None
            try:
                handle = win.foreground_window()
            except Exception:
                handle = None
            for label in priority:
                for control in controls:
                    info = self.uia.info(control)
                    if "button" not in info["control_type"].lower():
                        continue
                    if info["name"].strip().lower() == label:
                        if self.uia.invoke(control) or self.uia.legacy_default_action(control):
                            return f"Confirmed file dialog with '{info['name']}'"
                        center = self.uia.center(control)
                        if center:
                            input.click(center[0], center[1])
                            time.sleep(0.4)
                            if handle and any(item["handle"] == handle for item in win.enum_windows()):
                                input.press_key("enter")
                            return f"Confirmed file dialog with '{info['name']}'"
        return "ERROR: could not find confirm button."

    # --- menus ---

    def menu_select(self, value, path: str) -> str:
        error = self._require_uia()
        if error:
            return error
        window = self._window_element(value)
        if window is None:
            return f"ERROR: Window '{value}' not found."
        parts = [p.strip() for p in path.split("->") if p.strip()]
        if not parts:
            return "ERROR: empty menu path."
        target = None
        for index, part in enumerate(parts):
            target = self.uia.find(window, name=part)
            if target is None:
                return f"ERROR: menu item '{part}' not found."
            if index < len(parts) - 1:
                center = self.uia.center(target)
                if center:
                    input.click(center[0], center[1])
                else:
                    self.uia.expand(target)
                time.sleep(0.3)
        if self.uia.invoke(target) or self.uia.legacy_default_action(target):
            return f"Selected menu '{path}'"
        center = self.uia.center(target)
        if center:
            input.click(center[0], center[1])
            return f"Selected menu '{path}'"
        return f"ERROR: could not select menu '{path}'."

    def context_menu_click(self, x: int, y: int, item: str) -> str:
        input.right_click(x, y)
        if self.uia is None:
            return f"ERROR: context menu item '{item}' not found."
        deadline = time.time() + 4
        while time.time() < deadline:
            scopes = []
            for info in win.enum_windows():
                if info["class"] not in ("#32768", "PopupMenu", "ContextMenu"):
                    continue
                element = self.uia.element_from_handle(info["handle"])
                if element is not None:
                    scopes.append(element)
            for scope in scopes:
                target = self.uia.find(scope, name=item, control_type="MenuItem")
                if target is None:
                    continue
                if self.uia.invoke(target) or self.uia.legacy_default_action(target):
                    return f"Clicked context menu item '{item}'"
                center = self.uia.center(target)
                if center:
                    input.click(center[0], center[1])
                    return f"Clicked context menu item '{item}'"
            time.sleep(0.2)
        return f"ERROR: context menu item '{item}' not found."

    def tray_icon_click(self, name: str, action: str = "left") -> str:
        error = self._require_uia()
        if error:
            return error
        for info in win.enum_windows():
            if info["class"] != "Shell_TrayWnd":
                continue
            element = self.uia.element_from_handle(info["handle"])
            if element is None:
                continue
            target = self.uia.find(element, name=name)
            if target is None:
                target = self.uia.find(element, automation_id=name)
            if target is not None:
                center = self.uia.center(target)
                if center:
                    if action == "right":
                        input.right_click(center[0], center[1])
                    else:
                        input.click(center[0], center[1])
                    return f"Clicked tray icon '{name}'"
        return f"ERROR: tray icon '{name}' not found."

    # --- extended: elements ---

    def screenshot_element(self, value, control_identifier: str, grid: bool = False):
        control = self._find_control(value, control_identifier)
        if control is None:
            return None
        rect = self.uia.info(control).get("rect")
        if not rect:
            return None
        left, top, right, bottom = rect
        image = screen.grab((left, top, right, bottom))
        return self._draw_grid(image, left, top) if grid else image

    def highlight_element(self, value, control_identifier: str, duration: float = 1.0, color: str = "red", width: int = 3) -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        rect = self.uia.info(control).get("rect")
        if not rect:
            return f"ERROR: control '{control_identifier}' has no position."
        from mcp_winaccess_win.adapter import win32_overlay

        win32_overlay.highlight(rect[0], rect[1], rect[2], rect[3], duration, color, width)
        return f"Highlighted '{control_identifier}' for {duration}s"

    def get_element_at_point(self, x: int, y: int) -> str:
        error = self._require_uia()
        if error:
            return error
        element = self.uia.element_from_point(x, y)
        if element is None:
            return f"ERROR: no element at ({x}, {y})."
        return f"Element at ({x}, {y}): {self._format_control(self.uia.info(element), 0)}"

    def get_active_element(self) -> str:
        error = self._require_uia()
        if error:
            return error
        element = self.uia.focused_element()
        if element is None:
            return "ERROR: no focused element."
        return f"Focused element: {self._format_control(self.uia.info(element), 0)}"

    def wait_for_element_gone(self, value, control_identifier: str, timeout: float = 10.0) -> str:
        start = time.time()
        while time.time() - start < timeout:
            if self._find_control(value, control_identifier) is None:
                return f"ELEMENT GONE: '{control_identifier}'"
            time.sleep(0.3)
        return f"ERROR: timeout ({timeout}s) waiting for '{control_identifier}' to disappear."

    def wait_for_window_gone(self, value, timeout: float = 10.0) -> str:
        start = time.time()
        while time.time() - start < timeout:
            if self._find_handle(value) is None:
                return f"WINDOW GONE: '{value}'"
            time.sleep(0.3)
        return f"ERROR: timeout ({timeout}s) waiting for window '{value}' to disappear."

    # --- extended: hold keys and drag-and-drop ---

    def key_down(self, key: str) -> str:
        input.key_down(key)
        return f"Key down: {key}"

    def key_up(self, key: str) -> str:
        input.key_up(key)
        return f"Key up: {key}"

    def mouse_down(self, x: int = 0, y: int = 0, button: str = "left") -> str:
        if x or y:
            input.move_mouse(x, y)
        input.mouse_down(x, y, button)
        return f"Mouse down ({button}) at ({x}, {y})"

    def mouse_up(self, button: str = "left") -> str:
        input.mouse_up(button)
        return f"Mouse up ({button})"

    def mouse_move_relative(self, dx: int, dy: int) -> str:
        input.move_rel(dx, dy)
        return f"Mouse moved by ({dx}, {dy})"

    def scroll_element(self, value, control_identifier: str, direction: str = "down", amount: int = 3) -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        center = self.uia.center(control)
        if center is None:
            return f"ERROR: control '{control_identifier}' has no position."
        return self.scroll(direction, amount, center[0], center[1])

    def drag_element_to_element(self, from_value, from_control: str, to_value, to_control: str, duration: float = 0.5) -> str:
        source = self._find_control(from_value, from_control)
        target = self._find_control(to_value, to_control)
        if source is None:
            return f"ERROR: control '{from_control}' not found."
        if target is None:
            return f"ERROR: control '{to_control}' not found."
        start = self.uia.center(source)
        end = self.uia.center(target)
        if start is None or end is None:
            return "ERROR: could not resolve element positions."
        input.drag(start[0], start[1], end[0], end[1], duration)
        return f"Dragged '{from_control}' to '{to_control}'"

    # --- extended: lists, tables, tree, menu ---

    def get_list_items(self, value, control_identifier: str, limit: int = 200) -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        items = self.uia.list_items(control, limit)
        return "\n".join(f"- {item}" for item in items) if items else "No items found."

    def get_table_data(self, value, control_identifier: str, limit: int = 200) -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        rows = self.uia.table_rows(control, limit)
        return "\n".join(" | ".join(row) for row in rows) if rows else "No table data found."

    def expand_element(self, value, control_identifier: str) -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        return f"Expanded '{control_identifier}'" if self.uia.expand(control) else f"ERROR: could not expand '{control_identifier}'."

    def collapse_element(self, value, control_identifier: str) -> str:
        control = self._find_control(value, control_identifier)
        if control is None:
            return f"ERROR: control '{control_identifier}' not found."
        return f"Collapsed '{control_identifier}'" if self.uia.collapse(control) else f"ERROR: could not collapse '{control_identifier}'."

    # --- extended: clipboard files and images ---

    def clipboard_set_files(self, paths) -> str:
        if isinstance(paths, str):
            paths = [part for part in re.split(r"[;\n]", paths) if part.strip()]
        try:
            count = clipboard.set_files(paths)
            return f"Clipboard files set: {count}"
        except Exception as exc:
            return f"ERROR: clipboard files failed: {exc}"

    def clipboard_get_files(self) -> str:
        try:
            files = clipboard.get_files()
        except Exception as exc:
            return f"ERROR: clipboard files read failed: {exc}"
        return "Clipboard files:\n" + "\n".join(files) if files else "No files in clipboard."

    def clipboard_set_image(self, path: str) -> str:
        try:
            clipboard.set_image(path)
            return "Clipboard image set."
        except Exception as exc:
            return f"ERROR: clipboard image failed: {exc}"

    def clipboard_get_image(self, save_path: str = "") -> str:
        try:
            image = clipboard.get_image(save_path)
        except Exception as exc:
            return f"ERROR: clipboard image read failed: {exc}"
        if image is None:
            return "No image in clipboard."
        if save_path:
            return f"Clipboard image saved: {save_path}"
        return f"Clipboard image: {image.size[0]}x{image.size[1]}"

    # --- extended: screenshot comparison ---

    def compare_screenshots(self, image_a: str, image_b: str, save_diff: str = "") -> str:
        try:
            from PIL import Image

            first = Image.open(image_a).convert("RGB")
            second = Image.open(image_b).convert("RGB")
        except Exception as exc:
            return f"ERROR: could not open images: {exc}"
        result = screen.compare(first, second, save_diff=save_diff)
        if result is None:
            return "ERROR: image sizes differ."
        changed, total, percent = result
        text = f"Screenshots differ: {changed}/{total} pixels ({percent:.2f}%)"
        if save_diff:
            text += f", diff saved: {save_diff}"
        return text

    # --- extended: notifications ---

    def list_notifications(self) -> str:
        items = win32_notifications.list_notifications()
        if not items:
            error = self._require_uia()
            if error:
                return error
            try:
                element = self._open_notification_center()
                if element is not None:
                    items = [self.uia.info(child)["name"] for child in self.uia.descendants(element, max_items=200) if self.uia.info(child)["name"]]
            finally:
                input.press_key("esc")
        return "Notifications:\n" + "\n".join(f"- {item}" for item in items) if items else "No notifications."

    def dismiss_notifications(self) -> str:
        if win32_notifications.clear_via_api():
            return "Dismissed notifications."
        error = self._require_uia()
        if error:
            return error
        try:
            element = self._open_notification_center()
            if element is None:
                return "ERROR: notification center not found."
            for _ in range(10):
                for label in ("Очистить уведомления", "Очистить все", "Очистить", "Clear all notifications", "Clear all", "Clear"):
                    button = self.uia.find(element, name=label)
                    if button is None:
                        continue
                    if self.uia.invoke(button) or self.uia.legacy_default_action(button):
                        return "Dismissed notifications."
                time.sleep(0.3)
            return "ERROR: could not clear notifications (the WinRT API is unavailable to desktop apps and the UI clear-all button was not found)."
        finally:
            input.press_key("esc")

    def _notification_center(self):
        try:
            root = self.uia.root()
        except Exception:
            return None
        for child in self.uia.children(root):
            info = self.uia.info(child)
            name = (info["name"] or "").lower()
            if ("уведомлен" in name or "notification center" in name) and not info.get("offscreen"):
                return child
        return None

    def _open_notification_center(self):
        element = self._notification_center()
        if element is not None:
            return element
        for shortcut in ("win+n", "win+a"):
            input.hotkey(shortcut)
            time.sleep(0.9)
            element = self._notification_center()
            if element is not None:
                return element
        for label in ("Центр уведомлений", "Notification center"):
            self.tray_icon_click(label)
            time.sleep(0.9)
            element = self._notification_center()
            if element is not None:
                return element
        return None

    # --- extended: virtual desktops ---

    def switch_desktop(self, direction: str = "right") -> str:
        direction = (direction or "right").lower()
        if direction not in ("left", "right"):
            return "ERROR: direction must be 'left' or 'right'."
        input.hotkey(f"win+ctrl+{direction}")
        return f"Switched desktop {direction}"

    def move_window_to_desktop(self, value, direction: str = "right") -> str:
        direction = (direction or "right").lower()
        if direction not in ("left", "right"):
            return "ERROR: direction must be 'left' or 'right'."
        handle = self._find_handle(value)
        if handle is None:
            return f"ERROR: Window '{value}' not found."
        win.set_foreground(handle)
        time.sleep(0.2)
        input.hotkey(f"win+ctrl+shift+{direction}")
        return f"Moved '{value}' to desktop {direction}"

    # --- extended: process control ---

    def run_app(self, path: str, args: str = "", cwd: str = "") -> str:
        if not path:
            return "ERROR: path is required."
        try:
            pid = process.run(path, args, cwd)
        except Exception as exc:
            return f"ERROR: could not launch '{path}': {exc}"
        return f"Launched '{path}' (pid={pid})"

    def kill_process(self, pid_or_name: str) -> str:
        if not (pid_or_name or "").strip():
            return "ERROR: pid or process name is required."
        ok, output = process.kill(pid_or_name)
        if ok:
            return f"Killed process '{pid_or_name}'."
        return f"ERROR: could not kill '{pid_or_name}': {output}"

    def list_processes(self, filter: str = "") -> str:
        items = process.list_processes(filter)
        if not items:
            return "No processes found."
        return "\n".join(f"PID {pid} | {exe}" for pid, exe in sorted(items, key=lambda item: item[1].lower()))

    def wait_for_pixel_color(self, x: int, y: int, color: str, timeout: float = 10.0, tolerance: int = 0) -> str:
        target = self._parse_color(color)
        if target is None:
            return "ERROR: color must be 'r,g,b' (0-255) or '#rrggbb'."
        start = time.time()
        last = None
        while time.time() - start < timeout:
            try:
                red, green, blue = screen.get_pixel(x, y)
            except Exception as exc:
                return f"ERROR: pixel read failed: {exc}"
            last = (red, green, blue)
            if all(abs(a - b) <= tolerance for a, b in zip(last, target, strict=True)):
                return f"Pixel ({x}, {y}) matched RGB{target} (tolerance {tolerance}) after {time.time() - start:.2f}s."
            time.sleep(0.2)
        return f"ERROR: timeout ({timeout}s) waiting for RGB{target} at ({x}, {y}); last={last}."

    @staticmethod
    def _parse_color(color) -> tuple[int, int, int] | None:
        if isinstance(color, (tuple, list)) and len(color) == 3:
            return tuple(int(part) for part in color)  # type: ignore[return-value]
        text = str(color or "").strip()
        try:
            if text.startswith("#") and len(text) == 7:
                return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)
            parts = [int(part) for part in text.replace(";", ",").split(",")]
            if len(parts) == 3:
                return parts[0], parts[1], parts[2]
        except ValueError:
            return None
        return None
