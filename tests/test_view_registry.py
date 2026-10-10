"""Tests for the view registry (single multi-board view)."""

from __future__ import annotations

from pathlib import Path

import pytest
from kanbai import view_registry


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KANBAI_HOME", str(tmp_path / "home"))


def test_load_view_returns_empty_when_no_file() -> None:
    assert view_registry.load_view() == []


def test_save_and_load_view() -> None:
    view_registry.save_view(["proj-a", "proj-b"])
    assert view_registry.load_view() == ["proj-a", "proj-b"]


def test_save_view_replaces_previous() -> None:
    view_registry.save_view(["a", "b"])
    view_registry.save_view(["c"])
    assert view_registry.load_view() == ["c"]


def test_save_empty_view() -> None:
    view_registry.save_view(["a"])
    view_registry.save_view([])
    assert view_registry.load_view() == []
