"""Tests for the hub daemon (`kanbai hub start/stop/status/logs`)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from kanbai import daemon
from kanbai.errors import HubAlreadyRunningError, HubNotRunningError


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the daemon at a temp dir so tests never touch the real ~/.kanbai."""
    monkeypatch.setenv("KANBAI_HOME", str(tmp_path / "home"))


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid


class _FakeLauncher:
    """A launcher stub that records the command/kwargs it was called with."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, cmd: list[str], **kwargs: object) -> _FakeProcess:
        self.calls.append((cmd, kwargs))
        return _FakeProcess(self.pid)


def _fake_launcher(pid: int) -> Any:  # noqa: ANN401 - test double stands in for a callable
    return _FakeLauncher(pid)


def test_daemon_dir_respects_kanbai_home(tmp_path: Path) -> None:
    assert daemon.daemon_dir() == tmp_path / "home"
    assert daemon.pid_path() == tmp_path / "home" / "hub.pid"
    assert daemon.log_path() == tmp_path / "home" / "hub.log"


def test_status_is_none_when_never_started() -> None:
    assert daemon.status() is None


def test_start_writes_pid_sidecar_and_returns_info() -> None:
    launcher = _fake_launcher(pid=4242)
    info = daemon.start("127.0.0.1", 9000, launcher=launcher)
    assert info.pid == 4242
    assert info.host == "127.0.0.1"
    assert info.port == 9000
    assert daemon.pid_path().exists()


def test_start_passes_expected_command(monkeypatch: pytest.MonkeyPatch) -> None:
    launcher = _fake_launcher(pid=1)
    daemon.start("0.0.0.0", 1234, launcher=launcher)
    cmd, kwargs = launcher.calls[0]
    assert cmd[1:] == [
        "-m",
        "kanbai.cli",
        "hub",
        "--host",
        "0.0.0.0",
        "--port",
        "1234",
        "--no-browser",
    ]
    assert "stdout" in kwargs
    assert kwargs["stderr"] == subprocess.STDOUT


def test_start_truncates_a_stale_log_file() -> None:
    daemon.log_path().parent.mkdir(parents=True, exist_ok=True)
    daemon.log_path().write_text("stale output from a previous run\n" * 100)
    daemon.start("127.0.0.1", 9000, launcher=_fake_launcher(pid=1))
    assert daemon.log_path().read_text() == ""


def test_start_raises_when_already_running(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon.start("127.0.0.1", 9000, launcher=_fake_launcher(pid=1))
    monkeypatch.setattr(daemon, "is_alive", lambda pid: True)
    with pytest.raises(HubAlreadyRunningError):
        daemon.start("127.0.0.1", 9000, launcher=_fake_launcher(pid=2))


def test_status_clears_a_stale_pid_file(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon.start("127.0.0.1", 9000, launcher=_fake_launcher(pid=1))
    monkeypatch.setattr(daemon, "is_alive", lambda pid: False)
    assert daemon.status() is None
    assert not daemon.pid_path().exists()


def test_status_reports_running_when_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon.start("127.0.0.1", 9000, launcher=_fake_launcher(pid=1))
    monkeypatch.setattr(daemon, "is_alive", lambda pid: True)
    info = daemon.status()
    assert info is not None
    assert info.pid == 1


def test_stop_raises_when_not_running() -> None:
    with pytest.raises(HubNotRunningError):
        daemon.stop()


def test_stop_sends_sigterm_and_removes_pid_file(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon.start("127.0.0.1", 9000, launcher=_fake_launcher(pid=777))
    alive = [True]  # alive until kill() is called, simulating a graceful SIGTERM exit
    monkeypatch.setattr(daemon, "is_alive", lambda pid: alive[0])
    kill_calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))
        alive[0] = False

    daemon.stop(kill=fake_kill)
    assert kill_calls == [(777, 15)]  # SIGTERM
    monkeypatch.setattr(daemon, "is_alive", lambda pid: False)
    assert daemon.status() is None


def test_stop_escalates_to_sigkill_when_still_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon.start("127.0.0.1", 9000, launcher=_fake_launcher(pid=777))
    monkeypatch.setattr(daemon, "is_alive", lambda pid: True)
    kill_calls: list[tuple[int, int]] = []
    daemon.stop(timeout=0.3, kill=lambda pid, sig: kill_calls.append((pid, sig)))
    assert len(kill_calls) == 2
    assert kill_calls[0][0] == 777
    assert kill_calls[1][0] == 777
    assert not daemon.pid_path().exists()
