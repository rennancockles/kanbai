"""Persistent registry of boards for the multi-board hub (``~/.kanbai/boards.toml``).

The hub (``kanbai hub``) serves several boards at once; this module is the source of truth
for *which* boards it knows about. The base directory can be overridden with ``$KANBAI_HOME``
(handy for tests), otherwise it is the user's ``~/.kanbai``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import storage
from .config import load_config
from .errors import KanbaiError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib  # ty: ignore[unresolved-import]


def registry_path() -> Path:
    """Location of the hub registry file (override the base dir with ``$KANBAI_HOME``)."""
    base = os.environ.get("KANBAI_HOME")
    root = Path(base) if base else Path.home() / ".kanbai"
    return root / "boards.toml"


def load_boards() -> dict[str, str]:
    """Return the registered boards as an ordered ``{name: absolute path}`` mapping."""
    path = registry_path()
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    boards = raw.get("boards", {})
    return {str(name): str(location) for name, location in boards.items()}


def _save_boards(boards: dict[str, str]) -> None:
    lines = ["[boards]\n"]
    lines += [f'"{name}" = "{location}"\n' for name, location in sorted(boards.items())]
    storage.atomic_write(registry_path(), "".join(lines))


def add_board(path: Path) -> tuple[str, bool]:
    """Register the board at ``path``, named after its ``config.toml``.

    Returns ``(name, replaced)`` where ``replaced`` is true if a board with that name was
    already registered. Raises :class:`KanbaiError` if ``path`` has no ``.kanbai/`` board.
    """
    board_dir = path.expanduser().resolve()
    kanbai_dir = board_dir / storage.KANBAI_DIRNAME
    if not kanbai_dir.is_dir():
        raise KanbaiError(f"No .kanbai board at {board_dir}. Run `kanbai init` there first.")
    name = load_config(kanbai_dir).name
    boards = load_boards()
    replaced = name in boards
    boards[name] = str(board_dir)
    _save_boards(boards)
    return name, replaced


def remove_board(name: str) -> None:
    """Unregister the board called ``name``. Raises :class:`KanbaiError` if unknown."""
    boards = load_boards()
    if name not in boards:
        raise KanbaiError(f"No board named '{name}' in the hub registry.")
    del boards[name]
    _save_boards(boards)
