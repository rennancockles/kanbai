"""Hosted mode with the local files as the source of truth.

:class:`MirrorBoard` wraps the project's local :class:`~kanbai.board.Board` and the hosted board
it is connected to. Reads (``list``, ``show``, ``next``...) come from the local files, so they
work offline. Every command that changes cards is applied locally first and then replicated to
the host, card by card, reusing the remote operations ``hosted push`` is built from.

Replicating never makes the command fail: when the server is unreachable, rejects a change, or
holds a card that no longer matches what the local board had, the change stays local, the
project is recorded as out of sync (``kanbai.sync_state``) and the user is told to run
``kanbai hosted push`` or ``pull``. Notifications fire once, from the local board; the remote
board is never given a notification callback.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from . import hosted, storage, sync_state
from .board import Board
from .config import RemoteConfig
from .errors import KanbaiError, RemoteAPIError
from .models import Card
from .remote_board import RemoteBoard

R = TypeVar("R")

_NOT_FOUND = 404
#: Card fields replicated as one edit; ``body`` is sent as ``description``.
_EDITABLE = (
    "title",
    "body",
    "priority",
    "type",
    "version",
    "labels",
    "deps",
    "assignee",
    "order",
    "notice",
    "notice_sent",
)
#: Fields the API can only clear with an empty string (``None`` means "leave unchanged").
_CLEARED_WITH_EMPTY_STRING = ("type", "version")


class MirrorBoard:
    """Local board (read and written) that mirrors every change to its hosted board."""

    def __init__(
        self,
        local: Board,
        remote_config: RemoteConfig,
        warn: Callable[[str], None],
    ) -> None:
        self.local = local
        self._remote_config = remote_config
        self._remote: RemoteBoard | None = None
        self._warn = warn

    # Reads (and ``config``, ``kanbai_dir``, ...) are the local board's.
    def __getattr__(self, name: str) -> Any:
        return getattr(self.local, name)

    @property
    def on_notify(self) -> Callable[[str, str], None] | None:
        return self.local.on_notify

    @on_notify.setter
    def on_notify(self, callback: Callable[[str, str], None] | None) -> None:
        self.local.on_notify = callback

    # Every mutation runs on the local board, then replicates whatever it changed.
    def _run(self, method: Callable[..., R], *args: Any, **kwargs: Any) -> R:
        before = self._snapshot()
        result = method(*args, **kwargs)
        self._replicate(before, self._snapshot())
        return result

    def add(self, title: str, **fields: Any) -> Card:
        return self._run(self.local.add, title, **fields)

    def move(self, card_id: str, column: str, *, position: int | None = None) -> Card:
        return self._run(self.local.move, card_id, column, position=position)

    def edit(self, card_id: str, **fields: Any) -> Card:
        return self._run(self.local.edit, card_id, **fields)

    def archive(self, card_id: str) -> Card:
        return self._run(self.local.archive, card_id)

    def remove(self, card_id: str) -> Card:
        return self._run(self.local.remove, card_id)

    def restore(self, card_id: str) -> Card:
        return self._run(self.local.restore, card_id)

    def clear_archive(self) -> int:
        return self._run(self.local.clear_archive)

    def sort_column(self, column: str, key: str = "id", *, descending: bool = False) -> list[Card]:
        return self._run(self.local.sort_column, column, key, descending=descending)

    def new_sprint(self, *, reset_to_backlog: bool, version: str | None = None) -> dict[str, int]:
        return self._run(self.local.new_sprint, reset_to_backlog=reset_to_backlog, version=version)

    # ------------------------------------------------------------------ replication

    def _snapshot(self) -> dict[str, Card]:
        local = self.local
        cards = [c for column in local.columns for c in local.list_column(column)]
        return {c.id: c for c in (*cards, *local.list_archive())}

    def _remote_board(self) -> RemoteBoard:
        if self._remote is None:
            self._remote = RemoteBoard(self._remote_config)
        return self._remote

    def _replicate(self, before: dict[str, Card], after: dict[str, Card]) -> None:
        removed = [card_id for card_id in before if card_id not in after]
        changed = [card_id for card_id, card in after.items() if before.get(card_id) != card]
        if not removed and not changed:
            return
        problems: list[str] = []
        try:
            remote = self._remote_board()
            for card_id in removed:
                self._replicate_removal(remote, card_id)
            for card_id in changed:
                self._replicate_card(remote, before.get(card_id), after[card_id], problems)
        except KanbaiError as exc:
            problems.append(f"could not update the hosted board: {exc}")
        if problems:
            sync_state.mark_out_of_sync(self.local.kanbai_dir, problems)
            self._warn(
                f"Hosted board is out of sync ({'; '.join(problems)}). {sync_state.SYNC_HINT}"
            )

    @staticmethod
    def _replicate_removal(remote: RemoteBoard, card_id: str) -> None:
        try:
            remote.remove(card_id)
        except RemoteAPIError as exc:
            if exc.status_code != _NOT_FOUND:
                raise

    def _replicate_card(
        self, remote: RemoteBoard, before: Card | None, after: Card, problems: list[str]
    ) -> None:
        try:
            current: Card | None = remote.show(after.id)
        except RemoteAPIError as exc:
            if exc.status_code != _NOT_FOUND:
                raise
            current = None

        if current is None:
            if before is not None:
                problems.append(f"card #{after.id} was missing on the host")
            hosted._create_remote(remote, after, self.local.config.add_column)  # noqa: SLF001
            if after.deps:
                remote.edit(after.id, deps=after.deps)
            return
        if before is None:
            # A brand-new local id that the host already uses: never overwrite the host's card.
            if hosted._diff_card(after, current).changes:  # noqa: SLF001
                problems.append(f"card #{after.id} already exists on the host with other content")
            return

        drift = hosted._diff_card(before, current).changes  # noqa: SLF001
        if drift:
            fields = ", ".join(change.field for change in drift)
            problems.append(f"card #{after.id} was changed on the host ({fields})")
        self._apply_delta(remote, before, after, current)

    @staticmethod
    def _apply_delta(remote: RemoteBoard, before: Card, after: Card, current: Card) -> None:
        """Send only what this command changed, so edits made elsewhere to other fields survive."""
        status_changed = before.status != after.status
        if status_changed and current.status != after.status:
            if after.status == storage.ARCHIVE_DIRNAME:
                remote.archive(after.id)
            else:
                status = current.status
                if status == storage.ARCHIVE_DIRNAME:
                    status = remote.restore(after.id).status
                if status != after.status:
                    remote.move(after.id, after.status)
        edits: dict[str, Any] = {}
        for name in _EDITABLE:
            value = getattr(after, name)
            if getattr(before, name) == value:
                continue
            if value is None and name in _CLEARED_WITH_EMPTY_STRING:
                value = ""
            edits["description" if name == "body" else name] = value
        edits = {k: v for k, v in edits.items() if v is not None}
        if edits:
            remote.edit(after.id, **edits)
