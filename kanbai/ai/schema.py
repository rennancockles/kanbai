"""The card fields the AI command extracts, and the JSON schema it's constrained to."""

from __future__ import annotations

from pydantic import BaseModel, Field

#: Shared system prompt for both providers — kept in one place so the labels-inference
#: instruction (and any future tweak) doesn't drift between _anthropic.py/_openai.py.
SYSTEM_PROMPT = (
    "Extract kanban card fields from the user's instruction. Always propose 1-3 relevant "
    "labels based on the topic and content, even if the user didn't type any explicitly. "
    "Respond only with the structured fields — no extra commentary."
)


class ExtractedCard(BaseModel):
    """A card's fields as extracted from a natural-language instruction.

    ``column``/``type``/``priority`` are free-text here — the route handler clamps them
    to the target board's real config (see ``kanbai.web.app``'s clamping helper) rather
    than trusting the model's guess, so this model doesn't need to know a board's actual
    columns/types to be useful.
    """

    title: str
    description: str = ""
    type: str | None = None
    priority: str = "medium"
    labels: list[str] = Field(default_factory=list)
    column: str
    board: str | None = None  # only meaningful when extracted in hub mode


def build_schema(*, board_names: list[str] | None) -> dict[str, object]:
    """The JSON schema passed to the LLM for structured extraction.

    ``board_names=None`` (single-board mode) omits the ``board`` property entirely —
    the board is implicit. ``board_names=[...]`` (hub mode) makes ``board`` a required
    enum of the registered board names, so the model must pick one of the boards that
    actually exist.

    ``column``/``type``/``priority`` are always free-text strings, not per-board enums:
    in hub mode the real columns/types aren't known until after the model picks a board,
    and in single-board mode the real values are re-derived and clamped server-side
    anyway (see the caller) — constraining the LLM call itself would need a second
    round-trip for no real accuracy gain.
    """
    # Both providers' strict JSON-schema modes require every property to be listed in
    # `required` when `additionalProperties: false` — "optional" fields are modeled as
    # nullable types instead of being omitted from `required`.
    properties: dict[str, object] = {
        "title": {"type": "string", "description": "A short, specific card title."},
        "description": {
            "type": "string",
            "description": "A one or two sentence description of the task, or empty string.",
        },
        "type": {
            "type": ["string", "null"],
            "description": "The card type (e.g. feature, bug, chore), or null if unclear.",
        },
        "priority": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "The card's priority; default to 'medium' if not stated.",
        },
        "labels": {
            "type": "array",
            "items": {"type": "string"},
            "description": "1-3 short, lowercase labels/tags for this card — infer them "
            "from the topic and content of the instruction (e.g. the area of the codebase, "
            "the kind of work), not just literal tags the user typed. Empty only if truly "
            "nothing relevant comes to mind.",
        },
        "column": {
            "type": "string",
            "description": "Which column/stage the card belongs in "
            "(e.g. backlog, todo, doing); default to the backlog if unclear.",
        },
    }
    required = ["title", "description", "type", "priority", "labels", "column"]

    if board_names is not None:
        properties["board"] = {
            "type": "string",
            "enum": board_names,
            "description": "Which registered board the card belongs to.",
        }
        required.append("board")

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
