"""`kanbai init`: scaffold the board directory and Claude Code integration files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import storage
from .config import render_config
from .models import BoardConfig

RULE_DOC = """# kanbai board workflow

This project uses **kanbai**, a file-based Kanban board stored in `.kanbai/`. Each column
is a folder and each task is one Markdown card. Manage the board through the `kanbai` CLI —
do not edit the card files by hand (frontmatter must stay valid).

Columns follow a sprint workflow:

- `backlog` — everything that needs doing eventually (future work). New cards land here.
- `todo` — the current sprint: what is planned to be worked on now.
- `doing` — in progress.
- `done` — finished.

`kanbai next` reads the **todo** (sprint) column only, so backlog cards are not picked up
until they are planned into the sprint.

When asked to work on the project, do **one card at a time** and stop:

1. Run `kanbai next --json` to get the next actionable sprint task (respects order and
   blocking dependencies). If it returns `null`, the sprint is empty or blocked — tell the
   user (they may need to move cards from `backlog` into `todo`) and stop.
2. Run `kanbai start <id>` to move the card into `doing`.
3. Implement the task. Consult `kanbai show <id> --json` for the full description and
   acceptance criteria.
4. When it is complete and verified, run `kanbai done <id>` to move it into `done`.
5. **Stop and report. Do NOT pick up the next card** — wait for the user to tell you to
   continue (they may want to review or commit first).

Only work several cards back-to-back when the user explicitly asks for it (for example
"work the whole sprint", or the `kanbai-sprint` skill).

Capturing new work:

- `kanbai add "title" -d "description" -p high` puts a card in the **backlog** by default.
- Add straight into the sprint with `kanbai add "title" -c todo`.
- Plan a backlog card into the sprint with `kanbai move <id> todo`.

Other useful commands:

- `kanbai list --json` — the whole board.
- `kanbai move <id> <column>` — move a card to any column.
"""

SKILL_NEXT = """---
name: kanbai-next
description: >-
  Work ONE kanbai task: pick the next actionable card, move it to "doing", implement it,
  move it to "done", then stop. Use when the user asks to pick up the next task or work on
  the board. Does one card and waits — it does not continue to the next on its own.
allowed-tools: Bash(kanbai *)
---

# Work the next kanbai task

Pick up and complete exactly ONE task, using the `kanbai` CLI for all board changes (never
edit `.kanbai/` files directly):

1. Run `kanbai next --json`. If it prints `null`, tell the user the sprint is empty or
   fully blocked and stop.
2. Note the card `id`. Run `kanbai start <id>` to move it into the in-progress column.
3. Read the full task with `kanbai show <id> --json` and implement it, satisfying any
   acceptance criteria in the body.
4. Once the work is complete and verified, run `kanbai done <id>`.
5. **Stop and report which card you finished. Do NOT start the next card** — wait for the
   user to ask for it (they may want to review or commit first).

To work several cards back-to-back, use the `kanbai-sprint` skill instead.
"""

SKILL_SPRINT = """---
name: kanbai-sprint
description: >-
  Work through the ENTIRE kanbai sprint (the todo column) card by card without stopping,
  until it is empty or blocked. Use ONLY when the user explicitly asks to work the whole
  sprint or do all the todo cards at once. For a single task, use kanbai-next instead.
allowed-tools: Bash(kanbai *)
---

# Work the whole kanbai sprint

Loop until the sprint (todo column) is empty, using the `kanbai` CLI for all board changes
(never edit `.kanbai/` files directly):

1. Run `kanbai next --json`. If it prints `null`, the sprint is empty or fully blocked —
   report a summary of everything you did and stop.
2. Run `kanbai start <id>`, implement the task (see `kanbai show <id> --json` for the
   description and acceptance criteria), verify it, then run `kanbai done <id>`.
3. Repeat from step 1 for the next card, reporting each card's outcome as you go.

Note: this changes many files without committing along the way. Prefer `kanbai-next` (one
card at a time) unless the user asked for the whole sprint.
"""

SKILL_STATUS = """---
name: kanbai-status
description: >-
  Show the current kanbai board — the tasks in each column (todo / doing / done). Use when
  the user asks about board status, what is in progress, or what is left to do.
allowed-tools: Bash(kanbai *)
---

# Show the kanbai board

Run `kanbai list --json` and summarize the board for the user: what is in progress, what
is queued (in order), and what is done. Call out any cards that are blocked by unfinished
dependencies.
"""


@dataclass
class ScaffoldResult:
    """What `init_board` produced.

    ``created`` and ``skipped`` (already present) together with ``failed`` — files that
    could not be written and why — let callers report a partial init honestly instead of
    crashing on the first unwritable path.
    """

    kanbai_dir: Path
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def _write(
    path: Path,
    content: str,
    root: Path,
    result: ScaffoldResult,
    force: bool,
    *,
    optional: bool = False,
) -> None:
    """Write a scaffold file, recording the outcome on ``result``.

    Existing files are left untouched (recorded as skipped) unless ``force`` is set, which
    makes ``init`` idempotent: re-running fills in whatever is missing. When ``optional`` is
    set, a filesystem error (e.g. a sandbox denying ``.claude/skills``) is recorded as a
    failure and swallowed so the rest of the scaffold still completes; otherwise it
    propagates, since the board itself could not be created.
    """
    rel = str(path.relative_to(root))
    if path.exists() and not force:
        result.skipped.append(rel)
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        if not optional:
            raise
        result.failed.append((rel, exc.strerror or str(exc)))
        return
    result.created.append(rel)


def init_board(root: Path, *, force: bool = False, name: str | None = None) -> ScaffoldResult:
    """Create the `.kanbai/` board and Claude integration files under ``root``.

    Idempotent: running it again creates only what is missing (pass ``force`` to overwrite).
    The `.claude/` integration files are optional — if they cannot be written they are
    recorded in the result rather than aborting the board setup.
    """
    kanbai_dir = root / storage.KANBAI_DIRNAME
    config = BoardConfig(name=name or root.resolve().name)
    result = ScaffoldResult(kanbai_dir=kanbai_dir)

    # Essential board files. A failure here is fatal (there is no usable board without them).
    _write(kanbai_dir / "config.toml", render_config(config), root, result, force)
    # Column folders (kept in git via .gitkeep so an empty board still has structure).
    for column in (*config.columns, storage.ARCHIVE_DIRNAME):
        _write(kanbai_dir / column / ".gitkeep", "", root, result, force)

    # Claude Code integration (optional — degrade gracefully if unwritable).
    _write(root / ".claude" / "rules" / "kanbai.md", RULE_DOC, root, result, force, optional=True)
    _write(
        root / ".claude" / "skills" / "kanbai-next" / "SKILL.md",
        SKILL_NEXT,
        root,
        result,
        force,
        optional=True,
    )
    _write(
        root / ".claude" / "skills" / "kanbai-sprint" / "SKILL.md",
        SKILL_SPRINT,
        root,
        result,
        force,
        optional=True,
    )
    _write(
        root / ".claude" / "skills" / "kanbai-status" / "SKILL.md",
        SKILL_STATUS,
        root,
        result,
        force,
        optional=True,
    )

    return result
