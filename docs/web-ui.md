# Web UI

KanbAI ships a friendly local web UI (FastAPI + HTMX, with all assets vendored so it works
**offline**). It needs the [`ui` extra](installation.md#the-web-ui-extra).

```bash
kanbai ui                    # serve the board and open your browser
kanbai ui --port 9000 --no-browser
kanbai ui --reload           # auto-restart on code changes (development)
kanbai ui --poll             # for sandboxes/containers without OS file events
```

![KanbAI web UI](assets/webui.png)

## What you can do

- **View the board** and **create, edit, move, archive, or delete** cards.
- **Drag-and-drop** cards between columns (the new order is persisted), or move from a card's
  detail modal.
- **Plan a sprint** — move several backlog cards into `todo` at once — and **start a new
  sprint** (archive done cards, optionally reset the active columns).
- **Search** cards and **filter by label**.
- Browse and **restore** archived cards.
- See **WIP-limit** and **blocked-by-dependency** indicators.

## Live updates

The UI subscribes to the board over **Server-Sent Events**. When Claude (or you) moves a card
from the CLI in another terminal, the board updates in place — no refresh needed.

!!! note "Sandboxes and containers"
    Live updates rely on OS file-change events. In environments that don't deliver them
    (some containers, network mounts), start the UI with `--poll` to fall back to polling.

## Sorting the backlog

The backlog column has a small sort control in its header. Pick a key (**id**, **priority**,
or **title**) and a direction (**↑** ascending / **↓** descending); the new order is written
back to the cards, so it sticks everywhere — including the CLI. Ascending priority reads
`low → medium → high`; use **↓** to put the highest priority first.

## Hiding the backlog

Use the **eye toggle** in the top bar to hide the backlog column and give the sprint columns
the full width. The choice is remembered in your browser.

## Multiple projects

To watch several projects at once from a single server, use the
[multi-board hub](hub.md).
