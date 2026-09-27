"""The AI command input: extract kanban card fields from a natural-language instruction.

Provider-agnostic — works with Anthropic or OpenAI, whichever the user has an API key
for (env vars only, never `.kanbai/config.toml`, since this is a process-wide "which AI
does my kanbai use" setting rather than a per-board one — see card 069's plan for why).
Opt-in by presence: with neither key set, :func:`ai_available` is False and the web UI
hides the input entirely rather than showing an error.
"""

from __future__ import annotations

import os

from pydantic import ValidationError

from ..models import BoardConfig
from . import _anthropic, _openai
from .schema import ExtractedCard, build_schema

__all__ = [
    "ExtractedCard",
    "ai_available",
    "clamp_to_board",
    "configured_provider",
    "extract_card",
]

#: Explicit provider override — takes precedence over which key is present, but the
#: named provider still needs its own key set (see `configured_provider`'s docstring).
_PROVIDER_ENV = "KANBAI_AI_PROVIDER"
#: Explicit model override, for either provider.
_MODEL_ENV = "KANBAI_AI_MODEL"

_PROVIDERS = {
    "anthropic": _anthropic,
    "openai": _openai,
}


def configured_provider() -> tuple[str, str] | None:
    """The ``(provider, model)`` to use, or ``None`` if neither provider is usable.

    Auto-detects from ``ANTHROPIC_API_KEY``/``OPENAI_API_KEY`` (Anthropic wins if both
    are set). ``KANBAI_AI_PROVIDER`` picks precedence between providers whose keys are
    already present — it does not bypass the key check. Forcing a provider with no key
    set would make the feature appear available with no way to actually call it, which
    is worse than staying hidden.
    """
    override = os.environ.get(_PROVIDER_ENV, "").strip().lower()
    if override in _PROVIDERS and _PROVIDERS[override].has_key():
        provider = override
    elif _anthropic.has_key():
        provider = "anthropic"
    elif _openai.has_key():
        provider = "openai"
    else:
        return None

    model = os.environ.get(_MODEL_ENV, "").strip() or _PROVIDERS[provider].DEFAULT_MODEL
    return provider, model


def ai_available() -> bool:
    """Whether the AI command input should be shown at all."""
    return configured_provider() is not None


def extract_card(instruction: str, *, board_names: list[str] | None) -> ExtractedCard | None:
    """Extract card fields from ``instruction`` using the configured provider.

    ``board_names=None`` for single-board mode (no ``board`` field in the schema);
    ``board_names=[...]`` for hub mode (``board`` becomes a required enum). Returns
    ``None`` on any failure — missing provider, API error, refusal, or a response that
    doesn't validate against :class:`ExtractedCard` — callers render a single generic
    "couldn't understand that" message rather than branching on failure type.
    """
    resolved = configured_provider()
    if resolved is None:
        return None
    provider, model = resolved

    schema = build_schema(board_names=board_names)
    raw = _PROVIDERS[provider].call(instruction, schema, model)
    if raw is None:
        return None
    try:
        return ExtractedCard.model_validate(raw)
    except ValidationError:
        return None


def clamp_to_board(card: ExtractedCard, config: BoardConfig) -> ExtractedCard:
    """Coerce an AI-extracted card's ``column``/``type`` to values this board actually has.

    The AI is never told a specific board's real columns/types (see ``schema``'s
    docstring) — its guess is free text, so it's sanity-checked here before ending up in
    a ``<select>`` the browser would otherwise render as an invalid/blank option.
    """
    column = card.column if card.column in config.visible_columns else config.add_column
    type_ = card.type if card.type in config.types else None
    return card.model_copy(update={"column": column, "type": type_})
