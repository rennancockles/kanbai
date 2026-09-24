"""Push notifications to ntfy.sh (https://ntfy.sh) — no ``ui`` extra required.

Only depends on ``httpx2``, a core dependency, so a plain CLI install (no ``[ui]`` extra) can
still push notifications via this channel.
"""

from __future__ import annotations

import httpx2 as httpx

_NTFY_TIMEOUT = 5.0


def notify_ntfy(topic: str, title: str, message: str) -> None:
    """Push a notification to a public ntfy.sh topic.

    ntfy.sh needs no authentication — the topic name itself acts as the secret. Any failure
    (offline ntfy.sh, DNS, a misconfigured proxy, ...) is swallowed rather than raised, so
    this best-effort channel never breaks the CLI command or web request that triggered it.
    """
    try:
        with httpx.Client(timeout=_NTFY_TIMEOUT) as client:
            client.post(f"https://ntfy.sh/{topic}", content=message, headers={"Title": title})
    except Exception:  # noqa: BLE001 - see docstring: this channel must never propagate
        pass
