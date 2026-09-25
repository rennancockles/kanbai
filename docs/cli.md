# CLI reference

Every board operation is a `kanbai` subcommand. Run `kanbai --help` for the full list, or
`kanbai <command> --help` for a command's options.

!!! tip "Machine-readable output"
    The read-only commands (`add`, `list`, `next`, `show`, `edit`, `sort`) accept `--json`,
    which prints structured JSON that's easy for an agent — or a script — to parse.

## Overview

| Command | Description |
|---------|-------------|
| [`init`](#init) | Scaffold `.kanbai/` and install the Claude Code integration. |
| [`add`](#add) | Create a card (defaults to the backlog). |
| [`list`](#list) | Show the board, a single column, or the archive. |
| [`next`](#next) | Print the next actionable card in the sprint. |
| [`show`](#show) | Show the full details of a card. |
| [`move`](#move) | Move a card to a column. |
| [`start`](#start) | Move a card to `doing`. |
| [`review`](#review) | Finish a card into `review`. |
| [`done`](#done) | Approve a card into `done`. |
| [`edit`](#edit) | Update fields on a card. |
| [`sort`](#sort) | Sort a column and persist the order. |
| [`archive`](#archive) / [`restore`](#restore) | Archive / restore a card. |
| [`rm`](#rm) | Delete a card permanently. |
| [`close-sprint`](#close-sprint) | Archive done cards, close out the current sprint. |
| [`ui`](#ui) | Serve the local web UI. |
| [`hub`](#hub) | Serve or manage the multi-board hub. |

---

## init

Scaffold a `.kanbai/` board in the current directory and install the
[Claude Code integration](claude-code.md). Safe to re-run — it only creates what's missing.
This also merges a [`Notification` hook](claude-code.md#notified-when-claude-needs-you) into
`.claude/settings.json` (pointed at the hidden `notify-hook` command), without touching any
other keys or hooks already there.

```bash
kanbai init                      # scaffold in the current directory
kanbai init --name my-project    # set the board name in config.toml
kanbai init --force              # overwrite existing files
```

## add

Create a card. New cards land in the **backlog** unless you target another column with `-c`.

```bash
kanbai add "Build the login screen"
kanbai add "Fix the flaky test" -p high -t bug -l ci
kanbai add "Sprint task now" -c todo
kanbai add "Depends on 001" --dep 001
kanbai add "Ship the release" -v v1.2.0
```

| Option | Description |
|--------|-------------|
| `-d`, `--desc` | Card description / body. |
| `-p`, `--priority` | `low`, `medium`, or `high`. |
| `-t`, `--type` | Card [type](concepts.md#card-type) (must be one of the board's configured types). |
| `-v`, `--version` | Release version (free-form, e.g. `v1.2.0`). |
| `-c`, `--column` | Target column (default: `backlog`). |
| `-l`, `--label` | Add a label (repeatable). |
| `--dep` | Id of a blocking card (repeatable). |
| `-a`, `--assignee` | Assignee. |
| `--json` | Emit the created card as JSON. |

## list

Show the whole board, a single column, or the archive.

```bash
kanbai list              # the whole board
kanbai list todo         # only the sprint column
kanbai list archive      # archived cards
kanbai list --type bug   # only cards of a given type, in any column filter above
kanbai list --json       # machine-readable board
```

## next

Print the next actionable card in the **sprint** (`todo`), respecting order and skipping
[blocked](concepts.md#dependencies) cards. Prints nothing actionable (or `null` with
`--json`) when the sprint is empty or fully blocked.

```bash
kanbai next
kanbai next --json
```

## show

Show a card's full details, including its body / acceptance criteria.

```bash
kanbai show 001
kanbai show 001 --json
```

## move

Move a card to any column.

```bash
kanbai move 001 todo         # plan a backlog card into the sprint
kanbai move 001 done
```

## start

Shortcut to move a card into the in-progress column (`doing`).

```bash
kanbai start 001
```

## review

Finish a card: move it to `review` to **await approval**. This is the agent's last step on a
card — it does **not** approve. Sends a [notification](web-ui.md#notifications) that the
card is ready for you (or, on boards with no `review` column, that same notification fires
on `done` instead).

```bash
kanbai review 001
```

## done

Approve a card into `done`. This is the **human** step. Sends the same
[notification](web-ui.md#notifications) as `review` on boards with no `review` column, and
notifies separately if this move leaves the sprint with no actionable card left.

```bash
kanbai done 001
```

## edit

Update fields on a card. Only the options you pass change.

```bash
kanbai edit 001 --title "New title"
kanbai edit 001 -p high -l backend -l urgent
kanbai edit 001 -t feature              # change the card type
kanbai edit 001 --dep 002 --dep 003     # replace the blocking ids
```

| Option | Description |
|--------|-------------|
| `--title` | New title. |
| `-d`, `--desc` | New description / body. |
| `-p`, `--priority` | New priority. |
| `-t`, `--type` | New type (must be one of the board's configured types; pass an empty string to clear it). |
| `-v`, `--version` | New release version (pass an empty string to clear it). |
| `-l`, `--label` | Replace labels. |
| `--dep` | Replace blocking card ids. |
| `-a`, `--assignee` | New assignee. |
| `--order` | New in-column order. |

## sort

Sort a column by a field and **persist** the new order to disk.

```bash
kanbai sort backlog --by priority --desc   # highest priority first
kanbai sort backlog --by title             # alphabetical
kanbai sort backlog --by type              # group by card type
```

| Option | Description |
|--------|-------------|
| `--by` | Sort key: `id`, `priority`, `type`, or `title` (default `id`). |
| `--desc` | Sort descending. |
| `--json` | Emit the sorted column as JSON. |

!!! note "Ascending vs. descending priority"
    Ascending (`↑`) reads `low → medium → high` — consistent with `id` and `title`. Use
    `--desc` to put the **highest** priority first.

## archive

Archive a card — move it off the board into `.kanbai/archive/`, remembering the column it came
from.

```bash
kanbai archive 001
```

## restore

Restore an archived card to the column it was archived from (or the backlog).

```bash
kanbai restore 001
```

## rm

Delete a card **permanently**.

```bash
kanbai rm 001
```

## close-sprint

Close the current sprint: archive all `done` cards, and optionally reset the active columns
(`todo`/`doing`/`review`) back to the backlog. Optionally stamp every archived card with a
release `--version`. Refuses to run (no changes made) while any card is still in `review`.

```bash
kanbai close-sprint --yes                          # archive done cards
kanbai close-sprint --to-backlog --yes             # also reset active columns to the backlog
kanbai close-sprint --version v1.2.0 --yes         # stamp archived cards with a release version
```

## ui

Serve the board in a local [web UI](web-ui.md) (needs the [`ui` extra](installation.md#the-web-ui-extra)).

```bash
kanbai ui                    # serve and open the browser
kanbai ui --port 9000 --no-browser
kanbai ui --reload           # auto-restart on code changes (development)
kanbai ui --poll             # for sandboxes/containers without OS file events
```

## hub

Serve or manage the [multi-board hub](hub.md).

```bash
kanbai hub add ~/projects/api        # register a board (named after its config.toml)
kanbai hub list                      # show registered boards
kanbai hub remove api                # unregister a board
kanbai hub                           # serve all registered boards on one port
```
