"""Board operations built on top of the storage layer.

``Board`` is the object both the CLI and web UI talk to. It owns the board root and its
configuration and exposes the verbs of the app: add / move / list / next / show / edit /
archive / remove.
"""

from __future__ import annotations

from pathlib import Path

from . import storage
from .config import load_config
from .errors import (
    BoardNotFoundError,
    CardNotFoundError,
    ColumnNotFoundError,
)
from .models import BoardConfig, Card, Priority


class Board:
    """A loaded kanbai board rooted at a ``.kanbai/`` directory."""

    def __init__(self, kanbai_dir: Path, config: BoardConfig) -> None:
        self.kanbai_dir = kanbai_dir
        self.config = config

    @classmethod
    def load(cls, start: Path | None = None) -> Board:
        """Find the nearest ``.kanbai/`` directory and load its configuration."""
        kanbai_dir = storage.find_kanbai_dir(start)
        if kanbai_dir is None:
            raise BoardNotFoundError()
        return cls(kanbai_dir, load_config(kanbai_dir))

    @property
    def columns(self) -> list[str]:
        return self.config.columns

    def _require_column(self, column: str) -> None:
        if column not in self.columns:
            raise ColumnNotFoundError(column, self.columns)

    def _locate(self, card_id: str) -> tuple[Card, Path, str]:
        found = storage.find_card_path(self.kanbai_dir, self.columns, card_id)
        if found is None:
            raise CardNotFoundError(card_id)
        path, column = found
        return storage.parse_card(path, column), path, column

    def _next_order(self, column: str) -> int:
        cards = storage.read_column(self.kanbai_dir, column)
        return max((c.order for c in cards), default=0) + 1

    # ------------------------------------------------------------------ commands

    def add(
        self,
        title: str,
        *,
        description: str = "",
        priority: str | Priority | None = None,
        column: str | None = None,
        labels: list[str] | None = None,
        deps: list[str] | None = None,
        assignee: str | None = None,
    ) -> Card:
        """Create a new card and write it to disk."""
        column = column or self.config.add_column
        self._require_column(column)
        resolved_priority = (
            storage.coerce_priority(priority)
            if priority is not None
            else self.config.default_priority
        )
        timestamp = storage.now()
        card = Card(
            id=storage.next_id(self.kanbai_dir, self.columns),
            title=title,
            status=column,
            priority=resolved_priority,
            order=self._next_order(column),
            labels=labels or [],
            deps=deps or [],
            assignee=assignee,
            created=timestamp,
            updated=timestamp,
            body=description,
        )
        storage.write_card(self.kanbai_dir, card)
        return card

    def move(self, card_id: str, column: str, *, position: int | None = None) -> Card:
        """Move a card to ``column``, updating its status, order and timestamp.

        When ``position`` is given, the card is inserted at that index within the column and
        the column's ``order`` values are reflowed — this is what persists drag-to-reorder
        (including reordering within the same column). When ``position`` is ``None`` the card
        is appended to the end of a new column (unchanged when staying in the same column).
        """
        self._require_column(column)
        card, old_path, old_column = self._locate(card_id)
        card.status = column
        if position is None and column != old_column:
            card.order = self._next_order(column)
        card.updated = storage.now()
        storage.delete_card_file(old_path)
        storage.write_card(self.kanbai_dir, card)
        if position is not None:
            self._place_at(column, card_id, position)
            card, _, _ = self._locate(card_id)
        return card

    def _place_at(self, column: str, card_id: str, position: int) -> None:
        """Insert ``card_id`` at ``position`` within ``column`` and reflow order values."""
        cards = storage.read_column(self.kanbai_dir, column)
        moved = next(c for c in cards if c.id == card_id)
        others = [c for c in cards if c.id != card_id]
        index = max(0, min(position, len(others)))
        ordered = [*others[:index], moved, *others[index:]]
        for new_order, card in enumerate(ordered, start=1):
            if card.order != new_order:
                card.order = new_order
                storage.write_card(self.kanbai_dir, card)

    def board(self) -> dict[str, list[Card]]:
        """Return every column and its cards."""
        return storage.read_all(self.kanbai_dir, self.columns)

    def list_column(self, column: str) -> list[Card]:
        """Return the cards in a single column."""
        self._require_column(column)
        return storage.read_column(self.kanbai_dir, column)

    def next(self) -> Card | None:
        """Return the next actionable card in the sprint (the ``todo`` column).

        The backlog is intentionally not considered — only cards planned into the sprint are
        picked up. A card is actionable when every dependency it lists is already in the done
        column (an unknown dependency id is treated as non-blocking). Cards are considered in
        column order, so the top of the sprint wins ties.
        """
        location = self._status_by_id()
        for card in storage.read_column(self.kanbai_dir, self.config.sprint_column):
            if self._deps_met(card, location):
                return card
        return None

    def blocked_ids(self) -> set[str]:
        """Return the ids of cards with at least one dependency not yet in the done column.

        Mirrors the actionability check used by :meth:`next` (an unknown dependency id is
        treated as satisfied), so the UI can flag exactly the cards `next` would skip.
        """
        columns = self.board()
        location = {card.id: column for column, cards in columns.items() for card in cards}
        done = self.config.done_column
        blocked: set[str] = set()
        for cards in columns.values():
            for card in cards:
                if card.deps and any(location.get(dep, done) != done for dep in card.deps):
                    blocked.add(card.id)
        return blocked

    def show(self, card_id: str) -> Card:
        """Return the full card for ``card_id``."""
        card, _, _ = self._locate(card_id)
        return card

    def edit(  # noqa: PLR0913 - one keyword-only param per editable card field
        self,
        card_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: str | Priority | None = None,
        labels: list[str] | None = None,
        deps: list[str] | None = None,
        assignee: str | None = None,
        order: int | None = None,
    ) -> Card:
        """Update fields on a card. Only provided fields change."""
        card, old_path, _ = self._locate(card_id)
        if title is not None:
            card.title = title
        if description is not None:
            card.body = description
        if priority is not None:
            card.priority = storage.coerce_priority(priority)
        if labels is not None:
            card.labels = labels
        if deps is not None:
            card.deps = deps
        if assignee is not None:
            card.assignee = assignee
        if order is not None:
            card.order = order
        card.updated = storage.now()
        storage.delete_card_file(old_path)
        storage.write_card(self.kanbai_dir, card)
        return card

    def archive(self, card_id: str) -> Card:
        """Move a card into the ``.kanbai/archive/`` folder, recording where it came from."""
        card, old_path, old_column = self._locate(card_id)
        if old_column != storage.ARCHIVE_DIRNAME:
            card.archived_from = old_column
        card.status = storage.ARCHIVE_DIRNAME
        card.updated = storage.now()
        storage.delete_card_file(old_path)
        storage.write_card(self.kanbai_dir, card)
        return card

    def remove(self, card_id: str) -> Card:
        """Delete a card from disk entirely."""
        card, path, _ = self._locate(card_id)
        storage.delete_card_file(path)
        return card

    def new_sprint(self, *, reset_to_backlog: bool) -> dict[str, int]:
        """Start a fresh sprint: archive every done card, then optionally send the active
        columns (everything except backlog and done) back to the backlog.

        Returns counts of what happened: ``{"archived": n, "reset": m}``.
        """
        backlog = self.config.add_column
        done = self.config.done_column

        archived = 0
        for card in self.list_column(done):
            self.archive(card.id)
            archived += 1

        reset = 0
        if reset_to_backlog:
            for column in self.columns:
                if column in (backlog, done):
                    continue
                for card in self.list_column(column):
                    self.move(card.id, backlog)
                    reset += 1

        return {"archived": archived, "reset": reset}

    # ------------------------------------------------------------------ helpers

    def _status_by_id(self) -> dict[str, str]:
        location: dict[str, str] = {}
        for column, cards in self.board().items():
            for card in cards:
                location[card.id] = column
        return location

    def _deps_met(self, card: Card, location: dict[str, str]) -> bool:
        done = self.config.done_column
        return all(location.get(dep, done) == done for dep in card.deps)
