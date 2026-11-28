# Working with Claude Code

Claude Code gets a first-class, auto-installed integration. Running [`kanbai init`](cli.md#init)
writes everything Claude needs into `.claude/`:

- **`.claude/rules/kanbai.md`** — teaches Claude the board convention and workflow. Loaded
  every session, so Claude always knows how to drive the board.
- **`.claude/rules/kanbai-tickets.md`** — what Claude does for cards linked to an external ticket
  (see [Cards linked to a ticket](#cards-linked-to-a-ticket)).
- **Skills** — installed under `.claude/skills/`:
    - `kanbai-next` — work **one** card and stop.
    - `kanbai-sprint` — work the **whole** sprint back-to-back.
    - `kanbai-status` — summarize the current board.

## Cards linked to a ticket

A card can carry a [`ticket`](concepts.md#cards) — the key or URL of its record in an external
tracker such as Jira. `.claude/rules/kanbai-tickets.md` tells Claude to keep that ticket up to date
as the card moves, **when the board turns it on** with an
[`[integration]`](configuration.md#integration) section in `.kanbai/config.toml`: which tracker, which
skill carries out the updates, and in which stages (`start`, `review`, `done`) the ticket is touched. The
skill itself knows what the ticket's statuses are called. Without that section, or for a card without a
ticket, nothing happens.

One ticket can be linked to **several cards** — a large ticket split into smaller cards that all
share the same `ticket` — so the ticket follows the cards together. When Claude splits a ticket into
cards it gives every card the same `--ticket`. For the stages that are turned on:

| A linked card… | The ticket… |
|---|---|
| is the **first** to enter `doing` (stage `start`) | moves to the start stage, with a comment |
| enters `review` | gets a progress comment; reaches the review stage only when **every** linked card is in `review` or done |
| enters `done` | reaches the done stage only when **every** linked card is done; before that it gets a progress comment ("2 of 3 cards done") |

A stage that is not listed does nothing to the ticket. Claude counts the cards with
[`kanbai list --ticket KEY`](cli.md#list). The skill named in the config keeps its own rules (what it
may touch, whether it asks first). This only happens when Claude moves the card through the CLI:
dragging a card in the web UI, or running `kanbai move` yourself, does not touch the ticket.

## The one-card-at-a-time loop

By default Claude works a single card and then stops for your review:

1. **`kanbai next --json`** — pick the next actionable sprint task (respecting order and
   [dependencies](concepts.md#dependencies)). If it returns `null`, the sprint is empty or
   blocked — Claude tells you and stops.
2. **`kanbai start <id>`** — move the card into `doing`.
3. **Implement it**, reading `kanbai show <id> --json` for the description and acceptance
   criteria. If the scope or a design decision is unclear, Claude stops and asks first.
4. **`kanbai review <id>`** — move the card into `review` **as soon as the work is
   verified**, on Claude's own initiative — it never asks whether you want to review it
   first, and never leaves a finished card sitting in `doing` waiting for permission.
   It also never moves a card to `review` with failing lints, type checks, or tests — a
   card in `review` is a claim that the work is verified. Then Claude **stops**.
5. **You review** the work in the `review` column and give your verdict:
    - **You approve it** (e.g. "aprovado", "looks good") — Claude runs **`kanbai done
      <id>`** itself right away and commits the work, without waiting for you to run the
      command or asking for confirmation first. If the card has a [notice](concepts.md#card-notice),
      Claude also states it explicitly in its reply, so you can pass it on, and marks it as
      sent once you confirm.
    - **You ask for a change** — Claude moves the card back to `doing` first (it never
      edits a card's work while it sits in `review`), makes the change, and repeats from
      step 4 — as many rounds as it takes.

This keeps you in the loop: nothing is marked complete without your approval, but once you
give it, Claude finishes the job (move to `done` + commit) without extra prompting.

!!! tip "Work the whole sprint"
    When you explicitly want Claude to work several cards back-to-back, invoke the
    `kanbai-sprint` skill (or just ask it to “work the whole sprint”). It runs the same loop
    per card, still finishing each into `review` for your approval.

## Allowing the CLI and skills without prompts

Claude Code asks before running shell commands or invoking skills. `kanbai init` automatically
merges two entries into `permissions.allow` in `.claude/settings.json` so Claude never prompts
for kanbai operations:

```json
{
  "permissions": {
    "allow": ["Bash(kanbai *)", "Skill(kanbai-*)"]
  }
}
```

- **`Bash(kanbai *)`** — pre-approves every `kanbai` CLI call.
- **`Skill(kanbai-*)`** — pre-approves the `kanbai-next`, `kanbai-sprint`, and `kanbai-status`
  skills so they run without a prompt.

The merge is additive: any entries already in your `allow` list (or any other key in
`settings.json`) are left exactly as-is. Re-running `init` won't duplicate the entries.

## Notified when Claude needs you

`kanbai init` also registers Claude Code's [`Notification`
hook](https://code.claude.com/docs/en/hooks#notification) in `.claude/settings.json`, pointed
at `kanbai notify-hook`. It fires the same [native desktop and ntfy
channels](web-ui.md#notifications) configured in `config.toml` whenever Claude is waiting on
you, independently of any board activity. Each situation gets its own title, emoji and ntfy
priority, and the message carries Claude's own text (for example which tool needs approval):

| `notification_type` | Notification |
|---------------------|--------------|
| `permission_prompt` | 🔒 *Claude needs your approval* (high priority) |
| `elicitation_dialog`, `elicitation_url_dialog`, `agent_needs_input` | ❓ *Claude needs your input* (high priority) |
| `idle_prompt` | ⏳ *Claude is waiting for you* |

When exactly one card is in `doing`, the message also names it. Every other type
(`auth_success`, `agent_completed`, `quota_*`, ...) is ignored. The hook keeps its single `*`
matcher and tells the types apart itself, so an existing install picks this up by just
updating kanbai — no need to re-run `init`.

The merge is additive and non-destructive: it only touches `hooks.Notification`, leaving
every other key (and any hooks you've configured yourself) exactly as they were. Re-running
`init` won't duplicate the entry.

## Planning work for Claude

You decide **what** Claude works on by curating the sprint:

```bash
kanbai add "Add OAuth login" -d "Support Google sign-in" -p high -t feature  # capture in the backlog
kanbai move 004 todo                                                         # plan it into the sprint
```

Claude always picks a [type](concepts.md#card-type) when creating a card, evaluating which
of the board's configured types fits best rather than leaving it unset.

Only cards in `todo` are picked up by `kanbai next`, so the backlog is a safe place to stash
future ideas without distracting the agent. You can also plan and reorder visually in the
[web UI](web-ui.md).

Using a different assistant? See [Other AI harnesses](other-harnesses.md) — the board is
harness-agnostic.
