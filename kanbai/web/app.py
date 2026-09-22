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
from ..models import Priority
from . import watcher

_WEB_DIR = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_WEB_DIR / "templates"))

# Maps a card priority value to the CSS modifier class used by the template.
PRIORITY_CLASS = {"high": "pri-high", "medium": "pri-medium", "low": "pri-low"}


def create_app(board: Board | None = None, *, force_polling: bool = False) -> FastAPI:
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

    def context() -> dict[str, object]:
        return {
            "app_name": APP_NAME,
            "board_name": resolved.config.name,
            "columns": [{"name": name, "cards": cards} for name, cards in resolved.board().items()],
            "column_names": resolved.columns,
            "priorities": [p.value for p in Priority],
            "priority_class": PRIORITY_CLASS,
        }

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Response:
        return _TEMPLATES.TemplateResponse(request, "board.html", context())

    @app.get("/board", response_class=HTMLResponse)
    def board_partial(request: Request) -> Response:
        return _TEMPLATES.TemplateResponse(request, "_board.html", context())

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
        return _TEMPLATES.TemplateResponse(request, "_board.html", context())

    @app.post("/cards/{card_id}/move", response_class=HTMLResponse)
    def move_card(request: Request, card_id: str, column: str = Form(...)) -> Response:
        # unknown card/column — re-render the board unchanged
        with contextlib.suppress(KanbaiError):
            resolved.move(card_id, column)
        return _TEMPLATES.TemplateResponse(request, "_board.html", context())

    return app
