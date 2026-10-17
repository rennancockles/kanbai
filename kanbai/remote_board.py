"""HTTP client mirroring ``kanbai.board.Board``'s public verbs against a hosted kanbai_server.

``RemoteBoard`` is a drop-in replacement for ``Board`` in ``kanbai.cli``: every command
function in ``cli.py`` only calls methods this class also implements (``add``, ``move``,
``board``, ``list_column``, ``sort_column``, ``next``, ``blocked_ids``, ``show``, ``edit``,
``archive``, ``remove``, ``list_archive``, ``restore``, ``new_sprint``) plus the ``config``
and ``columns`` accessors — so ``cli._load()`` can return either without the rest of the
module knowing which one it got.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx2 as httpx

from .config import RemoteConfig
from .errors import HostUnreachableError, RemoteAPIError
from .models import BoardConfig, Card, Priority

_TIMEOUT = 10.0


def _send(client: httpx.Client, base_url: str, method: str, path: str, **kwargs: Any) -> Any:
    """Send a request through ``client``, raising :class:`RemoteAPIError` on any failure.

    Shared by :class:`RemoteBoard` and the standalone :func:`login`/:func:`create_remote_board`
    helpers, which need to talk to the API before a board (and thus a ``RemoteBoard``) exists.
    """
    try:
        response = client.request(method, path, **kwargs)
    except httpx.RequestError as exc:
        raise HostUnreachableError(f"Could not reach {base_url}: {exc}") from exc
    if response.is_error:
        if not _is_api_response(response):
            raise HostUnreachableError(
                f"{_error_detail(response)} — {base_url} did not answer like a kanbai server "
                "(blocked by a VPN, firewall or proxy?)",
                status_code=response.status_code,
            )
        detail = _error_detail(response)
        if response.status_code == httpx.codes.UNAUTHORIZED and "Authorization" in client.headers:
            detail = (
                f"{detail} — your hosted token is expired or invalid; "
                "run `kanbai hosted login` to renew it."
            )
        raise RemoteAPIError(detail, status_code=response.status_code)
    if response.status_code == httpx.codes.NO_CONTENT or not response.content:
        return None
    return response.json()


def login(url: str, email: str, password: str) -> str:
    """Authenticate with a hosted kanbai_server, returning a bearer access token."""
    with httpx.Client(base_url=url, timeout=_TIMEOUT) as client:
        data = _send(
            client, url, "POST", "/auth/login", json={"email": email, "password": password}
        )
    return str(data["access_token"])


def create_remote_board(url: str, token: str, config: BoardConfig) -> RemoteConfig:
    """Provision a new hosted board matching ``config``, returning its :class:`RemoteConfig`."""
    with httpx.Client(
        base_url=url, headers={"Authorization": f"Bearer {token}"}, timeout=_TIMEOUT
    ) as client:
        data = _send(
            client,
            url,
            "POST",
            "/boards",
            json={
                "name": config.name,
                "columns": config.columns,
                "default_priority": config.default_priority.value,
                "types": config.types,
                "type_colors": config.type_colors,
                "wip": config.wip,
                "bypass_review": config.bypass_review,
                "category": config.category,
            },
        )
    return RemoteConfig(url=url, token=token, board_id=str(data["id"]))


def list_remote_boards(url: str, token: str) -> list[dict[str, str]]:
    """Boards owned by the account behind ``token`` on ``url``: ``{"id", "name", "category"}``."""
    with httpx.Client(
        base_url=url, headers={"Authorization": f"Bearer {token}"}, timeout=_TIMEOUT
    ) as client:
        data = _send(client, url, "GET", "/boards")
    return [
        {"id": str(b["id"]), "name": str(b["name"]), "category": str(b.get("category", ""))}
        for b in data
    ]


class RemoteBoard:
    """A board served by a hosted kanbai_server, addressed by ``config.board_id``."""

    def __init__(self, config: RemoteConfig) -> None:
        self._remote = config
        self._client = httpx.Client(
            base_url=config.url,
            headers={"Authorization": f"Bearer {config.token}"},
            timeout=_TIMEOUT,
        )
        self.on_notify: Callable[[str, str], None] | None = None
        self.config = self._fetch_config()

    def _fetch_config(self) -> BoardConfig:
        data = self._request("GET", "/boards")
        for entry in data:
            if entry["id"] == self._remote.board_id:
                return _config_from_entry(entry)
        raise RemoteAPIError(
            f"Board '{self._remote.board_id}' was not found on {self._remote.url} "
            "(check config.toml's [server] board_id)."
        )

    def update_settings(self, config: BoardConfig) -> BoardConfig:
        """Make the hosted board's settings match ``config`` (everything but the columns)."""
        try:
            data = self._request(
                "PATCH", self._board_path(), json={f: _setting_value(config, f) for f in SETTINGS}
            )
        except RemoteAPIError as exc:
            if exc.status_code == httpx.codes.METHOD_NOT_ALLOWED:
                raise RemoteAPIError(
                    "This server cannot update board settings yet; update kanbai_server first.",
                    status_code=exc.status_code,
                ) from exc
            raise
        self.config = _config_from_entry(data)
        return self.config

    @property
    def columns(self) -> list[str]:
        return self.config.columns

    def _board_path(self, suffix: str = "") -> str:
        return f"/boards/{self._remote.board_id}{suffix}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Send a request to the hosted API, raising :class:`RemoteAPIError` on any failure."""
        return _send(self._client, self._remote.url, method, path, **kwargs)

    # ------------------------------------------------------------------ commands

    def add(  # noqa: PLR0913 - mirrors kanbai.board.Board.add's signature
        self,
        title: str,
        *,
        description: str = "",
        priority: str | Priority | None = None,
        type: str | None = None,  # noqa: A002 - mirrors the Card.type field name
        version: str | None = None,
        column: str | None = None,
        labels: list[str] | None = None,
        deps: list[str] | None = None,
        assignee: str | None = None,
        card_id: str | None = None,
    ) -> Card:
        """Create a new card on the hosted board.

        ``card_id`` asks the server to keep that id (so a local board can be published or
        pushed without ids diverging). Raises :class:`RemoteAPIError` if the server answers
        with a different id — an older server that ignores the field.
        """
        resolved_priority = priority.value if isinstance(priority, Priority) else priority
        data = self._request(
            "POST",
            self._board_path("/cards"),
            json={
                "id": card_id,
                "title": title,
                "description": description,
                "priority": resolved_priority,
                "type": type,
                "version": version,
                "column": column,
                "labels": labels or [],
                "deps": deps or [],
                "assignee": assignee,
            },
        )
        card = Card.model_validate(data)
        if card_id is not None and card.id != card_id:
            raise RemoteAPIError(
                f"The server assigned id '{card.id}' to card '{card_id}' instead of keeping it. "
                "It does not support explicit card ids — upgrade kanbai_server and retry."
            )
        return card

    def move(self, card_id: str, column: str, *, position: int | None = None) -> Card:
        """Move a card to ``column`` on the hosted board."""
        data = self._request(
            "POST",
            self._board_path(f"/cards/{card_id}/move"),
            json={"column": column, "position": position},
        )
        card = Card.model_validate(data)
        notify = self.on_notify
        if notify is not None:
            self._notify_on_move(notify, card, column)
        return card

    def _notify_on_move(self, notify: Callable[[str, str], None], card: Card, column: str) -> None:
        """Mirrors ``kanbai.board.Board._notify_on_move`` — same triggers, remote data."""
        review = self.config.review_column
        done = self.config.done_column
        review_or_done_target = review if review is not None else done
        if column == review_or_done_target:
            label = "review" if review is not None else "done"
            notify(f"{self.config.name}: card {card.id} in {label}", card.title)
        if column in (review, done) and self.next() is None:
            notify(
                f"{self.config.name}: sprint empty",
                "No actionable cards in the sprint — plan work into todo.",
            )

    def board(self) -> dict[str, list[Card]]:
        """Return every column and its cards."""
        data = self._request("GET", self._board_path("/cards"))
        return {column: [Card.model_validate(c) for c in cards] for column, cards in data.items()}

    def list_column(self, column: str) -> list[Card]:
        """Return the cards in a single column."""
        data = self._request("GET", self._board_path("/cards"), params={"column": column})
        return [Card.model_validate(c) for c in data]

    #: Sort keys available for :meth:`sort_column` (mirrors ``kanbai.board.Board.SORT_KEYS``).
    SORT_KEYS = ("id", "priority", "type", "title")

    def sort_column(self, column: str, key: str = "id", *, descending: bool = False) -> list[Card]:
        """Reorder ``column`` by ``key`` on the hosted board."""
        data = self._request(
            "POST",
            self._board_path(f"/columns/{column}/sort"),
            json={"key": key, "descending": descending},
        )
        return [Card.model_validate(c) for c in data]

    def next(self) -> Card | None:
        """Return the next actionable card in the sprint, if any."""
        data = self._request("GET", self._board_path("/next"))
        return Card.model_validate(data) if data is not None else None

    def blocked_ids(self) -> set[str]:
        """Return the ids of cards with at least one unmet dependency."""
        data = self._request("GET", self._board_path("/blocked"))
        return set(data)

    def show(self, card_id: str) -> Card:
        """Return the full card for ``card_id``."""
        data = self._request("GET", self._board_path(f"/cards/{card_id}"))
        return Card.model_validate(data)

    def edit(  # noqa: PLR0913 - mirrors kanbai.board.Board.edit's signature
        self,
        card_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: str | Priority | None = None,
        type: str | None = None,  # noqa: A002 - mirrors the Card.type field name
        version: str | None = None,
        labels: list[str] | None = None,
        deps: list[str] | None = None,
        assignee: str | None = None,
        order: int | None = None,
    ) -> Card:
        """Update fields on a card. Only provided fields change."""
        resolved_priority = priority.value if isinstance(priority, Priority) else priority
        data = self._request(
            "PATCH",
            self._board_path(f"/cards/{card_id}"),
            json={
                "title": title,
                "description": description,
                "priority": resolved_priority,
                "type": type,
                "version": version,
                "labels": labels,
                "deps": deps,
                "assignee": assignee,
                "order": order,
            },
        )
        return Card.model_validate(data)

    def archive(self, card_id: str) -> Card:
        """Archive a card, recording the column it came from."""
        data = self._request("POST", self._board_path(f"/cards/{card_id}/archive"))
        return Card.model_validate(data)

    def remove(self, card_id: str) -> Card:
        """Delete a card permanently."""
        data = self._request("DELETE", self._board_path(f"/cards/{card_id}"))
        return Card.model_validate(data)

    def list_archive(self) -> list[Card]:
        """Return the archived cards."""
        data = self._request("GET", self._board_path("/archive"))
        return [Card.model_validate(c) for c in data]

    def restore(self, card_id: str) -> Card:
        """Restore an archived card to the column it came from (or the backlog)."""
        data = self._request("POST", self._board_path(f"/cards/{card_id}/restore"))
        return Card.model_validate(data)

    def new_sprint(self, *, reset_to_backlog: bool, version: str | None = None) -> dict[str, int]:
        """Archive every done card, optionally resetting active columns to the backlog."""
        data = self._request(
            "POST",
            self._board_path("/sprint/close"),
            json={"reset_to_backlog": reset_to_backlog, "version": version},
        )
        return {"archived": data["archived"], "reset": data["reset"]}


#: Board settings that can be synced with the hosted board (the columns cannot: renaming or
#: removing one would strand its cards).
SETTINGS = (
    "name",
    "category",
    "default_priority",
    "types",
    "type_colors",
    "wip",
    "bypass_review",
    "notifications_native",
    "notifications_ntfy_topic",
)


def _setting_value(config: BoardConfig, name: str) -> object:
    value = getattr(config, name)
    return value.value if isinstance(value, Priority) else value


def _config_from_entry(entry: dict[str, Any]) -> BoardConfig:
    return BoardConfig(
        name=entry["name"],
        columns=entry["columns"],
        default_priority=Priority(entry["default_priority"]),
        types=entry["types"],
        type_colors=entry["type_colors"],
        wip=entry["wip"],
        bypass_review=entry["bypass_review"],
        category=entry.get("category", ""),
        notifications_native=entry.get("notifications_native", True),
        notifications_ntfy_topic=entry.get("notifications_ntfy_topic", ""),
    )


def _is_api_response(response: httpx.Response) -> bool:
    """Whether the reply is the hosted API's own JSON (as opposed to a proxy's block page)."""
    try:
        return isinstance(response.json(), dict)
    except ValueError:
        return False


def _error_detail(response: httpx.Response) -> str:
    """Extract the hosted API's ``{"detail": "..."}`` error body, falling back to the status."""
    try:
        body = response.json()
    except ValueError:
        return f"{response.status_code} {response.reason_phrase}"
    detail = body.get("detail") if isinstance(body, dict) else None
    return str(detail) if detail else f"{response.status_code} {response.reason_phrase}"
