# Hosted boards

A **hosted board** is a copy of a board kept on a `kanbai_server`: you can open it from any
browser, share it across machines, and reach it from tools like ChatGPT. The `.kanbai/` files on
your machine **stay the source of truth** — the hosted board follows them, and you can still work
offline.

## Connect a project

From a project that already has a `.kanbai/` board:

```bash
kanbai hosted connect --url https://kanbai.example.com --email me@example.com --create
kanbai hosted push                      # send the existing cards
```

`connect` logs in and saves a [`[server]`](configuration.md#server) section in `config.toml`;
`--create` makes a new hosted board from this one, `--board <id|name>` links to an existing one.
On another machine, copy a hosted board into a fresh project with:

```bash
mkdir myproject && cd myproject
kanbai hosted clone --url https://kanbai.example.com --email me@example.com
```

Tokens expire after about a day: run `kanbai hosted login` once to renew the token for every
project on that server.

## How it stays in step

Once connected, every command that changes a card (`add`, `move`, `start`, `review`, `done`,
`edit`, `archive`, …) is applied to your local files first and then mirrored to the hosted board,
keeping the same card ids. Mirroring never makes a command fail: if the server is unreachable or
disagrees, your local change stands, you get a warning, and the project is marked **out of sync**.
Then pick a side:

| Command | Meaning |
|---------|---------|
| `kanbai hosted push` | **Local wins** — make the hosted board match your files. |
| `kanbai hosted pull` | **Server wins** — make your files match the hosted board. |
| `kanbai hosted diff` | Compare the two without changing anything. |
| `kanbai hosted status` | Show whether you are connected, mirroring, and out of sync. |

`push`, `pull` and `diff` also take `--all` to run on every connected board of the
[hub](hub.md). The full reference, including `--archived`, `--delete`, `enable`/`disable` for
working offline, is in the [CLI reference](cli.md#hosted).

### Board settings

By default only cards are synced. Add `--settings` to also sync the board's settings — name,
category, default priority, card types and colors, WIP limits, `bypass_review` and the
notification settings (never the columns):

```bash
kanbai hosted push --settings      # local config.toml -> hosted board
kanbai hosted pull --settings      # hosted board -> local config.toml
```

This is how, for example, a new `category` reaches the hosted hub. `pull --settings` rewrites
`config.toml` (keeping the `[server]` section but not comments).

## In the browser

The server has its own web hub, signed in with your account:

- a **boards list** grouped by category, with card counts and a **New board** button;
- the board page — create, edit, move, archive and delete cards, plan and close sprints,
  search and filter — plus the optional [AI input](web-ui.md#ai-command-input) when the operator
  configured a key;
- a **Settings** button to edit the board's settings, and **Send to board** on a card to move it
  to the backlog of another of your boards (it gets a new id there, and its dependencies are
  dropped);
- a **multi-board view** across several boards;
- a **ChatGPT** button that connects the board to the ChatGPT app, so ideas from a conversation
  become cards in `todo`.

Moving a card in the browser does not fire [notifications](web-ui.md#notifications), and the
change is not copied back to your local files until you `kanbai hosted pull`.
