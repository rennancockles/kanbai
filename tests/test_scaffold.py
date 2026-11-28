"""Tests for `kanbai init` scaffolding."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from kanbai import scaffold
from kanbai.cli import app
from typer.testing import CliRunner

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib


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
    assert result.updated  # force rewrites what already exists
    assert not result.created


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


# --------------------------------------------------------------------------- update / force


def _customize_board(root: Path) -> str:
    """Give the board a config only a human would have written, and one card; return the config."""
    config_path = root / ".kanbai" / "config.toml"
    config_path.write_text(
        config_path.read_text().replace(f'name = "{root.resolve().name}"', 'name = "Team board"')
        + '\n[wip]\ndoing = 2\n\n[integration]\nsystem = "jira"\n\n'
        '[server]\nurl = "https://host"\ntoken = "secret"\nboard_id = "b1"\n',
        encoding="utf-8",
    )
    (root / ".kanbai" / "todo" / "001-task.md").write_text("---\nid: '001'\n---\n", "utf-8")
    return config_path.read_text()


def test_update_refreshes_the_integration_and_keeps_config_and_cards(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    custom = _customize_board(tmp_path)
    rule = tmp_path / ".claude" / "rules" / "kanbai.md"
    skill = tmp_path / ".claude" / "skills" / "kanbai-next" / "SKILL.md"
    rule.write_text("stale rule")
    skill.write_text("stale skill")

    result = scaffold.init_board(tmp_path, update=True)

    assert rule.read_text() == scaffold.RULE_DOC
    assert skill.read_text() == scaffold.SKILL_NEXT
    assert {".claude/rules/kanbai.md", ".claude/skills/kanbai-next/SKILL.md"} <= set(result.updated)
    assert (tmp_path / ".kanbai" / "config.toml").read_text() == custom
    assert ".kanbai/config.toml" in result.skipped
    assert (tmp_path / ".kanbai" / "todo" / "001-task.md").exists()
    assert not result.created


def test_update_is_a_no_op_when_everything_is_current(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)

    result = scaffold.init_board(tmp_path, update=True)

    assert result.created == []
    assert result.updated == []
    assert not result.failed


def test_update_on_a_fresh_directory_creates_the_board(tmp_path: Path) -> None:
    result = scaffold.init_board(tmp_path, update=True)

    assert (tmp_path / ".kanbai" / "config.toml").exists()
    assert (tmp_path / ".claude" / "rules" / "kanbai.md").exists()
    assert result.created


def test_update_adds_missing_permissions_without_touching_other_settings(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.write_text(
        json.dumps({"env": {"X": "1"}, "permissions": {"allow": ["Bash(ls)"]}, "hooks": {}})
    )

    scaffold.init_board(tmp_path, update=True)

    settings = json.loads(settings_path.read_text())
    assert settings["env"] == {"X": "1"}
    assert "Bash(ls)" in settings["permissions"]["allow"]
    assert set(scaffold.KANBAI_PERMISSIONS) <= set(settings["permissions"]["allow"])
    assert _kanbai_hook_count(settings) == 1


def test_force_resets_the_config_but_never_touches_cards(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    _customize_board(tmp_path)

    result = scaffold.init_board(tmp_path, force=True)

    config = (tmp_path / ".kanbai" / "config.toml").read_text()
    assert 'name = "Team board"' not in config
    parsed = tomllib.loads(config)
    assert "server" not in parsed  # the hosted connection is reset too
    assert "integration" not in parsed  # only the commented example is left
    assert ".kanbai/config.toml" in result.updated
    assert (tmp_path / ".kanbai" / "todo" / "001-task.md").exists()


def test_cli_update_keeps_the_config_and_refreshes_the_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, ["init", "--name", "Demo"]).exit_code == 0
    custom = _customize_board(tmp_path)
    (tmp_path / ".claude" / "rules" / "kanbai.md").write_text("stale")

    result = runner.invoke(app, ["init", "--update"])

    assert result.exit_code == 0, result.output
    assert "updated" in result.output
    assert (tmp_path / ".claude" / "rules" / "kanbai.md").read_text() == scaffold.RULE_DOC
    assert (tmp_path / ".kanbai" / "config.toml").read_text() == custom


@pytest.mark.parametrize(
    "args", [["init", "--force", "--update"], ["init", "--update", "--name", "X"]]
)
def test_cli_rejects_conflicting_init_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, args)

    assert result.exit_code > 0
    assert not (tmp_path / ".kanbai").exists()


def test_next_steps_are_shown_only_for_a_brand_new_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    first = runner.invoke(app, ["init"]).output
    assert "Next steps" in first
    assert "Create your first card" in first
    assert "Allow the CLI" not in first  # init already adds the permission to settings.json

    for args in (["init"], ["init", "--update"], ["init", "--force"]):
        output = runner.invoke(app, args).output
        assert "Next steps" not in output, args


def test_next_steps_ask_for_the_permission_when_settings_json_could_not_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude").write_text("not a directory")  # blocks every .claude/** write

    output = CliRunner().invoke(app, ["init"]).output

    assert "Next steps" in output
    assert "1. Allow the CLI for Claude" in output
    assert "2. Create your first card" in output


# --------------------------------------------------------------------------- tickets rule


def test_init_installs_the_tickets_rule(tmp_path: Path) -> None:
    result = scaffold.init_board(tmp_path)

    rule = tmp_path / ".claude" / "rules" / "kanbai-tickets.md"
    assert rule.read_text() == scaffold.RULE_TICKETS
    assert ".claude/rules/kanbai-tickets.md" in result.created
    assert "kanbai-tickets.md" in scaffold.RULE_DOC  # the main rule points to it


def test_tickets_rule_describes_the_one_ticket_many_cards_flow() -> None:
    rule = scaffold.RULE_TICKETS
    assert "kanbai list --ticket" in rule
    assert "kanbai list archive --ticket" in rule
    assert "several cards" in rule  # one ticket can be linked to several cards
    for stage in ("enters `doing`", "enters `review`", "enters `done`"):
        assert stage in rule
    assert "every" in rule and "no other linked card has started" in rule
    assert "a card without a `ticket`" in rule  # cards without a ticket are unaffected
    flat = " ".join(rule.split())
    assert 'give every card the same ticket** (`kanbai add "..." --ticket <KEY>`)' in flat


def test_tickets_rule_is_driven_by_the_board_config_and_names_no_skill() -> None:
    rule = scaffold.RULE_TICKETS
    block = re.search(r"```toml\n(.*?)```", rule, re.S)
    assert block is not None
    example = tomllib.loads(block.group(1))["integration"]  # the documented example is valid TOML
    assert set(example) >= {"tool", "skill", "stages"}
    assert set(example["stages"]) <= {"start", "review", "done"}

    assert "`[integration]` section of `.kanbai/config.toml`" in rule
    flat = " ".join(rule.split())  # the rule wraps lines; compare the text, not the line breaks
    assert "does nothing to the ticket" in flat  # a stage that is not listed is ignored
    assert "map" not in example  # kanbai does not map statuses: the skill does
    assert "that is the skill's job" in flat  # the tracker's status names are not kanbai's concern
    assert "enabled" in rule  # the integration can be paused
    # the skill name only appears inside the documented example, never as an instruction
    assert rule.count(example["skill"]) == 1
    assert "jira-workflow" not in scaffold.RULE_DOC


def test_rerun_keeps_a_customized_tickets_rule_but_update_refreshes_it(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    rule = tmp_path / ".claude" / "rules" / "kanbai-tickets.md"
    rule.write_text("my own version")

    scaffold.init_board(tmp_path)
    assert rule.read_text() == "my own version"  # a plain init never overwrites

    result = scaffold.init_board(tmp_path, update=True)
    assert rule.read_text() == scaffold.RULE_TICKETS
    assert ".claude/rules/kanbai-tickets.md" in result.updated


def test_update_installs_the_tickets_rule_on_a_board_created_before_it_existed(
    tmp_path: Path,
) -> None:
    scaffold.init_board(tmp_path)
    (tmp_path / ".claude" / "rules" / "kanbai-tickets.md").unlink()

    result = scaffold.init_board(tmp_path, update=True)

    assert (tmp_path / ".claude" / "rules" / "kanbai-tickets.md").exists()
    assert ".claude/rules/kanbai-tickets.md" in result.created
