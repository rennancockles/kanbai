"""Native desktop notifications, backed by the ``desktop-notifier`` library.

Cross-platform (macOS Notification Center, Linux via dbus, Windows toast); this module is
only imported when the optional ``ui`` extra is installed, matching the rest of ``kanbai.web``.
"""

from __future__ import annotations

from desktop_notifier import DEFAULT_SOUND, DesktopNotifierSync

from .. import APP_NAME

# A single notifier per process — the library expects at most one instance.
_notifier = DesktopNotifierSync(app_name=APP_NAME)


def notify_native(title: str, message: str) -> None:
    """Show a native desktop notification with the platform's default sound.

    On macOS this silently does nothing if the running Python executable isn't code-signed
    (true for most Homebrew/pip/uv installs) — Notification Center only allows signed
    executables to post. The `ntfy` channel is unaffected and is a reliable fallback there.
    """
    _notifier.send(title=title, message=message, sound=DEFAULT_SOUND)
