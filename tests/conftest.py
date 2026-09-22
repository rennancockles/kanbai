"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from kanbai import scaffold
from kanbai.board import Board


@pytest.fixture
def board(tmp_path: Path) -> Board:
    """An initialized, empty board rooted at a temp directory."""
    scaffold.init_board(tmp_path)
    return Board.load(tmp_path)
