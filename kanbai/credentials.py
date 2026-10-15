"""Global hosted-server credentials (``~/.kanbai/credentials.toml``).

One access token per hosted server URL, shared by every project connected to that server, so
renewing it once (`kanbai hosted login`) fixes them all instead of editing each project's
``config.toml``. The base directory can be overridden with ``$KANBAI_HOME`` like the registry.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import storage
from .errors import KanbaiError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib  # ty: ignore[unresolved-import]


def credentials_path() -> Path:
    """Location of the credentials file (override the base dir with ``$KANBAI_HOME``)."""
    base = os.environ.get("KANBAI_HOME")
    root = Path(base) if base else Path.home() / ".kanbai"
    return root / "credentials.toml"


def _key(url: str) -> str:
    return url.strip().rstrip("/")


def _read(*, strict: bool) -> dict[str, str]:
    path = credentials_path()
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        if strict:
            raise KanbaiError(
                f"Could not read {path} ({exc}). Fix or delete it, then log in again."
            ) from exc
        return {}
    tokens = raw.get("tokens", {})
    if not isinstance(tokens, dict):
        return {}
    return {str(url): token for url, token in tokens.items() if isinstance(token, str)}


def load_token(url: str) -> str | None:
    """The global token saved for ``url``, or ``None`` (also when the file is unreadable)."""
    return _read(strict=False).get(_key(url))


def save_token(url: str, token: str) -> Path:
    """Save ``token`` as the global credential for ``url``, keeping the other servers' tokens.

    The file is written atomically and readable only by the current user. Raises
    :class:`KanbaiError` if an existing file is corrupt (it is left untouched).
    """
    tokens = _read(strict=True)
    tokens[_key(url)] = token
    lines = ["[tokens]\n"]
    lines += [f"{json.dumps(key)} = {json.dumps(value)}\n" for key, value in sorted(tokens.items())]
    path = credentials_path()
    storage.atomic_write(path, "".join(lines))
    return path


def refresh_token(url: str, token: str) -> None:
    """Replace the global token for ``url`` only if one is already saved and differs.

    Called when the CLI obtains a fresh token another way (connect, clone, per-project login),
    so an older global token can never override it. It never creates a global entry.
    """
    current = load_token(url)
    if current is not None and current != token:
        save_token(url, token)
