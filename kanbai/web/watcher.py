"""Watch the ``.kanbai/`` directory and yield an event whenever it changes.

Backs the Server-Sent Events endpoint: when the board files change on disk (e.g. Claude
moves a card via the CLI), the web UI refreshes itself without a manual reload.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from watchfiles import awatch
from watchfiles.main import FileChange


async def watch_board(kanbai_dir: Path, *, force_polling: bool = False) -> AsyncIterator[None]:
    """Yield ``None`` once per batch of filesystem changes under ``kanbai_dir``.

    Some environments (sandboxes, containers, network filesystems) don't deliver OS-level
    file events; pass ``force_polling=True`` to poll the directory instead. When ``False``,
    watchfiles auto-detects and still honours the ``WATCHFILES_FORCE_POLLING`` env var.
    """
    async for _changes in awatch(kanbai_dir, force_polling=True if force_polling else None):
        yield None


def _existing_dirs(kanbai_dirs: dict[str, Path]) -> dict[str, Path]:
    return {name: d.resolve() for name, d in kanbai_dirs.items() if d.is_dir()}


def _boards_changed(dirs: dict[str, Path], changes: set[FileChange]) -> list[str]:
    changed = {Path(path).resolve() for _, path in changes}
    names = [name for name, d in dirs.items() if any(p.is_relative_to(d) for p in changed)]
    return names or list(dirs)


async def watch_boards(
    kanbai_dirs: dict[str, Path], *, force_polling: bool = False
) -> AsyncIterator[list[str]]:
    """Watch several boards at once; yield the names of the boards that changed.

    One watcher (and one SSE connection) serves a whole multi-board view. If a changed path
    can't be attributed to a board (e.g. symlinked paths), every board is reported so the UI
    still refreshes. Directories that don't exist are skipped; with none left, it ends.
    """
    dirs = _existing_dirs(kanbai_dirs)
    if not dirs:
        return
    async for changes in awatch(*dirs.values(), force_polling=True if force_polling else None):
        yield _boards_changed(dirs, changes)
