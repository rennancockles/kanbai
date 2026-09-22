# KanbAI

A file-based Kanban board that lives in your repo, designed for **Claude Code** and
other AI coding harnesses (and humans too). Installed and invoked as `kanbai`.

KanbAI keeps a `.kanbai/` folder in your project. Each column of the board is a folder and
each task is a single Markdown card. The default columns follow a sprint workflow:

- **`backlog`** — everything to do eventually (future work). New cards land here.
- **`todo`** — the current sprint: what is planned to be worked on now.
- **`doing`** — in progress.
- **`done`** — finished.

Claude reads the `todo` (sprint) column to know **what** to build and in **which order**,
and moves cards across columns as it works — all through a simple CLI:

```bash
kanbai next            # next actionable card in the sprint (todo)
kanbai start 001       # move card 001 to "doing"
kanbai done 001        # move card 001 to "done"
```

A friendly local web UI (`kanbai ui`) lets you watch and manage the board while Claude
works — create cards, drag them between columns, and see the board update live as Claude
moves cards from the CLI. Install the extra and launch it:

```bash
pip install 'kanbai[ui]'   # or: uv add 'kanbai[ui]'
kanbai ui                  # serves the board and opens your browser
```

Use `kanbai ui --poll` in sandboxes/containers where OS file events don't fire.

## Install

```bash
uv add --dev kanbai        # add to your project as a dev dependency
# or
pip install kanbai
```

## Quick start

```bash
kanbai init                          # scaffold .kanbai/ + Claude integration
kanbai add "Build the login screen" --priority high   # lands in the backlog
kanbai move 001 todo                 # plan it into the sprint
kanbai list                          # show the board
```

Then open a Claude Code session and ask it to *"work through the kanbai board"*.

## Commands

| Command | Description |
|---------|-------------|
| `kanbai init` | Scaffold `.kanbai/` and install the Claude Code integration. |
| `kanbai add "title"` | Create a new card in `backlog` (use `-c todo` for the sprint). |
| `kanbai list [column]` | Show the board (or a single column). |
| `kanbai next` | Print the next actionable card in the sprint (`todo`). |
| `kanbai show <id>` | Show full details of a card. |
| `kanbai move <id> <column>` | Move a card to a column. |
| `kanbai start <id>` / `kanbai done <id>` | Shortcuts for moving to `doing` / `done`. |
| `kanbai edit <id>` | Update fields of a card. |
| `kanbai archive <id>` / `kanbai rm <id>` | Archive or delete a card. |
| `kanbai ui` | Serve the board in a local web UI (needs the `ui` extra). |

Add `--json` to read-only commands for machine-readable output.

## License

MIT
