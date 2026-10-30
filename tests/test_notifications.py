"""The structured notification events and how ntfy renders them."""

from __future__ import annotations

from pathlib import Path

import pytest
from kanbai import scaffold
from kanbai.board import Board
from kanbai.models import Card
from kanbai.notifications import Kind, Notification, hook_notification, move_notifications
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
        Kind.permission: ("lock", 4),
        Kind.input_needed: ("question", 4),
        Kind.idle: ("hourglass_flowing_sand", 3),
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
    payload = _payload("topic", Notification(Kind.idle, "Ação — pronta", "Olá", "Demo"))
    assert payload["title"] == "Ação — pronta"
    assert "Olá" in str(payload["message"])


@pytest.mark.parametrize(
    ("notification_type", "kind", "title"),
    [
        ("permission_prompt", Kind.permission, "Demo: Claude needs your approval"),
        ("elicitation_dialog", Kind.input_needed, "Demo: Claude needs your input"),
        ("elicitation_url_dialog", Kind.input_needed, "Demo: Claude needs your input"),
        ("agent_needs_input", Kind.input_needed, "Demo: Claude needs your input"),
        ("idle_prompt", Kind.idle, "Demo: Claude is waiting for you"),
    ],
)
def test_each_waiting_hook_type_gets_its_own_kind_and_title(
    notification_type: str, kind: Kind, title: str
) -> None:
    event = hook_notification({"notification_type": notification_type}, "Demo", [])

    assert event is not None
    assert (event.kind, event.title, event.board, event.card) == (kind, title, "Demo", None)


@pytest.mark.parametrize(
    "notification_type",
    ["auth_success", "agent_completed", "elicitation_complete", "quota_auto_resume_fired", None],
)
def test_unrelated_hook_types_are_ignored(notification_type: str | None) -> None:
    assert hook_notification({"notification_type": notification_type}, "Demo", []) is None
    assert hook_notification({}, "Demo", []) is None


def test_the_hook_body_is_claudes_own_message_or_a_per_type_fallback() -> None:
    said = hook_notification(
        {"notification_type": "permission_prompt", "message": "  Claude needs permission to Bash "},
        "Demo",
        [],
    )
    assert said is not None
    assert said.body == "Claude needs permission to Bash"

    for message in (None, "", "   ", 42):
        fallback = hook_notification(
            {"notification_type": "permission_prompt", "message": message}, "Demo", []
        )
        assert fallback is not None
        assert fallback.body == "Claude is waiting for your approval."
    idle = hook_notification({"notification_type": "idle_prompt"}, "Demo", [])
    assert idle is not None
    assert idle.body != "Claude is waiting for your approval."


def test_the_hook_names_the_card_only_when_exactly_one_is_in_progress(board: Board) -> None:
    first = board.add("First", column="doing")
    second = board.add("Second", column="doing")
    payload = {"notification_type": "idle_prompt", "message": "Done"}

    one = hook_notification(payload, "Demo", [first])
    none = hook_notification(payload, "Demo", [])
    several = hook_notification(payload, "Demo", [first, second])

    assert one is not None
    assert one.body == f"Done\n\nCard #{first.id}: First"
    assert none is not None
    assert several is not None
    assert none.body == several.body == "Done"
