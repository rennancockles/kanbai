"""End-to-end tests for the CLI via Typer's test runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from kanbai import scaffold
from kanbai.cli import app
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp dir that is the current working directory, with a board initialized."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--name", "Demo"])
    assert result.exit_code == 0, result.output
    return tmp_path


def test_add_lands_in_backlog_json(project: Path) -> None:
    add = runner.invoke(app, ["add", "First task", "--priority", "high", "--json"])
    assert add.exit_code == 0, add.output
    card = json.loads(add.output)
    assert card["id"] == "001"
    assert card["priority"] == "high"
    assert card["status"] == "backlog"

    listed = runner.invoke(app, ["list", "--json"])
    assert listed.exit_code == 0, listed.output
    board = json.loads(listed.output)
    assert [c["id"] for c in board["backlog"]] == ["001"]
    assert board["todo"] == []
    assert board["doing"] == []


def test_next_and_lifecycle(project: Path) -> None:
    # Plan the work straight into the sprint so `next` can pick it up.
    runner.invoke(app, ["add", "Task A", "-c", "todo"])
    runner.invoke(app, ["add", "Task B", "-c", "todo"])

    nxt = runner.invoke(app, ["next", "--json"])
    assert nxt.exit_code == 0
    assert json.loads(nxt.output)["id"] == "001"

    assert runner.invoke(app, ["start", "001"]).exit_code == 0
    assert json.loads(runner.invoke(app, ["list", "doing", "--json"]).output)[0]["id"] == "001"

    assert runner.invoke(app, ["done", "001"]).exit_code == 0
    assert json.loads(runner.invoke(app, ["list", "done", "--json"]).output)[0]["id"] == "001"


def test_review_then_done_flow(project: Path) -> None:
    runner.invoke(app, ["add", "Task", "-c", "todo"])
    runner.invoke(app, ["start", "001"])

    # `review` finishes the card into the review column (agent's step)...
    assert runner.invoke(app, ["review", "001"]).exit_code == 0
    assert json.loads(runner.invoke(app, ["list", "review", "--json"]).output)[0]["id"] == "001"
    assert runner.invoke(app, ["list", "done", "--json"]).output.strip() == "[]"

    # ...and `done` approves it (user's step).
    assert runner.invoke(app, ["done", "001"]).exit_code == 0
    assert json.loads(runner.invoke(app, ["list", "done", "--json"]).output)[0]["id"] == "001"


def test_new_sprint_archives_done_and_keeps_active(project: Path) -> None:
    runner.invoke(app, ["add", "A", "-c", "todo"])
    runner.invoke(app, ["add", "B", "-c", "done"])
    result = runner.invoke(app, ["new-sprint", "--yes"])
    assert result.exit_code == 0
    assert runner.invoke(app, ["list", "done", "--json"]).output.strip() == "[]"
    todo = json.loads(runner.invoke(app, ["list", "todo", "--json"]).output)
    assert [c["title"] for c in todo] == ["A"]  # active columns left in place


def test_new_sprint_to_backlog(project: Path) -> None:
    runner.invoke(app, ["add", "A", "-c", "todo"])
    runner.invoke(app, ["add", "B", "-c", "done"])
    result = runner.invoke(app, ["new-sprint", "--to-backlog", "--yes"])
    assert result.exit_code == 0
    assert runner.invoke(app, ["list", "todo", "--json"]).output.strip() == "[]"
    backlog = json.loads(runner.invoke(app, ["list", "backlog", "--json"]).output)
    assert any(c["title"] == "A" for c in backlog)


def test_next_ignores_backlog(project: Path) -> None:
    runner.invoke(app, ["add", "Backlog only"])  # defaults to backlog
    result = runner.invoke(app, ["next", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) is None


def test_wip_limit_warns_when_exceeded(project: Path) -> None:
    cfg = project / ".kanbai" / "config.toml"
    cfg.write_text(cfg.read_text() + "\n[wip]\ntodo = 1\n")
    runner.invoke(app, ["add", "A", "-c", "todo"])  # todo now 1 (at limit, no warning)
    result = runner.invoke(app, ["add", "B", "-c", "todo"])  # todo now 2 > 1
    assert result.exit_code == 0
    assert "WIP limit" in result.output


def test_next_empty_returns_null(project: Path) -> None:
    result = runner.invoke(app, ["next", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) is None


def test_list_archive_and_restore(project: Path) -> None:
    runner.invoke(app, ["add", "Task", "-c", "done"])  # 001 in done
    runner.invoke(app, ["archive", "001"])
    archived = json.loads(runner.invoke(app, ["list", "archive", "--json"]).output)
    assert [c["id"] for c in archived] == ["001"]

    assert runner.invoke(app, ["restore", "001"]).exit_code == 0
    done = json.loads(runner.invoke(app, ["list", "done", "--json"]).output)
    assert [c["id"] for c in done] == ["001"]  # restored to origin column
    assert runner.invoke(app, ["list", "archive", "--json"]).output.strip() == "[]"


def test_missing_card_exits_nonzero(project: Path) -> None:
    result = runner.invoke(app, ["show", "404"])
    assert result.exit_code == 1


def test_no_board_exits_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 1


def test_hub_add_list_remove(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KANBAI_HOME", str(tmp_path / "home"))
    board = tmp_path / "proj"
    scaffold.init_board(board)

    assert runner.invoke(app, ["hub", "add", str(board)]).exit_code == 0
    listed = json.loads(runner.invoke(app, ["hub", "list", "--json"]).output)
    assert listed == {"proj": str(board.resolve())}

    assert runner.invoke(app, ["hub", "remove", "proj"]).exit_code == 0
    assert json.loads(runner.invoke(app, ["hub", "list", "--json"]).output) == {}


def test_hub_add_rejects_path_without_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KANBAI_HOME", str(tmp_path / "home"))
    (tmp_path / "empty").mkdir()
    result = runner.invoke(app, ["hub", "add", str(tmp_path / "empty")])
    assert result.exit_code == 1


def test_hub_serve_without_boards_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KANBAI_HOME", str(tmp_path / "home"))
    result = runner.invoke(app, ["hub"])
    assert result.exit_code == 1


def test_hub_serve_invokes_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KANBAI_HOME", str(tmp_path / "home"))
    board = tmp_path / "proj"
    scaffold.init_board(board)
    runner.invoke(app, ["hub", "add", str(board)])

    calls: dict[str, object] = {}

    def fake_serve_hub(
        boards: dict[str, str], *, host: str, port: int, open_browser: bool
    ) -> None:
        calls.update(host=host, port=port, count=len(boards), open_browser=open_browser)

    monkeypatch.setattr("kanbai.web.server.serve_hub", fake_serve_hub)
    result = runner.invoke(app, ["hub", "--port", "9000", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert calls == {"host": "127.0.0.1", "port": 9000, "count": 1, "open_browser": False}
