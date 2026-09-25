"""Push notifications to ntfy.sh (https://ntfy.sh) — no ``ui`` extra required.

Only depends on ``httpx2``, a core dependency, so a plain CLI install (no ``[ui]`` extra) can
still push notifications via this channel.
"""

from __future__ import annotations

import sys
import threading

import httpx2 as httpx

# Short: a short-lived CLI command blocks on this call, so a slow/unresponsive network should
# give up quickly rather than hang the command for long.
_NTFY_TIMEOUT = 3.0


def notify_ntfy(topic: str, title: str, message: str) -> None:
    """Push a notification to a public ntfy.sh topic, synchronously.

    ntfy.sh needs no authentication — the topic name itself acts as the secret. Any failure
    (offline ntfy.sh, DNS, a misconfigured proxy, ...) is swallowed rather than raised, so
    this best-effort channel never breaks the caller — but it's printed to stderr rather than
    fully silenced, so a persistent misconfiguration (e.g. a SOCKS proxy without ``socksio``
    installed) is still noticeable. Use :func:`notify_ntfy_background` for a caller (the web
    UI) that must never block on this at all, even for the few seconds above.
    """
    try:
        with httpx.Client(timeout=_NTFY_TIMEOUT) as client:
            client.post(f"https://ntfy.sh/{topic}", content=message, headers={"Title": title})
    except Exception as exc:  # noqa: BLE001 - see docstring: this channel must never propagate
        print(f"kanbai: ntfy notification failed: {exc}", file=sys.stderr)


def notify_ntfy_background(topic: str, title: str, message: str) -> None:
    """Push a notification to a public ntfy.sh topic without waiting for the result.

    Fire-and-forget, for a long-lived caller (the web UI) that keeps running regardless — a
    thread here always gets to finish on its own time, unlike in a short-lived CLI command
    that would otherwise kill it mid-request on exit. See :func:`notify_ntfy` for the
    synchronous version used there instead.
    """
    threading.Thread(target=notify_ntfy, args=(topic, title, message), daemon=True).start()
