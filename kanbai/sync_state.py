"""Whether a hosted project's local files and its hosted board may have drifted apart.

Written by the mirror (``kanbai.mirror``) when replicating a change to the server fails or finds
the host's card in an unexpected state, and cleared by a successful ``kanbai hosted push`` /
``pull``. It lives in ``.kanbai/.sync-state.json`` — local to this checkout, never synced.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import storage

STATE_FILENAME = ".sync-state.json"
_MAX_REASONS = 5

#: What to tell the user to do about it.
SYNC_HINT = "Run `kanbai hosted push` (local wins) or `kanbai hosted pull` (server wins) to sync."


def _path(kanbai_dir: Path) -> Path:
    return kanbai_dir / STATE_FILENAME


def load_out_of_sync(kanbai_dir: Path) -> list[str] | None:
    """The recorded reasons the project is out of sync, or ``None`` when nothing is pending."""
    path = _path(kanbai_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["the sync state file is unreadable"]
    reasons = data.get("reasons") if isinstance(data, dict) else None
    if not isinstance(reasons, list):
        return ["the sync state file is unreadable"]
    return [str(reason) for reason in reasons] or None


def mark_out_of_sync(kanbai_dir: Path, reasons: list[str]) -> None:
    """Record ``reasons`` (keeping earlier distinct ones, newest last, capped)."""
    merged = [r for r in (load_out_of_sync(kanbai_dir) or []) if r not in reasons] + reasons
    storage.atomic_write(
        _path(kanbai_dir), json.dumps({"reasons": merged[-_MAX_REASONS:]}, ensure_ascii=False)
    )


def clear_out_of_sync(kanbai_dir: Path) -> None:
    """Forget any recorded drift (called after a successful push or pull)."""
    _path(kanbai_dir).unlink(missing_ok=True)
