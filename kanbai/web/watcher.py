"""Watch the ``.kanbai/`` directory and yield an event whenever it changes.

Backs the Server-Sent Events endpoint: when the board files change on disk (e.g. Claude
moves a card via the CLI), the web UI refreshes itself without a manual reload.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from watchfiles import awatch


async def watch_board(kanbai_dir: Path, *, force_polling: bool = False) -> AsyncIterator[None]:
    """Yield ``None`` once per batch of filesystem changes under ``kanbai_dir``.

    Some environments (sandboxes, containers, network filesystems) don't deliver OS-level
    file events; pass ``force_polling=True`` to poll the directory instead. When ``False``,
    watchfiles auto-detects and still honours the ``WATCHFILES_FORCE_POLLING`` env var.
    """
    async for _changes in awatch(kanbai_dir, force_polling=True if force_polling else None):
        yield None
