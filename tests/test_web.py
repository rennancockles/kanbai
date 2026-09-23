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
from kanbai.web.hub import create_hub_app
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


def test_base_path_prefixes_urls(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Task", column="todo")
    html = TestClient(create_app(board, base_path="/b/proj")).get("/").text
    assert "/b/proj/static/style.css" in html
    assert 'hx-get="/b/proj/cards/new"' in html
    assert 'var BASE = "/b/proj"' in html


def test_default_base_path_has_no_prefix(tmp_path: Path) -> None:
    html = _client(tmp_path).get("/").text
    assert "/static/style.css" in html
    assert "/b/" not in html


def test_board_switcher_shown_with_boards(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    switcher = [{"name": "a", "url": "/b/a/"}, {"name": "b", "url": "/b/b/"}]
    client = TestClient(create_app(board, base_path="/b/a", boards=switcher, current="a"))
    html = client.get("/").text
    assert 'class="board-switcher"' in html
    assert '<option value="/b/a/" selected>a</option>' in html
    assert '<option value="/b/b/">b</option>' in html


def test_no_switcher_for_single_board(tmp_path: Path) -> None:
    assert "board-switcher" not in _client(tmp_path).get("/").text


def test_hub_board_pages_have_switcher(tmp_path: Path) -> None:
    board_a = tmp_path / "a"
    board_b = tmp_path / "b"
    scaffold.init_board(board_a)
    scaffold.init_board(board_b)
    page = TestClient(create_hub_app({"a": str(board_a), "b": str(board_b)})).get("/b/a/").text
    assert 'class="board-switcher"' in page
    assert "/b/b/" in page  # can switch to the other board


def test_hub_lists_and_serves_boards(tmp_path: Path) -> None:
    board_a = tmp_path / "a"
    board_b = tmp_path / "b"
    scaffold.init_board(board_a)
    scaffold.init_board(board_b)
    client = TestClient(create_hub_app({"a": str(board_a), "b": str(board_b)}))

    root = client.get("/")
    assert root.status_code == 200
    assert "/b/a/" in root.text
    assert "/b/b/" in root.text
    # each board is served under its prefix
    assert client.get("/b/a/").status_code == 200
    assert client.get("/b/b/board").status_code == 200


def test_hub_skips_missing_boards(tmp_path: Path) -> None:
    board_a = tmp_path / "a"
    scaffold.init_board(board_a)
    client = TestClient(create_hub_app({"a": str(board_a), "gone": str(tmp_path / "nope")}))
    assert client.get("/b/a/").status_code == 200
    assert client.get("/b/gone/").status_code == 404  # unmounted


def test_index_has_favicon_and_logo(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/").text
    assert 'rel="icon"' in body
    assert "/static/icon.png" in body
    assert 'class="logo"' in body  # logo shown in the topbar


def test_icon_asset_is_served(tmp_path: Path) -> None:
    resp = _client(tmp_path).get("/static/icon.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")


def test_index_wires_escape_to_close_modal(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/").text
    assert "keydown" in body
    assert "Escape" in body  # ESC closes the modal


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


def test_create_card_with_labels_and_description_via_post(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    client = TestClient(create_app(board))

    resp = client.post(
        "/cards",
        data={
            "title": "Nova tarefa",
            "column": "todo",
            "priority": "high",
            "labels": "a, b",
            "description": "some details",
        },
    )
    assert resp.status_code == 200
    card = board.list_column("todo")[0]
    assert card.labels == ["a", "b"]
    assert card.body == "some details"


def test_new_card_form_renders_all_fields(tmp_path: Path) -> None:
    resp = _client(tmp_path).get("/cards/new")
    assert resp.status_code == 200
    assert 'name="title"' in resp.text
    assert 'name="column"' in resp.text
    assert 'name="priority"' in resp.text
    assert 'name="type"' in resp.text
    assert 'name="labels"' in resp.text
    assert 'name="description"' in resp.text


def test_board_has_new_card_button(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/").text
    assert 'hx-get="/cards/new"' in body


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


def test_create_card_invalid_priority_is_ignored(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    client = TestClient(create_app(board))

    # A bad priority must not blow up with a 500.
    resp = client.post("/cards", data={"title": "Nope", "column": "todo", "priority": "urgent"})
    assert resp.status_code == 200
    assert all(not cards for cards in board.board().values())


def test_create_card_with_type_via_post(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    client = TestClient(create_app(board))

    resp = client.post(
        "/cards", data={"title": "Fix it", "column": "todo", "priority": "high", "type": "bug"}
    )
    assert resp.status_code == 200
    assert board.list_column("todo")[0].type == "bug"


def test_create_card_invalid_type_is_ignored(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    client = TestClient(create_app(board))

    resp = client.post(
        "/cards", data={"title": "Nope", "column": "todo", "priority": "low", "type": "bogus"}
    )
    assert resp.status_code == 200
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


def test_blocked_card_is_flagged_in_ui(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    blocker = board.add("Blocker", column="todo")  # 001
    board.add("Blocked", column="todo", deps=[blocker.id])  # 002 depends on 001
    body = TestClient(create_app(board)).get("/").text
    # The blocked card carries the marker; the blocker does not.
    assert "card-lock" in body
    assert "blocked" in body


def test_board_has_plan_sprint_button(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/").text
    assert 'hx-get="/sprint/plan"' in body


def test_toolbar_has_search_and_label_filter(tmp_path: Path) -> None:
    board_client = _client(tmp_path)  # adds a card labelled "ui"
    body = board_client.get("/").text
    assert 'name="q"' in body  # search input
    assert 'name="label"' in body  # label filter
    assert '<option value="ui"' in body  # label present in the filter


def test_board_filters_by_search_text(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Login screen", column="todo")
    board.add("Signup flow", column="todo")
    resp = TestClient(create_app(board)).get("/board", params={"q": "login"})
    assert "Login screen" in resp.text
    assert "Signup flow" not in resp.text


def test_board_filters_by_label(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Alpha", column="todo", labels=["ui"])
    board.add("Beta", column="todo", labels=["backend"])
    resp = TestClient(create_app(board)).get("/board", params={"label": "ui"})
    assert "Alpha" in resp.text
    assert "Beta" not in resp.text


def test_toolbar_has_type_filter(tmp_path: Path) -> None:
    board_client = _client(tmp_path)
    body = board_client.get("/").text
    assert 'class="type-filter"' in body
    assert '<option value="bug"' in body


def test_board_filters_by_type(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Alpha", column="todo", type="bug")
    board.add("Beta", column="todo", type="feature")
    resp = TestClient(create_app(board)).get("/board", params={"type": "bug"})
    assert "Alpha" in resp.text
    assert "Beta" not in resp.text


def test_custom_type_color_renders_as_inline_style(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    cfg = tmp_path / ".kanbai" / "config.toml"
    cfg.write_text(cfg.read_text() + '\n[types.colors]\nbug = "#ff0000"\n')
    board = Board.load(tmp_path)
    board.add("Alpha", column="todo", type="bug")
    resp = TestClient(create_app(board)).get("/board")
    assert 'style="color: #ff0000; background: rgba(255, 0, 0, 0.14);"' in resp.text
    # the CSS fallback class is dropped in favor of the inline color
    assert 'card-type type-bug' not in resp.text


def test_type_without_color_override_still_uses_css_class(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Alpha", column="todo", type="bug")
    resp = TestClient(create_app(board)).get("/board")
    assert 'card-type type-bug' in resp.text
    assert 'style="color:' not in resp.text


def test_column_over_wip_limit_is_flagged(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    cfg = tmp_path / ".kanbai" / "config.toml"
    cfg.write_text(cfg.read_text() + "\n[wip]\ntodo = 1\n")
    board = Board.load(tmp_path)
    board.add("A", column="todo")
    board.add("B", column="todo")  # 2 > 1
    body = TestClient(create_app(board)).get("/").text
    assert "2/1" in body  # count/limit shown
    assert "count over" in body  # over-limit styling hook


def test_board_has_close_sprint_button(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/").text
    assert 'hx-get="/sprint/new"' in body
    assert "Close sprint" in body
    assert "New sprint" not in body


def test_backlog_has_sort_control(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/").text
    assert 'hx-post="/columns/backlog/sort"' in body
    assert body.count('class="col-sort"') == 1  # only the backlog column
    assert '<option value="type">type</option>' in body


def test_sort_backlog_via_post(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("zeta", priority="low")
    board.add("alpha", priority="high")
    resp = TestClient(create_app(board)).post(
        "/columns/backlog/sort", data={"by": "priority", "dir": "desc"}
    )
    assert resp.status_code == 200
    assert [c.title for c in board.list_column("backlog")] == ["alpha", "zeta"]  # desc: high first


def test_sort_backlog_by_type_via_post(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("fix it", type="bug")
    board.add("new thing", type="feature")
    resp = TestClient(create_app(board)).post("/columns/backlog/sort", data={"by": "type"})
    assert resp.status_code == 200
    assert [c.title for c in board.list_column("backlog")] == ["fix it", "new thing"]


def test_board_has_archive_button(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/").text
    assert 'hx-get="/archive"' in body


def test_backlog_toggle_button_and_marker(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/").text
    assert 'id="toggle-backlog"' in body  # topbar toggle rendered
    assert "is-backlog" in body  # backlog column tagged for the CSS hide rule


def test_archive_view_lists_cards_with_origin(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    card = board.add("Done task", column="done")
    board.archive(card.id)
    resp = TestClient(create_app(board)).get("/archive")
    assert resp.status_code == 200
    assert "Done task" in resp.text
    assert "from done" in resp.text  # archived_from shown
    assert f'hx-post="/cards/{card.id}/restore"' in resp.text


def test_archive_view_shows_version_when_set(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    card = board.add("Done task", column="done", version="v1.2.0")
    board.archive(card.id)
    resp = TestClient(create_app(board)).get("/archive")
    assert "v1.2.0" in resp.text


def test_plan_and_archive_modals_render_priority_and_labels(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Themed backlog card", priority="high", labels=["ui"])  # backlog -> plan modal
    done = board.add("Old done card", column="done", priority="low", labels=["infra"])
    board.archive(done.id)
    client = TestClient(create_app(board))

    plan = client.get("/sprint/plan").text
    assert 'class="plan-item pri-high"' in plan  # priority accent on the row
    assert '<span class="item-pri">high</span>' in plan  # priority pill
    assert ">ui<" in plan  # label chip

    archive = client.get("/archive").text
    assert 'class="archive-item pri-low"' in archive
    assert ">infra<" in archive


def test_plan_and_archive_modals_have_friendly_empty_states(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    client = TestClient(create_app(Board.load(tmp_path)))  # empty board
    assert "modal-empty" in client.get("/sprint/plan").text
    assert "modal-empty" in client.get("/archive").text


def test_restore_card_via_post(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    card = board.add("Done task", column="done")
    board.archive(card.id)
    resp = TestClient(create_app(board)).post(f"/cards/{card.id}/restore")
    assert resp.status_code == 200
    assert [c.id for c in board.list_column("done")] == [card.id]
    assert board.list_archive() == []


def test_new_sprint_modal_and_action(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("A", column="todo")
    board.add("B", column="done")
    client = TestClient(create_app(board))

    modal = client.get("/sprint/new").text
    assert "Close sprint" in modal
    assert 'name="reset"' in modal  # the reset choice is offered
    assert 'name="version"' in modal  # optional version stamp

    resp = client.post("/sprint/new", data={"reset": "1"})
    assert resp.status_code == 200
    assert board.list_column("done") == []  # done archived
    assert [c.title for c in board.list_column("backlog")] == ["A"]  # active reset to backlog


def test_close_sprint_stamps_version_on_archived_cards(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("B", column="done")
    client = TestClient(create_app(board))

    resp = client.post("/sprint/new", data={"reset": "0", "version": "v1.2.0"})
    assert resp.status_code == 200
    assert board.list_archive()[0].version == "v1.2.0"


def test_close_sprint_without_version_leaves_it_unset(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("B", column="done")
    client = TestClient(create_app(board))

    resp = client.post("/sprint/new", data={"reset": "0"})
    assert resp.status_code == 200
    assert board.list_archive()[0].version is None


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


def test_plan_and_archive_modals_have_client_side_search(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Backlog card")  # so the plan modal has a list
    done = board.add("Done card", column="done")
    board.archive(done.id)  # so the archive modal has a list
    client = TestClient(create_app(board))

    for path in ("/sprint/plan", "/archive"):
        html = client.get(path).text
        assert 'class="modal-search"' in html
        assert "kanbaiFilterModal(this)" in html


def test_board_defines_modal_filter_function(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/").text
    assert "function kanbaiFilterModal" in body  # client-side filter preserves selection


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
        type="feature",
        labels=["ui"],
    )
    resp = TestClient(create_app(board)).get("/cards/001")
    assert resp.status_code == 200
    assert "Login screen" in resp.text
    assert "do the thing" in resp.text  # the body/description is now visible
    assert "ui" in resp.text  # label
    assert "feature" in resp.text  # type badge


def test_card_detail_does_not_show_assignee(tmp_path: Path) -> None:
    # assignee is fully supported in model/CLI/board but unused today, so the UI hides it.
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Task", column="todo", assignee="claude")
    resp = TestClient(create_app(board)).get("/cards/001")
    assert "assignee" not in resp.text.lower()


def test_detail_offers_move_to_other_columns(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Task", column="todo")  # 001, currently in todo
    text = TestClient(create_app(board)).get("/cards/001").text
    assert 'hx-post="/cards/001/move"' in text  # the select posts a move
    assert 'name="column"' in text
    assert '<option value="doing">' in text  # can move to another column
    assert '<option value="todo">' not in text  # not to its current column


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
    board.add(
        "Old title", column="todo", description="old body", priority="low", type="bug", labels=["a"]
    )
    resp = TestClient(create_app(board)).get("/cards/001/edit")
    assert resp.status_code == 200
    assert 'name="title"' in resp.text
    assert "Old title" in resp.text
    assert "old body" in resp.text
    assert 'name="type"' in resp.text
    assert '<option value="bug" selected>' in resp.text


def test_edit_card_persists_changes(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    board = Board.load(tmp_path)
    board.add("Old", column="todo", priority="low")
    client = TestClient(create_app(board))

    resp = client.post(
        "/cards/001/edit",
        data={
            "title": "New",
            "description": "desc",
            "priority": "high",
            "type": "bug",
            "labels": "x, y",
        },
    )
    assert resp.status_code == 200
    card = board.show("001")
    assert card.title == "New"
    assert card.body == "desc"
    assert card.priority.value == "high"
    assert card.type == "bug"
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
    # The SSE stream would otherwise hang reload on shutdown.
    assert calls["timeout_graceful_shutdown"] == 1


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


def test_events_streams_reload_on_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
