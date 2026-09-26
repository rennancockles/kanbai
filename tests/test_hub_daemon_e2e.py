"""End-to-end test for `kanbai hub start/status/stop` against a real subprocess.

Unlike `tests/test_daemon.py` (which injects fakes for the launcher/kill functions) and
`tests/test_cli.py` (which mocks `kanbai.daemon.*`), this spawns the actual daemon process
and talks to it over a real socket — the one place we verify the whole stack (re-exec,
detach, PID file, uvicorn binding the port, graceful shutdown) together.
"""

from __future__ import annotations

import json
import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from kanbai import daemon, scaffold
from kanbai.cli import app
from typer.testing import CliRunner

runner = CliRunner()

# CI runs on ubuntu-latest only; the daemon's Windows liveness check is best-effort and
# untested there (see kanbai/daemon.py's `_is_alive_windows`), so this real-process test
# is skipped rather than flaking on a platform nobody runs CI on.
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="daemon e2e test is POSIX-only")


def _free_port() -> int:
    """An ephemeral port that's free right now (best-effort — no reservation)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until(
    predicate: Callable[[], bool], *, timeout: float = 5.0, interval: float = 0.1
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_hub_start_status_stop_against_a_real_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KANBAI_HOME", str(tmp_path / "home"))
    board = tmp_path / "proj"
    scaffold.init_board(board)
    assert runner.invoke(app, ["hub", "add", str(board)]).exit_code == 0

    port = _free_port()
    try:
        result = runner.invoke(app, ["hub", "start", "--port", str(port), "--no-browser"])
        assert result.exit_code == 0, result.output

        def is_running() -> bool:
            status = json.loads(runner.invoke(app, ["hub", "status", "--json"]).output)
            return bool(status["running"])

        assert _wait_until(is_running), "hub did not report running within the timeout"

        def is_serving() -> bool:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return True
            except OSError:
                return False

        assert _wait_until(is_serving), "hub did not accept connections within the timeout"

        stop_result = runner.invoke(app, ["hub", "stop"])
        assert stop_result.exit_code == 0, stop_result.output

        def is_stopped() -> bool:
            status = json.loads(runner.invoke(app, ["hub", "status", "--json"]).output)
            return not status["running"]

        assert _wait_until(is_stopped), "hub did not stop within the timeout"
    finally:
        # Belt-and-suspenders: never leak a background process if an assertion above
        # failed partway through.
        info = daemon.status()
        if info is not None:
            daemon.stop()
