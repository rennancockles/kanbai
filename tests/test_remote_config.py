"""Tests for the optional [server] section that switches the CLI into hosted (remote) mode."""

from __future__ import annotations

from pathlib import Path

from kanbai import scaffold
from kanbai.config import RemoteConfig, load_remote_config


def test_absent_server_section_returns_none(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)

    assert load_remote_config(tmp_path / ".kanbai") is None


def test_missing_config_file_returns_none(tmp_path: Path) -> None:
    (tmp_path / ".kanbai").mkdir()

    assert load_remote_config(tmp_path / ".kanbai") is None


def test_complete_server_section_is_parsed(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    cfg = tmp_path / ".kanbai" / "config.toml"
    cfg.write_text(
        cfg.read_text()
        + '\n[server]\nurl = "https://kanbai.example.com"\ntoken = "abc123"\nboard_id = "b-1"\n'
    )

    remote = load_remote_config(tmp_path / ".kanbai")

    assert remote == RemoteConfig(url="https://kanbai.example.com", token="abc123", board_id="b-1")


def test_server_section_missing_a_field_returns_none(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    cfg = tmp_path / ".kanbai" / "config.toml"
    cfg.write_text(cfg.read_text() + '\n[server]\nurl = "https://kanbai.example.com"\n')

    assert load_remote_config(tmp_path / ".kanbai") is None


def test_server_section_wrong_type_returns_none(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    cfg = tmp_path / ".kanbai" / "config.toml"
    cfg.write_text(cfg.read_text() + "\nserver = true\n")

    assert load_remote_config(tmp_path / ".kanbai") is None


def test_enabled_defaults_to_true(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    cfg = tmp_path / ".kanbai" / "config.toml"
    cfg.write_text(cfg.read_text() + '\n[server]\nurl = "https://x"\ntoken = "t"\nboard_id = "b"\n')

    remote = load_remote_config(tmp_path / ".kanbai")

    assert remote is not None
    assert remote.enabled is True


def test_enabled_false_is_parsed_and_keeps_the_connection(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    cfg = tmp_path / ".kanbai" / "config.toml"
    cfg.write_text(
        cfg.read_text()
        + '\n[server]\nurl = "https://x"\ntoken = "t"\nboard_id = "b"\nenabled = false\n'
    )

    assert load_remote_config(tmp_path / ".kanbai") == RemoteConfig(
        url="https://x", token="t", board_id="b", enabled=False
    )
