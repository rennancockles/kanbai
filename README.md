<p align="center">
  <img src="https://raw.githubusercontent.com/rennancockles/kanbai/main/assets/logo.png" alt="KanbAI" width="650">
</p>

# KanbAI

<p align="center">
  <a href="https://pypi.org/project/kanbai/"><img src="https://img.shields.io/pypi/v/kanbai?logo=pypi&logoColor=green&color=5865f9" alt="PyPI version"></a>
  <a href="https://pypi.org/project/kanbai/"><img src="https://img.shields.io/pypi/pyversions/kanbai" alt="Python versions"></a>
  <a href="https://github.com/rennancockles/kanbai/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/rennancockles/kanbai/ci.yml?branch=main&label=CI" alt="CI"></a>
  <a href="https://github.com/rennancockles/kanbai/blob/main/LICENSE"><img src="https://img.shields.io/github/license/rennancockles/kanbai" alt="License"></a>
  <a href="https://www.r3ck.com.br/kanbai/"><img src="https://img.shields.io/badge/docs-mkdocs--material-526cfe?logo=materialformkdocs&logoColor=white" alt="Documentation"></a>
</p>

A file-based Kanban board that lives in your repo, built for **Claude Code** and other AI
coding harnesses (and humans too). The board is plain Markdown files under `.kanbai/`,
driven by a simple `kanbai` CLI and a local web UI. Installed and invoked as `kanbai`.

📖 **Full documentation: [www.r3ck.com.br/kanbai](https://www.r3ck.com.br/kanbai/)**

<p align="center">
  <img src="https://raw.githubusercontent.com/rennancockles/kanbai/main/assets/board.png" alt="KanbAI web UI" width="840">
</p>

## Why

- **The board lives in your repo.** One Markdown card per task, one folder per column —
  git-friendly, diffable, no external service, no database.
- **Claude drives it.** `kanbai init` installs a rule + skills so Claude picks the next
  task, implements it, and moves it across the board while you review.
- **You stay in control.** Finished work waits in `review` for your approval, and a
  friendly local web UI lets you watch and manage everything live.

## How it works

`kanbai init` creates a `.kanbai/` folder — one directory per column, one Markdown card
per task:

```
.kanbai/
├── config.toml
├── backlog/
│   └── 004-add-oauth-login.md
├── todo/
├── doing/
├── review/
├── done/
└── archive/
```

Each card is Markdown with YAML frontmatter (managed by the CLI — don't edit by hand):

```markdown
---
id: "004"
title: Add OAuth login
status: backlog
priority: high
order: 1
labels: [auth, backend]
deps: []
---

## Description
Support "Sign in with Google".

## Acceptance criteria
- [ ] OAuth flow works end to end
```

### The sprint workflow

Cards flow through five columns:

| Column | Meaning |
|--------|---------|
| `backlog` | Everything to do eventually. New cards land here. |
| `todo` | The current sprint — what's planned for now. |
| `doing` | In progress. |
| `review` | Finished, awaiting your approval. |
| `done` | Approved and complete. |

`kanbai next` only reads the **sprint** (`todo`), respecting card order and blocking
dependencies — so the backlog stays out of the way until you plan work into the sprint.
When work is finished it goes to `review`; **you** approve it into `done`.

## Install

```bash
uv add --dev kanbai          # add to your project as a dev dependency
# or
pip install kanbai

# for the web UI, install the extra:
uv add --dev 'kanbai[ui]'    # or: pip install 'kanbai[ui]'
```

## Quick start

```bash
kanbai init                              # scaffold .kanbai/ + Claude integration
kanbai add "Build the login screen" -p high   # lands in the backlog
kanbai move 001 todo                     # plan it into the sprint
kanbai list                              # show the board
```

Then open a Claude Code session and ask it to *"work through the KanbAI board"*.

## Working with Claude Code

`kanbai init` installs the integration into `.claude/`:

- **`.claude/rules/kanbai.md`** — teaches Claude the board convention, loaded every session.
- **Skills** — `kanbai-next` (work one card and stop), `kanbai-sprint` (work the whole
  sprint), and `kanbai-status` (summarize the board).

Claude then works one card at a time:

1. `kanbai next --json` — pick the next actionable sprint task.
2. `kanbai start <id>` — move it to `doing`.
3. Implement it (reading `kanbai show <id> --json` for the details).
4. `kanbai review <id>` — send it to `review` and **stop**.
5. You review the work and approve it with `kanbai done <id>`.

Allow the CLI without prompts by adding `Bash(kanbai *)` to your `.claude/settings.json`.

Using another assistant (Cursor, Windsurf, Aider, Copilot, …)? The board is harness-agnostic
— see [docs/other-harnesses.md](https://github.com/rennancockles/kanbai/blob/main/docs/other-harnesses.md).

## Web UI

```bash
kanbai ui                    # serves the board and opens your browser
kanbai ui --reload           # auto-restart on code changes (development)
kanbai ui --poll             # for sandboxes/containers without OS file events
```

The UI (FastAPI + HTMX, assets vendored so it works offline) lets you:

- View the board and **create, edit, move, archive, or delete** cards.
- **Drag-and-drop** between columns (with persisted reordering) or move from a card's modal.
- **Plan a sprint** (move several backlog cards to `todo` at once) and **start a new sprint**
  (archive done cards, optionally reset the active columns).
- **Search** cards and **filter by label**.
- Browse and **restore** archived cards.
- See **WIP-limit** and **blocked-by-dependency** indicators, and **live updates** as Claude
  moves cards from the CLI (via Server-Sent Events).

## Multi-board hub

Working across several projects? The **hub** serves all of them from one place, on a single
port, with a board switcher — no more one server per project.

Since the hub spans projects, install KanbAI **globally** (or run it with `uvx`):

```bash
pipx install 'kanbai[ui]'
# or run without installing:
uvx --from 'kanbai[ui]' kanbai hub
```

Register your boards (each must already have a `.kanbai/` — run `kanbai init` there), then
start the hub:

```bash
kanbai hub add ~/projects/api        # register a board (name defaults to the folder)
kanbai hub add ~/projects/web --name web
kanbai hub list                      # show registered boards
kanbai hub                           # serve them all; opens a landing to pick a board
```

Each board is served at `/b/<name>/` and the registry lives in `~/.kanbai/boards.toml`.
Remove one with `kanbai hub remove <name>`.

## Configuration

`.kanbai/config.toml` is created by `init` and can be edited:

```toml
[board]
name = "my-project"
columns = ["backlog", "todo", "doing", "review", "done"]

[defaults]
priority = "medium"

# Optional work-in-progress limits per column (the CLI and UI warn when exceeded).
[wip]
doing = 3
```

## Commands

| Command | Description |
|---------|-------------|
| `kanbai init` | Scaffold `.kanbai/` and install the Claude Code integration. |
| `kanbai add "title"` | Create a card in `backlog` (use `-c todo` for the sprint). |
| `kanbai list [column]` | Show the board, a single column, or the `archive`. |
| `kanbai next` | Print the next actionable card in the sprint (`todo`). |
| `kanbai show <id>` | Show full details of a card. |
| `kanbai move <id> <column>` | Move a card to a column. |
| `kanbai start <id>` | Move a card to `doing`. |
| `kanbai review <id>` / `kanbai done <id>` | Send a card to `review` / approve it to `done`. |
| `kanbai edit <id>` | Update fields of a card. |
| `kanbai archive <id>` / `kanbai restore <id>` | Archive a card / restore it from the archive. |
| `kanbai rm <id>` | Delete a card permanently. |
| `kanbai close-sprint` | Archive done cards (optionally reset active columns to the backlog). |
| `kanbai ui` | Serve the board in a local web UI (needs the `ui` extra). |
| `kanbai hub add/list/remove` | Manage the multi-board hub registry. |
| `kanbai hub` | Serve all registered boards on one port (needs the `ui` extra). |

Add `--json` to read-only commands for machine-readable output.

## Changelog

See [CHANGELOG.md](https://github.com/rennancockles/kanbai/blob/main/CHANGELOG.md).

## License

MIT
