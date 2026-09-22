"""Web UI for kanbai — a FastAPI app that renders the board (served by `kanbai ui`).

Everything here depends on the optional ``ui`` extra (fastapi, uvicorn, jinja2, watchfiles);
the core CLI never imports this package, so kanbai works without those installed.
"""
