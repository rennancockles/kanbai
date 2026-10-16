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


def test_disabled_hosted_works_on_local_files_without_touching_the_server(
    remote_project: tuple[Path, _FakeServer], monkeypatch: pytest.MonkeyPatch
) -> None:
    runner.invoke(app, ["hosted", "disable"])

    def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request to {request.url}")

    patch_transport(monkeypatch, httpx.MockTransport(no_network))

    added = runner.invoke(app, ["add", "Offline task", "-c", "todo", "--json"])
    assert added.exit_code == 0, added.output
    card_id = json.loads(added.output)["id"]
    assert runner.invoke(app, ["move", card_id, "doing"]).exit_code == 0
    board = json.loads(runner.invoke(app, ["list", "--json"]).output)
    assert [c["title"] for c in board["doing"]] == ["Offline task"]


def test_enable_restores_hosted_mode(remote_project: tuple[Path, _FakeServer]) -> None:
    runner.invoke(app, ["hosted", "disable"])
    runner.invoke(app, ["hosted", "enable"])

    result = runner.invoke(app, ["add", "Remote again", "--json"])

    assert result.exit_code == 0, result.output
    assert any(
        c["title"] == "Remote again"
        for cards in remote_project[1].cards.values()
        for c in cards.values()
    )


# --------------------------------------------------------------------------- notifications


def _configure_notifications(project: Path, body: str) -> None:
    cfg = project / ".kanbai" / "config.toml"
    cfg.write_text(cfg.read_text() + f"\n[notifications]\n{body}\n")


@pytest.fixture
def ntfy_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "kanbai.cli.notify_ntfy", lambda topic, title, body: calls.append((topic, title, body))
    )
    return calls


@pytest.fixture
def native_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr("kanbai.web.notify.notify_native", lambda t, b: calls.append((t, b)))
    return calls


def _remote_card_in_todo() -> str:
    return str(json.loads(runner.invoke(app, ["add", "Task", "-c", "todo", "--json"]).output)["id"])


def test_review_pushes_ntfy_in_hosted_mode_using_the_local_config(
    remote_project: tuple[Path, _FakeServer], ntfy_calls: list[tuple[str, str, str]]
) -> None:
    project, _server = remote_project
    _configure_notifications(project, 'ntfy_topic = "my-topic"')
    card_id = _remote_card_in_todo()

    result = runner.invoke(app, ["review", card_id])

    assert result.exit_code == 0, result.output
    assert ntfy_calls
    assert all(topic == "my-topic" for topic, _, _ in ntfy_calls)
    assert any("in review" in title for _, title, _ in ntfy_calls)


def test_review_in_hosted_mode_skips_ntfy_without_a_topic(
    remote_project: tuple[Path, _FakeServer], ntfy_calls: list[tuple[str, str, str]]
) -> None:
    card_id = _remote_card_in_todo()

    assert runner.invoke(app, ["review", card_id]).exit_code == 0

    assert ntfy_calls == []


def test_hosted_mode_does_not_notify_for_moves_that_are_not_review_or_done(
    remote_project: tuple[Path, _FakeServer], ntfy_calls: list[tuple[str, str, str]]
) -> None:
    project, _server = remote_project
    _configure_notifications(project, 'ntfy_topic = "my-topic"')
    card_id = _remote_card_in_todo()

    assert runner.invoke(app, ["start", card_id]).exit_code == 0

    assert ntfy_calls == []


def test_hosted_native_notification_follows_the_local_native_setting(
    remote_project: tuple[Path, _FakeServer], native_calls: list[tuple[str, str]]
) -> None:
    project, _server = remote_project
    first = _remote_card_in_todo()
    assert runner.invoke(app, ["review", first]).exit_code == 0
    assert native_calls  # on by default

    native_calls.clear()
    _configure_notifications(project, "native = false")
    second = _remote_card_in_todo()
    assert runner.invoke(app, ["review", second]).exit_code == 0

    assert native_calls == []


def test_notify_hook_in_a_hosted_project_uses_the_local_notification_config(
    remote_project: tuple[Path, _FakeServer], ntfy_calls: list[tuple[str, str, str]]
) -> None:
    project, _server = remote_project
    _configure_notifications(project, 'ntfy_topic = "my-topic"')
    payload = json.dumps({"notification_type": "agent_needs_input", "cwd": str(project)})

    result = runner.invoke(app, ["notify-hook"], input=payload)

    assert result.exit_code == 0
    assert [topic for topic, _, _ in ntfy_calls] == ["my-topic"]
