"""Shared HTML error page, registered as the HTTPException handler on both the hub app and
each per-board app so an unknown route renders something better than FastAPI's bare
``{"detail": "Not Found"}`` JSON. API clients that explicitly ask for JSON still get it.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from .. import APP_NAME


def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept


def render_http_error(
    request: Request,
    exc: StarletteHTTPException,
    templates: Jinja2Templates,
    *,
    base_path: str = "",
    boards: list[dict[str, str]] | None = None,
) -> Response:
    """Build the response for a raised ``HTTPException`` (typically a 404 from no route
    matching). ``base_path`` and ``boards`` mirror the same-named ``create_app``/hub
    parameters, so the page can link back to the right place.
    """
    if _wants_json(request):
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "app_name": APP_NAME,
            "status_code": exc.status_code,
            "detail": exc.detail,
            "base": base_path,
            "boards": boards or [],
        },
        status_code=exc.status_code,
    )
