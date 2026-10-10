"""The multi-board hub: serve several registered boards under ``/b/<name>/`` on one port."""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.routing import Mount

from .. import APP_NAME, __version__
from ..ai import ai_available, clamp_to_board, extract_card
from ..board import Board
from ..errors import KanbaiError
from ..models import Priority
from .app import create_app
from .errors import render_http_error

_WEB_DIR = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_WEB_DIR / "templates"))
_OVERVIEW_COLS = ("todo", "doing", "review", "done")


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

    mounted: list[dict[str, Any]] = []
    for name, path, board in loaded:
        try:
            all_cols = board.board()
            counts = {col: len(all_cols.get(col, [])) for col in _OVERVIEW_COLS}
        except (KanbaiError, OSError):
            counts = dict.fromkeys(_OVERVIEW_COLS, 0)
        mounted.append(
            {
                "name": name,
                "path": path,
                "url": f"/b/{name}/",
                "category": board.config.category,
                "counts": counts,
            }
        )
    switcher: list[dict[str, str | None]] = [
        {"name": str(item["name"]), "url": str(item["url"]), "category": item.get("category")}
        for item in mounted
    ]

    for name, _path, board in loaded:
        base = f"/b/{name}"
        hub.mount(base, create_app(board, base_path=base, boards=switcher, current=name))

    return mounted, switcher


def create_hub_app(boards_provider: dict[str, str] | Callable[[], dict[str, str]]) -> FastAPI:
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
                "boards": mounted,
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

    @hub.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        return render_http_error(request, exc, _TEMPLATES, boards=switcher)

    return hub
