"""Tests for the multi-board hub registry."""

from __future__ import annotations

from pathlib import Path

import pytest
from kanbai import registry, scaffold
from kanbai.errors import KanbaiError


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the registry at a temp dir so tests never touch the real ~/.kanbai."""
    monkeypatch.setenv("KANBAI_HOME", str(tmp_path / "home"))


def test_add_list_remove(tmp_path: Path) -> None:
    board = tmp_path / "proj"
    scaffold.init_board(board)

    name, replaced = registry.add_board(board)
    assert name == "proj"  # defaults to the directory name
    assert replaced is False
    assert registry.load_boards() == {"proj": str(board.resolve())}

    registry.remove_board("proj")
    assert registry.load_boards() == {}


def test_add_uses_config_name(tmp_path: Path) -> None:
    board = tmp_path / "proj"
    scaffold.init_board(board, name="mine")
    name, _ = registry.add_board(board)
    assert name == "mine"
    assert set(registry.load_boards()) == {"mine"}


def test_add_overwrite(tmp_path: Path) -> None:
    board = tmp_path / "proj"
    scaffold.init_board(board, name="mine")
    registry.add_board(board)
    _, replaced = registry.add_board(board)
    assert replaced is True
    assert set(registry.load_boards()) == {"mine"}


def test_add_rejects_path_without_board(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(KanbaiError):
        registry.add_board(tmp_path / "empty")


def test_remove_unknown_raises(tmp_path: Path) -> None:
    with pytest.raises(KanbaiError):
        registry.remove_board("nope")
