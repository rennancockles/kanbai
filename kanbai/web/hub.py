"""The multi-board hub: serve several registered boards under ``/b/<name>/`` on one port."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response
from starlette.routing import Mount

from .. import APP_NAME, __version__
from ..board import Board
from ..errors import KanbaiError
from .app import create_app

_WEB_DIR = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_WEB_DIR / "templates"))


def _mount_boards(hub: FastAPI, boards: dict[str, str]) -> list[dict[str, str]]:
    """(Re)mount one board app per registered board under ``/b/<name>``, replacing any prior
    ``/b/*`` mounts. Returns the ``mounted`` list used by the landing page. A board whose path
    no longer has a ``.kanbai/`` is skipped rather than crashing the whole hub.
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
    mounted = [{"name": name, "path": path, "url": f"/b/{name}/"} for name, path, _ in loaded]
    switcher = [{"name": item["name"], "url": item["url"]} for item in mounted]

    for name, _path, board in loaded:
        base = f"/b/{name}"
        hub.mount(base, create_app(board, base_path=base, boards=switcher, current=name))

    return mounted


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
    mounted = _mount_boards(hub, last_boards)

    @hub.middleware("http")
    async def refresh_boards(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        nonlocal last_boards, mounted
        current = dict(get_boards())
        if current != last_boards:
            last_boards = current
            mounted = _mount_boards(hub, current)
        return await call_next(request)

    @hub.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Response:
        return _TEMPLATES.TemplateResponse(
            request,
            "hub.html",
            {"boards": mounted, "app_name": APP_NAME, "app_version": __version__},
        )

    return hub
