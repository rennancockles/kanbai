"""The multi-board hub: serve several registered boards under ``/b/<name>/`` on one port."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from .. import APP_NAME
from ..board import Board
from ..errors import KanbaiError
from .app import create_app

_WEB_DIR = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_WEB_DIR / "templates"))


def create_hub_app(boards: dict[str, str]) -> FastAPI:
    """Build a hub app that mounts one board app per registered board under ``/b/<name>``.

    ``boards`` maps a name to a project path (as stored in the registry). A board whose path
    no longer has a ``.kanbai/`` is skipped rather than crashing the whole hub.
    """
    hub = FastAPI(title=f"{APP_NAME} hub", docs_url=None, redoc_url=None)
    hub.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")

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

    @hub.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Response:
        return _TEMPLATES.TemplateResponse(
            request, "hub.html", {"boards": mounted, "app_name": APP_NAME}
        )

    return hub
