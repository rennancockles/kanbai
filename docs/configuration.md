# Configuration

Every board has a `.kanbai/config.toml`, created by [`kanbai init`](cli.md#init). It's plain
TOML you can edit by hand.

```toml
[board]
name = "my-project"
columns = ["backlog", "todo", "doing", "review", "done"]
# bypass_review = true
# category = "Work"

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
| `bypass_review` | Skip the review stage. Default `false` — see [below](#skipping-review). |
| `category` | Optional grouping label: the [hub](hub.md#categories-and-card-counts) lists boards that share a category together. Default empty (no grouping). |

### Skipping review

With `bypass_review = true`, [`kanbai review`](cli.md#review) (and the Claude workflow
skills) finalize a card straight to `done` instead of `review` — there's no approval step.
The `review` column, if still present in `columns`, is treated as absent everywhere a
column role resolves and disappears from the web UI, without needing to remove it from
`columns`.

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

For a project connected to a [hosted board](hosted.md) these settings are always read from the
project's local `config.toml` (even though `push --settings` can copy them to the server), and the
notification is sent by the machine running the CLI.

!!! warning "The ntfy topic is your only secret"
    ntfy.sh is a public server with no signup or authentication — anyone who knows (or
    guesses) your topic name receives your notifications. Pick something unguessable, not
    e.g. `my-project`.

## `[integration]`

Keep an external ticket (Jira, for example) in step with the cards linked to it — a card's
[`ticket`](concepts.md#cards). It is **off** unless this section exists, and it only affects cards that
have a `ticket`.

```toml
[integration]
tool = "jira"               # the tracker the tickets live in
skill = "jira-workflow"     # the skill (or tool) that carries out every ticket update
stages = ["start", "done"]  # which stages act on the ticket: start, review, done
# enabled = false           # pause the integration without deleting the section
```

- `tool` — the tracker. It is informational: it tells the agent which system `skill` talks to.
- `skill` — what carries out the updates (moving the ticket, commenting). The rule never names a skill
  itself, so any tracker and any skill can be plugged in. If the agent does not have it, it says so once
  and leaves the ticket alone.
- `stages` — **in which stages** the ticket is touched: `start` (a card enters `doing`), `review` (a card
  enters `review`) and `done` (a card enters `done`). **A stage that is not listed does nothing** (no
  move, no comment); leave `review` out to never touch the ticket on review. Without `stages`, all three
  act.

kanbai does **not** know what the ticket's statuses are called. It asks the skill to bring the ticket to a
stage, and the skill maps the stage to the tracker's real status with its own settings (for the Jira
skill, `[stages]` in `.jira/config.toml`: `review = "In Review"`, and so on). That is how one side can say
"move the ticket on review" while the other says what review is called.

When several cards share one ticket, the ticket only reaches `review` and `done` once **every** linked
card has got there, and `start` when the **first** one starts. The agent reads this section as the
`bypass_review` setting is read; the rule that explains the flow is `.claude/rules/kanbai-tickets.md`
(see [Working with Claude Code](claude-code.md#cards-linked-to-a-ticket)). The section is yours: kanbai
never rewrites it, and `hosted pull --settings` keeps it.

## `[server]`

Written by [`kanbai hosted connect`](cli.md#hosted) (or `clone`); its presence is what connects
the project to a [hosted board](hosted.md). You normally never edit it by hand.

| Key | Description |
|-----|-------------|
| `url` | Base URL of the hosted `kanbai_server`. |
| `token` | Access token. A token saved by [`kanbai hosted login`](cli.md#hosted) for the same server takes precedence over this one. |
| `board_id` | Id of the hosted board this project follows. |
| `enabled` | `false` keeps the connection but runs the project locally only (`kanbai hosted disable`). Default `true`. |

The `[board]`, `[defaults]`, `[types]`, `[wip]` and `[notifications]` settings can be kept in step
with the hosted board with `kanbai hosted push --settings` / `pull --settings` (the columns are
never synced).
