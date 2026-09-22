"""Tests for board operations."""

from __future__ import annotations

import pytest
from kanbai.board import Board
from kanbai.errors import CardNotFoundError, ColumnNotFoundError
from kanbai.models import Priority


def test_add_lands_in_backlog_with_sequential_ids_and_order(board: Board) -> None:
    first = board.add("Task one")
    second = board.add("Task two")
    assert first.id == "001"
    assert second.id == "002"
    assert first.status == "backlog"  # new cards are captured in the backlog by default
    assert first.order == 1
    assert second.order == 2


def test_add_can_target_a_column(board: Board) -> None:
    card = board.add("Sprint task", column="todo")
    assert card.status == "todo"


def test_add_uses_default_priority(board: Board) -> None:
    card = board.add("Task")
    assert card.priority == Priority.medium
    high = board.add("Urgent", priority="high")
    assert high.priority == Priority.high


def test_move_updates_status_and_order(board: Board) -> None:
    card = board.add("Task")  # lands in backlog
    moved = board.move(card.id, "doing")
    assert moved.status == "doing"
    assert moved.order == 1
    assert board.list_column("doing")[0].id == card.id
    assert board.list_column("backlog") == []


def test_move_unknown_column_raises(board: Board) -> None:
    card = board.add("Task")
    with pytest.raises(ColumnNotFoundError):
        board.move(card.id, "nope")


def test_next_reads_the_sprint_not_the_backlog(board: Board) -> None:
    board.add("Backlog item")  # goes to backlog, must be ignored by next
    sprint_first = board.add("Sprint first", column="todo")
    board.add("Sprint second", column="todo")
    result = board.next()
    assert result is not None
    assert result.id == sprint_first.id


def test_next_ignores_backlog_only_cards(board: Board) -> None:
    board.add("Only in backlog")
    assert board.next() is None  # nothing planned into the sprint yet


def test_next_skips_blocked_cards(board: Board) -> None:
    blocker = board.add("Blocker", column="todo")  # 001, order 1
    blocked = board.add("Blocked", column="todo", deps=[blocker.id])  # 002, order 2
    # Make the blocked card sort first, yet it must still be skipped while blocked.
    board.edit(blocked.id, order=0)

    assert board.next().id == blocker.id  # type: ignore[union-attr]

    board.move(blocker.id, "done")
    assert board.next().id == blocked.id  # type: ignore[union-attr]


def test_next_none_when_empty(board: Board) -> None:
    assert board.next() is None


def test_next_missing_dependency_is_not_blocking(board: Board) -> None:
    card = board.add("Task", column="todo", deps=["999"])
    assert board.next().id == card.id  # type: ignore[union-attr]


def test_edit_renames_file_on_title_change(board: Board) -> None:
    card = board.add("Old title")  # backlog
    board.edit(card.id, title="New title")
    backlog = board.list_column("backlog")
    assert len(backlog) == 1
    assert backlog[0].title == "New title"
    files = list((board.kanbai_dir / "backlog").glob("*.md"))
    assert len(files) == 1
    assert files[0].name == "001-new-title.md"


def test_edit_replaces_labels_and_deps(board: Board) -> None:
    card = board.add("Task", labels=["a"])
    edited = board.edit(card.id, labels=["b", "c"], deps=["005"])
    assert edited.labels == ["b", "c"]
    assert edited.deps == ["005"]


def test_archive_moves_off_board(board: Board) -> None:
    card = board.add("Task")
    board.archive(card.id)
    assert all(card.id not in [c.id for c in cards] for cards in board.board().values())
    assert list((board.kanbai_dir / "archive").glob("*.md"))


def test_remove_deletes_card(board: Board) -> None:
    card = board.add("Task")
    board.remove(card.id)
    with pytest.raises(CardNotFoundError):
        board.show(card.id)


def test_show_unknown_raises(board: Board) -> None:
    with pytest.raises(CardNotFoundError):
        board.show("404")
