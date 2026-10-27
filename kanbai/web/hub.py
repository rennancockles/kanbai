"""The multi-board hub: serve several registered boards under ``/b/<name>/`` on one port."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.routing import Mount

from .. import APP_NAME, __version__, view_registry
from ..ai import ai_available, clamp_to_board, extract_card
from ..board import Board
from ..errors import KanbaiError
from ..models import Priority
from . import watcher
from .app import PRIORITY_CLASS, TYPE_CLASS, create_app
from .errors import render_http_error

_WEB_DIR = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_WEB_DIR / "templates"))
_OVERVIEW_COLS = ("todo", "doing", "review", "done")


def _board_view_data(name: str, path: str) -> dict[str, Any] | None:
    """Load board at *path* and return the context dict needed to render it in a view.

    Returns ``None`` if the board can't be loaded.
    """
    try:
        board = Board.load(Path(path))
    except (KanbaiError, OSError):
        return None
    all_cols = board.board()
    visible = board.config.visible_columns
    blocked = board.blocked_ids()
    type_style = {
        t: f"background: {color}; color: #000"
        for t, color in (board.config.type_colors or {}).items()
    }

    def col_view(col_name: str) -> dict[str, Any]:
        cards = all_cols.get(col_name, [])
        limit = board.config.wip_limit(col_name)
        return {
            "name": col_name,
            "cards": cards,
            "limit": limit,
            "over": limit is not None and len(cards) > limit,
        }

    return {
        "name": name,
        "board_name": board.config.name,
        "base": f"/b/{name}",
        "columns": [col_view(c) for c in visible],
        "backlog_column": board.config.add_column,
        "blocked": blocked,
        "priority_class": PRIORITY_CLASS,
        "type_class": TYPE_CLASS,
        "type_style": type_style,
    }


def _board_counts(path: str) -> dict[str, int]:
    """Read the overview column counts for the board at *path* straight from disk."""
    try:
        all_cols = Board.load(Path(path)).board()
    except (KanbaiError, OSError):
        return dict.fromkeys(_OVERVIEW_COLS, 0)
    return {col: len(all_cols.get(col, [])) for col in _OVERVIEW_COLS}


def _mount_boards(
    hub: FastAPI, boards: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, str | None]]]:
    """(Re)mount one board app per registered board under ``/b/<name>``, replacing any prior
    ``/b/*`` mounts. Returns ``(mounted, switcher)`` where ``mounted`` is the full list used by
    the landing page (includes column counts) and ``switcher`` is the name/url-only list used by
    per-board topbars and error pages. A board whose path no longer has a ``.kanbai/`` is skipped
    rather than crashing the whole hub — likewise a board the process simply can't read (e.g.
    macOS TCC denying access to a protected folder like ``~/Documents`` when the hub runs
    detached, without the terminal's grant) is skipped with a warning.
    """
    hub.router.routes = [
        r for r in hub.router.routes if not (isinstance(r, Mount) and r.path.startswith("/b/"))
    ]

    # Resolve which boards actually load first, so every board's switcher lists the same set.
    loaded: list[tuple[str, str, Board]] = []
    for name, path in sorted(boards.items()):
        try:
            loaded.append((name, path, Board.load(Path(path))))
        except KanbaiError:
            continue
        except OSError as exc:
            print(f"! skipping board '{name}' at {path}: {exc}", file=sys.stderr)
            continue

    mounted: list[dict[str, Any]] = [
        {
            "name": name,
            "path": path,
            "url": f"/b/{name}/",
            "category": board.config.category,
        }
        for name, path, board in loaded
    ]
    switcher: list[dict[str, str | None]] = [
        {"name": str(item["name"]), "url": str(item["url"]), "category": item.get("category")}
        for item in mounted
    ]

    for name, _path, board in loaded:
        base = f"/b/{name}"
        hub.mount(base, create_app(board, base_path=base, boards=switcher, current=name))

    return mounted, switcher


def create_hub_app(boards_provider: dict[str, str] | Callable[[], dict[str, str]]) -> FastAPI:  # noqa: C901
    """Build a hub app that mounts one board app per registered board under ``/b/<name>``.

    ``boards_provider`` is either a static ``{name: path}`` mapping (as stored in the
    registry) or a callable returning one. When it's a callable, the hub re-reads it before
    each request and remounts the boards if the registered set changed — so boards added via
    ``kanbai hub add`` while the hub is already running show up without a restart.
    """
    hub = FastAPI(title=f"{APP_NAME} hub", docs_url=None, redoc_url=None)
    hub.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")

    get_boards = boards_provider if callable(boards_provider) else (lambda: boards_provider)
    last_boards = dict(get_boards())
    mounted, switcher = _mount_boards(hub, last_boards)

    @hub.middleware("http")
    async def refresh_boards(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        nonlocal last_boards, mounted, switcher
        current = dict(get_boards())
        if current != last_boards:
            last_boards = current
            mounted, switcher = _mount_boards(hub, current)
        return await call_next(request)

    @hub.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Response:
        return _TEMPLATES.TemplateResponse(
            request,
            "hub.html",
            {
                "boards": [{**b, "counts": _board_counts(b["path"])} for b in mounted],
                "view_board_names": view_registry.load_view(),
                "app_name": APP_NAME,
                "app_version": __version__,
                "ai_available": ai_available(),
            },
        )

    @hub.post("/ai/command", response_class=HTMLResponse)
    def ai_command(request: Request, instruction: str = Form(...)) -> Response:
        card = extract_card(instruction, board_names=[item["name"] for item in mounted])
        board_entry = next((b for b in mounted if card and b["name"] == card.board), None)
        if card is None or board_entry is None:
            response = _TEMPLATES.TemplateResponse(request, "_ai_error.html")
            response.headers["HX-Retarget"] = "#detail"
            response.headers["HX-Reswap"] = "innerHTML"
            return response

        board = Board.load(Path(board_entry["path"]))
        prefill = clamp_to_board(card, board.config)
        base = board_entry["url"].removesuffix("/")
        return _TEMPLATES.TemplateResponse(
            request,
            "_new_card.html",
            {
                "base": base,
                "column_names": board.config.visible_columns,
                "default_column": prefill.column,
                "priorities": [p.value for p in Priority],
                "types": board.config.types,
                "default_type": prefill.type,
                "default_priority": prefill.priority,
                "prefill_title": prefill.title,
                "prefill_description": prefill.description,
                "prefill_labels": ", ".join(prefill.labels),
                "redirect_url": board_entry["url"],
            },
        )

    @hub.get("/view/edit", response_class=HTMLResponse)
    def edit_view_form(request: Request) -> Response:
        current = view_registry.load_view()
        ordered = view_registry.view_first(mounted)
        return _TEMPLATES.TemplateResponse(
            request,
            "_edit_view.html",
            {
                "all_boards": [{"name": b["name"], "category": b.get("category")} for b in ordered],
                "current_boards": current,
            },
        )

    @hub.post("/view", response_class=HTMLResponse)
    def save_view(request: Request, boards: list[str] = Form(default=[])) -> Response:
        # Keep only board names that are actually registered.
        valid = {str(b["name"]) for b in mounted}
        view_registry.save_view([b for b in boards if b in valid])
        return Response(status_code=303, headers={"Location": "/v/"})

    @hub.post("/view/order")
    def reorder_view(boards: list[str] = Form(default=[])) -> Response:
        view_registry.reorder_view(boards)
        return Response(status_code=204)

    @hub.post("/view/delete", response_class=HTMLResponse)
    def delete_view(request: Request) -> Response:
        view_registry.save_view([])
        return Response(status_code=303, headers={"Location": "/"})

    @hub.get("/v/", response_class=HTMLResponse)
    def view_page(request: Request) -> Response:
        board_names = view_registry.load_view()
        view_boards = []
        for name in board_names:
            path = last_boards.get(name)
            if path is None:
                continue
            data = _board_view_data(name, path)
            if data is not None:
                view_boards.append(data)
        return _TEMPLATES.TemplateResponse(
            request,
            "view.html",
            {
                "view_boards": view_boards,
                "app_name": APP_NAME,
                "app_version": __version__,
            },
        )

    @hub.get("/v/events")
    def view_events() -> StreamingResponse:
        view_dirs = {
            name: Path(last_boards[name]) / ".kanbai"
            for name in view_registry.load_view()
            if name in last_boards
        }

        async def stream() -> AsyncIterator[str]:
            yield ": connected\n\n"
            async for names in watcher.watch_boards(view_dirs):
                for name in names:
                    yield f"data: {name}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @hub.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        return render_http_error(request, exc, _TEMPLATES, boards=switcher)

    return hub
