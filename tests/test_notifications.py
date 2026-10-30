"""The structured notification events and how ntfy renders them."""

from __future__ import annotations

from pathlib import Path

import pytest
from kanbai import scaffold
from kanbai.board import Board
from kanbai.models import Card
from kanbai.notifications import Kind, Notification, move_notifications
from kanbai.notify_ntfy import _message, _payload, _priority


@pytest.fixture
def board(tmp_path: Path) -> Board:
    scaffold.init_board(tmp_path, name="Demo")
    return Board.load(tmp_path)


def _card(board: Board, notice: str = "") -> Card:
    return board.add(
        "Fix *export* [now]", type="bug", priority="high", column="todo", notice=notice
    )


def _event(kind: Kind, card: Card | None = None, body: str = "body") -> Notification:
    return Notification(kind=kind, title="Demo: title", body=body, board="Demo", card=card)


def test_a_review_move_builds_a_review_event_carrying_the_card(board: Board) -> None:
    board.add("Other", column="todo")
    card = _card(board)
    moved = board.move(card.id, "review")

    [event] = move_notifications(board.config, moved, "review", lambda: board.next() is None)

    assert (event.kind, event.board, event.card) == (Kind.review, "Demo", moved)
    assert event.title == f"Demo: card {card.id} in review"
    assert event.body == moved.title


def test_a_move_to_done_with_a_pending_notice_builds_a_notice_event_first(board: Board) -> None:
    board.add("Other", column="todo")
    card = _card(board, notice="Tell Ana")
    moved = board.move(card.id, "done")

    events = move_notifications(board.config, moved, "done", lambda: False)

    assert [e.kind for e in events] == [Kind.notice]
    assert events[0].body == "Tell Ana"


def test_an_empty_sprint_event_has_no_card(board: Board) -> None:
    card = _card(board)
    moved = board.move(card.id, "review")

    events = move_notifications(board.config, moved, "review", lambda: True)

    assert [e.kind for e in events] == [Kind.review, Kind.sprint_empty]
    assert events[1].card is None


def test_the_ntfy_payload_has_a_tag_and_a_priority_per_kind(board: Board) -> None:
    card = _card(board)
    expected = {
        Kind.review: ("eyes", 4),  # a high-priority card raises the push priority
        Kind.done: ("white_check_mark", 4),
        Kind.notice: ("bell", 4),
        Kind.sprint_empty: ("zzz", 2),
        Kind.agent_waiting: ("robot", 4),
    }
    for kind, (tag, priority) in expected.items():
        payload = _payload("topic", _event(kind, card))
        assert payload["tags"] == [tag]
        assert payload["priority"] == priority
        assert "markdown" not in payload
        assert (payload["topic"], payload["title"]) == ("topic", "Demo: title")


def test_a_normal_priority_review_uses_the_default_ntfy_priority(board: Board) -> None:
    card = board.add("Plain", priority="low")
    assert _priority(_event(Kind.review, card)) == 3
    assert _priority(_event(Kind.done, None)) == 3


def test_a_card_message_is_plain_text_with_title_type_priority_and_board(board: Board) -> None:
    card = _card(board)

    message = _message(_event(Kind.review, card))

    assert message == f"Fix *export* [now]\n#{card.id} · bug · high priority\nBoard: Demo"


def test_a_notice_message_puts_the_notice_first_then_the_card(board: Board) -> None:
    card = _card(board, notice="Tell Ana")

    message = _message(_event(Kind.notice, card, body="Tell Ana"))

    assert message.splitlines()[0] == "Tell Ana"
    assert "Fix" in message
    assert message.endswith("Board: Demo")


def test_a_message_without_a_card_is_the_body_and_the_board() -> None:
    assert _message(_event(Kind.sprint_empty, body="Plan work")) == "Plan work\n\nBoard: Demo"


def test_non_ascii_text_is_sent_as_is() -> None:
    payload = _payload("topic", Notification(Kind.agent_waiting, "Ação — pronta", "Olá", "Demo"))
    assert payload["title"] == "Ação — pronta"
    assert "Olá" in str(payload["message"])
