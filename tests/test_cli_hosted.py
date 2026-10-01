"""CLI-level tests for `kanbai hosted import`/`kanbai hosted export`."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx2 as httpx
import pytest
from kanbai import scaffold
from kanbai.board import Board
from kanbai.cli import app
from typer.testing import CliRunner

from test_remote_board import ADMIN_EMAIL, ADMIN_PASSWORD, _FakeServer, patch_transport

runner = CliRunner()


@pytest.fixture
def fake_server(monkeypatch: pytest.MonkeyPatch) -> _FakeServer:
    server = _FakeServer()
    patch_transport(monkeypatch, httpx.MockTransport(server.handle))
    return server


@pytest.fixture
def local_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    scaffold.init_board(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_hosted_import_uploads_and_configures_server_section(
    local_project: Path, fake_server: _FakeServer
) -> None:
    runner.invoke(app, ["add", "Local card"])

    result = runner.invoke(
        app,
        [
            "hosted",
            "import",
            "--url",
            "https://kanbai.example.com",
            "--email",
            ADMIN_EMAIL,
            "--password",
            ADMIN_PASSWORD,
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[server]" in (local_project / ".kanbai" / "config.toml").read_text()


def test_hosted_import_fails_with_bad_credentials(
    local_project: Path, fake_server: _FakeServer
) -> None:
    result = runner.invoke(
        app,
        [
            "hosted",
            "import",
            "--url",
            "https://kanbai.example.com",
            "--email",
            ADMIN_EMAIL,
            "--password",
            "wrong",
        ],
    )

    assert result.exit_code == 1
    assert "error" in result.output.lower()


def test_hosted_import_fails_without_a_local_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_server: _FakeServer
) -> None:
    monkeypatch.chdir(tmp_path)  # no .kanbai/ here

    result = runner.invoke(
        app,
        [
            "hosted",
            "import",
            "--url",
            "https://kanbai.example.com",
            "--email",
            ADMIN_EMAIL,
            "--password",
            ADMIN_PASSWORD,
        ],
    )

    assert result.exit_code == 1


def test_hosted_export_requires_server_section(local_project: Path) -> None:
    result = runner.invoke(app, ["hosted", "export"])

    assert result.exit_code == 1
    assert "error" in result.output.lower()


def test_hosted_export_writes_cards_locally(local_project: Path, fake_server: _FakeServer) -> None:
    runner.invoke(app, ["add", "Local card"])
    import_result = runner.invoke(
        app,
        [
            "hosted",
            "import",
            "--url",
            "https://kanbai.example.com",
            "--email",
            ADMIN_EMAIL,
            "--password",
            ADMIN_PASSWORD,
        ],
    )
    assert import_result.exit_code == 0, import_result.output

    # Add a card directly on the hosted side to prove export reflects the current remote state.
    cfg_text = (local_project / ".kanbai" / "config.toml").read_text()
    board_id = re.search(r'board_id = "([^"]+)"', cfg_text).group(1)  # type: ignore[union-attr]
    fake_server.cards[board_id]["999"] = fake_server._card_dict(  # noqa: SLF001
        board_id, id="999", title="Added remotely"
    )

    result = runner.invoke(app, ["hosted", "export"])

    assert result.exit_code == 0, result.output
    exported = Board.load(local_project)
    titles = {c.title for c in exported.list_column("backlog")}
    assert "Added remotely" in titles


def _import(local_project: Path) -> None:
    result = runner.invoke(
        app,
        [
            "hosted",
            "import",
            "--url",
            "https://kanbai.example.com",
            "--email",
            ADMIN_EMAIL,
            "--password",
            ADMIN_PASSWORD,
        ],
    )
    assert result.exit_code == 0, result.output


def test_hosted_diff_requires_server_section(local_project: Path) -> None:
    result = runner.invoke(app, ["hosted", "diff"])

    assert result.exit_code == 1
    assert "error" in result.output.lower()


def test_hosted_diff_exits_zero_when_in_sync(local_project: Path, fake_server: _FakeServer) -> None:
    runner.invoke(app, ["add", "Local card"])
    _import(local_project)

    result = runner.invoke(app, ["hosted", "diff"])

    assert result.exit_code == 0, result.output
    assert "in sync" in result.output.lower()


def test_hosted_diff_exits_one_and_reports_only_remote_card(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _import(local_project)
    cfg_text = (local_project / ".kanbai" / "config.toml").read_text()
    board_id = re.search(r'board_id = "([^"]+)"', cfg_text).group(1)  # type: ignore[union-attr]
    fake_server.cards[board_id]["999"] = fake_server._card_dict(  # noqa: SLF001
        board_id, id="999", title="Added remotely"
    )

    result = runner.invoke(app, ["hosted", "diff"])

    assert result.exit_code == 1
    assert "999" in result.output


def test_hosted_diff_json_output(local_project: Path, fake_server: _FakeServer) -> None:
    _import(local_project)
    cfg_text = (local_project / ".kanbai" / "config.toml").read_text()
    board_id = re.search(r'board_id = "([^"]+)"', cfg_text).group(1)  # type: ignore[union-attr]
    fake_server.cards[board_id]["999"] = fake_server._card_dict(  # noqa: SLF001
        board_id, id="999", title="Added remotely"
    )

    result = runner.invoke(app, ["hosted", "diff", "--json"])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["in_sync"] is False
    assert data["only_remote"] == ["999"]
    assert data["only_local"] == []
    assert data["changed"] == []
