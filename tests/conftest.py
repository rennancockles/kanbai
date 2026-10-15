"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from kanbai import scaffold
from kanbai.board import Board


@pytest.fixture(autouse=True)
def _isolated_kanbai_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never read or write the developer's real ~/.kanbai (registry, global credentials)."""
    monkeypatch.setenv("KANBAI_HOME", str(tmp_path_factory.mktemp("kanbai_home")))


@pytest.fixture
def board(tmp_path: Path) -> Board:
    """An initialized, empty board rooted at a temp directory."""
    scaffold.init_board(tmp_path)
    return Board.load(tmp_path)
