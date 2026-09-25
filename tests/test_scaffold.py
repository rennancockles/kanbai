"""Tests for `kanbai init` scaffolding."""

from __future__ import annotations

import json
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


def _notify_hooks(settings: dict) -> list[dict]:
    return settings.get("hooks", {}).get("Notification", [])


def _kanbai_hook_count(settings: dict) -> int:
    return sum(
        1
        for entry in _notify_hooks(settings)
        for hook in entry.get("hooks", [])
        if hook.get("command") == scaffold.KANBAI_NOTIFY_HOOK_COMMAND
    )


def test_init_writes_notification_hook_into_fresh_settings_json(tmp_path: Path) -> None:
    result = scaffold.init_board(tmp_path)

    settings_path = tmp_path / ".claude" / "settings.json"
    assert settings_path.exists()
    settings = json.loads(settings_path.read_text())
    assert _kanbai_hook_count(settings) == 1
    assert any(".claude/settings.json" in created for created in result.created)


def test_init_merges_hook_into_existing_settings_json_preserving_other_keys(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    existing = {
        "env": {"SOME_VAR": "1"},
        "permissions": {"allow": ["Bash(kanbai *)"]},
        "hooks": {
            "Notification": [
                {
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": "curl https://ntfy.sh/my-topic"}],
                }
            ]
        },
    }
    settings_path.write_text(json.dumps(existing))

    scaffold.init_board(tmp_path)

    settings = json.loads(settings_path.read_text())
    assert settings["env"] == {"SOME_VAR": "1"}
    assert settings["permissions"] == {"allow": ["Bash(kanbai *)"]}
    commands = [
        hook["command"] for entry in _notify_hooks(settings) for hook in entry.get("hooks", [])
    ]
    assert "curl https://ntfy.sh/my-topic" in commands
    assert scaffold.KANBAI_NOTIFY_HOOK_COMMAND in commands


def test_init_notification_hook_is_idempotent(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    result = scaffold.init_board(tmp_path)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert _kanbai_hook_count(settings) == 1
    assert any(".claude/settings.json" in skipped for skipped in result.skipped)


def test_init_force_reinitializes_settings_hook_without_duplicating(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    scaffold.init_board(tmp_path, force=True)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert _kanbai_hook_count(settings) == 1


def test_init_degrades_when_settings_json_malformed(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("{not json")

    result = scaffold.init_board(tmp_path)

    assert (tmp_path / ".kanbai" / "config.toml").exists()  # the board itself still works
    assert settings_path.read_text() == "{not json"  # left untouched, not overwritten
    assert any(".claude/settings.json" in path for path, _ in result.failed)
