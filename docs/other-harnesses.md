# Using KanbAI with other AI coding harnesses

KanbAI's core is **harness-agnostic**: the board is just Markdown files under `.kanbai/`,
and everything is driven through the `kanbai` CLI. Any assistant that can run shell commands
and read files can drive the board — Claude Code just gets a first-class, auto-installed
integration.

`kanbai init` writes the Claude-specific integration (`.claude/rules/kanbai.md` and the
`kanbai-*` skills). For any other tool, give your assistant the same workflow instructions
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
