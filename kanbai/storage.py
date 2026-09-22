"""Filesystem access layer: reading, writing and moving card files.

This module is the single point of contact with the ``.kanbai/`` directory. Both the CLI
and the (future) web UI go through ``Board`` which in turn uses these helpers, so the
on-disk format lives in exactly one place.
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from .models import Card, Priority

KANBAI_DIRNAME = ".kanbai"
ARCHIVE_DIRNAME = "archive"

_FRONTMATTER_RE = re.compile(r"^---\n(?P<meta>.*?)\n---\n?(?P<body>.*)$", re.DOTALL)
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")
_ID_PREFIX_RE = re.compile(r"^(\d+)-")


class _NoAliasDumper(yaml.SafeDumper):
    """YAML dumper that never emits anchors/aliases, keeping card files readable."""

    def ignore_aliases(self, data: object) -> bool:
        return True


# --------------------------------------------------------------------------- board root


def find_kanbai_dir(start: Path | None = None) -> Path | None:
    """Walk upwards from ``start`` (default: cwd) to find a ``.kanbai/`` directory."""
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / KANBAI_DIRNAME
        if candidate.is_dir():
            return candidate
    return None


# --------------------------------------------------------------------------- slug / id


def slugify(title: str) -> str:
    """Turn a card title into a filesystem-friendly slug."""
    slug = _SLUG_STRIP_RE.sub("-", title.strip().lower()).strip("-")
    return slug or "card"


def next_id(kanbai_dir: Path, columns: list[str]) -> str:
    """Return the next zero-padded card id, one greater than the current maximum."""
    highest = 0
    for column in (*columns, ARCHIVE_DIRNAME):
        for path in _column_files(kanbai_dir / column):
            match = _ID_PREFIX_RE.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"{highest + 1:03d}"


# --------------------------------------------------------------------------- serialize


def dump_card(card: Card) -> str:
    """Serialize a card to Markdown-with-frontmatter text."""
    meta = yaml.dump(
        card.frontmatter(),
        Dumper=_NoAliasDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    body = card.body.strip("\n")
    return f"---\n{meta}---\n\n{body}\n" if body else f"---\n{meta}---\n"


def parse_card(path: Path, status: str) -> Card:
    """Parse a card file, using ``status`` (the column folder) as the authoritative status."""
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"Card file {path} is missing YAML frontmatter.")

    meta = yaml.safe_load(match.group("meta")) or {}
    body = match.group("body").strip("\n")
    meta["status"] = status
    meta.setdefault("body", body)
    meta["body"] = body
    return Card.model_validate(meta)


# --------------------------------------------------------------------------- read


def _column_files(column_dir: Path) -> list[Path]:
    if not column_dir.is_dir():
        return []
    return sorted(p for p in column_dir.iterdir() if p.suffix == ".md" and p.is_file())


def read_column(kanbai_dir: Path, column: str) -> list[Card]:
    """Read all cards in a column, sorted by their in-column order."""
    cards = [parse_card(path, column) for path in _column_files(kanbai_dir / column)]
    cards.sort(key=Card.sort_key)
    return cards


def read_all(kanbai_dir: Path, columns: list[str]) -> dict[str, list[Card]]:
    """Read every column into an ordered mapping of column name to its cards."""
    return {column: read_column(kanbai_dir, column) for column in columns}


def find_card_path(kanbai_dir: Path, columns: list[str], card_id: str) -> tuple[Path, str] | None:
    """Locate a card's file and its current column by id, searching all columns + archive."""
    for column in (*columns, ARCHIVE_DIRNAME):
        for path in _column_files(kanbai_dir / column):
            match = _ID_PREFIX_RE.match(path.name)
            if match and match.group(1) == card_id:
                return path, column
    return None


# --------------------------------------------------------------------------- write


def card_filename(card: Card) -> str:
    """The canonical filename for a card: ``<id>-<slug>.md``."""
    return f"{card.id}-{slugify(card.title)}.md"


def atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file in the same dir, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def write_card(kanbai_dir: Path, card: Card) -> Path:
    """Write a card into its status column, returning the file path."""
    path = kanbai_dir / card.status / card_filename(card)
    atomic_write(path, dump_card(card))
    return path


def delete_card_file(path: Path) -> None:
    """Remove a card file from disk."""
    path.unlink(missing_ok=True)


def now() -> datetime:
    """Current local time without microseconds (kept tidy in frontmatter)."""
    return datetime.now().replace(microsecond=0)


def coerce_priority(value: str | Priority) -> Priority:
    """Accept a priority as a string or enum and return the enum."""
    return value if isinstance(value, Priority) else Priority(value)
