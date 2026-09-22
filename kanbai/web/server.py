"""Run the kanbai web UI with uvicorn (backs the `kanbai ui` command).

Importing this module pulls in the optional ``ui`` extra (fastapi, uvicorn). The CLI imports
it lazily so a missing extra surfaces as a friendly message rather than an import crash.
"""

from __future__ import annotations

import threading
import webbrowser

import uvicorn

from ..board import Board
from .app import create_app


def serve(
    board: Board,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
    force_polling: bool = False,
) -> None:
    """Serve the board for ``board`` and (optionally) open a browser once it is up."""
    app = create_app(board, force_polling=force_polling)
    if open_browser:
        url = f"http://{host}:{port}"
        # Fire slightly after uvicorn starts so the first request hits a live server.
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="info")
