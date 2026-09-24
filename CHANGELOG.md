# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-09-24

### Added

- **Card type** — a single structured category per card (`feature`, `bug`, `refactor`,
  `chore`, `docs`, `spike` by default), configurable via `[types]` in `config.toml` with
  optional per-type color overrides (`[types.colors]`). Set with `--type/-t` on `add`/`edit`,
  shown in `show`/`list`/`--json`, filterable and sortable in the CLI and the web UI, with a
  colored badge on cards and in the Plan sprint / Archive modals.
- **Release version on cards** — a free-form `version` field (e.g. `v1.2.0`), settable via
  `--version/-v` on `add`/`edit`. `kanbai close-sprint --version <v>` stamps it on every card
  archived from `done`, so the archive later shows which release shipped each card.
- **New card modal** — card creation moved from a cramped top-bar form into a dedicated modal
  with every field (title, column, priority, type, labels, description), behind a single
  "New card" button.
- **Archive list opens the card detail** — clicking a row in the Archive modal opens that
  card's detail (reusing the existing card view); closing it returns to the archive list with
  its scroll position preserved instead of closing everything.

### Changed

- **`new-sprint` renamed to `close-sprint`** (CLI) and the matching web UI button/modal
  renamed from "New sprint" to "Close sprint" — same action (archive `done`, optionally reset
  active columns), now also carrying the optional release version above.
- The Archive modal no longer shows labels in the row listing, to keep it focused on the
  essentials (id, type, title, origin column, version).
- CLI command order: `sort` now comes before `ui`, so the two web-server commands (`ui`,
  `hub`) are grouped together at the end of `kanbai --help`.
- The `assignee` field is hidden from the web UI (unused today) while keeping the underlying
  model/CLI/board support intact for future use.

### Fixed

- **Hub routing** — card detail/edit/move actions issued from the multi-board hub
  (`/b/<board>/...`) now correctly keep the board's URL prefix; they previously 404'd because
  several routes rendered their template without it.
- **`close-sprint` no longer archives/moves unapproved work** — it now refuses to run (no
  changes made) while any card is still in `review`, both in the CLI (clear error, exit code
  1) and the web UI (an alert shown proactively in the modal, with the submit button disabled).

## [0.2.0] - 2026-09-23

### Added

- **Multi-board hub** — serve several boards from one port under `/b/<name>/`, with a board
  switcher and a landing page. Manage the registry with `kanbai hub add/list/remove` (stored
  in `~/.kanbai/boards.toml`); install globally via pipx/uvx.
- **Sort the backlog** — a sort control on the backlog column (by id, priority, or title,
  ascending/descending) that persists the new order, plus a `kanbai sort` CLI command.
- **Hide/show the backlog column** in the web UI, remembered per browser.
- **Documentation site** built with MkDocs Material and published to GitHub Pages — a landing
  hero plus guides for concepts, the CLI, harness integrations, the web UI, the hub,
  configuration, and an FAQ.

### Changed

- Polished the web UI: friendlier top-bar buttons (icons, tooltips, visual hierarchy) and
  richer Plan sprint / Archive modal listings (priority accents, labels, friendly empty states).

### Fixed

- `--json` output is now always plain text, even when `FORCE_COLOR` is set — it previously
  emitted ANSI escape codes that broke machine parsing.
- Development tooling: `make lint` (ruff formatting) and `make test` (coverage now measures the
  `kanbai` package), and the Makefile `install` target (uses `uv sync`).

## [0.1.1] - 2026-09-23

### Added

- README badges (PyPI, Python versions, CI, license) via shields.io.
- Trove classifiers in the package metadata (Python 3.10–3.13, license, topics).

### Fixed

- README images and links now use absolute URLs so they render on PyPI — relative paths
  only worked on GitHub.
- Corrected the repository owner in the changelog links.

## [0.1.0] - 2026-09-23

Initial release: a file-based Kanban board for Claude Code and other AI coding harnesses.

### Added

- **Board storage** — one Markdown card per file with YAML frontmatter, organized in
  per-column folders under `.kanbai/`. Atomic writes; the folder is the source of truth
  for a card's column.
- **Sprint workflow columns** — `backlog → todo → doing → review → done`. `kanbai next`
  reads the sprint (`todo`) and respects card order and blocking dependencies.
- **CLI** (`kanbai`): `init`, `add`, `list`, `next`, `show`, `move`, `start`, `review`,
  `done`, `edit`, `archive`, `rm`, `new-sprint`, and `ui`. Read commands support `--json`.
- **`kanbai init`** — scaffolds `.kanbai/` and the Claude Code integration (`.claude/rules`
  + skills `kanbai-next` / `kanbai-sprint` / `kanbai-status`). Idempotent and degrades
  gracefully when integration files can't be written.
- **Review flow** — finished cards go to `review` via `kanbai review`; the user approves
  them to `done` with `kanbai done`.
- **Web UI** (`kanbai ui`, FastAPI + HTMX, assets vendored for offline use):
  - Board view; create cards; move cards by drag-and-drop (with persisted reordering) or
    from the card detail modal.
  - Card detail, edit, archive, and delete modals.
  - "Plan sprint" and "New sprint" modals; text search and label filtering.
  - Live updates via Server-Sent Events; WIP-limit and blocked-by-dependency indicators.
  - Logo and favicon; `--reload` development mode; `--poll` for sandboxes/containers.
- **WIP limits** — optional `[wip]` config per column; the CLI and UI warn (never block)
  when a column is over its limit.
- **`new-sprint`** — archives `done` cards (recording each card's origin column in
  `archived_from`) and optionally moves the active columns back to the backlog.

### Packaging

- Packaged with hatchling; `kanbai` console entry point. Optional `ui` extra
  (fastapi, uvicorn, jinja2, watchfiles, python-multipart). MIT licensed.

[Unreleased]: https://github.com/rennancockles/kanbai/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/rennancockles/kanbai/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/rennancockles/kanbai/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/rennancockles/kanbai/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/rennancockles/kanbai/releases/tag/v0.1.0
