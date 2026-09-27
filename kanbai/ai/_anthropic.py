"""The Anthropic-specific half of the AI command: one structured-output call.

Imported lazily by ``kanbai.ai.extract_card`` — the ``anthropic`` package is only
required when the user actually has ``ANTHROPIC_API_KEY`` set and picks this provider,
via the optional ``ai`` extra.
"""

from __future__ import annotations

import json
import os

from .schema import SYSTEM_PROMPT


def call(instruction: str, schema: dict[str, object], model: str) -> dict[str, object] | None:
    """Ask Claude to extract card fields from ``instruction``, constrained to ``schema``.

    Returns the parsed JSON dict, or ``None`` on any failure (missing SDK, bad key,
    network error, refusal, or a response that isn't valid JSON) — callers treat every
    failure mode the same way, so there's no exception type for them to handle.
    """
    try:
        import anthropic  # noqa: PLC0415 - optional extra, imported on demand
    except ImportError:
        return None

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": instruction}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except Exception:  # noqa: BLE001 - any SDK/network/auth failure degrades the same way
        return None

    if response.stop_reason == "refusal":
        return None
    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


#: Default model when the user hasn't overridden it via ``KANBAI_AI_MODEL`` — cheap and
#: fast, sufficient for this simple field-extraction task (see card 069's spike).
DEFAULT_MODEL = "claude-haiku-4-5"

#: The env var this provider's API key is read from (by the SDK itself, implicitly).
API_KEY_ENV = "ANTHROPIC_API_KEY"


def has_key() -> bool:
    return bool(os.environ.get(API_KEY_ENV))
