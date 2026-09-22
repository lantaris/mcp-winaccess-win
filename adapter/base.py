"""Base adapter: interface, capability flags and shared helpers.

The Windows adapter implements the low-level hooks. Vision and OCR are implemented
here on top of ``screenshot`` / ``click``.
"""

from __future__ import annotations

import importlib.util
import io
import os
import re
import tempfile
import time
import uuid

from PIL import ImageDraw


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


HAS_CV2 = _has_module("cv2")
HAS_TESSERACT = _has_module("pytesseract")

if HAS_CV2:
    import cv2

if HAS_TESSERACT:
    import pytesseract

    from adapter import tesseract_setup

    _tesseract_cmd = tesseract_setup.find_tesseract()
    if _tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd


def _tesseract_ready() -> bool:
    """Ensure a Tesseract binary is available (auto-installing it on first use)."""
    if not HAS_TESSERACT:
        return False
    from adapter import tesseract_setup

    path = tesseract_setup.ensure_tesseract()
    if path:
        pytesseract.pytesseract.tesseract_cmd = path
        return True
    return False

SYSTEM_KEYS = {
    "win": "win",
    "super": "win",
    "meta": "win",
    "volumeup": "volumeup",
    "volume_up": "volumeup",
    "volumedown": "volumedown",
    "volume_down": "volumedown",
    "volumemute": "volumemute",
    "volume_mute": "volumemute",
    "mute": "volumemute",
    "playpause": "playpause",
    "play_pause": "playpause",
    "nexttrack": "nexttrack",
    "next_track": "nexttrack",
    "prevtrack": "prevtrack",
    "prev_track": "prevtrack",
    "printscreen": "printscreen",
    "print_screen": "printscreen",
}


class BaseAdapter:
    """Shared interface. The Windows adapter provides the low-level operations."""

    name = "base"

    @property
    def capabilities(self) -> set[str]:
        caps = {"screenshot", "screenshot_region", "screenshot_monitor", "input", "monitors"}
        if self._clipboard_available():
            caps.add("clipboard")
        if HAS_CV2:
            caps.add("vision")
        if HAS_TESSERACT:
            caps.add("ocr")
        caps |= self._platform_capabilities()
        return caps

    def _platform_capabilities(self) -> set[str]:
        return set()

    def _clipboard_available(self) -> bool:
        return False

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    @staticmethod
    def _coerce(value):
        if isinstance(value, str) and value.lstrip("-").isdigit():
            return int(value)
        return value

    @staticmethod
    def _match(value, title: str = "", cls: str = "", handle=None) -> bool:
        value = BaseAdapter._coerce(value)
        if isinstance(value, int):
            return handle == value
        if not value:
            return False
        return value.lower() in (title or "").lower() or value.lower() in (cls or "").lower()

    @staticmethod
    def _jpeg_bytes(img, quality: int = 85) -> bytes:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=quality)
        return buf.getvalue()

    @staticmethod
    def _draw_grid(img, origin_x: int = 0, origin_y: int = 0, step: int = 100):
        img = img.convert("RGB")
        draw = ImageDraw.Draw(img)
        width, height = img.size
        for x in range(0, width, step):
            draw.line([(x, 0), (x, height)], fill=(255, 0, 0), width=1)
            draw.text((x + 2, 2), str(origin_x + x), fill=(255, 0, 0))
        for y in range(0, height, step):
            draw.line([(0, y), (width, y)], fill=(255, 0, 0), width=1)
            draw.text((2, y + 2), str(origin_y + y), fill=(255, 0, 0))
        return img

    def _get_monitors(self) -> list[dict]:
        width, height = self._screen_size()
        return [{"index": 0, "left": 0, "top": 0, "width": width, "height": height, "primary": True}]

    def list_monitors(self) -> str:
        lines = []
        for m in self._get_monitors():
            primary = " primary" if m["primary"] else ""
            scale = m.get("scale", 1.0)
            lines.append(f"Monitor {m['index']}{primary}: left={m['left']}, top={m['top']}, width={m['width']}, height={m['height']}, scale={scale}")
        return "\n".join(lines) if lines else "No monitors found."

    def image_to_screen_coords(self, x: int, y: int, monitor_index: int = 0) -> str:
        monitors = self._get_monitors()
        if not monitors:
            return "ERROR: no monitors detected."
        monitor_index = max(0, min(monitor_index, len(monitors) - 1))
        m = monitors[monitor_index]
        return f"Screen coords: ({m['left'] + x}, {m['top'] + y})"

    def screenshot_jpg(self, path: str = "") -> str:
        if not path:
            path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.jpg")
        self.screenshot().convert("RGB").save(path, "JPEG")
        return f"Saved screenshot: {path}"

    def screenshot_window(self, value, grid: bool = False):
        rect = self.window_rect(value)
        if not rect:
            return None
        left, top, width, height = rect
        return self.screenshot_region(left, top, width, height, grid=grid)

    def screenshot_monitor(self, index: int = 0, grid: bool = False):
        monitors = self._get_monitors()
        if not monitors:
            return None
        index = max(0, min(index, len(monitors) - 1))
        m = monitors[index]
        return self.screenshot_region(m["left"], m["top"], m["width"], m["height"], grid=grid)

    def locate_image_on_screen(self, image_path: str, confidence: float = 0.9, grayscale: bool = False) -> str:
        if not HAS_CV2:
            return "ERROR: vision requires opencv-python (install the 'vision' extra)."
        try:
            import numpy as np

            template = cv2.imread(image_path)
            if template is None:
                return f"ERROR: could not read template '{image_path}'."
            screen = cv2.cvtColor(np.array(self.screenshot().convert("RGB")), cv2.COLOR_RGB2BGR)
            haystack = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY) if grayscale else screen
            needle = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY) if grayscale else template
            result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
            _, max_value, _, max_loc = cv2.minMaxLoc(result)
        except Exception as exc:
            return f"ERROR: locate failed: {exc}"
        if max_value < confidence:
            return f"ERROR: image '{image_path}' not found (score={max_value:.3f})."
        height, width = template.shape[:2]
        left, top = max_loc
        center_x, center_y = left + width // 2, top + height // 2
        return f"FOUND: region=({left}, {top}, {width}, {height}), center=({center_x}, {center_y})"

    def wait_for_image(self, image_path: str, confidence: float = 0.9, timeout: float = 10.0) -> str:
        if not HAS_CV2:
            return "ERROR: vision requires opencv-python (install the 'vision' extra)."
        start = time.time()
        while time.time() - start < timeout:
            result = self.locate_image_on_screen(image_path, confidence)
            if result.startswith("FOUND"):
                return result
            time.sleep(0.4)
        return f"ERROR: timeout ({timeout}s) waiting for image '{image_path}'."

    def click_image(self, image_path: str, confidence: float = 0.9, timeout: float = 10.0) -> str:
        result = self.wait_for_image(image_path, confidence, timeout)
        if not result.startswith("FOUND"):
            return result
        match = re.search(r"center=\((\d+), (\d+)\)", result)
        if not match:
            return result
        self.click(int(match.group(1)), int(match.group(2)))
        return f"Clicked image at ({match.group(1)}, {match.group(2)})"

    def ocr_screen(self, left: int = 0, top: int = 0, width: int = 0, height: int = 0, lang: str = "") -> str:
        if not _tesseract_ready():
            return "ERROR: OCR requires the Tesseract binary (auto-install failed; set TESSERACT_CMD or install Tesseract)."
        image = self.screenshot_region(left, top, width, height) if width and height else self.screenshot()
        try:
            text = pytesseract.image_to_string(image, lang=lang or None)
        except Exception as exc:
            return f"ERROR: OCR failed: {exc}"
        return text.strip() or "(no text found)"

    def find_text_on_screen(self, text: str, confidence: int = 60, lang: str = "") -> str:
        if not _tesseract_ready():
            return "ERROR: OCR requires the Tesseract binary (auto-install failed; set TESSERACT_CMD or install Tesseract)."
        try:
            data = pytesseract.image_to_data(self.screenshot(), output_type=pytesseract.Output.DICT, lang=lang or None)
        except Exception as exc:
            return f"ERROR: OCR failed: {exc}"
        needle = (text or "").lower()
        for index, word in enumerate(data.get("text", [])):
            if needle and needle in (word or "").lower():
                try:
                    if int(data["conf"][index]) < confidence:
                        continue
                except Exception:
                    pass
                x = data["left"][index] + data["width"][index] // 2
                y = data["top"][index] + data["height"][index] // 2
                return f"FOUND '{word}' at ({x}, {y})"
        return f"ERROR: text '{text}' not found on screen."

    def click_text(self, text: str, confidence: int = 60, lang: str = "") -> str:
        result = self.find_text_on_screen(text, confidence=confidence, lang=lang)
        if not result.startswith("FOUND"):
            return result
        match = re.search(r"\((\d+), (\d+)\)", result)
        if not match:
            return result
        self.click(int(match.group(1)), int(match.group(2)))
        return f"Clicked text '{text}' at ({match.group(1)}, {match.group(2)})"

    def wait_for_text(self, text: str, timeout: float = 10.0, lang: str = "", confidence: int = 60) -> str:
        start = time.time()
        while time.time() - start < timeout:
            result = self.find_text_on_screen(text, confidence=confidence, lang=lang)
            if result.startswith("FOUND"):
                return result
            time.sleep(0.5)
        return f"ERROR: timeout ({timeout}s) waiting for text '{text}'."

    # --- hooks implemented by the Windows adapter ---

    def _screen_size(self) -> tuple[int, int]:
        raise NotImplementedError

    def screenshot(self, grid: bool = False, include_cursor: bool = False):
        raise NotImplementedError

    def screenshot_region(self, left: int, top: int, width: int, height: int, grid: bool = False):
        raise NotImplementedError

    def get_mouse_position(self) -> str:
        return "ERROR: input is not supported on this platform."

    def move_mouse(self, x: int, y: int) -> str:
        return "ERROR: input is not supported on this platform."

    def click(self, x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1) -> str:
        return "ERROR: input is not supported on this platform."

    def drag(self, x_from: int, y_from: int, x_to: int, y_to: int, duration: float = 0.5) -> str:
        return "ERROR: input is not supported on this platform."

    def scroll(self, direction: str = "down", amount: int = 3, x: int = 0, y: int = 0) -> str:
        return "ERROR: input is not supported on this platform."

    def type_text(self, text: str) -> str:
        return "ERROR: input is not supported on this platform."

    def press_key(self, key: str) -> str:
        return "ERROR: input is not supported on this platform."

    def hotkey(self, keys) -> str:
        return "ERROR: input is not supported on this platform."

    def get_pixel_color(self, x: int, y: int) -> str:
        return "ERROR: pixel access is not supported on this platform."

    def wait_for_pixel_color(self, x: int, y: int, color: str, timeout: float = 10.0, tolerance: int = 0) -> str:
        return "ERROR: pixel access is not supported on this platform."

    def run_app(self, path: str, args: str = "", cwd: str = "") -> str:
        return "ERROR: process launch is not supported on this platform."

    def kill_process(self, pid_or_name: str) -> str:
        return "ERROR: process control is not supported on this platform."

    def list_processes(self, filter: str = "") -> str:
        return "ERROR: process listing is not supported on this platform."

    def window_rect(self, value) -> tuple | None:
        return None

    def clipboard_get(self) -> str:
        return "ERROR: clipboard is not supported on this platform."

    def clipboard_set(self, text: str) -> str:
        return "ERROR: clipboard is not supported on this platform."

    def clipboard_clear(self) -> str:
        return "ERROR: clipboard is not supported on this platform."

    # --- window / ui-tree interface (overridden where supported) ---

    def list_windows(self, process: str = "") -> str:
        return "ERROR: window automation is not supported on this platform."

    def find_window(self, value) -> str:
        return "ERROR: window automation is not supported on this platform."

    def get_active_window(self) -> str:
        return "ERROR: window automation is not supported on this platform."

    def switch_to_window(self, value) -> str:
        return "ERROR: window automation is not supported on this platform."

    def manage_window(self, value, action: str = "restore", x: int = 0, y: int = 0) -> str:
        return "ERROR: window automation is not supported on this platform."

    def minimize_window(self, value) -> str:
        return "ERROR: window automation is not supported on this platform."

    def maximize_window(self, value) -> str:
        return "ERROR: window automation is not supported on this platform."

    def restore_window(self, value) -> str:
        return "ERROR: window automation is not supported on this platform."

    def move_window(self, value, x: int, y: int) -> str:
        return "ERROR: window automation is not supported on this platform."

    def resize_window(self, value, x: int, y: int, width: int, height: int) -> str:
        return "ERROR: window automation is not supported on this platform."

    def snap_window(self, value, position: str = "left") -> str:
        return "ERROR: window automation is not supported on this platform."

    def set_always_on_top(self, value, enabled: bool = True) -> str:
        return "ERROR: window automation is not supported on this platform."

    def wait_for_window(self, value, timeout: float = 10.0, require_ready: bool = False) -> str:
        return "ERROR: window automation is not supported on this platform."

    def get_window_state(self, value) -> str:
        return "ERROR: window automation is not supported on this platform."

    def close_window(self, value) -> str:
        return "ERROR: window automation is not supported on this platform."

    def list_dialogs(self) -> str:
        return "ERROR: dialog automation is not supported on this platform."

    def handle_dialog(self, button_text: str, title: str = "") -> str:
        return "ERROR: dialog automation is not supported on this platform."

    def file_dialog_set_path(self, path: str, title: str = "") -> str:
        return "ERROR: file dialog automation is not supported on this platform."

    def file_dialog_confirm(self, title: str = "") -> str:
        return "ERROR: file dialog automation is not supported on this platform."

    def menu_select(self, value, path: str) -> str:
        return "ERROR: menu automation is not supported on this platform."

    def context_menu_click(self, x: int, y: int, item: str) -> str:
        return "ERROR: menu automation is not supported on this platform."

    def tray_icon_click(self, name: str, action: str = "left") -> str:
        return "ERROR: tray automation is not supported on this platform."

    def get_all_controls(self, value, limit: int = 150, query: str = "", control_type: str = "") -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def click_element(self, value, control_identifier: str) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def double_click_element(self, value, control_identifier: str) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def get_text(self, value, control_identifier: str) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def set_text(self, value, control_identifier: str, text: str, mode: str = "value") -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def select_item(self, value, control_identifier: str, item: str) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def toggle_checkbox(self, value, control_identifier: str, state: str = "toggle") -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def get_control_state(self, value, control_identifier: str) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def set_slider(self, value, control_identifier: str, amount: float) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def get_selected_text(self, value, control_identifier: str) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def scroll_into_view(self, value, control_identifier: str) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def wait_for_element(self, value, control_identifier: str, timeout: float = 10.0) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def drag_element(self, value, control_identifier: str, x_to: int, y_to: int, duration: float = 0.5) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def screenshot_element(self, value, control_identifier: str, grid: bool = False):
        return None

    def highlight_element(self, value, control_identifier: str, duration: float = 1.0, color: str = "red", width: int = 3) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def get_element_at_point(self, x: int, y: int) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def get_active_element(self) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def wait_for_element_gone(self, value, control_identifier: str, timeout: float = 10.0) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def wait_for_window_gone(self, value, timeout: float = 10.0) -> str:
        return "ERROR: window automation is not supported on this platform."

    def key_down(self, key: str) -> str:
        return "ERROR: input is not supported on this platform."

    def key_up(self, key: str) -> str:
        return "ERROR: input is not supported on this platform."

    def mouse_down(self, x: int = 0, y: int = 0, button: str = "left") -> str:
        return "ERROR: input is not supported on this platform."

    def mouse_up(self, button: str = "left") -> str:
        return "ERROR: input is not supported on this platform."

    def mouse_move_relative(self, dx: int, dy: int) -> str:
        return "ERROR: input is not supported on this platform."

    def scroll_element(self, value, control_identifier: str, direction: str = "down", amount: int = 3) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def drag_element_to_element(self, from_value, from_control: str, to_value, to_control: str, duration: float = 0.5) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def get_list_items(self, value, control_identifier: str, limit: int = 200) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def get_table_data(self, value, control_identifier: str, limit: int = 200) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def expand_element(self, value, control_identifier: str) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def collapse_element(self, value, control_identifier: str) -> str:
        return "ERROR: UI tree automation is not supported on this platform."

    def clipboard_set_files(self, paths) -> str:
        return "ERROR: clipboard is not supported on this platform."

    def clipboard_get_files(self) -> str:
        return "ERROR: clipboard is not supported on this platform."

    def clipboard_set_image(self, path: str) -> str:
        return "ERROR: clipboard is not supported on this platform."

    def clipboard_get_image(self, save_path: str = "") -> str:
        return "ERROR: clipboard is not supported on this platform."

    def compare_screenshots(self, image_a: str, image_b: str, save_diff: str = "") -> str:
        return "ERROR: screenshots are not supported on this platform."

    def list_notifications(self) -> str:
        return "ERROR: notifications are not supported on this platform."

    def dismiss_notifications(self) -> str:
        return "ERROR: notifications are not supported on this platform."

    def switch_desktop(self, direction: str = "right") -> str:
        return "ERROR: virtual desktops are not supported on this platform."

    def move_window_to_desktop(self, value, direction: str = "right") -> str:
        return "ERROR: virtual desktops are not supported on this platform."
