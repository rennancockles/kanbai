"""Domain models for kanbai cards and board configuration."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Priority(str, Enum):
    """Card priority. Ordered so that ``high`` sorts before ``low``."""

    low = "low"
    medium = "medium"
    high = "high"

    @property
    def rank(self) -> int:
        """Lower rank sorts first (high-priority cards come first)."""
        return {Priority.high: 0, Priority.medium: 1, Priority.low: 2}[self]


# Fields that live in the YAML frontmatter, in the order they are written to disk.
FRONTMATTER_FIELDS = (
    "id",
    "title",
    "status",
    "priority",
    "type",
    "version",
    "order",
    "labels",
    "deps",
    "assignee",
    "archived_from",
    "created",
    "updated",
)


class Card(BaseModel):
    """A single task on the board.

    ``status`` mirrors the column folder the card lives in; the folder is the source of
    truth and ``status`` is kept in sync on every write. ``body`` is the Markdown content
    after the frontmatter and is not itself a frontmatter field.
    """

    model_config = ConfigDict(use_enum_values=False)

    id: str
    title: str
    status: str
    priority: Priority = Priority.medium
    # Single structured category (feature/bug/chore/...), distinct from the free-form labels
    # below. Unset for cards created before this field existed, or when the user skips it.
    type: str | None = None
    # Free-form release marker (e.g. "v1.2.0"), set when a card is closed out in a sprint so
    # the archive can later show which release shipped it. Not validated against any list.
    version: str | None = None
    order: int = 0
    labels: list[str] = Field(default_factory=list)
    deps: list[str] = Field(default_factory=list)
    assignee: str | None = None
    # The column a card was in before it was archived (so we know it was, e.g., finished).
    archived_from: str | None = None
    created: datetime
    updated: datetime
    body: str = ""

    def frontmatter(self) -> dict[str, object]:
        """Return an ordered mapping of the frontmatter fields for serialization."""
        data: dict[str, object] = {}
        for field in FRONTMATTER_FIELDS:
            value = getattr(self, field)
            # Only archived cards carry this marker — keep it off every other card.
            if field == "archived_from" and value is None:
                continue
            # Untyped cards (created before this field existed, or left unset) omit it too.
            if field == "type" and value is None:
                continue
            if field == "version" and value is None:
                continue
            if isinstance(value, Priority):
                value = value.value
            data[field] = value
        return data

    def sort_key(self) -> tuple[int, int, str]:
        """Ordering within a column: explicit order, then priority, then id."""
        return (self.order, self.priority.rank, self.id)


class BoardConfig(BaseModel):
    """Board-level configuration loaded from ``.kanbai/config.toml``."""

    name: str = "kanbai board"
    columns: list[str] = Field(
        default_factory=lambda: ["backlog", "todo", "doing", "review", "done"]
    )
    default_priority: Priority = Priority.medium
    # Configurable list of valid card types; empty means the board doesn't use types at all.
    types: list[str] = Field(
        default_factory=lambda: ["feature", "bug", "refactor", "chore", "docs", "spike"]
    )
    # Optional per-type hex color override (e.g. {"spec": "#ffaa00"}); a type absent here
    # uses the built-in color for known types, or a neutral gray for unknown ones.
    type_colors: dict[str, str] = Field(default_factory=dict)
    # Optional work-in-progress limits per column; a column absent here has no limit.
    wip: dict[str, int] = Field(default_factory=dict)
    # Notify the user when a card reaches review/done, or the sprint runs out of actionable
    # cards. On by default — it degrades gracefully if unsupported (e.g. an unsigned
    # executable on macOS), so there's no setup cost to leaving it on.
    notifications_native: bool = True
    # ntfy (https://ntfy.sh) topic to push to; empty/unset means the channel is off. Opt-in
    # by presence (unlike the two booleans above) since a topic is required to publish at all.
    notifications_ntfy_topic: str = ""

    def wip_limit(self, column: str) -> int | None:
        """The configured WIP limit for ``column``, or ``None`` if it has no limit."""
        return self.wip.get(column)

    def _column_from_end(self, offset: int) -> str:
        """Column ``offset`` positions from the end (0 = last), clamped to the first column."""
        index = max(len(self.columns) - 1 - offset, 0)
        return self.columns[index]

    def _named_or(self, name: str, offset: int) -> str:
        """The column called ``name`` if the board has it, else the positional fallback.

        Roles resolve by well-known name first (so adding a ``review`` column doesn't shift
        the others), falling back to an end-anchored position for boards with custom names.
        """
        return name if name in self.columns else self._column_from_end(offset)

    @property
    def add_column(self) -> str:
        """Where `kanbai add` puts new cards by default (the backlog, or the first column)."""
        return "backlog" if "backlog" in self.columns else self.columns[0]

    @property
    def sprint_column(self) -> str:
        """The column `next` pulls from — the planned work (``todo``), not the backlog."""
        return self._named_or("todo", 2)

    @property
    def review_column(self) -> str | None:
        """The column finished cards await approval in, if the board has a ``review`` stage."""
        return "review" if "review" in self.columns else None

    @property
    def doing_column(self) -> str:
        """The in-progress column `start` moves cards to."""
        return self._named_or("doing", 1)

    @property
    def done_column(self) -> str:
        """The terminal column `done` (approval) moves cards to (the last column)."""
        return self._named_or("done", 0)
