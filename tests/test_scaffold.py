"""Tests for `kanbai init` scaffolding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from kanbai import scaffold
from kanbai.cli import app
from typer.testing import CliRunner


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
        "permissions": {"allow": ["SomeTool(*)"]},
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
    # Existing unrelated permission is preserved; kanbai ones are appended.
    allow = settings["permissions"]["allow"]
    assert "SomeTool(*)" in allow
    for perm in scaffold.KANBAI_PERMISSIONS:
        assert perm in allow
    commands = [
        hook["command"] for entry in _notify_hooks(settings) for hook in entry.get("hooks", [])
    ]
    assert "curl https://ntfy.sh/my-topic" in commands
    assert scaffold.KANBAI_NOTIFY_HOOK_COMMAND in commands


def test_init_writes_permissions_into_fresh_settings_json(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    allow = settings.get("permissions", {}).get("allow", [])
    for perm in scaffold.KANBAI_PERMISSIONS:
        assert perm in allow


def test_init_permissions_are_idempotent(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    scaffold.init_board(tmp_path)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    allow = settings.get("permissions", {}).get("allow", [])
    for perm in scaffold.KANBAI_PERMISSIONS:
        assert allow.count(perm) == 1


def test_init_permissions_added_when_allow_list_already_exists(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"permissions": {"allow": ["Bash(kanbai *)"]}}))

    scaffold.init_board(tmp_path)

    settings = json.loads(settings_path.read_text())
    allow = settings["permissions"]["allow"]
    assert allow.count("Bash(kanbai *)") == 1
    assert "Skill(kanbai-*)" in allow


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


def _git_repo(path: Path) -> Path:
    (path / ".git").mkdir(parents=True)
    return path


def test_init_does_not_create_gitignore_outside_a_git_repo(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)

    assert not (tmp_path / ".gitignore").exists()


def test_init_creates_gitignore_with_the_board_entry_in_a_git_repo(tmp_path: Path) -> None:
    _git_repo(tmp_path)

    result = scaffold.init_board(tmp_path)

    assert (tmp_path / ".gitignore").read_text() == "# KanbAI\n.kanbai/\n"
    assert any(line.startswith(".gitignore") for line in result.created)


def test_init_appends_to_an_existing_gitignore_without_touching_it(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("node_modules/\n*.pyc")  # no trailing newline

    scaffold.init_board(tmp_path)

    assert (tmp_path / ".gitignore").read_text() == "node_modules/\n*.pyc\n\n# KanbAI\n.kanbai/\n"


@pytest.mark.parametrize(
    "entry",
    [
        ".kanbai",
        ".kanbai/",
        "/.kanbai",
        "/.kanbai/",
        ".kanbai/*",
        ".kanbai/**",
        "**/.kanbai",
        "**/.kanbai/",
        "  .kanbai/  ",
    ],
)
def test_init_does_not_duplicate_an_entry_already_in_gitignore(tmp_path: Path, entry: str) -> None:
    _git_repo(tmp_path)
    original = f"dist/\n{entry}\n"
    (tmp_path / ".gitignore").write_text(original)

    result = scaffold.init_board(tmp_path)

    assert (tmp_path / ".gitignore").read_text() == original
    assert ".gitignore" in result.skipped


def test_init_repeated_keeps_a_single_entry(tmp_path: Path) -> None:
    _git_repo(tmp_path)

    scaffold.init_board(tmp_path)
    scaffold.init_board(tmp_path)
    scaffold.init_board(tmp_path, force=True)

    assert (tmp_path / ".gitignore").read_text().splitlines() == ["# KanbAI", ".kanbai/"]


def test_init_in_a_subdirectory_of_a_git_repo_writes_the_gitignore_there(tmp_path: Path) -> None:
    project = _git_repo(tmp_path) / "packages" / "app"
    project.mkdir(parents=True)

    scaffold.init_board(project)

    assert (project / ".gitignore").read_text() == "# KanbAI\n.kanbai/\n"


def test_init_recognises_a_git_worktree_where_dot_git_is_a_file(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")

    scaffold.init_board(tmp_path)

    assert (tmp_path / ".gitignore").read_text() == "# KanbAI\n.kanbai/\n"


def test_init_can_opt_out_of_touching_gitignore(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("dist/\n")

    scaffold.init_board(tmp_path, gitignore=False)

    assert (tmp_path / ".gitignore").read_text() == "dist/\n"


def test_init_reports_an_unwritable_gitignore_without_aborting(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    (tmp_path / ".gitignore").mkdir()  # a directory where the file should be

    result = scaffold.init_board(tmp_path)

    assert (tmp_path / ".kanbai" / "config.toml").exists()
    assert [path for path, _reason in result.failed] == [".gitignore"]


def test_cli_init_adds_the_gitignore_entry_unless_told_not_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_dir = _git_repo(tmp_path / "default")
    optout_dir = _git_repo(tmp_path / "optout")

    monkeypatch.chdir(default_dir)
    assert CliRunner().invoke(app, ["init"]).exit_code == 0
    monkeypatch.chdir(optout_dir)
    assert CliRunner().invoke(app, ["init", "--no-gitignore"]).exit_code == 0

    assert (default_dir / ".gitignore").read_text() == "# KanbAI\n.kanbai/\n"
    assert not (optout_dir / ".gitignore").exists()


def test_init_puts_exactly_one_blank_line_before_the_block(tmp_path: Path) -> None:
    cases = {
        "no_newline": ("dist/", "dist/\n\n# KanbAI\n.kanbai/\n"),
        "newline": ("dist/\n", "dist/\n\n# KanbAI\n.kanbai/\n"),
        "blank_line": ("dist/\n\n", "dist/\n\n# KanbAI\n.kanbai/\n"),
        "empty": ("", "# KanbAI\n.kanbai/\n"),
    }
    for name, (before, after) in cases.items():
        project = _git_repo(tmp_path / name)
        (project / ".gitignore").write_text(before)

        scaffold.init_board(project)

        assert (project / ".gitignore").read_text() == after, name


def test_init_ignores_a_similarly_named_entry_and_still_adds_the_board(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text(".kanbai-backup/\n")

    scaffold.init_board(tmp_path)

    assert ".kanbai/" in (tmp_path / ".gitignore").read_text().splitlines()
