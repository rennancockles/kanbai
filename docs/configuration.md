# Configuration

Every board has a `.kanbai/config.toml`, created by [`kanbai init`](cli.md#init). It's plain
TOML you can edit by hand.

```toml
[board]
name = "my-project"
columns = ["backlog", "todo", "doing", "review", "done"]

[defaults]
priority = "medium"

[types]
available = ["feature", "bug", "refactor", "chore", "docs", "spike"]

# Optional hex color overrides for the UI badge, per type (default is a
# built-in color for the types above, or gray for anything else).
# [types.colors]
# bug = "#ff0000"

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
| Done | `done` | [`done`](cli.md#done), [`close-sprint`](cli.md#close-sprint) |

!!! tip
    You can add extra columns (e.g. a `blocked` or `qa` stage). Keep the first column as the
    capture/backlog column and the last as the done column for the roles to resolve cleanly.

## `[defaults]`

| Key | Description |
|-----|-------------|
| `priority` | Default priority for new cards when `--priority` isn't given (`low`/`medium`/`high`). |

## `[types]`

Configures the valid values for a card's [`type`](concepts.md#card-type).

| Key | Description |
|-----|-------------|
| `available` | The list of valid types. Defaults to `feature`, `bug`, `refactor`, `chore`, `docs`, `spike`. |

### `[types.colors]`

Optional per-type hex color (`#rrggbb`) for the badge shown in the web UI — overrides the
built-in color for a default type, or gives a custom type its own color instead of the neutral
gray fallback. Invalid values are silently ignored.

```toml
[types.colors]
bug = "#ff0000"
spec = "#00ffaa"
```

## `[wip]`

Set a work-in-progress limit per column. When a column exceeds its limit, the CLI and web UI
show a warning — they **never block** the move, so limits are a nudge, not a gate.

```toml
[wip]
doing = 3
review = 5
```

## `[notifications]`

Controls the [native desktop and ntfy notifications](web-ui.md#notifications) fired whenever
a card reaches `review`/`done`, from any command (`kanbai review`/`done`/`move`, the CLI in
general, or the web UI) — no background process required.

| Key | Description |
|-----|-------------|
| `native` | Native desktop notifications (macOS/Linux/Windows). Default `true`. |
| `ntfy_topic` | [ntfy.sh](https://ntfy.sh) topic to push to. Default unset (channel off). |

```toml
[notifications]
native = false
ntfy_topic = "my-kanbai-topic"
```

!!! warning "The ntfy topic is your only secret"
    ntfy.sh is a public server with no signup or authentication — anyone who knows (or
    guesses) your topic name receives your notifications. Pick something unguessable, not
    e.g. `my-project`.
