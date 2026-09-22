"""Tests for the web UI (board rendering)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from kanbai import scaffold
from kanbai.board import Board
from kanbai.cli import app as cli_app
from kanbai.errors import CardNotFoundError
from kanbai.web import server
from kanbai.web.app import create_app
from kanbai.web.watcher import watch_board
from typer.testing import CliRunner

cli_runner = CliRunner()


def _client(tmp_path: Path) -> TestClient:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Sprint task", column="todo", priority="high", labels=["ui"])
    board.add("Future idea")  # lands in backlog
    return TestClient(create_app(board))


def test_index_renders_all_columns(tmp_path: Path) -> None:
    resp = _client(tmp_path).get("/")
    assert resp.status_code == 200
    for column in ("backlog", "todo", "doing", "done"):
        assert column in resp.text


def test_index_shows_brand_name(tmp_path: Path) -> None:
    resp = _client(tmp_path).get("/")
    assert "KanbAI" in resp.text  # app name is branded with AI uppercased


def test_index_shows_cards_with_details(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/").text
    assert "Sprint task" in body
    assert "Future idea" in body
    assert "#001" in body  # card id
    assert "ui" in body  # label
    assert "pri-high" in body  # priority styling hook


def test_static_assets_are_served(tmp_path: Path) -> None:
    client = _client(tmp_path)
    htmx = client.get("/static/htmx.min.js")
    assert htmx.status_code == 200
    assert "htmx" in htmx.text.lower()
    sortable = client.get("/static/Sortable.min.js")
    assert sortable.status_code == 200


def test_create_card_via_post(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    client = TestClient(create_app(board))

    resp = client.post(
        "/cards", data={"title": "Nova tarefa", "column": "todo", "priority": "high"}
    )
    assert resp.status_code == 200
    assert "Nova tarefa" in resp.text  # returned partial shows the new card
    # ...and it was actually persisted to the board.
    todo = board.list_column("todo")
    assert [c.title for c in todo] == ["Nova tarefa"]
    assert todo[0].priority.value == "high"


def test_move_card_via_post(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    card = board.add("Task", column="todo")
    client = TestClient(create_app(board))

    resp = client.post(f"/cards/{card.id}/move", data={"column": "doing"})
    assert resp.status_code == 200
    assert board.list_column("doing")[0].id == card.id
    assert board.list_column("todo") == []


def test_create_card_invalid_column_is_ignored(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    client = TestClient(create_app(board))

    resp = client.post("/cards", data={"title": "Nope", "column": "bogus", "priority": "low"})
    assert resp.status_code == 200  # suppressed, board re-rendered unchanged
    assert all(not cards for cards in board.board().values())


def test_move_with_position_persists_reorder(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    a = board.add("A", column="todo")
    b = board.add("B", column="todo")
    c = board.add("C", column="todo")
    client = TestClient(create_app(board))

    resp = client.post(f"/cards/{c.id}/move", data={"column": "todo", "position": 0})
    assert resp.status_code == 200
    assert [x.id for x in board.list_column("todo")] == [c.id, a.id, b.id]


def test_move_card_partial_reflects_new_column(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    card = board.add("Slice", column="todo")
    client = TestClient(create_app(board))

    resp = client.post(f"/cards/{card.id}/move", data={"column": "done"})
    # The returned partial places the card's markup after the "done" column header.
    done_index = resp.text.index('data-column="done"')
    assert resp.text.index(f'data-id="{card.id}"') > done_index


def test_move_unknown_card_is_ignored(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    client = TestClient(create_app(board))

    resp = client.post("/cards/999/move", data={"column": "doing"})
    assert resp.status_code == 200  # no crash, board re-rendered unchanged


def test_board_has_plan_sprint_button(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/").text
    assert 'hx-get="/sprint/plan"' in body


def test_sprint_plan_lists_backlog_cards(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Future A")  # backlog
    board.add("Future B")  # backlog
    resp = TestClient(create_app(board)).get("/sprint/plan")
    assert resp.status_code == 200
    assert "Future A" in resp.text
    assert "Future B" in resp.text
    assert 'name="ids"' in resp.text  # checkboxes
    assert 'class="modal card' in resp.text  # opaque background (not transparent)


def test_sprint_plan_moves_selected_cards_to_sprint(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("A")  # 001 backlog
    board.add("B")  # 002 backlog
    board.add("C")  # 003 backlog
    client = TestClient(create_app(board))

    resp = client.post("/sprint/plan", data={"ids": ["001", "003"]})
    assert resp.status_code == 200
    assert [c.id for c in board.list_column("todo")] == ["001", "003"]
    assert [c.id for c in board.list_column("backlog")] == ["002"]


def test_card_detail_shows_full_card(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add(
        "Login screen",
        column="todo",
        description="## Criteria\n- do the thing",
        priority="high",
        labels=["ui"],
    )
    resp = TestClient(create_app(board)).get("/cards/001")
    assert resp.status_code == 200
    assert "Login screen" in resp.text
    assert "do the thing" in resp.text  # the body/description is now visible
    assert "ui" in resp.text  # label


def test_card_detail_unknown_returns_404(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    resp = TestClient(create_app(board)).get("/cards/999")
    assert resp.status_code == 404


def test_board_cards_link_to_detail(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/").text
    assert 'hx-get="/cards/001"' in body  # clicking a card opens its detail
    assert 'id="detail"' in body  # modal target present


def test_detail_has_edit_button(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Task", column="todo")
    resp = TestClient(create_app(board)).get("/cards/001")
    assert 'hx-get="/cards/001/edit"' in resp.text


def test_edit_form_prefills_current_values(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Old title", column="todo", description="old body", priority="low", labels=["a"])
    resp = TestClient(create_app(board)).get("/cards/001/edit")
    assert resp.status_code == 200
    assert 'name="title"' in resp.text
    assert "Old title" in resp.text
    assert "old body" in resp.text


def test_edit_card_persists_changes(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Old", column="todo", priority="low")
    client = TestClient(create_app(board))

    resp = client.post(
        "/cards/001/edit",
        data={"title": "New", "description": "desc", "priority": "high", "labels": "x, y"},
    )
    assert resp.status_code == 200
    card = board.show("001")
    assert card.title == "New"
    assert card.body == "desc"
    assert card.priority.value == "high"
    assert card.labels == ["x", "y"]


def test_edit_form_unknown_returns_404(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    resp = TestClient(create_app(board)).get("/cards/999/edit")
    assert resp.status_code == 404


def test_detail_has_archive_and_delete_buttons(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Task", column="todo")
    text = TestClient(create_app(board)).get("/cards/001").text
    assert 'hx-post="/cards/001/archive"' in text
    assert 'hx-post="/cards/001/delete"' in text
    assert "hx-confirm" in text  # destructive actions ask for confirmation


def test_archive_card_via_post(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Task", column="todo")
    resp = TestClient(create_app(board)).post("/cards/001/archive")
    assert resp.status_code == 200
    assert all("001" not in [c.id for c in cards] for cards in board.board().values())
    assert list((board.kanbai_dir / "archive").glob("001-*.md"))  # moved to archive


def test_delete_card_via_post(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Task", column="todo")
    resp = TestClient(create_app(board)).post("/cards/001/delete")
    assert resp.status_code == 200
    with pytest.raises(CardNotFoundError):
        board.show("001")


def test_ui_command_invokes_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scaffold.init_board(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls: dict[str, object] = {}

    def fake_serve(
        board: Board,
        *,
        host: str,
        port: int,
        open_browser: bool,
        force_polling: bool,
        reload: bool,
    ) -> None:
        calls.update(
            host=host,
            port=port,
            open_browser=open_browser,
            force_polling=force_polling,
            reload=reload,
        )

    # The `ui` command imports serve lazily, so patching the module attribute is enough.
    monkeypatch.setattr("kanbai.web.server.serve", fake_serve)
    result = cli_runner.invoke(
        cli_app, ["ui", "--port", "9999", "--no-browser", "--poll", "--reload"]
    )
    assert result.exit_code == 0, result.output
    assert calls == {
        "host": "127.0.0.1",
        "port": 9999,
        "open_browser": False,
        "force_polling": True,
        "reload": True,
    }


def test_serve_reload_uses_import_string_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, object] = {}

    def fake_run(app: object, **kwargs: object) -> None:
        calls["app"] = app
        calls.update(kwargs)

    monkeypatch.setattr(server.uvicorn, "run", fake_run)
    monkeypatch.setattr(server.webbrowser, "open", lambda *a: None)
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)

    server.serve(board, reload=True, open_browser=False, port=1234)
    assert calls["app"] == "kanbai.web.app:create_app"
    assert calls["reload"] is True
    assert calls["factory"] is True


def test_ui_command_without_board_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # no board here
    result = cli_runner.invoke(cli_app, ["ui"])
    assert result.exit_code == 1


def test_board_partial_is_returned(tmp_path: Path) -> None:
    resp = _client(tmp_path).get("/board")
    assert resp.status_code == 200
    assert 'id="board"' in resp.text
    assert "<!DOCTYPE html>" not in resp.text  # partial only, not the full page


def test_events_streams_reload_on_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)

    async def fake_watch(kanbai_dir: Path, *, force_polling: bool = False) -> AsyncIterator[None]:
        yield None  # simulate a single filesystem change, then finish

    monkeypatch.setattr("kanbai.web.watcher.watch_board", fake_watch)
    resp = TestClient(create_app(board)).get("/events")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "data: reload" in resp.text


def test_watch_board_detects_change_with_polling(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    kanbai_dir = tmp_path / ".kanbai"

    async def run() -> None:
        agen = watch_board(kanbai_dir, force_polling=True)

        async def poke() -> None:
            await asyncio.sleep(0.3)
            (kanbai_dir / "todo" / "probe.md").write_text("x")

        task = asyncio.create_task(poke())
        try:
            assert await asyncio.wait_for(agen.__anext__(), timeout=10) is None
        finally:
            await task
            await agen.aclose()

    asyncio.run(run())
