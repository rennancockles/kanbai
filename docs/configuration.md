# Configuration

Every board has a `.kanbai/config.toml`, created by [`kanbai init`](cli.md#init). It's plain
TOML you can edit by hand.

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

## `[board]`

| Key | Description |
|-----|-------------|
| `name` | The board's display name (shown in the CLI and the web UI). |
| `columns` | The ordered list of columns. The folders under `.kanbai/` follow this list. |

### Column roles

KanbAI resolves a few **roles** from the column list, by name when possible and by position
otherwise, so the workflow keeps working even if you rename columns:

| Role | Default column | Used by |
|------|----------------|---------|
| Capture (where new cards land) | `backlog` | [`add`](cli.md#add) |
| Sprint (what `next` reads) | `todo` | [`next`](cli.md#next) |
| In progress | `doing` | [`start`](cli.md#start) |
| Review | `review` | [`review`](cli.md#review) |
| Done | `done` | [`done`](cli.md#done), [`new-sprint`](cli.md#new-sprint) |

!!! tip
    You can add extra columns (e.g. a `blocked` or `qa` stage). Keep the first column as the
    capture/backlog column and the last as the done column for the roles to resolve cleanly.

## `[defaults]`

| Key | Description |
|-----|-------------|
| `priority` | Default priority for new cards when `--priority` isn't given (`low`/`medium`/`high`). |

## `[wip]`

Set a work-in-progress limit per column. When a column exceeds its limit, the CLI and web UI
show a warning — they **never block** the move, so limits are a nudge, not a gate.

```toml
[wip]
doing = 3
review = 5
```
