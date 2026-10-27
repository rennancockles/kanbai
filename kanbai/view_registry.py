"""Single configurable multi-board view for the hub (``~/.kanbai/view.toml``)."""

from __future__ import annotations

import sys
from pathlib import Path

from . import storage
from .registry import registry_path as _board_registry_path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib  # ty: ignore[unresolved-import]


def _view_path() -> Path:
    return _board_registry_path().with_name("view.toml")


def load_view() -> list[str]:
    """Return the ordered list of board names configured in the view."""
    path = _view_path()
    if not path.exists():
        return []
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    return [str(b) for b in raw.get("boards", [])]


def save_view(boards: list[str]) -> None:
    """Persist the view's board list, replacing the previous configuration."""
    boards_str = ", ".join(f'"{b}"' for b in boards)
    storage.atomic_write(_view_path(), f"boards = [{boards_str}]\n")


def reorder_view(boards: list[str]) -> None:
    """Put the view's boards in the order of ``boards``; unknown names are ignored and boards
    it does not mention keep their place at the end."""
    current = load_view()
    ordered = [b for b in dict.fromkeys(boards) if b in current]
    save_view(ordered + [b for b in current if b not in ordered])


def view_first(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    """``entries`` (dicts with a ``name``) with the boards already in the view first, in view
    order, followed by the others in their given order."""
    position = {name: i for i, name in enumerate(load_view())}
    return sorted(entries, key=lambda e: position.get(str(e["name"]), len(position)))
