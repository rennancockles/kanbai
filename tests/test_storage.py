"""Tests for the storage layer."""

from __future__ import annotations

from pathlib import Path

import pytest
from kanbai import storage
from kanbai.errors import KanbaiError
from kanbai.models import Card, Priority


def _make_card(**overrides: object) -> Card:
    timestamp = storage.now()
    defaults: dict[str, object] = {
        "id": "001",
        "title": "Build the login screen",
        "status": "todo",
        "priority": Priority.high,
        "order": 1,
        "labels": ["frontend", "auth"],
        "deps": ["000"],
        "assignee": "claude",
        "created": timestamp,
        "updated": timestamp,
        "body": "## Descrição\nDo the thing.",
    }
    defaults.update(overrides)
    return Card(**defaults)  # type: ignore[arg-type]


def test_slugify() -> None:
    assert storage.slugify("Build the Login Screen!") == "build-the-login-screen"
    assert storage.slugify("   ") == "card"
    assert storage.slugify("Café & Crème") == "caf-cr-me"


def test_dump_parse_round_trip(tmp_path: Path) -> None:
    card = _make_card()
    path = tmp_path / "todo" / storage.card_filename(card)
    storage.atomic_write(path, storage.dump_card(card))

    parsed = storage.parse_card(path, "todo")
    assert parsed.id == card.id
    assert parsed.title == card.title
    assert parsed.priority == Priority.high
    assert parsed.labels == ["frontend", "auth"]
    assert parsed.deps == ["000"]
    assert parsed.assignee == "claude"
    assert parsed.body == card.body
    assert parsed.created == card.created


def test_status_comes_from_folder(tmp_path: Path) -> None:
    card = _make_card(status="todo")
    path = tmp_path / "doing" / storage.card_filename(card)
    storage.atomic_write(path, storage.dump_card(card))
    # Even though the frontmatter says "todo", the folder is authoritative.
    assert storage.parse_card(path, "doing").status == "doing"


def test_next_id_increments(tmp_path: Path) -> None:
    columns = ["todo", "doing", "done"]
    assert storage.next_id(tmp_path, columns) == "001"
    storage.atomic_write(tmp_path / "todo" / "001-a.md", "---\nid: '001'\n---\n")
    storage.atomic_write(tmp_path / "done" / "007-b.md", "---\nid: '007'\n---\n")
    assert storage.next_id(tmp_path, columns) == "008"


def test_card_filename() -> None:
    card = _make_card(title="Fix the bug")
    assert storage.card_filename(card) == "001-fix-the-bug.md"


def test_coerce_priority_rejects_unknown_value() -> None:
    assert storage.coerce_priority("high") == Priority.high
    assert storage.coerce_priority(Priority.low) == Priority.low
    with pytest.raises(KanbaiError):  # not a raw ValueError
        storage.coerce_priority("urgent")
