"""The OpenAI-specific half of the AI command: one structured-output call.

Imported lazily by ``kanbai.ai.extract_card`` — the ``openai`` package is only required
when the user actually has ``OPENAI_API_KEY`` set and picks this provider, via the
optional ``ai`` extra.
"""

from __future__ import annotations

import json
import os

from .schema import SYSTEM_PROMPT


def call(instruction: str, schema: dict[str, object], model: str) -> dict[str, object] | None:
    """Ask the model to extract card fields from ``instruction``, constrained to ``schema``.

    Returns the parsed JSON dict, or ``None`` on any failure (missing SDK, bad key,
    network error, or a response that isn't valid JSON) — mirrors ``_anthropic.call``'s
    contract so ``extract_card`` can treat both providers identically.
    """
    try:
        import openai  # noqa: PLC0415 - optional extra, imported on demand
    except ImportError:
        return None

    try:
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": instruction},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "extracted_card", "schema": schema, "strict": True},
            },
        )
    except Exception:  # noqa: BLE001 - any SDK/network/auth failure degrades the same way
        return None

    choice = response.choices[0] if response.choices else None
    if choice is None or choice.finish_reason == "content_filter" or choice.message.refusal:
        return None
    text = choice.message.content
    if text is None:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


#: Default model when the user hasn't overridden it via ``KANBAI_AI_MODEL`` — cheap and
#: fast, and supports structured outputs.
DEFAULT_MODEL = "gpt-4o-mini"

#: The env var this provider's API key is read from (by the SDK itself, implicitly).
API_KEY_ENV = "OPENAI_API_KEY"


def has_key() -> bool:
    return bool(os.environ.get(API_KEY_ENV))
