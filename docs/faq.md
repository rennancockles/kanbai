# FAQ

## Is KanbAI tied to Claude Code?

No. The core is **harness-agnostic** — the board is just Markdown files driven by the `kanbai`
CLI. Claude Code gets an auto-installed integration, but any assistant that can run shell
commands works. See [Other AI harnesses](other-harnesses.md).

## Do I commit the `.kanbai/` folder?

Usually yes — the point is that the board lives **in your repo** and travels with it, with a
clean git history of every card and move. If you'd rather keep it local, add `.kanbai/` to
`.gitignore`.

## Can I edit card files directly?

Prefer the CLI. The [`kanbai edit`](cli.md#edit) / [`move`](cli.md#move) commands keep the
frontmatter valid and in sync with the folder a card lives in. Hand-editing risks an
inconsistent `status` or a malformed header.

## Why doesn't Claude pick up my backlog cards?

[`kanbai next`](cli.md#next) reads only the **sprint** (`todo`), never the backlog — by
design. Plan a card into the sprint with [`kanbai move <id> todo`](cli.md#move) (or the UI's
*Plan sprint* button) and it becomes actionable.

## Why is a card being skipped even though it's next?

It's probably **blocked** by an unfinished [dependency](concepts.md#dependencies). `kanbai
next` skips blocked cards, and the web UI shows a 🔒. Finish (approve to `done`) the cards in
its `deps` and it becomes actionable.

## Who moves a card to `done`?

**You do.** The agent finishes a card into `review` with [`kanbai review`](cli.md#review) and
stops; approving it into `done` with [`kanbai done`](cli.md#done) is a human step.

## Can I add or rename columns?

Yes — edit `columns` in [`config.toml`](configuration.md). The role resolution falls back to
position, so the workflow keeps working; keep the first column as the backlog and the last as
`done` for the cleanest results.

## The web UI won't update live in my container.

Live updates use OS file-change events. Where those aren't delivered, run `kanbai ui --poll`
to fall back to polling. See [Web UI › Live updates](web-ui.md#live-updates).

## `kanbai ui` says it needs an extra.

Install the UI dependencies: `pip install 'kanbai[ui]'` (or `uv add --dev 'kanbai[ui]'`). See
[Installation](installation.md#the-web-ui-extra).
