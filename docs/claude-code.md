# Working with Claude Code

Claude Code gets a first-class, auto-installed integration. Running [`kanbai init`](cli.md#init)
writes everything Claude needs into `.claude/`:

- **`.claude/rules/kanbai.md`** — teaches Claude the board convention and workflow. Loaded
  every session, so Claude always knows how to drive the board.
- **Skills** — installed under `.claude/skills/`:
    - `kanbai-next` — work **one** card and stop.
    - `kanbai-sprint` — work the **whole** sprint back-to-back.
    - `kanbai-status` — summarize the current board.

## The one-card-at-a-time loop

By default Claude works a single card and then stops for your review:

1. **`kanbai next --json`** — pick the next actionable sprint task (respecting order and
   [dependencies](concepts.md#dependencies)). If it returns `null`, the sprint is empty or
   blocked — Claude tells you and stops.
2. **`kanbai start <id>`** — move the card into `doing`.
3. **Implement it**, reading `kanbai show <id> --json` for the description and acceptance
   criteria. If the scope or a design decision is unclear, Claude stops and asks first.
4. **`kanbai review <id>`** — move the card into `review` and **stop**. Claude never runs
   `kanbai done`, and never moves a card to `review` with failing lints, type checks, or
   tests — a card in `review` is a claim that the work is verified.
5. **You review** the work and approve it with **`kanbai done <id>`**. If you instead ask for
   a change, Claude moves the card back to `doing` first — it never edits a card's work while
   it sits in `review`.

This keeps you in the loop: nothing is marked complete without your approval, and you can
review or commit between cards.

!!! tip "Work the whole sprint"
    When you explicitly want Claude to work several cards back-to-back, invoke the
    `kanbai-sprint` skill (or just ask it to “work the whole sprint”). It runs the same loop
    per card, still finishing each into `review` for your approval.

## Allowing the CLI without prompts

Claude Code asks before running shell commands. Pre-approve KanbAI by adding `Bash(kanbai *)`
to the `permissions.allow` list in `.claude/settings.json`:

```json
{
  "permissions": {
    "allow": ["Bash(kanbai *)"]
  }
}
```

`kanbai init` prints this reminder. Editing the rest of `settings.json` is left to you, since
it's a sensitive file — the one exception is the `Notification` hook below, which `init`
merges in on its own.

## Notified when Claude needs you

`kanbai init` also registers Claude Code's [`Notification`
hook](https://code.claude.com/docs/en/hooks#notification) in `.claude/settings.json`, pointed
at `kanbai notify-hook`. It fires the same [native desktop and ntfy
channels](web-ui.md#notifications) configured in `config.toml` whenever Claude is waiting on
you — a permission prompt, an `AskUserQuestion`, or plain idleness — independently of any
board activity.

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
