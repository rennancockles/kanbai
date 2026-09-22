"""Tests for `kanbai init` scaffolding."""

from __future__ import annotations

from pathlib import Path

from kanbai import scaffold


def test_init_creates_board_and_integration(tmp_path: Path) -> None:
    result = scaffold.init_board(tmp_path, name="Demo")

    assert (tmp_path / ".kanbai" / "config.toml").exists()
    assert 'name = "Demo"' in (tmp_path / ".kanbai" / "config.toml").read_text()
    for column in ("backlog", "todo", "doing", "review", "done", "archive"):
        assert (tmp_path / ".kanbai" / column / ".gitkeep").exists()
    assert (tmp_path / ".claude" / "rules" / "kanbai.md").exists()
    assert (tmp_path / ".claude" / "skills" / "kanbai-next" / "SKILL.md").exists()
    assert (tmp_path / ".claude" / "skills" / "kanbai-sprint" / "SKILL.md").exists()
    assert (tmp_path / ".claude" / "skills" / "kanbai-status" / "SKILL.md").exists()
    assert result.created  # reported what it made
    assert not result.failed


def test_workflow_docs_tell_agent_to_ask_when_unclear() -> None:
    assert "unclear" in scaffold.RULE_DOC.lower()
    assert "ask the user" in scaffold.RULE_DOC.lower()
    assert "unclear" in scaffold.SKILL_NEXT.lower()


def test_init_defaults_name_to_directory(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    config = (tmp_path / ".kanbai" / "config.toml").read_text()
    assert f'name = "{tmp_path.resolve().name}"' in config


def test_init_is_idempotent(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    result = scaffold.init_board(tmp_path)  # must not raise
    assert result.created == []  # nothing new was written
    assert result.skipped  # everything was already present
    assert (tmp_path / ".kanbai" / "config.toml").exists()


def test_init_force_reinitializes(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    result = scaffold.init_board(tmp_path, force=True, name="Renamed")
    assert 'name = "Renamed"' in (tmp_path / ".kanbai" / "config.toml").read_text()
    assert result.created  # force overwrites, so files are (re)created


def test_init_degrades_when_integration_unwritable(tmp_path: Path) -> None:
    # A regular file where the `.claude` directory should go blocks all `.claude/**` writes.
    (tmp_path / ".claude").write_text("not a directory")

    result = scaffold.init_board(tmp_path)

    # The board itself is still fully created...
    assert (tmp_path / ".kanbai" / "config.toml").exists()
    assert (tmp_path / ".kanbai" / "todo" / ".gitkeep").exists()
    # ...and the integration failures are recorded, not raised.
    assert result.failed
    assert all(".claude" in path for path, _ in result.failed)


def test_init_completes_missing_pieces_on_rerun(tmp_path: Path) -> None:
    (tmp_path / ".claude").write_text("blocker")  # integration writes will fail
    scaffold.init_board(tmp_path)

    (tmp_path / ".claude").unlink()  # remove the blocker
    result = scaffold.init_board(tmp_path)  # re-run fills in what was missing

    assert (tmp_path / ".claude" / "rules" / "kanbai.md").exists()
    assert any("kanbai.md" in created for created in result.created)
