# Using KanbAI with other AI coding harnesses

KanbAI's core is **harness-agnostic**: the board is just Markdown files under `.kanbai/`,
and everything is driven through the `kanbai` CLI. Any assistant that can run shell commands
and read files can drive the board — Claude Code just gets a first-class, auto-installed
integration.

`kanbai init` writes the Claude-specific integration (`.claude/rules/kanbai.md`,
`.claude/rules/kanbai-tickets.md` and the `kanbai-*` skills). For any other tool, give your assistant the same workflow instructions
through **that tool's own rules / system-prompt mechanism**.

## The portable workflow

Paste (or adapt) this into your assistant's rules/instructions:

```markdown
This project uses KanbAI, a file-based Kanban board in `.kanbai/`. Manage it only through
the `kanbai` CLI — never edit the card files by hand.

Columns: backlog → todo → doing → review → done. `kanbai next` reads the sprint (`todo`).

Work one card at a time:
1. `kanbai next --json` — the next actionable sprint task (null = sprint empty/blocked; stop).
2. `kanbai start <id>` — move it to `doing`.
3. Implement it (see `kanbai show <id> --json` for the description and acceptance criteria).
   If the scope is unclear, stop and ask before coding.
4. `kanbai review <id>` — send it to `review`, then stop. Do NOT run `kanbai done`;
   the human approves it to `done`.

Create work with `kanbai add "title" -d "..." -p high` (lands in the backlog) and plan it
with `kanbai move <id> todo`.
```

`--json` on the read commands (`next`, `show`, `list`) gives structured output that's easy
for an agent to parse.

## Cards linked to an external ticket

If your cards carry a `ticket` (`kanbai add ... --ticket PROJ-123`) and the board has an
[`[integration]`](configuration.md#integration) section, add this too. It is the portable version of
`.claude/rules/kanbai-tickets.md`:

```markdown
A card may have a `ticket`: the key or URL of its record in an external tracker (Jira...). Read the
`[integration]` section of `.kanbai/config.toml`: it is on only if the section exists, `enabled` is not
false, and it has a `skill`. If not, or for a card without a ticket, do nothing. Do every ticket update
through the `skill` named there (say so once and leave the ticket alone if you do not have it); ask it to
bring the ticket to a stage and it finds the tracker's status itself. `stages` lists which stages act:
start (a card enters doing), review, done; a stage that is not listed does nothing to the ticket, and
without `stages` all three act.

One ticket can be linked to several cards, so the ticket follows the cards together; when you split a
ticket into cards, give every card the same ticket (`kanbai add "..." --ticket KEY`). Find them with
`kanbai list --ticket KEY --json` (and `kanbai list archive --ticket KEY --json`); a card is done when it
is in `done` or was archived from `done`, anything else is pending. For a stage that acts:
- a card enters `doing` and no other linked card has started -> ticket to the start stage + a comment;
- a card enters `review` -> comment; ticket to the review stage only when every linked card is in review or done;
- a card enters `done` -> ticket to the done stage only when every linked card is done, otherwise
  comment the progress ("2 of 3 cards done").
Never repeat a status the ticket already has; ask before moving a ticket back or reopening a done one;
on a tracker error, show it and stop (do not undo the card move).
```

## Per-tool pointers

- **Cursor** — put the workflow in a rule under `.cursor/rules/` (or `.cursorrules`).
- **Windsurf** — add it to `.windsurfrules` (or a workspace rule).
- **Aider** — add it to a `CONVENTIONS.md` and load it (`aider --read CONVENTIONS.md`), or
  paste it into the chat.
- **GitHub Copilot** — add it to `.github/copilot-instructions.md`.
- **Anything else** — put it in the tool's system prompt / custom instructions.

The only tool-specific piece is *where* the instructions live; the CLI workflow is identical
everywhere. If you'd like a tool's integration auto-installed by `kanbai init` (like the
Claude one), open an issue or PR.

## Allowing the CLI without prompts

Most agent tools ask before running shell commands. Pre-approve KanbAI where your tool
supports it (for Claude Code, add `Bash(kanbai *)` to `.claude/settings.json`).
