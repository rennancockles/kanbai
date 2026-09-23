"""FastAPI application that renders the kanbai board and mutates it over HTMX."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from .. import APP_NAME
from ..board import Board
from ..errors import KanbaiError
from ..models import Card, Priority
from . import watcher

_WEB_DIR = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_WEB_DIR / "templates"))

# Maps a card priority value to the CSS modifier class used by the template.
PRIORITY_CLASS = {"high": "pri-high", "medium": "pri-medium", "low": "pri-low"}


def create_app(  # noqa: C901, PLR0915 - route-registration factory; size == route count
    board: Board | None = None, *, force_polling: bool = False, base_path: str = ""
) -> FastAPI:
    """Build the FastAPI app.

    ``board`` is injected in tests and by `kanbai ui`; when omitted it is loaded from the
    current working directory, so the app always reflects a real ``.kanbai/`` board.
    ``force_polling`` makes the live-update watcher poll instead of relying on OS file events.

    Routes render server-side and return HTMX partials so the board updates in place:
    ``GET /`` (full page), ``GET /board`` (partial), ``POST /cards`` (create),
    ``POST /cards/{id}/move`` (move), and ``GET /events`` (SSE live updates).
    """
    resolved = board if board is not None else Board.load()
    app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")

    def render(request: Request, name: str, ctx: dict[str, object] | None = None) -> Response:
        """Render a template, injecting ``base`` so URLs work under the hub's ``/b/<name>``."""
        return _TEMPLATES.TemplateResponse(request, name, {**(ctx or {}), "base": base_path})

    def context(search: str = "", label: str = "") -> dict[str, object]:
        query = search.strip().lower()

        def matches(card: Card) -> bool:
            if query and query not in card.title.lower() and query != card.id:
                return False
            return not (label and label not in card.labels)

        board_data = resolved.board()
        all_labels = sorted({lb for cards in board_data.values() for c in cards for lb in c.labels})

        def column_view(name: str, cards: list[Card]) -> dict[str, object]:
            limit = resolved.config.wip_limit(name)
            return {
                "name": name,
                "cards": [c for c in cards if matches(c)],
                "limit": limit,
                "over": limit is not None and len(cards) > limit,  # WIP uses the real count
            }

        return {
            "app_name": APP_NAME,
            "board_name": resolved.config.name,
            "columns": [column_view(name, cards) for name, cards in board_data.items()],
            "column_names": resolved.columns,
            "priorities": [p.value for p in Priority],
            "priority_class": PRIORITY_CLASS,
            "blocked": resolved.blocked_ids(),
            "labels": all_labels,
            "search": search,
            "label": label,
        }

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Response:
        return render(request, "board.html", context())

    @app.get("/board", response_class=HTMLResponse)
    def board_partial(request: Request, q: str = "", label: str = "") -> Response:
        return render(request, "_board.html", context(q, label))

    @app.get("/cards/{card_id}", response_class=HTMLResponse)
    def card_detail(request: Request, card_id: str) -> Response:
        try:
            card = resolved.show(card_id)
        except KanbaiError:
            return Response(status_code=404)
        return _TEMPLATES.TemplateResponse(
            request,
            "_detail.html",
            {
                "card": card,
                "priority_class": PRIORITY_CLASS,
                "column_names": resolved.columns,
            },
        )

    @app.get("/sprint/plan", response_class=HTMLResponse)
    def sprint_plan_form(request: Request) -> Response:
        backlog = resolved.list_column(resolved.config.add_column)
        return _TEMPLATES.TemplateResponse(
            request,
            "_plan.html",
            {
                "cards": backlog,
                "sprint": resolved.config.sprint_column,
                "priority_class": PRIORITY_CLASS,
            },
        )

    @app.post("/sprint/plan", response_class=HTMLResponse)
    def sprint_plan(request: Request, ids: list[str] = Form(default=[])) -> Response:
        for card_id in ids:
            with contextlib.suppress(KanbaiError):
                resolved.move(card_id, resolved.config.sprint_column)
        return render(request, "_board.html", context())

    @app.get("/archive", response_class=HTMLResponse)
    def archive_view(request: Request) -> Response:
        return _TEMPLATES.TemplateResponse(
            request, "_archive.html", {"cards": resolved.list_archive()}
        )

    @app.post("/cards/{card_id}/restore", response_class=HTMLResponse)
    def restore_card(request: Request, card_id: str) -> Response:
        with contextlib.suppress(KanbaiError):
            resolved.restore(card_id)
        return render(request, "_board.html", context())

    @app.get("/sprint/new", response_class=HTMLResponse)
    def sprint_new_form(request: Request) -> Response:
        return render(request, "_new_sprint.html", {})

    @app.post("/sprint/new", response_class=HTMLResponse)
    def sprint_new(request: Request, reset: str = Form("")) -> Response:
        resolved.new_sprint(reset_to_backlog=reset == "1")
        return render(request, "_board.html", context())

    @app.get("/cards/{card_id}/edit", response_class=HTMLResponse)
    def card_edit_form(request: Request, card_id: str) -> Response:
        try:
            card = resolved.show(card_id)
        except KanbaiError:
            return Response(status_code=404)
        return _TEMPLATES.TemplateResponse(
            request,
            "_edit.html",
            {
                "card": card,
                "priorities": [p.value for p in Priority],
                "priority_class": PRIORITY_CLASS,
            },
        )

    @app.post("/cards/{card_id}/edit", response_class=HTMLResponse)
    def card_edit(
        request: Request,
        card_id: str,
        title: str = Form(...),
        description: str = Form(""),
        priority: str = Form("medium"),
        labels: str = Form(""),
    ) -> Response:
        label_list = [s.strip() for s in labels.split(",") if s.strip()]
        with contextlib.suppress(KanbaiError):
            resolved.edit(
                card_id,
                title=title,
                description=description,
                priority=priority,
                labels=label_list,
            )
        return render(request, "_board.html", context())

    @app.post("/cards/{card_id}/archive", response_class=HTMLResponse)
    def card_archive(request: Request, card_id: str) -> Response:
        with contextlib.suppress(KanbaiError):
            resolved.archive(card_id)
        return render(request, "_board.html", context())

    @app.post("/cards/{card_id}/delete", response_class=HTMLResponse)
    def card_delete(request: Request, card_id: str) -> Response:
        with contextlib.suppress(KanbaiError):
            resolved.remove(card_id)
        return render(request, "_board.html", context())

    @app.get("/events")
    def events() -> StreamingResponse:
        async def stream() -> AsyncIterator[str]:
            yield ": connected\n\n"  # open the stream immediately
            async for _ in watcher.watch_board(resolved.kanbai_dir, force_polling=force_polling):
                yield "data: reload\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/cards", response_class=HTMLResponse)
    def create_card(
        request: Request,
        title: str = Form(...),
        column: str = Form(...),
        priority: str = Form("medium"),
    ) -> Response:
        # invalid column/priority — re-render the board unchanged
        with contextlib.suppress(KanbaiError):
            resolved.add(title, column=column, priority=priority)
        return render(request, "_board.html", context())

    @app.post("/cards/{card_id}/move", response_class=HTMLResponse)
    def move_card(
        request: Request,
        card_id: str,
        column: str = Form(...),
        position: int | None = Form(None),
    ) -> Response:
        # unknown card/column — re-render the board unchanged
        with contextlib.suppress(KanbaiError):
            resolved.move(card_id, column, position=position)
        return render(request, "_board.html", context())

    return app
