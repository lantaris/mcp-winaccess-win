"""UI Automation access for Windows via comtypes (no pywinauto)."""

from __future__ import annotations

import threading
from ctypes import wintypes

import comtypes
import comtypes.client

_local = threading.local()
_module = None


def _load_module():
    global _module
    if _module is not None:
        return _module
    try:
        from comtypes.gen import UIAutomationClient as uia

        _module = uia
    except Exception:
        _module = comtypes.client.GetModule("UIAutomationCore.dll")
    return _module


def _client():
    client = getattr(_local, "client", None)
    if client is None:
        uia = _load_module()
        comtypes.CoInitialize()
        client = comtypes.client.CreateObject(uia.CUIAutomation, interface=uia.IUIAutomation)
        _local.client = client
    return client


def _control_type_names(uia) -> dict[int, str]:
    names = getattr(_local, "control_type_names", None)
    if names is None:
        names = {}
        for attr in dir(uia):
            if attr.startswith("UIA_") and attr.endswith("ControlTypeId"):
                try:
                    names[int(getattr(uia, attr))] = attr[len("UIA_") : -len("ControlTypeId")]
                except Exception:
                    continue
        _local.control_type_names = names
    return names


def _control_type_id(uia, name: str) -> int | None:
    if not name:
        return None
    key = "UIA_" + name.strip() + "ControlTypeId"
    for candidate in (key, key[:4] + key[4:].capitalize()):
        value = getattr(uia, candidate, None)
        if value is not None:
            return int(value)
    lowered = name.strip().lower()
    for attr in dir(uia):
        if attr.startswith("UIA_") and attr.endswith("ControlTypeId") and lowered in attr.lower():
            return int(getattr(uia, attr))
    return None


class UiaClient:
    """Thin wrapper around IUIAutomation with the operations the adapter needs."""

    def __init__(self):
        self.uia = _load_module()

    def _auto(self):
        return _client()

    def root(self):
        return self._auto().GetRootElement()

    def element_from_handle(self, hwnd: int):
        try:
            return self._auto().ElementFromHandle(hwnd)
        except Exception:
            return None

    def _pattern(self, element, pattern_id, interface):
        try:
            unknown = element.GetCurrentPattern(pattern_id)
        except Exception:
            return None
        try:
            return unknown.QueryInterface(interface)
        except Exception:
            return None

    def info(self, element) -> dict:
        rect = None
        try:
            r = element.CurrentBoundingRectangle
            rect = (r.left, r.top, r.right, r.bottom)
        except Exception:
            rect = None
        return {
            "name": self._safe(lambda: element.CurrentName) or "",
            "automation_id": self._safe(lambda: element.CurrentAutomationId) or "",
            "class_name": self._safe(lambda: element.CurrentClassName) or "",
            "control_type": self._control_type_name(element),
            "handle": self._safe(lambda: int(element.CurrentNativeWindowHandle)) or 0,
            "pid": self._safe(lambda: int(element.CurrentProcessId)) or 0,
            "enabled": bool(self._safe(lambda: element.CurrentIsEnabled)),
            "offscreen": bool(self._safe(lambda: element.CurrentIsOffscreen)),
            "rect": rect,
            "text": self.value_get(element) or self._safe(lambda: element.CurrentName) or "",
        }

    def _control_type_name(self, element) -> str:
        try:
            control_type = int(element.CurrentControlType)
        except Exception:
            return ""
        return _control_type_names(self.uia).get(control_type, str(control_type))

    @staticmethod
    def _safe(getter, default=None):
        try:
            return getter()
        except Exception:
            return default

    def children(self, element) -> list:
        try:
            array = element.FindAll(self.uia.TreeScope_Children, self._auto().CreateTrueCondition())
        except Exception:
            return []
        result = []
        for index in range(array.Length):
            try:
                result.append(array.GetElement(index))
            except Exception:
                continue
        return result

    def descendants(self, element, max_items: int = 4000) -> list:
        result: list = []
        stack = list(self.children(element))
        while stack and len(result) < max_items:
            node = stack.pop(0)
            result.append(node)
            try:
                stack.extend(self.children(node))
            except Exception:
                continue
        return result

    def find(self, element, name: str = "", automation_id: str = "", control_type: str = "", class_name: str = ""):
        control_type_id = _control_type_id(self.uia, control_type) if control_type else None
        children = self.descendants(element)
        infos = [self.info(child) for child in children]

        def matches(index: int, exact: bool):
            info = infos[index]
            if control_type_id is not None and self._control_type_id_of(children[index]) != control_type_id:
                return None
            if class_name and info["class_name"] != class_name:
                return None
            if automation_id:
                if info["automation_id"] == automation_id:
                    return children[index]
                if not exact and automation_id.lower() in info["automation_id"].lower():
                    return children[index]
                return None
            if name:
                if info["name"] == name:
                    return children[index]
                if not exact and name.lower() in info["name"].lower():
                    return children[index]
                return None
            return children[index]

        for index in range(len(children)):
            found = matches(index, True)
            if found is not None:
                return found
        for index in range(len(children)):
            found = matches(index, False)
            if found is not None:
                return found
        return None

    def _control_type_id_of(self, element) -> int:
        try:
            return int(element.CurrentControlType)
        except Exception:
            return -1

    def center(self, element) -> tuple[int, int] | None:
        try:
            r = element.CurrentBoundingRectangle
            return (r.left + r.right) // 2, (r.top + r.bottom) // 2
        except Exception:
            return None

    def value_get(self, element):
        pattern = self._pattern(element, self.uia.UIA_ValuePatternId, self.uia.IUIAutomationValuePattern)
        if pattern is not None:
            return self._safe(lambda: pattern.CurrentValue)
        return None

    def value_set(self, element, text: str) -> bool:
        pattern = self._pattern(element, self.uia.UIA_ValuePatternId, self.uia.IUIAutomationValuePattern)
        if pattern is None:
            return False
        try:
            pattern.SetValue(text)
            return True
        except Exception:
            return False

    def invoke(self, element) -> bool:
        pattern = self._pattern(element, self.uia.UIA_InvokePatternId, self.uia.IUIAutomationInvokePattern)
        if pattern is None:
            return False
        try:
            pattern.Invoke()
            return True
        except Exception:
            return False

    def toggle(self, element) -> bool:
        pattern = self._pattern(element, self.uia.UIA_TogglePatternId, self.uia.IUIAutomationTogglePattern)
        if pattern is None:
            return False
        try:
            pattern.Toggle()
            return True
        except Exception:
            return False

    def toggle_state(self, element):
        pattern = self._pattern(element, self.uia.UIA_TogglePatternId, self.uia.IUIAutomationTogglePattern)
        if pattern is None:
            return None
        return self._safe(lambda: int(pattern.CurrentToggleState))

    def select(self, element) -> bool:
        pattern = self._pattern(element, self.uia.UIA_SelectionItemPatternId, self.uia.IUIAutomationSelectionItemPattern)
        if pattern is None:
            return False
        try:
            pattern.Select()
            return True
        except Exception:
            return False

    def range_set(self, element, value: float) -> bool:
        pattern = self._pattern(element, self.uia.UIA_RangeValuePatternId, self.uia.IUIAutomationRangeValuePattern)
        if pattern is None:
            return False
        try:
            pattern.SetValue(float(value))
            return True
        except Exception:
            return False

    def scroll_into_view(self, element) -> bool:
        pattern = self._pattern(element, self.uia.UIA_ScrollItemPatternId, self.uia.IUIAutomationScrollItemPattern)
        if pattern is None:
            return False
        try:
            pattern.ScrollIntoView()
            return True
        except Exception:
            return False

    def set_focus(self, element) -> bool:
        try:
            element.SetFocus()
            return True
        except Exception:
            return False

    def expand(self, element) -> bool:
        pattern = self._pattern(element, self.uia.UIA_ExpandCollapsePatternId, self.uia.IUIAutomationExpandCollapsePattern)
        if pattern is None:
            return False
        try:
            pattern.Expand()
            return True
        except Exception:
            return False

    def collapse(self, element) -> bool:
        pattern = self._pattern(element, self.uia.UIA_ExpandCollapsePatternId, self.uia.IUIAutomationExpandCollapsePattern)
        if pattern is None:
            return False
        try:
            pattern.Collapse()
            return True
        except Exception:
            return False

    def text(self, element):
        pattern = self._pattern(element, self.uia.UIA_TextPatternId, self.uia.IUIAutomationTextPattern)
        if pattern is None:
            return None
        try:
            return pattern.DocumentRange.GetText(-1)
        except Exception:
            return None

    def selection_text(self, element):
        pattern = self._pattern(element, self.uia.UIA_TextPatternId, self.uia.IUIAutomationTextPattern)
        if pattern is None:
            return None
        try:
            ranges = pattern.GetSelection()
        except Exception:
            return None
        if ranges is None:
            return None
        parts = []
        try:
            count = ranges.Length
        except Exception:
            count = 0
        for index in range(count):
            try:
                part = ranges.GetElement(index).GetText(-1)
                if part:
                    parts.append(part)
            except Exception:
                continue
        return "".join(parts) or None

    def window_close(self, element) -> bool:
        pattern = self._pattern(element, self.uia.UIA_WindowPatternId, self.uia.IUIAutomationWindowPattern)
        if pattern is None:
            return False
        try:
            pattern.Close()
            return True
        except Exception:
            return False

    def window_state(self, element, state: str) -> bool:
        pattern = self._pattern(element, self.uia.UIA_WindowPatternId, self.uia.IUIAutomationWindowPattern)
        if pattern is None:
            return False
        mapping = {"normal": 0, "maximized": 1, "minimized": 2}
        value = mapping.get((state or "").lower())
        if value is None:
            return False
        try:
            pattern.SetWindowVisualState(value)
            return True
        except Exception:
            return False

    def transform_move(self, element, x: int, y: int) -> bool:
        pattern = self._pattern(element, self.uia.UIA_TransformPatternId, self.uia.IUIAutomationTransformPattern)
        if pattern is None:
            return False
        try:
            pattern.Move(x, y)
            return True
        except Exception:
            return False

    def transform_resize(self, element, width: int, height: int) -> bool:
        pattern = self._pattern(element, self.uia.UIA_TransformPatternId, self.uia.IUIAutomationTransformPattern)
        if pattern is None:
            return False
        try:
            pattern.Resize(width, height)
            return True
        except Exception:
            return False

    def legacy_default_action(self, element) -> bool:
        pattern = self._pattern(element, self.uia.UIA_LegacyIAccessiblePatternId, self.uia.IUIAutomationLegacyIAccessiblePattern)
        if pattern is None:
            return False
        try:
            pattern.DoDefaultAction()
            return True
        except Exception:
            return False

    def element_from_point(self, x: int, y: int):
        point = None
        for factory in (lambda: self.uia.tagPOINT(x, y), lambda: wintypes.POINT(x, y)):
            try:
                point = factory()
                break
            except Exception:
                continue
        if point is None:
            return None
        try:
            return self._auto().ElementFromPoint(point)
        except Exception:
            return None

    def focused_element(self):
        try:
            return self._auto().GetFocusedElement()
        except Exception:
            return None

    def list_items(self, element, limit: int = 200) -> list[str]:
        items: list[str] = []
        for child in self.descendants(element, max_items=max(limit * 4, 200)):
            info = self.info(child)
            if info["control_type"] in ("ListItem", "DataItem", "TreeItem"):
                text = info["name"] or info["text"]
                if text:
                    items.append(text)
            if len(items) >= limit:
                break
        return items

    def table_rows(self, element, limit: int = 200) -> list[list[str]]:
        cells = []
        for child in self.descendants(element, max_items=max(limit * 20, 500)):
            info = self.info(child)
            rect = info.get("rect")
            text = info["name"] or info["text"]
            if rect and text and info["control_type"] not in ("ScrollBar", "Header", "HeaderItem"):
                cells.append((rect[1], rect[0], text))
        rows: dict[int, list[tuple[int, str]]] = {}
        for top, left, text in cells:
            key = top // 8
            rows.setdefault(key, []).append((left, text))
        result = []
        for key in sorted(rows):
            row = [text for _left, text in sorted(rows[key])]
            result.append(row)
            if len(result) >= limit:
                break
        return result

    def menu_item_state(self, element):
        toggle = self.toggle_state(element)
        if toggle is not None:
            return toggle
        pattern = self._pattern(element, self.uia.UIA_LegacyIAccessiblePatternId, self.uia.IUIAutomationLegacyIAccessiblePattern)
        if pattern is not None:
            try:
                state = int(pattern.CurrentState)
                return 1 if state & 0x10 else 0
            except Exception:
                return None
        return None
