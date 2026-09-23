"""Run the kanbai web UI with uvicorn (backs the `kanbai ui` command).

Importing this module pulls in the optional ``ui`` extra (fastapi, uvicorn). The CLI imports
it lazily so a missing extra surfaces as a friendly message rather than an import crash.
"""

from __future__ import annotations

import os
import threading
import webbrowser

import uvicorn

from ..board import Board
from .app import create_app
from .hub import create_hub_app

# Import string uvicorn re-imports on each reload; `create_app()` loads the board from cwd.
_APP_FACTORY = "kanbai.web.app:create_app"

# The /events SSE stream holds a connection open indefinitely, so bound uvicorn's graceful
# shutdown — otherwise a reload (or Ctrl+C) hangs on "Waiting for connections to close".
_GRACEFUL_TIMEOUT = 1


def serve(
    board: Board,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
    force_polling: bool = False,
    reload: bool = False,
) -> None:
    """Serve the board for ``board`` and (optionally) open a browser once it is up.

    With ``reload`` the server watches the source and restarts on changes (dev only). Reload
    needs an import-string app, so the injected ``board`` is ignored and each worker loads the
    board from the current directory via the ``create_app`` factory.
    """
    if open_browser:
        url = f"http://{host}:{port}"
        # Fire slightly after uvicorn starts so the first request hits a live server.
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    if reload:
        if force_polling:
            # watchfiles honours this for both uvicorn's reloader and the board watcher.
            os.environ["WATCHFILES_FORCE_POLLING"] = "true"
        uvicorn.run(
            _APP_FACTORY,
            factory=True,
            reload=True,
            host=host,
            port=port,
            log_level="info",
            timeout_graceful_shutdown=_GRACEFUL_TIMEOUT,
        )
    else:
        uvicorn.run(
            create_app(board, force_polling=force_polling),
            host=host,
            port=port,
            log_level="info",
            timeout_graceful_shutdown=_GRACEFUL_TIMEOUT,
        )


def serve_hub(
    boards: dict[str, str],
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
) -> None:
    """Serve the multi-board hub (all registered boards under ``/b/<name>/``) on one port."""
    app = create_hub_app(boards)
    if open_browser:
        url = f"http://{host}:{port}"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(
        app, host=host, port=port, log_level="info", timeout_graceful_shutdown=_GRACEFUL_TIMEOUT
    )
