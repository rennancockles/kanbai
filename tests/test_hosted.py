"""Tests for kanbai.hosted: import (local -> hosted) and export (hosted -> local)."""

from __future__ import annotations

from pathlib import Path

import httpx2 as httpx
import pytest
from kanbai import hosted, scaffold
from kanbai.board import Board
from kanbai.config import load_remote_config
from kanbai.errors import RemoteAPIError
from kanbai.remote_board import RemoteBoard

from test_remote_board import ADMIN_EMAIL, ADMIN_PASSWORD, _FakeServer, patch_transport


@pytest.fixture
def fake_server() -> _FakeServer:
    return _FakeServer()


@pytest.fixture(autouse=True)
def _patched_transport(fake_server: _FakeServer, monkeypatch: pytest.MonkeyPatch) -> None:
    patch_transport(monkeypatch, httpx.MockTransport(fake_server.handle))


@pytest.fixture
def local_project(tmp_path: Path) -> Path:
    scaffold.init_board(tmp_path, name="Local project")
    return tmp_path


def test_import_uploads_every_card_and_writes_server_section(local_project: Path) -> None:
    board = Board.load(local_project)
    board.add("First card", priority="high")
    board.add("Second card")

    remote_config = hosted.import_board(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )

    remote = RemoteBoard(remote_config)
    assert [c.title for c in remote.list_column("backlog")] == ["First card", "Second card"]
    cfg_text = (local_project / ".kanbai" / "config.toml").read_text()
    assert "[server]" in cfg_text
    assert remote_config.board_id in cfg_text
    assert remote_config.token in cfg_text


def test_reimporting_overwrites_the_server_section_instead_of_duplicating_it(
    local_project: Path,
) -> None:
    hosted.import_board(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )

    second_remote_config = hosted.import_board(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )

    cfg_text = (local_project / ".kanbai" / "config.toml").read_text()
    assert cfg_text.count("[server]") == 1
    assert second_remote_config.board_id in cfg_text
    assert load_remote_config(local_project / ".kanbai") == second_remote_config


def test_import_preserves_dependency_ids(local_project: Path) -> None:
    board = Board.load(local_project)
    blocker = board.add("Blocker")
    board.add("Blocked", deps=[blocker.id])

    remote_config = hosted.import_board(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )

    remote = RemoteBoard(remote_config)
    blocked_card = next(c for c in remote.list_column("backlog") if c.title == "Blocked")
    blocker_card = next(c for c in remote.list_column("backlog") if c.title == "Blocker")
    assert blocked_card.deps == [blocker_card.id]


def test_import_preserves_archived_cards_and_their_column(local_project: Path) -> None:
    board = Board.load(local_project)
    card = board.add("To archive", column="todo")
    board.archive(card.id)

    remote_config = hosted.import_board(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )

    remote = RemoteBoard(remote_config)
    archived = remote.list_archive()
    assert [c.title for c in archived] == ["To archive"]
    assert archived[0].archived_from == "todo"


def test_import_uploads_the_local_board_config(local_project: Path) -> None:
    remote_config = hosted.import_board(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )

    remote = RemoteBoard(remote_config)
    assert remote.config.name == "Local project"


def test_import_raises_on_bad_credentials(local_project: Path) -> None:
    with pytest.raises(RemoteAPIError):
        hosted.import_board(
            local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, "wrong"
        )


def test_export_writes_every_card_locally(local_project: Path) -> None:
    remote_config = hosted.import_board(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )
    remote = RemoteBoard(remote_config)
    remote.add("Uploaded directly", column="todo")

    export_dir = local_project / "exported"
    count = hosted.export_board(remote, export_dir / ".kanbai")

    assert count == 1
    exported = Board.load(export_dir)
    assert [c.title for c in exported.list_column("todo")] == ["Uploaded directly"]


def test_export_includes_archived_cards(local_project: Path) -> None:
    remote_config = hosted.import_board(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )
    remote = RemoteBoard(remote_config)
    card = remote.add("Will be archived")
    remote.archive(card.id)

    export_dir = local_project / "exported"
    hosted.export_board(remote, export_dir / ".kanbai")

    exported = Board.load(export_dir)
    assert [c.title for c in exported.list_archive()] == ["Will be archived"]


def test_round_trip_import_then_export_preserves_cards_and_deps(local_project: Path) -> None:
    board = Board.load(local_project)
    blocker = board.add("Blocker", priority="high", labels=["urgent"])
    board.add("Blocked", deps=[blocker.id], column="todo")

    remote_config = hosted.import_board(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )
    remote = RemoteBoard(remote_config)

    export_dir = local_project / "exported"
    hosted.export_board(remote, export_dir / ".kanbai")
    exported = Board.load(export_dir)

    exported_blocker = next(
        c for col in exported.columns for c in exported.list_column(col) if c.title == "Blocker"
    )
    exported_blocked = next(
        c for col in exported.columns for c in exported.list_column(col) if c.title == "Blocked"
    )
    assert exported_blocker.priority.value == "high"
    assert exported_blocker.labels == ["urgent"]
    assert exported_blocked.deps == [exported_blocker.id]
