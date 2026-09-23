# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/rennancockles/kanbai/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/rennancockles/kanbai/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/rennancockles/kanbai/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/rennancockles/kanbai/releases/tag/v0.1.0
