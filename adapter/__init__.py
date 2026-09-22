"""Windows adapter entry point."""

from __future__ import annotations

from adapter.base import BaseAdapter

_adapter: BaseAdapter | None = None


def get_adapter() -> BaseAdapter:
    global _adapter
    if _adapter is None:
        try:
            from adapter.windows import WindowsAdapter

            _adapter = WindowsAdapter()
        except Exception:
            _adapter = BaseAdapter()
    return _adapter
