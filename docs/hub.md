# Multi-board hub

Working across several projects? The **hub** serves all of their boards from one place, on a
single port, with a board switcher — no more one server per project.

## Install globally

Since the hub spans projects, install KanbAI **globally** rather than into a single project
(and include the [`ui` extra](installation.md#the-web-ui-extra)):

```bash
pipx install 'kanbai[ui]'
# or run it without installing anything:
uvx --from 'kanbai[ui]' kanbai hub
```

## Register your boards

Each board must already have a `.kanbai/` folder — run [`kanbai init`](cli.md#init) there
first. Then register it with the hub:

```bash
kanbai hub add ~/projects/api          # named after `[board] name` in its config.toml
kanbai hub list                        # show registered boards
kanbai hub remove api                  # unregister
```

## Serve them

```bash
kanbai hub                     # serve all registered boards; opens a landing to pick one
kanbai hub --port 9000 --no-browser
```

The hub root is a landing page that lists every registered board:

![The hub landing page listing registered boards](assets/hub.png)

Each board is served at `/b/<name>/`, and a **board switcher** in the top bar lets you jump
between boards without leaving the page:

![A board served through the hub, with the board switcher in the top bar](assets/hub_board.png)

Visiting an unregistered or misspelled board URL shows a themed 404 page — with the
registered boards listed as suggestions — instead of a bare JSON error. A board whose
`.kanbai/config.toml` can't be read (a missing folder, or a permissions issue — e.g. macOS
denying a detached daemon access to a protected folder like `~/Documents`) is skipped with
a warning rather than taking every other board down with it.

![The themed 404 page for an unregistered or misspelled board URL, listing registered boards as suggestions](assets/hub_404.png)

## Running the hub in the background

`kanbai hub` blocks the terminal it runs in. To keep it always available without tying up a
terminal, run it as a background daemon instead:

```bash
kanbai hub start --port 8000   # start it, detached
kanbai hub status              # check whether it's running
kanbai hub status --json       # machine-readable
kanbai hub logs                # show its log
kanbai hub logs -f             # follow it
kanbai hub stop                # stop it
```

The daemon's PID and log file live under `~/.kanbai/` (`hub.pid` / `hub.log`), alongside the
registry. `kanbai hub start` refuses to run if a daemon is already running; `kanbai hub
stop` sends a graceful shutdown signal and escalates if it doesn't exit in time.

## Where the registry lives

The list of registered boards is stored in `~/.kanbai/boards.toml`. Override the location by
setting the `KANBAI_HOME` environment variable (handy for tests or isolated setups):

```bash
KANBAI_HOME=/tmp/kanbai-home kanbai hub list
```
