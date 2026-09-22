"""Windows adapter entry point."""

from __future__ import annotations

import sys

from mcp_winaccess_win.adapter.base import BaseAdapter

_adapter: BaseAdapter | None = None


def get_adapter() -> BaseAdapter:
    global _adapter
    if _adapter is None:
        try:
            from mcp_winaccess_win.adapter.windows import WindowsAdapter

            _adapter = WindowsAdapter()
        except Exception as exc:
            print(
                f"WARNING: Windows adapter failed to initialize ({exc}); "
                "falling back to BaseAdapter.",
                file=sys.stderr,
            )
            _adapter = BaseAdapter()
    return _adapter
