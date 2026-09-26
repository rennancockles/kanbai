"""Background daemon management for `kanbai hub start/stop/status/logs`.

Runs the hub as a detached child process (a re-exec of `python -m kanbai.cli hub ...`),
tracked via a small JSON PID file and a log file, both under the same base directory as
the hub registry (`$KANBAI_HOME` or `~/.kanbai` — see `registry.registry_path`). Stdlib
only, no `kanbai.web.*` import, so this module stays cheap to import and easy to unit test
with injected `launcher`/`kill` callables.
"""

from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import storage
from .errors import HubAlreadyRunningError, HubNotRunningError

#: How long `stop()` waits for a graceful SIGTERM exit before escalating to SIGKILL.
#: uvicorn's own graceful shutdown window (see `web/server.py`'s `_GRACEFUL_TIMEOUT`) is
#: 1s; this leaves buffer for process teardown and the log file being flushed.
_STOP_TIMEOUT = 3.0
_STOP_POLL_INTERVAL = 0.2


def daemon_dir() -> Path:
    """Base directory for the daemon's PID/log files (override with `$KANBAI_HOME`)."""
    base = os.environ.get("KANBAI_HOME")
    return Path(base) if base else Path.home() / ".kanbai"


def pid_path() -> Path:
    """Location of the hub daemon's PID sidecar file."""
    return daemon_dir() / "hub.pid"


def log_path() -> Path:
    """Location of the hub daemon's log file."""
    return daemon_dir() / "hub.log"


@dataclass(frozen=True)
class DaemonInfo:
    """What `hub.pid` records about a running (or once-running) hub daemon."""

    pid: int
    host: str
    port: int


def read_info() -> DaemonInfo | None:
    """Parse `hub.pid`, or `None` if it's missing or corrupt (never raises)."""
    path = pid_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return DaemonInfo(pid=int(data["pid"]), host=str(data["host"]), port=int(data["port"]))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def write_info(info: DaemonInfo) -> None:
    """Persist `info` to `hub.pid`, atomically."""
    payload = {"pid": info.pid, "host": info.host, "port": info.port}
    storage.atomic_write(pid_path(), json.dumps(payload))


def remove_info() -> None:
    """Delete `hub.pid` if present."""
    pid_path().unlink(missing_ok=True)


def is_alive(pid: int) -> bool:
    """Best-effort liveness check for `pid`.

    POSIX: `os.kill(pid, 0)` sends no signal, just checks the process exists.
    `ProcessLookupError` means dead; `PermissionError` means alive but owned by another
    user (treated as alive). Windows has no equivalent `os.kill` semantics, so this falls
    back to `OpenProcess` via ctypes — untested by CI (which is ubuntu-only); any failure
    there is treated as "assume not running" rather than raising.

    This does not fully rule out PID reuse (an unrelated process could have taken over the
    same PID since); `status()` additionally checks the recorded host/port as a sanity
    check, but a definitive check would need `psutil` or similar, which this project
    deliberately avoids for this feature (see card 071's spike).
    """
    if sys.platform == "win32":
        return _is_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _is_alive_windows(pid: int) -> bool:  # pragma: no cover - exercised only on Windows
    try:
        kernel32 = getattr(ctypes, "windll").kernel32  # noqa: B009 - only exists on Windows
        process_query_limited_information = 0x1000
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        return False
    return True


def status() -> DaemonInfo | None:
    """The running daemon's info, or `None` if it's not running.

    Clears a stale `hub.pid` (recorded PID is dead) as a side effect.
    """
    info = read_info()
    if info is None:
        return None
    if not is_alive(info.pid):
        remove_info()
        return None
    return info


def start(
    host: str,
    port: int,
    *,
    launcher: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> DaemonInfo:
    """Start the hub as a detached background process.

    Raises :class:`HubAlreadyRunningError` if a hub daemon is already running. Truncates
    the log file (each `start` gets a clean log, not an ever-growing append) and redirects
    the child's stdout/stderr there.
    """
    existing = status()
    if existing is not None:
        raise HubAlreadyRunningError(existing.pid, existing.host, existing.port)

    log_file = log_path()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_file.open("w", encoding="utf-8")
    try:
        cmd = [
            sys.executable,
            "-m",
            "kanbai.cli",
            "hub",
            "--host",
            host,
            "--port",
            str(port),
            "--no-browser",
        ]
        kwargs: dict[str, object] = {"stdout": log_handle, "stderr": subprocess.STDOUT}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            )
        else:
            kwargs["start_new_session"] = True
        process = launcher(cmd, **kwargs)
    finally:
        log_handle.close()

    info = DaemonInfo(pid=process.pid, host=host, port=port)
    write_info(info)
    return info


def stop(
    *,
    timeout: float = _STOP_TIMEOUT,
    kill: Callable[[int, int], None] = os.kill,
) -> None:
    """Stop the running hub daemon.

    Sends SIGTERM, polls for exit up to `timeout` seconds, then escalates to SIGKILL if
    still alive. Raises :class:`HubNotRunningError` if no hub daemon is running.
    """
    info = status()
    if info is None:
        raise HubNotRunningError()

    kill(info.pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_alive(info.pid):
            remove_info()
            return
        time.sleep(_STOP_POLL_INTERVAL)

    if is_alive(info.pid):
        # SIGKILL doesn't exist on Windows; os.kill(pid, SIGTERM) there already maps to
        # TerminateProcess, so a second SIGTERM is a harmless (if redundant) retry.
        kill(info.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        time.sleep(0.5)
    remove_info()
