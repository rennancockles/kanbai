"""Push notifications to ntfy.sh (https://ntfy.sh) — no ``ui`` extra required.

Only depends on ``httpx2``, a core dependency, so a plain CLI install (no ``[ui]`` extra) can
still push notifications via this channel.

Publishes through ntfy's JSON API rather than headers, so non-ASCII titles (board names,
card titles) reach the server intact.
"""

from __future__ import annotations

import sys
import threading
from typing import Any

import httpx2 as httpx

from .models import Priority
from .notifications import Kind, Notification

# Short: a short-lived CLI command blocks on this call, so a slow/unresponsive network should
# give up quickly rather than hang the command for long.
_NTFY_TIMEOUT = 3.0
_NTFY_URL = "https://ntfy.sh"

# ntfy turns a tag that is an emoji shortcode into that emoji in front of the title.
_TAGS = {
    Kind.review: "eyes",
    Kind.done: "white_check_mark",
    Kind.notice: "bell",
    Kind.sprint_empty: "zzz",
    Kind.permission: "lock",
    Kind.input_needed: "question",
    Kind.idle: "hourglass_flowing_sand",
}
_DEFAULT_PRIORITY = 3
_PRIORITIES = {
    Kind.notice: 4,
    Kind.permission: 4,
    Kind.input_needed: 4,
    Kind.sprint_empty: 2,
}
_HIGH_PRIORITY = 4


def _priority(notification: Notification) -> int:
    card = notification.card
    if notification.kind in (Kind.review, Kind.done) and card and card.priority == Priority.high:
        return _HIGH_PRIORITY
    return _PRIORITIES.get(notification.kind, _DEFAULT_PRIORITY)


def _message(notification: Notification) -> str:
    """The plain-text body: the card (or the notice) up front, then its type, priority and board.

    Deliberately not Markdown: the iOS app (and any notification banner) shows it unrendered.
    """
    card = notification.card
    if card is None:
        return f"{notification.body}\n\nBoard: {notification.board}"
    details = [f"#{card.id}"]
    if card.type:
        details.append(card.type)
    details.append(f"{card.priority.value} priority")
    lines = []
    if notification.kind is Kind.notice:
        lines += [notification.body, "", card.title]
    else:
        lines.append(card.title)
    lines += [" · ".join(details), f"Board: {notification.board}"]
    return "\n".join(lines)


def _payload(topic: str, notification: Notification) -> dict[str, Any]:
    return {
        "topic": topic,
        "title": notification.title,
        "message": _message(notification),
        "tags": [_TAGS[notification.kind]],
        "priority": _priority(notification),
    }


def notify_ntfy(topic: str, notification: Notification) -> None:
    """Push a notification to a public ntfy.sh topic, synchronously.

    ntfy.sh needs no authentication — the topic name itself acts as the secret. Any failure
    (offline ntfy.sh, DNS, a misconfigured proxy, ...) is swallowed rather than raised, so
    this best-effort channel never breaks the caller — but it's printed to stderr rather than
    fully silenced, so a persistent misconfiguration (e.g. a SOCKS proxy without ``socksio``
    installed) is still noticeable. Use :func:`notify_ntfy_background` for a caller (the web
    UI) that must never block on this at all, even for the few seconds above.
    """
    try:
        with httpx.Client(timeout=_NTFY_TIMEOUT) as client:
            client.post(_NTFY_URL, json=_payload(topic, notification))
    except Exception as exc:  # noqa: BLE001 - see docstring: this channel must never propagate
        print(f"kanbai: ntfy notification failed: {exc}", file=sys.stderr)


def notify_ntfy_background(topic: str, notification: Notification) -> None:
    """Push a notification to a public ntfy.sh topic without waiting for the result.

    Fire-and-forget, for a long-lived caller (the web UI) that keeps running regardless — a
    thread here always gets to finish on its own time, unlike in a short-lived CLI command
    that would otherwise kill it mid-request on exit. See :func:`notify_ntfy` for the
    synchronous version used there instead.
    """
    threading.Thread(target=notify_ntfy, args=(topic, notification), daemon=True).start()
