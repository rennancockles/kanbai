"""Tests for the AI command's provider detection and extraction (kanbai/ai/)."""

from __future__ import annotations

import pytest
from kanbai import ai
from kanbai.ai.schema import ExtractedCard
from kanbai.models import BoardConfig


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No AI env vars leak in from the real environment running the test suite."""
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "KANBAI_AI_PROVIDER", "KANBAI_AI_MODEL"):
        monkeypatch.delenv(var, raising=False)


def test_configured_provider_is_none_with_no_keys() -> None:
    assert ai.configured_provider() is None
    assert ai.ai_available() is False


def test_configured_provider_anthropic_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    resolved = ai.configured_provider()
    assert resolved is not None
    assert resolved == ("anthropic", ai._anthropic.DEFAULT_MODEL)
    assert ai.ai_available() is True


def test_configured_provider_openai_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    resolved = ai.configured_provider()
    assert resolved is not None
    assert resolved == ("openai", ai._openai.DEFAULT_MODEL)


def test_anthropic_wins_when_both_keys_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    resolved = ai.configured_provider()
    assert resolved is not None
    assert resolved[0] == "anthropic"


def test_provider_override_picks_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    monkeypatch.setenv("KANBAI_AI_PROVIDER", "openai")
    resolved = ai.configured_provider()
    assert resolved is not None
    assert resolved[0] == "openai"


def test_provider_override_does_not_bypass_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only ANTHROPIC_API_KEY is set; forcing "openai" without its own key must not make
    # the feature appear available with nothing to actually call.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("KANBAI_AI_PROVIDER", "openai")
    resolved = ai.configured_provider()
    assert resolved is not None
    assert resolved[0] == "anthropic"


def test_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("KANBAI_AI_MODEL", "custom-model")
    resolved = ai.configured_provider()
    assert resolved is not None
    assert resolved[1] == "custom-model"


def test_extract_card_returns_none_without_a_provider() -> None:
    assert ai.extract_card("create a card", board_names=None) is None


def test_extract_card_validates_provider_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    fake: dict[str, object] = {
        "title": "Fix login bug",
        "description": "desc",
        "type": "bug",
        "priority": "high",
        "labels": ["auth"],
        "column": "todo",
    }
    monkeypatch.setattr(ai._anthropic, "call", lambda *a, **kw: fake)  # noqa: ARG005
    card = ai.extract_card("fix the login bug", board_names=None)
    assert card == ExtractedCard.model_validate(fake)


def test_extract_card_none_when_provider_call_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(ai._anthropic, "call", lambda *a, **kw: None)  # noqa: ARG005
    assert ai.extract_card("gibberish", board_names=None) is None


def test_extract_card_none_on_malformed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    # missing the required "column" field
    monkeypatch.setattr(ai._anthropic, "call", lambda *a, **kw: {"title": "x"})  # noqa: ARG005
    assert ai.extract_card("bad shape", board_names=None) is None


def test_extract_card_uses_openai_when_that_is_the_configured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    fake: dict[str, object] = {
        "title": "Add feature",
        "description": "",
        "type": None,
        "priority": "medium",
        "labels": [],
        "column": "backlog",
        "board": "proj",
    }
    monkeypatch.setattr(ai._openai, "call", lambda *a, **kw: fake)  # noqa: ARG005
    card = ai.extract_card("add a feature to proj", board_names=["proj"])
    assert card == ExtractedCard.model_validate(fake)


def test_clamp_to_board_falls_back_when_column_or_type_are_invalid() -> None:
    config = BoardConfig(columns=["backlog", "todo", "done"], types=["feature", "bug"])
    card = ExtractedCard(title="x", column="nonexistent-column", type="nonexistent-type")
    clamped = ai.clamp_to_board(card, config)
    assert clamped.column == config.add_column
    assert clamped.type is None


def test_clamp_to_board_keeps_valid_values() -> None:
    config = BoardConfig(columns=["backlog", "todo", "done"], types=["feature", "bug"])
    card = ExtractedCard(title="x", column="todo", type="bug")
    clamped = ai.clamp_to_board(card, config)
    assert clamped.column == "todo"
    assert clamped.type == "bug"
