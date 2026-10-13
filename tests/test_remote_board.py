"""RemoteBoard tests: HTTP request/response mapping against a fake hosted API.

The fake server below is a minimal, in-memory stand-in for kanbai_server's HTTP API (a
separate package this repo does not depend on) — just enough request/response shape to
exercise ``RemoteBoard``'s mapping to/from ``Card``/``BoardConfig`` and its error handling.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from datetime import datetime

import httpx2 as httpx
import pytest
from kanbai.config import RemoteConfig
from kanbai.errors import HostUnreachableError, RemoteAPIError
from kanbai.models import Card, Priority
from kanbai.remote_board import RemoteBoard, login

BOARD_ID = "board-1"
_NOW = datetime(2026, 1, 1, 12, 0, 0)

#: Credentials the fake server accepts on POST /auth/login (mirrors an account provisioned
#: out-of-band by an admin, as ``kanbai hosted publish`` expects — see card 080).
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "s3cret"
ADMIN_TOKEN = "fake-admin-token"


class _FakeServer:
    """In-memory multi-board store, matching kanbai_server's request/response shapes closely
    enough for RemoteBoard/hosted publish/download tests. Not a reimplementation of the real
    API's business logic beyond what these tests exercise. Starts with one pre-existing
    board (id ``BOARD_ID``) for tests that don't care about `kanbai hosted publish`."""

    def __init__(self) -> None:
        self.boards: dict[str, dict[str, object]] = {
            BOARD_ID: {
                "id": BOARD_ID,
                "name": "Remote board",
                "columns": ["backlog", "todo", "doing", "review", "done"],
                "default_priority": "medium",
                "types": ["feature", "bug", "refactor", "chore", "docs", "spike"],
                "type_colors": {},
                "wip": {},
                "bypass_review": False,
            }
        }
        self.cards: dict[str, dict[str, dict[str, object]]] = {BOARD_ID: {}}
        self._next_board_id = 2  # BOARD_ID is already taken
        self._next_card_id: dict[str, int] = {BOARD_ID: 1}
        # Emulates an older kanbai_server that ignores an explicit `id` on card creation.
        self.ignores_card_ids = False

    def _card_dict(self, board_id: str, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "id": f"{self._next_card_id[board_id]:03d}",
            "title": "",
            "status": "backlog",
            "priority": "medium",
            "type": None,
            "version": None,
            "order": 1,
            "labels": [],
            "deps": [],
            "assignee": None,
            "archived_from": None,
            "created": _NOW.isoformat(),
            "updated": _NOW.isoformat(),
            "body": "",
        }
        base.update(overrides)
        return base

    def handle(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        body = _json_body(request)

        if path == "/auth/login":
            return self._login(body)
        if path == "/boards":
            return self._create_board(body) if method == "POST" else self._list_boards()

        board_match = re.match(r"^/boards/([\w-]+)/(.*)$", path)
        if board_match:
            return self._handle_board_route(
                request, board_match.group(1), board_match.group(2), body
            )

        return httpx.Response(404, json={"detail": f"unhandled route: {method} {path}"})

    def _login(self, body: dict[str, object]) -> httpx.Response:
        if body.get("email") == ADMIN_EMAIL and body.get("password") == ADMIN_PASSWORD:
            return httpx.Response(200, json={"access_token": ADMIN_TOKEN, "token_type": "bearer"})
        return httpx.Response(401, json={"detail": "Invalid email or password."})

    def _create_board(self, body: dict[str, object]) -> httpx.Response:
        board_id = f"board-{self._next_board_id}"
        self._next_board_id += 1
        board_config = {
            "id": board_id,
            "name": body.get("name") or "kanbai board",
            "columns": body.get("columns") or ["backlog", "todo", "doing", "review", "done"],
            "default_priority": body.get("default_priority") or "medium",
            "types": body.get("types") or [],
            "type_colors": body.get("type_colors") or {},
            "wip": body.get("wip") or {},
            "bypass_review": body.get("bypass_review") or False,
            "category": body.get("category") or "",
        }
        self.boards[board_id] = board_config
        self.cards[board_id] = {}
        self._next_card_id[board_id] = 1
        return httpx.Response(200, json=board_config)

    def _list_boards(self) -> httpx.Response:
        return httpx.Response(200, json=list(self.boards.values()))

    def _handle_board_route(
        self, request: httpx.Request, board_id: str, rest: str, body: dict[str, object]
    ) -> httpx.Response:
        if board_id not in self.boards:
            return httpx.Response(404, json={"detail": f"No board found with id '{board_id}'."})
        cards = self.cards[board_id]
        method = request.method

        fixed_routes: dict[str, Callable[[], httpx.Response]] = {
            "cards": lambda: self._handle_cards(request, board_id, body),
            "next": lambda: self._find_first(cards, lambda c: c["status"] == "todo"),
            "blocked": lambda: httpx.Response(200, json=[]),
            "archive": lambda: self._list_where(cards, lambda c: c["status"] == "archive"),
            "sprint/close": lambda: self._close_sprint(cards),
        }
        if rest in fixed_routes:
            return fixed_routes[rest]()

        card_match = re.match(r"^cards/(\w+)(?:/(move|archive|restore))?$", rest)
        if card_match:
            return self._handle_card(cards, method, card_match.group(1), card_match.group(2), body)
        sort_match = re.match(r"^columns/(\w+)/sort$", rest)
        if sort_match:
            return self._sort_column(cards, sort_match.group(1), body)

        return httpx.Response(404, json={"detail": f"unhandled route on {board_id}: {rest}"})

    def _handle_cards(
        self, request: httpx.Request, board_id: str, body: dict[str, object]
    ) -> httpx.Response:
        cards = self.cards[board_id]
        if request.method == "POST":
            return self._create_card(board_id, body)
        column = request.url.params.get("column")
        if column is not None:
            return self._list_where(cards, lambda c: c["status"] == column)
        return self._list_or_group_cards(board_id, cards)

    def _list_or_group_cards(
        self, board_id: str, cards: dict[str, dict[str, object]]
    ) -> httpx.Response:
        columns: dict[str, list[dict[str, object]]] = {
            c: []
            for c in self.boards[board_id]["columns"]  # type: ignore[union-attr]
        }
        for card in cards.values():
            columns.setdefault(str(card["status"]), []).append(card)
        return httpx.Response(200, json=columns)

    def _create_card(self, board_id: str, body: dict[str, object]) -> httpx.Response:
        cards = self.cards[board_id]
        pinned = None if self.ignores_card_ids else body.get("id")
        if isinstance(pinned, str) and pinned in cards:
            return httpx.Response(409, json={"detail": f"Card '{pinned}' already exists."})
        card_id = pinned if isinstance(pinned, str) else f"{self._next_card_id[board_id]:03d}"
        if isinstance(pinned, str):
            self._next_card_id[board_id] = max(self._next_card_id[board_id], int(pinned) + 1)
        else:
            self._next_card_id[board_id] += 1
        card = self._card_dict(
            board_id,
            id=card_id,
            title=body["title"],
            status=body.get("column") or "backlog",
            priority=body.get("priority") or "medium",
            type=body.get("type"),
            version=body.get("version"),
            labels=body.get("labels") or [],
            deps=body.get("deps") or [],
            assignee=body.get("assignee"),
            body=body.get("description") or "",
        )
        cards[card_id] = card
        return httpx.Response(200, json=card)

    def _handle_card(
        self,
        cards: dict[str, dict[str, object]],
        method: str,
        card_id: str,
        action: str | None,
        body: dict[str, object],
    ) -> httpx.Response:
        if card_id not in cards:
            return _not_found(card_id)
        if action == "move":
            cards[card_id]["status"] = body["column"]
        elif action == "archive":
            cards[card_id]["archived_from"] = cards[card_id]["status"]
            cards[card_id]["status"] = "archive"
        elif action == "restore":
            cards[card_id]["status"] = cards[card_id]["archived_from"] or "backlog"
            cards[card_id]["archived_from"] = None
        elif method == "PATCH":
            fields = ("title", "priority", "type", "version", "labels", "deps", "assignee")
            for field in fields:
                if body.get(field) is not None:
                    cards[card_id][field] = body[field]
        elif method == "DELETE":
            return httpx.Response(200, json=cards.pop(card_id))
        return httpx.Response(200, json=cards[card_id])

    def _sort_column(
        self, cards: dict[str, dict[str, object]], column: str, body: dict[str, object]
    ) -> httpx.Response:
        sorted_cards = sorted(
            (c for c in cards.values() if c["status"] == column),
            key=lambda c: str(c[body["key"]]),  # type: ignore[index]
            reverse=bool(body.get("descending", False)),
        )
        return httpx.Response(200, json=sorted_cards)

    def _close_sprint(self, cards: dict[str, dict[str, object]]) -> httpx.Response:
        archived = sum(1 for c in cards.values() if c["status"] == "done")
        for card in cards.values():
            if card["status"] == "done":
                card["status"] = "archive"
        return httpx.Response(200, json={"archived": archived, "reset": 0})

    def _list_where(
        self, cards: dict[str, dict[str, object]], predicate: Callable[[dict[str, object]], bool]
    ) -> httpx.Response:
        matches = [c for c in cards.values() if predicate(c)]
        return httpx.Response(200, json=matches)

    def _find_first(
        self, cards: dict[str, dict[str, object]], predicate: Callable[[dict[str, object]], bool]
    ) -> httpx.Response:
        for card in cards.values():
            if predicate(card):
                return httpx.Response(200, json=card)
        return httpx.Response(200, json=None)


def _not_found(card_id: str) -> httpx.Response:
    return httpx.Response(404, json={"detail": f"No card found with id '{card_id}'."})


def _json_body(request: httpx.Request) -> dict[str, object]:
    if not request.content:
        return {}
    return dict(json.loads(request.content))


def patch_transport(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    """Make every ``httpx2.Client`` created during the test route through ``transport``,
    standing in for the real network connection ``RemoteBoard`` would otherwise open."""
    original_init = httpx.Client.__init__

    def patched_init(self: httpx.Client, *args: object, **kwargs: object) -> None:
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx.Client, "__init__", patched_init)


@pytest.fixture
def fake_server() -> _FakeServer:
    return _FakeServer()


@pytest.fixture
def remote_board(
    fake_server: _FakeServer, monkeypatch: pytest.MonkeyPatch
) -> Iterator[RemoteBoard]:
    patch_transport(monkeypatch, httpx.MockTransport(fake_server.handle))
    config = RemoteConfig(url="https://kanbai.example.com", token="tok", board_id=BOARD_ID)
    yield RemoteBoard(config)


def test_load_fetches_config_for_the_configured_board(remote_board: RemoteBoard) -> None:
    assert remote_board.config.name == "Remote board"
    assert remote_board.columns == ["backlog", "todo", "doing", "review", "done"]


def test_load_raises_when_board_id_not_found(
    fake_server: _FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_transport(monkeypatch, httpx.MockTransport(fake_server.handle))
    config = RemoteConfig(url="https://kanbai.example.com", token="tok", board_id="missing")

    with pytest.raises(RemoteAPIError):
        RemoteBoard(config)


def test_add_creates_card_in_backlog_by_default(remote_board: RemoteBoard) -> None:
    card = remote_board.add("Do the thing")

    assert card.status == "backlog"
    assert card.title == "Do the thing"


def test_add_accepts_priority_enum(remote_board: RemoteBoard) -> None:
    card = remote_board.add("High priority", priority=Priority.high)

    assert card.priority == Priority.high


def test_move_updates_status(remote_board: RemoteBoard) -> None:
    card = remote_board.add("Card")

    moved = remote_board.move(card.id, "todo")

    assert moved.status == "todo"


def test_show_returns_full_card(remote_board: RemoteBoard) -> None:
    card = remote_board.add("Card", description="Some body")

    shown = remote_board.show(card.id)

    assert shown.id == card.id
    assert shown.title == "Card"


def test_show_unknown_card_raises_remote_api_error(remote_board: RemoteBoard) -> None:
    with pytest.raises(RemoteAPIError) as exc_info:
        remote_board.show("999")

    assert "999" in str(exc_info.value)
    assert exc_info.value.status_code == 404


def test_edit_updates_only_provided_fields(remote_board: RemoteBoard) -> None:
    card = remote_board.add("Original", priority="low")

    edited = remote_board.edit(card.id, title="Renamed")

    assert edited.title == "Renamed"
    assert edited.priority == Priority.low


def test_archive_then_restore(remote_board: RemoteBoard) -> None:
    card = remote_board.add("Card", column="todo")

    archived = remote_board.archive(card.id)
    assert archived.status == "archive"
    assert archived.archived_from == "todo"

    restored = remote_board.restore(card.id)
    assert restored.status == "todo"


def test_remove_deletes_card(remote_board: RemoteBoard) -> None:
    card = remote_board.add("Card")

    removed = remote_board.remove(card.id)

    assert removed.id == card.id
    with pytest.raises(RemoteAPIError):
        remote_board.show(card.id)


def test_list_column_filters_by_column(remote_board: RemoteBoard) -> None:
    remote_board.add("In backlog")
    remote_board.add("In todo", column="todo")

    todo_cards = remote_board.list_column("todo")

    assert [c.title for c in todo_cards] == ["In todo"]


def test_board_returns_every_column(remote_board: RemoteBoard) -> None:
    remote_board.add("Card")

    data = remote_board.board()

    assert [c.title for c in data["backlog"]] == ["Card"]
    assert data["todo"] == []


def test_next_returns_todo_card(remote_board: RemoteBoard) -> None:
    remote_board.add("Card", column="todo")

    card = remote_board.next()

    assert card is not None
    assert card.title == "Card"


def test_next_returns_none_when_empty(remote_board: RemoteBoard) -> None:
    assert remote_board.next() is None


def test_list_archive_returns_archived_cards(remote_board: RemoteBoard) -> None:
    card = remote_board.add("Card")
    remote_board.archive(card.id)

    archived = remote_board.list_archive()

    assert [c.id for c in archived] == [card.id]


def test_sort_column_orders_by_key(remote_board: RemoteBoard) -> None:
    remote_board.add("Bravo", column="todo")
    remote_board.add("Alpha", column="todo")

    sorted_cards = remote_board.sort_column("todo", "title")

    assert [c.title for c in sorted_cards] == ["Alpha", "Bravo"]


def test_new_sprint_archives_done_cards(remote_board: RemoteBoard) -> None:
    remote_board.add("Card", column="done")

    result = remote_board.new_sprint(reset_to_backlog=False)

    assert result == {"archived": 1, "reset": 0}


def test_network_error_raises_remote_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    patch_transport(monkeypatch, httpx.MockTransport(broken_handler))
    config = RemoteConfig(url="https://kanbai.example.com", token="tok", board_id=BOARD_ID)

    with pytest.raises(RemoteAPIError):
        RemoteBoard(config)


def test_move_fires_on_notify_when_review_reached(remote_board: RemoteBoard) -> None:
    notifications: list[tuple[str, str]] = []
    remote_board.on_notify = lambda title, body: notifications.append((title, body))
    card = remote_board.add("Card")

    remote_board.move(card.id, "review")

    assert any("review" in title for title, _ in notifications)


def test_add_returns_card_model(remote_board: RemoteBoard) -> None:
    card = remote_board.add("Card")

    assert isinstance(card, Card)


def _board_with_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> RemoteConfig:
    patch_transport(monkeypatch, httpx.MockTransport(handler))
    return RemoteConfig(url="https://kanbai.example.com", token="tok", board_id=BOARD_ID)


def test_network_failure_raises_host_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(HostUnreachableError, match="Could not reach"):
        RemoteBoard(_board_with_transport(monkeypatch, refuse))


def test_non_api_error_reply_is_reported_as_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def block_page(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="<html>blocked</html>")

    with pytest.raises(HostUnreachableError, match="VPN, firewall or proxy") as exc_info:
        RemoteBoard(_board_with_transport(monkeypatch, block_page))
    assert exc_info.value.status_code == 403


def test_json_error_reply_is_a_plain_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "not your board"})

    with pytest.raises(RemoteAPIError, match="not your board") as exc_info:
        RemoteBoard(_board_with_transport(monkeypatch, forbidden))
    assert not isinstance(exc_info.value, HostUnreachableError)


def test_expired_token_error_points_to_hosted_login(monkeypatch: pytest.MonkeyPatch) -> None:
    def expired(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Token has expired"})

    with pytest.raises(RemoteAPIError, match="Token has expired") as exc_info:
        RemoteBoard(_board_with_transport(monkeypatch, expired))
    assert "kanbai hosted login" in str(exc_info.value)
    assert exc_info.value.status_code == 401


def test_bad_login_credentials_do_not_suggest_hosted_login(
    fake_server: _FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_transport(monkeypatch, httpx.MockTransport(fake_server.handle))

    with pytest.raises(RemoteAPIError) as exc_info:
        login("https://kanbai.example.com", ADMIN_EMAIL, "wrong")
    assert "Invalid email or password" in str(exc_info.value)
    assert "hosted login" not in str(exc_info.value)
