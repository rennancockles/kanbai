"""Exception types raised across kanbai."""

from __future__ import annotations


class KanbaiError(Exception):
    """Base class for all recoverable kanbai errors (shown to the user as a message)."""


class BoardNotFoundError(KanbaiError):
    """Raised when no `.kanbai/` board can be found from the current directory."""

    def __init__(self) -> None:
        super().__init__("No kanbai board found. Run `kanbai init` in your project root first.")


class CardNotFoundError(KanbaiError):
    """Raised when a card id cannot be resolved on the board."""

    def __init__(self, card_id: str) -> None:
        self.card_id = card_id
        super().__init__(f"No card found with id '{card_id}'.")


class ColumnNotFoundError(KanbaiError):
    """Raised when a column name is not part of the board configuration."""

    def __init__(self, column: str, columns: list[str]) -> None:
        self.column = column
        super().__init__(f"Unknown column '{column}'. Valid columns: {', '.join(columns)}.")


class InvalidPriorityError(KanbaiError):
    """Raised when a priority value is not one of low / medium / high."""

    def __init__(self, value: str) -> None:
        self.value = value
        super().__init__(f"Invalid priority '{value}'. Use one of: low, medium, high.")


class InvalidTypeError(KanbaiError):
    """Raised when a card type is not one of the board's configured types."""

    def __init__(self, value: str, valid_types: list[str]) -> None:
        self.value = value
        super().__init__(f"Invalid type '{value}'. Use one of: {', '.join(valid_types)}.")
