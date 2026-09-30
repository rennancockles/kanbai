"""CLI-level tests for remote mode: [server] in config.toml routes commands over HTTP."""

from __future__ import annotations

import json
from pathlib import Path

import httpx2 as httpx
import pytest
from kanbai import scaffold
from kanbai.cli import app
from typer.testing import CliRunner

from test_remote_board import BOARD_ID, _FakeServer, patch_transport

runner = CliRunner()


@pytest.fixture
def remote_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, _FakeServer]:
    """A project directory whose config.toml has a complete [server] section."""
    scaffold.init_board(tmp_path)
    cfg = tmp_path / ".kanbai" / "config.toml"
    server_section = (
        f'\n[server]\nurl = "https://kanbai.example.com"\ntoken = "tok"\nboard_id = "{BOARD_ID}"\n'
    )
    cfg.write_text(cfg.read_text() + server_section)
    monkeypatch.chdir(tmp_path)

    fake_server = _FakeServer()
    patch_transport(monkeypatch, httpx.MockTransport(fake_server.handle))
    return tmp_path, fake_server


def test_add_goes_through_the_hosted_api(remote_project: tuple[Path, _FakeServer]) -> None:
    result = runner.invoke(app, ["add", "Remote task", "--json"])

    assert result.exit_code == 0, result.output
    card = json.loads(result.output)
    assert card["title"] == "Remote task"
    assert card["status"] == "backlog"


def test_list_reflects_cards_added_remotely(remote_project: tuple[Path, _FakeServer]) -> None:
    runner.invoke(app, ["add", "Remote task", "--json"])

    result = runner.invoke(app, ["list", "--json"])

    assert result.exit_code == 0, result.output
    board = json.loads(result.output)
    assert [c["title"] for c in board["backlog"]] == ["Remote task"]


def test_move_updates_the_hosted_card(remote_project: tuple[Path, _FakeServer]) -> None:
    add_result = runner.invoke(app, ["add", "Remote task", "--json"])
    card_id = json.loads(add_result.output)["id"]

    result = runner.invoke(app, ["move", card_id, "todo", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "todo"


def test_ui_command_rejects_remote_boards(remote_project: tuple[Path, _FakeServer]) -> None:
    result = runner.invoke(app, ["ui"])

    assert result.exit_code == 1
    assert "does not support hosted" in result.output


def test_local_project_is_unaffected_without_server_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scaffold.init_board(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["add", "Local task", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["title"] == "Local task"
    assert (tmp_path / ".kanbai" / "backlog").exists()
