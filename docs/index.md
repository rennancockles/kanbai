---
title: KanbAI
template: home.html
hide:
  - navigation
  - toc
---

## Why KanbAI

<div class="grid cards" markdown>

- :material-source-repository: **The board lives in your repo**

    ---

    One Markdown card per task, one folder per column — git-friendly, diffable, no external
    service, no database.

- :material-robot-happy: **Your agent drives it**

    ---

    `kanbai init` installs a rule + skills so Claude Code picks the next task, implements it,
    and moves it across the board.

- :material-check-decagram: **You stay in control**

    ---

    Finished work waits in `review` for your approval, and a friendly local web UI lets you
    watch everything live.

</div>

## Get started in 30 seconds

=== "pip"

    ```bash
    pip install kanbai
    kanbai init
    kanbai add "Build the login screen" -p high
    kanbai move 001 todo
    kanbai list
    ```

=== "uv"

    ```bash
    uv add --dev kanbai
    kanbai init
    kanbai add "Build the login screen" -p high
    kanbai move 001 todo
    kanbai list
    ```

Then open a Claude Code session and ask it to *“work through the KanbAI board”*.

<div class="kx-shot" markdown>
![The KanbAI web UI](assets/webui.png)
</div>

## Explore the docs

<div class="grid cards" markdown>

- :material-download: **[Installation](installation.md)** — pip, uv, or pipx/uvx.
- :material-lightbulb-on: **[Concepts](concepts.md)** — columns, the sprint workflow, dependencies.
- :material-console: **[CLI reference](cli.md)** — every command, flag by flag.
- :material-robot: **[Working with Claude Code](claude-code.md)** — the one-card-at-a-time loop.
- :material-monitor-dashboard: **[Web UI](web-ui.md)** — the local board with live updates.
- :material-view-grid-plus: **[Multi-board hub](hub.md)** — all your projects on one port.

</div>

KanbAI is released under the [MIT License](https://github.com/rennancockles/kanbai/blob/main/LICENSE).
