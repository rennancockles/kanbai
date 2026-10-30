# Changelog

All notable changes to this project are documented in this file.

Entries up to and including [0.4.0](#040---2026-09-24) were written by hand, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). From here on, releases are
automated by [python-semantic-release](https://python-semantic-release.readthedocs.io/) from
[Conventional Commits](https://www.conventionalcommits.org/), which uses its own format
(grouped by commit type) — the entries below this line follow that instead. This project
adheres to [Semantic Versioning](https://semver.org/).

<!-- version list -->

## v0.18.0 (2026-10-30)

### Bug Fixes

- Filtro de categoria persiste ao trocar de board (152)
  ([`eb10bda`](https://github.com/rennancockles/kanbai/commit/eb10bdadf0f06d1f47b4b15fd43d5958bdd44630))

- Hosted pull não duplica o arquivo do card quando o título muda no servidor (155)
  ([`257a508`](https://github.com/rennancockles/kanbai/commit/257a50868bc0cedd73ae0ff48e9eda47343bf15b))

### Features

- Aviso por card disparado ao concluir, com notice e notice_sent (153)
  ([`4288c73`](https://github.com/rennancockles/kanbai/commit/4288c73860e55db7a8ecc95775e080e3cc308610))

- Mensagens personalizadas por tipo de notificação do hook do Claude (158)
  ([`4654a48`](https://github.com/rennancockles/kanbai/commit/4654a4898a8ae96a525f5652c922f6eada865c4b))

- Notificações ntfy com emoji, prioridade e mensagem por tipo de evento (157)
  ([`14bb888`](https://github.com/rennancockles/kanbai/commit/14bb888148d75c5146ea0b2cea365f294505f792))

- Sincronizar o aviso dos cards com o kanbai_server (154)
  ([`ace633e`](https://github.com/rennancockles/kanbai/commit/ace633e44d4b76642482e177ea1572f06b080a19))


## v0.17.0 (2026-10-27)

### Features

- Reordenar os boards da multi view arrastando pelo ícone do cabeçalho (151)
  ([`47fefd6`](https://github.com/rennancockles/kanbai/commit/47fefd66fb630bd64c2c3a255f5e2d9e4c41b107))


## v0.16.1 (2026-10-27)

### Bug Fixes

- Hosted push corrige a coluna de origem de cards arquivados dos dois lados
  ([`17b6d14`](https://github.com/rennancockles/kanbai/commit/17b6d148aa14df6a822beb0bca386b01ad514a00))


## v0.16.0 (2026-10-22)

### Features

- Hosted push/pull mostram o que vai mudar e pedem confirmação, com -y para aplicar direto (149)
  ([`2b03952`](https://github.com/rennancockles/kanbai/commit/2b039521c762f10896a3555e8189531ff5ba765d))


## v0.15.0 (2026-10-17)

### Documentation

- Atualizar a documentação e os screenshots para o estado atual do produto (139)
  ([`afa279d`](https://github.com/rennancockles/kanbai/commit/afa279d1d8fd27ced985b33247fc82c9aab72ea7))

### Features

- Hosted push/pull --settings para sincronizar os settings do board com o host (137)
  ([`690e4fa`](https://github.com/rennancockles/kanbai/commit/690e4faa4ed5b7d1f14f566d5fc540f697d27b77))


## v0.14.0 (2026-10-16)

### Features

- Hosted com o local como fonte, replicando cada mudança no host e avisando divergências (132)
  ([`f25f55f`](https://github.com/rennancockles/kanbai/commit/f25f55fe7b4a67be230efc82d4a1a79f2a37b455))


## v0.13.0 (2026-10-16)

### Features

- Notificações nativa e ntfy também no modo hosted, disparadas pelo cliente (130)
  ([`07c96fe`](https://github.com/rennancockles/kanbai/commit/07c96fe6c7ba018a97f0c3c741e1141905bdcb16))


## v0.12.0 (2026-10-15)

### Bug Fixes

- Hosted push/pull sincronizam arquivamento de cards presentes nos dois lados (127)
  ([`57966aa`](https://github.com/rennancockles/kanbai/commit/57966aae548f89ebe813a412b8be45c6edcd3b0a))

### Features

- Hosted login global com credencial por servidor em ~/.kanbai (125)
  ([`6e2d2b1`](https://github.com/rennancockles/kanbai/commit/6e2d2b1a64487f8e6c06371d6a9b57ff0e18cc04))


## v0.11.0 (2026-10-15)

### Bug Fixes

- Atualizar a view multi-board ao vivo quando o CLI move cards (122)
  ([`4c0d16c`](https://github.com/rennancockles/kanbai/commit/4c0d16c4adf846c9e7f333b93822abfe41c1e243))

### Chores

- Trocar o modelo padrão da OpenAI para gpt-6-luna
  ([`5f8d561`](https://github.com/rennancockles/kanbai/commit/5f8d561f27072f4fc22c9477aafd3be3fbc0cf61))

### Features

- Kanbai init adiciona .kanbai/ ao .gitignore em repositórios git (123)
  ([`1b59327`](https://github.com/rennancockles/kanbai/commit/1b593276e87d9fea8adb69b8c2f4b445ffb5d7be))

- Melhorar UX e UI no mobile (120)
  ([`805b6a1`](https://github.com/rennancockles/kanbai/commit/805b6a147469089a27cd34ce744eea4cd4d33aa4))


## v0.10.0 (2026-10-13)

### Bug Fixes

- Contagem de cards por coluna do hub lida do disco a cada requisição (115)
  ([`34cfcaa`](https://github.com/rennancockles/kanbai/commit/34cfcaa977b65182025f9285477845a8fcad1c82))

### Features

- Hosted enable/disable/status para alternar o board local e o remoto (114)
  ([`3f2c0b0`](https://github.com/rennancockles/kanbai/commit/3f2c0b0f9976615617ae043b5c4e96dd3f0d0f5a))

- Hosted login para renovar o token e dica clara em erros 401 (119)
  ([`929acac`](https://github.com/rennancockles/kanbai/commit/929acac9cd45dd9a0f816290417ad3c6a71e94ab))

- Hosted push/pull/diff --all para sincronizar todos os boards do hub (117)
  ([`fbb2111`](https://github.com/rennancockles/kanbai/commit/fbb2111c07f961e0d89ca29a68f7a8d56a412314))

- Pular boards de host inalcançável no --all e detectar bloqueio de VPN/firewall (118)
  ([`566502b`](https://github.com/rennancockles/kanbai/commit/566502b628f409e9788648003c5dfdc09b072dd4))


## v0.9.0 (2026-10-11)

### Bug Fixes

- Modal de card na view multi-board fecha e ações atualizam o board (111)
  ([`38e26e1`](https://github.com/rennancockles/kanbai/commit/38e26e132fb0b3c39d70e7511e5855417afecd59))

- Preservar IDs locais em hosted publish e sync push (100)
  ([`7abc34b`](https://github.com/rennancockles/kanbai/commit/7abc34b9c2dc95a9180b8f091ed23371d982cb6c))

### Features

- Add kanbai sync pull/push commands to reconcile local and hosted boards (093)
  ([`77ac6f3`](https://github.com/rennancockles/kanbai/commit/77ac6f39729e34d4c261446d449e74b564472c62))

- Botão Clear archive no modal de arquivo do hub local (113)
  ([`75baa17`](https://github.com/rennancockles/kanbai/commit/75baa17928231f1f451e518e68443692d005194c))

- Enviar categoria do board no hosted publish (108)
  ([`d18617c`](https://github.com/rennancockles/kanbai/commit/d18617c66e052cba8296d47fad2a2b7a48afc248))

### Refactoring

- Renomear hosted import/export para hosted publish/download (101)
  ([`a6aaaee`](https://github.com/rennancockles/kanbai/commit/a6aaaeec6b613bbf8e7faf0809dde532a392dacd))

- Unificar hosted em connect/push/pull/clone/diff com --archived e remover sync (112)
  ([`2aba095`](https://github.com/rennancockles/kanbai/commit/2aba09506c03eb8c6ea7a7611e27fceba9d5d05c))


## v0.8.0 (2026-10-10)

### Features

- Aceitar path em 'kanbai hub remove' (089)
  ([`c715070`](https://github.com/rennancockles/kanbai/commit/c7150705dc27d1be1435b8e9a4d7da276802f322))

- Adicionar comando para comparar board local e hospedado (084)
  ([`21485c5`](https://github.com/rennancockles/kanbai/commit/21485c5a1099c10df9b2bb387e1799710f903344))

- Adicionar modo remoto ao CLI via [server] no config.toml (079)
  ([`47913cc`](https://github.com/rennancockles/kanbai/commit/47913ccabac9f0c3b932465ce23594d7df370d8c))

- Adicionar onboarding entre board local e hospedado (080)
  ([`973c75e`](https://github.com/rennancockles/kanbai/commit/973c75ece9f1e5738db1e991bcb325e9fc3ea137))

- Adicionar view multi-board no hub (088)
  ([`639dc2f`](https://github.com/rennancockles/kanbai/commit/639dc2fa030a57be0356115f61d5961a66a9e90a))

- Agrupar boards por categoria no hub (086)
  ([`dda4fdf`](https://github.com/rennancockles/kanbai/commit/dda4fdf4394732d05852c872489445dddd5aceab))

- Exibir contagens de cards por coluna na landing page do hub (088)
  ([`7863da0`](https://github.com/rennancockles/kanbai/commit/7863da0d9773ac866f581c25857c2833d8e650c3))

- Filtro de categoria no board switcher do hub (087)
  ([`ae73597`](https://github.com/rennancockles/kanbai/commit/ae735975c631d44a8998464e15ed50a2656ea2ac))

- Kanbai init now merges Skill(kanbai-*) into permissions.allow
  ([`5269b58`](https://github.com/rennancockles/kanbai/commit/5269b587fa4500d3bc6219e102497f9469f6d1cc))


## v0.7.0 (2026-09-28)

### Documentation

- Atualizar screenshots e consolidar assets em docs/assets
  ([`7558a1d`](https://github.com/rennancockles/kanbai/commit/7558a1d6fed28891c950f74c7a7d1115e520e680))

### Features

- Adicionar comando 'kanbai --version' (075)
  ([`4344ea5`](https://github.com/rennancockles/kanbai/commit/4344ea54814644e9cd7233bc6b124a7a89b966d8))


## v0.6.0 (2026-09-27)

### Bug Fixes

- Hub nao derruba boards saudaveis quando outro tem config.toml ilegivel (073)
  ([`5c8d64e`](https://github.com/rennancockles/kanbai/commit/5c8d64e1b37c14066fc78729244f42f88b8b37a0))

### Documentation

- Atualizar README e site com features das ultimas sprints (074)
  ([`c049609`](https://github.com/rennancockles/kanbai/commit/c049609bfb05c19cca19ae0644e7619edeb5b281))

### Features

- Input de IA na topbar para criar cards, provider-agnostic (069)
  ([`77fcc63`](https://github.com/rennancockles/kanbai/commit/77fcc633177134dcf56e50ec3d3d9e350e5eb476))

- Opcao bypass_review no config para pular a coluna review (030)
  ([`a98c681`](https://github.com/rennancockles/kanbai/commit/a98c681377045fcdca98a4f014978b4f5e361b8a))

- Pagina de erro 404 estilizada no hub/UI (072)
  ([`d166fa5`](https://github.com/rennancockles/kanbai/commit/d166fa5a24ea966948cf38db74222bfb1f61db7e))

- Rodar o hub como daemon em background (071)
  ([`d1ac4c4`](https://github.com/rennancockles/kanbai/commit/d1ac4c42e913294b7463b96af915e97792b67cd8))


## v0.5.1 (2026-09-25)

### Bug Fixes

- Hub detecta boards registrados apos o startup, sem restart (067)
  ([`4d99c68`](https://github.com/rennancockles/kanbai/commit/4d99c688210afedb2355d0bad0c74213b35f6224))

### Refactoring

- Nomear boards do hub pelo config.toml, mover versao para tooltip (065, 068)
  ([`dcd113c`](https://github.com/rennancockles/kanbai/commit/dcd113cbe4803388a1ef0c78424ff138d1ecbc49))


## v0.5.0 (2026-09-25)

### Bug Fixes

- **ci**: Fundir version e release em um workflow (062, 063)
  ([`2539ae2`](https://github.com/rennancockles/kanbai/commit/2539ae2a2db84687653bb128b5bc0e166b98b06a))

### Features

- Notificar via Claude Code Notification hook (064)
  ([`c426e5b`](https://github.com/rennancockles/kanbai/commit/c426e5b2011a01a2d83effe048ec9672604d8ded))


## v0.4.1 (2026-09-25)

### Bug Fixes

- Simplificar notify_ntfy, sincrona no CLI e background na web (061)
  ([`95e6278`](https://github.com/rennancockles/kanbai/commit/95e627806357aa572731726c72a64ba422d233fa))

### Continuous Integration

- Enable python semantic release
  ([`9930bcf`](https://github.com/rennancockles/kanbai/commit/9930bcf21bedf421d3f4be168e1de4a0d1658da2))

## [Unreleased]

## [0.4.0] - 2026-09-24

### Added

- **Notifications** — get notified (native desktop and/or [ntfy](https://ntfy.sh) push) the
  moment a card reaches `review` (or `done`, on boards with no `review` column), and again if
  that move leaves the sprint with no actionable card left. Fires from `Board.move()` itself,
  so it works from any command (`kanbai review`/`done`/`move`, drag-and-drop in the web UI) —
  no background process required. Configurable via `[notifications]` in `config.toml`
  (`native`, on by default; `ntfy_topic`, off by default).

### Changed

- Dropped the earlier watcher-based design (a live SSE stream plus a standalone `kanbai
  watch` command and a browser-notification channel) in favor of the event-driven approach
  above — the watcher only fired while `kanbai ui`/`hub`/`watch` was already running, which
  missed the common case of cards moved via a plain CLI command.

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

[Unreleased]: https://github.com/rennancockles/kanbai/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/rennancockles/kanbai/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/rennancockles/kanbai/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/rennancockles/kanbai/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/rennancockles/kanbai/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/rennancockles/kanbai/releases/tag/v0.1.0
