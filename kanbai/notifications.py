"""The structured event behind every kanbai notification.

``Board.on_notify`` hands one of these to the CLI/web hook, which fans it out to the channels:
the native desktop notification reads just ``title``/``body``, while ntfy also uses ``kind``
and ``card`` to pick tags, priority and a richer message.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from .models import BoardConfig, Card


class Kind(str, Enum):
    """What happened — decides the ntfy emoji tag and priority."""

    review = "review"
    done = "done"
    notice = "notice"
    sprint_empty = "sprint_empty"
    permission = "permission"
    input_needed = "input_needed"
    idle = "idle"


@dataclass(frozen=True)
class Notification:
    """One notification: plain ``title``/``body`` for simple channels, plus the event data."""

    kind: Kind
    title: str
    body: str
    board: str
    card: Card | None = None


def move_notifications(
    config: BoardConfig, card: Card, column: str, sprint_is_empty: Callable[[], bool]
) -> list[Notification]:
    """The notifications a move of ``card`` into ``column`` needs, in firing order.

    Independent checks, any of which may apply:
    - The card reached ``done`` carrying a notice that has not been passed on yet.
    - The card itself reached ``review`` (or ``done``, on boards with no ``review`` column —
      there the terminal move is the one that needs approval).
    - The sprint (``todo``) has no actionable card left to pick up next (``sprint_is_empty``,
      only evaluated when the card landed in review/done).
    """
    review = config.review_column
    done = config.done_column
    name = config.name
    found: list[Notification] = []
    if column == done and card.notice and not card.notice_sent:
        found.append(
            Notification(
                kind=Kind.notice,
                title=f"{name}: card {card.id} done, pass on the notice",
                body=card.notice,
                board=name,
                card=card,
            )
        )
    if column == (review if review is not None else done):
        label = "review" if review is not None else "done"
        found.append(
            Notification(
                kind=Kind.review if review is not None else Kind.done,
                title=f"{name}: card {card.id} in {label}",
                body=card.title,
                board=name,
                card=card,
            )
        )
    if column in (review, done) and sprint_is_empty():
        found.append(
            Notification(
                kind=Kind.sprint_empty,
                title=f"{name}: sprint empty",
                body="No actionable cards in the sprint — plan work into todo.",
                board=name,
            )
        )
    return found


# Claude Code `Notification` hook types worth a push, and what each one means. Every other
# `notification_type` (auth_success, agent_completed, quota_*, ...) is ignored.
_HOOK_KINDS = {
    "permission_prompt": Kind.permission,
    "elicitation_dialog": Kind.input_needed,
    "elicitation_url_dialog": Kind.input_needed,
    "agent_needs_input": Kind.input_needed,
    "idle_prompt": Kind.idle,
}
# kind -> (title suffix, fallback body when Claude's own message is missing)
_HOOK_TEXT = {
    Kind.permission: ("Claude needs your approval", "Claude is waiting for your approval."),
    Kind.input_needed: ("Claude needs your input", "Claude has a question for you."),
    Kind.idle: ("Claude is waiting for you", "Claude finished and is waiting for your next step."),
}


def hook_notification(
    payload: Mapping[str, object], board: str, in_progress: list[Card]
) -> Notification | None:
    """The notification for a Claude Code ``Notification`` hook payload, or ``None`` to ignore it.

    The body is Claude's own ``message`` (it names the tool or question) when present. When
    exactly one card is in progress, it is named too; with none or several, nothing is guessed.
    """
    kind = _HOOK_KINDS.get(str(payload.get("notification_type")))
    if kind is None:
        return None
    suffix, fallback = _HOOK_TEXT[kind]
    message = payload.get("message")
    body = message.strip() if isinstance(message, str) and message.strip() else fallback
    if len(in_progress) == 1:
        body += f"\n\nCard #{in_progress[0].id}: {in_progress[0].title}"
    return Notification(kind=kind, title=f"{board}: {suffix}", body=body, board=board)
