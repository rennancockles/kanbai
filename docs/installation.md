# Installation

KanbAI is a Python package (Python 3.10+). Install it as a **dev dependency** of the project
whose board you want to manage.

## Add it to a project

=== "uv"

    ```bash
    uv add --dev kanbai
    ```

=== "pip"

    ```bash
    pip install kanbai
    ```

=== "Poetry"

    ```bash
    poetry add --group dev kanbai
    ```

This gives you the `kanbai` command.

## The web UI extra

The [web UI](web-ui.md) and [multi-board hub](hub.md) need a few extra packages (FastAPI,
Uvicorn, …). Install the `ui` extra to enable them:

=== "uv"

    ```bash
    uv add --dev 'kanbai[ui]'
    ```

=== "pip"

    ```bash
    pip install 'kanbai[ui]'
    ```

Without the extra, the CLI works fully; only `kanbai ui` / `kanbai hub` are unavailable.

## Installing globally (for the hub)

The [hub](hub.md) serves the boards of **several** projects at once, so it makes sense to
install KanbAI globally rather than per-project:

```bash
pipx install 'kanbai[ui]'
# or run it without installing anything:
uvx --from 'kanbai[ui]' kanbai hub
```

## Verify

```bash
kanbai --help          # list all commands
kanbai --version       # print the installed version
```

Next: scaffold a board with [`kanbai init`](cli.md#init) and read about the
[concepts](concepts.md).
