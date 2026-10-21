"""Hosted mode keeps the local files as the source and mirrors every change to the host."""

from __future__ import annotations

import json
from pathlib import Path

import httpx2 as httpx
import pytest
from kanbai import scaffold, sync_state
from kanbai.board import Board
from kanbai.cli import app
from typer.testing import CliRunner

from test_remote_board import BOARD_ID, _FakeServer, patch_transport

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, _FakeServer]:
    """A project with a complete [server] section, talking to an in-memory fake host."""
    scaffold.init_board(tmp_path)
    cfg = tmp_path / ".kanbai" / "config.toml"
    server_section = (
        f'\n[server]\nurl = "https://kanbai.example.com"\ntoken = "tok"\nboard_id = "{BOARD_ID}"\n'
    )
    cfg.write_text(cfg.read_text() + server_section)
    monkeypatch.chdir(tmp_path)
    server = _FakeServer()
    server.down = False  # type: ignore[attr-defined]

    def handler(request: httpx.Request) -> httpx.Response:
        if server.down:  # type: ignore[attr-defined]
            raise httpx.ConnectError("connection refused", request=request)
        return server.handle(request)

    patch_transport(monkeypatch, httpx.MockTransport(handler))
    return tmp_path, server


def _kanbai_dir(project_dir: Path) -> Path:
    return project_dir / ".kanbai"


def _host(server: _FakeServer) -> dict[str, dict[str, object]]:
    return server.cards[BOARD_ID]


def _add(title: str = "Task", column: str = "todo") -> str:
    result = runner.invoke(app, ["add", title, "-c", column, "--json"])
    assert result.exit_code == 0, result.output
    return str(json.loads(result.output)["id"])


def _host_down(server: _FakeServer, *, down: bool = True) -> None:
    server.down = down  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- replication


def test_add_writes_the_local_file_and_creates_the_card_on_the_host_with_the_same_id(
    project: tuple[Path, _FakeServer],
) -> None:
    project_dir, server = project

    card_id = _add("Mirrored task")

    assert [c.title for c in Board.load(project_dir).list_column("todo")] == ["Mirrored task"]
    assert _host(server)[card_id]["title"] == "Mirrored task"
    assert _host(server)[card_id]["status"] == "todo"


def test_moves_are_applied_on_both_sides(project: tuple[Path, _FakeServer]) -> None:
    project_dir, server = project
    card_id = _add()

    assert runner.invoke(app, ["start", card_id]).exit_code == 0
    assert runner.invoke(app, ["review", card_id]).exit_code == 0

    assert [c.id for c in Board.load(project_dir).list_column("review")] == [card_id]
    assert _host(server)[card_id]["status"] == "review"


def test_edit_archive_restore_and_remove_are_replicated(
    project: tuple[Path, _FakeServer],
) -> None:
    project_dir, server = project
    card_id = _add("Old title")

    assert (
        runner.invoke(app, ["edit", card_id, "--title", "New title", "-p", "high"]).exit_code == 0
    )
    assert _host(server)[card_id]["title"] == "New title"
    assert _host(server)[card_id]["priority"] == "high"

    assert runner.invoke(app, ["archive", card_id]).exit_code == 0
    assert _host(server)[card_id]["status"] == "archive"

    assert runner.invoke(app, ["restore", card_id]).exit_code == 0
    assert _host(server)[card_id]["status"] == "todo"
    assert [c.id for c in Board.load(project_dir).list_column("todo")] == [card_id]

    assert runner.invoke(app, ["rm", card_id, "--yes"]).exit_code == 0
    assert card_id not in _host(server)
    assert sync_state.load_out_of_sync(_kanbai_dir(project_dir)) is None


def test_dependencies_are_replicated(project: tuple[Path, _FakeServer]) -> None:
    _project_dir, server = project
    blocker = _add("Blocker")
    result = runner.invoke(app, ["add", "Blocked", "-c", "todo", "--dep", blocker, "--json"])
    assert result.exit_code == 0, result.output
    blocked = json.loads(result.output)["id"]

    assert _host(server)[blocked]["deps"] == [blocker]


def test_a_move_notifies_once_not_once_per_side(
    project: tuple[Path, _FakeServer], monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir, _server = project
    cfg = _kanbai_dir(project_dir) / "config.toml"
    cfg.write_text(cfg.read_text() + '\n[notifications]\nntfy_topic = "my-topic"\n')
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "kanbai.cli.notify_ntfy", lambda topic, title, body: calls.append((topic, title, body))
    )
    card_id = _add()

    assert runner.invoke(app, ["review", card_id]).exit_code == 0

    assert len([title for _, title, _ in calls if "in review" in title]) == 1


# --------------------------------------------------------------------------- reads are local


def test_reads_work_with_the_host_down_and_never_touch_the_network(
    project: tuple[Path, _FakeServer],
) -> None:
    _project_dir, server = project
    card_id = _add("Offline readable")
    _host_down(server)

    listing = runner.invoke(app, ["list", "--json"])
    shown = runner.invoke(app, ["show", card_id, "--json"])
    upcoming = runner.invoke(app, ["next", "--json"])

    assert listing.exit_code == shown.exit_code == upcoming.exit_code == 0
    assert json.loads(shown.output)["title"] == "Offline readable"
    assert json.loads(upcoming.output)["id"] == card_id
    assert sync_state.load_out_of_sync(_kanbai_dir(_project_dir)) is None


# --------------------------------------------------------------------------- out of sync


def test_a_failed_replication_keeps_the_local_change_and_warns_to_push(
    project: tuple[Path, _FakeServer],
) -> None:
    project_dir, server = project
    _host_down(server)

    result = runner.invoke(app, ["add", "While offline", "-c", "todo", "--json"])

    assert result.exit_code == 0, result.output
    assert [c.title for c in Board.load(project_dir).list_column("todo")] == ["While offline"]
    assert "out of sync" in result.output
    assert "kanbai hosted push" in result.output
    assert "kanbai hosted pull" in result.output
    assert sync_state.load_out_of_sync(_kanbai_dir(project_dir))


def test_later_commands_keep_warning_until_a_push_or_pull_syncs(
    project: tuple[Path, _FakeServer],
) -> None:
    project_dir, server = project
    _host_down(server)
    runner.invoke(app, ["add", "While offline", "-c", "todo"])
    _host_down(server, down=False)

    assert "out of sync" in runner.invoke(app, ["list"]).output

    pushed = runner.invoke(app, ["hosted", "push", "-y"])

    assert pushed.exit_code == 0, pushed.output
    assert sync_state.load_out_of_sync(_kanbai_dir(project_dir)) is None
    assert "out of sync" not in runner.invoke(app, ["list"]).output
    assert [c["title"] for c in _host(server).values()] == ["While offline"]


def test_pull_also_clears_the_warning(project: tuple[Path, _FakeServer]) -> None:
    project_dir, _server = project
    sync_state.mark_out_of_sync(_kanbai_dir(project_dir), ["something drifted"])

    assert runner.invoke(app, ["hosted", "pull", "-y"]).exit_code == 0

    assert sync_state.load_out_of_sync(_kanbai_dir(project_dir)) is None


def test_a_card_changed_on_the_host_is_flagged_but_only_our_fields_are_sent(
    project: tuple[Path, _FakeServer],
) -> None:
    project_dir, server = project
    card_id = _add("Shared card")
    _host(server)[card_id]["priority"] = "low"  # someone edited it in the browser

    result = runner.invoke(app, ["edit", card_id, "--title", "Renamed here"])

    assert result.exit_code == 0, result.output
    assert "out of sync" in result.output
    assert f"card #{card_id} was changed on the host (priority)" in result.output
    assert _host(server)[card_id]["title"] == "Renamed here"  # our change went through...
    assert _host(server)[card_id]["priority"] == "low"  # ...their edit was not overwritten
    assert sync_state.load_out_of_sync(_kanbai_dir(project_dir))


def test_a_card_missing_on_the_host_is_recreated_and_flagged(
    project: tuple[Path, _FakeServer],
) -> None:
    project_dir, server = project
    card_id = _add("Vanishing card")
    del _host(server)[card_id]

    result = runner.invoke(app, ["start", card_id])

    assert result.exit_code == 0, result.output
    assert f"card #{card_id} was missing on the host" in result.output
    assert _host(server)[card_id]["status"] == "doing"
    assert sync_state.load_out_of_sync(_kanbai_dir(project_dir))


def test_a_new_local_id_already_used_on_the_host_never_overwrites_the_host_card(
    project: tuple[Path, _FakeServer],
) -> None:
    project_dir, server = project
    _host(server)["001"] = server._card_dict(  # noqa: SLF001
        BOARD_ID, id="001", title="Created in the browser"
    )

    result = runner.invoke(app, ["add", "Created locally", "-c", "todo", "--json"])

    assert result.exit_code == 0, result.output
    assert "already exists on the host" in result.output
    assert _host(server)["001"]["title"] == "Created in the browser"
    assert [c.title for c in Board.load(project_dir).list_column("todo")] == ["Created locally"]


def test_status_reports_the_pending_drift(project: tuple[Path, _FakeServer]) -> None:
    project_dir, _server = project
    sync_state.mark_out_of_sync(_kanbai_dir(project_dir), ["card #001 was changed on the host"])

    status = runner.invoke(app, ["hosted", "status"])

    assert status.exit_code == 0, status.output
    assert "Out of sync" in status.output
    assert "card #001 was changed on the host" in status.output


def test_disable_keeps_changes_local_only(project: tuple[Path, _FakeServer]) -> None:
    project_dir, server = project
    assert runner.invoke(app, ["hosted", "disable"]).exit_code == 0

    runner.invoke(app, ["add", "Local only", "-c", "todo"])

    assert [c.title for c in Board.load(project_dir).list_column("todo")] == ["Local only"]
    assert _host(server) == {}
