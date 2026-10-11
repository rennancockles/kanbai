"""The ``kanbai`` command-line interface."""

from __future__ import annotations

import contextlib
import json
import socket
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import APP_NAME, __version__, daemon, hosted, registry, scaffold, storage
from .board import Board
from .config import RemoteConfig, load_remote_config
from .errors import KanbaiError, RemoteAPIError
from .models import Card, Priority
from .notify_ntfy import notify_ntfy
from .remote_board import RemoteBoard, list_remote_boards, login

#: Either a local, filesystem-backed board or a hosted one talking to a kanbai_server API —
#: every command function below only calls verbs both implement, so callers never branch on
#: which one `_load()` returned.
AnyBoard = Board | RemoteBoard

app = typer.Typer(
    name="kanbai",
    help="A file-based Kanban board for Claude Code and other AI coding harnesses.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)


def _print_version(value: bool) -> None:
    if value:
        console.print(f"kanbai {__version__}")
        raise typer.Exit


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_print_version,
        is_eager=True,
        help="Show the installed kanbai version and exit.",
    ),
) -> None:
    pass


_PRIORITY_STYLE = {
    Priority.high: "bold red",
    Priority.medium: "yellow",
    Priority.low: "dim",
}


# --------------------------------------------------------------------------- helpers

# Notification-hook `notification_type` values that mean Claude Code is stuck waiting on the
# user (as opposed to e.g. a completed subagent or an auth event) — see `notify_hook()`.
_WAITING_NOTIFICATION_TYPES = frozenset({"agent_needs_input", "permission_prompt", "idle_prompt"})


def _notify(board: AnyBoard, title: str, body: str) -> None:
    """``Board.on_notify`` for the CLI: ntfy always, native desktop if the extra is installed.

    Native notifications need the optional ``ui`` extra (``desktop-notifier``); a plain CLI
    install silently skips that channel rather than failing the command that triggered it.
    """
    if board.config.notifications_ntfy_topic:
        notify_ntfy(board.config.notifications_ntfy_topic, title, body)
    if not board.config.notifications_native:
        return
    try:
        from .web.notify import notify_native  # noqa: PLC0415 - optional extra, on demand
    except ImportError:
        return
    notify_native(title, body)


def _load_board_at(start: Path | None) -> AnyBoard:
    """Load the board at (or above) ``start`` — remote if its `config.toml` has a complete
    `[server]` section, local (filesystem-backed) otherwise. Raises :class:`KanbaiError`."""
    kanbai_dir = storage.find_kanbai_dir(start)
    remote = load_remote_config(kanbai_dir) if kanbai_dir is not None else None
    board: AnyBoard = RemoteBoard(remote) if remote is not None else Board.load(start)
    board.on_notify = lambda title, body: _notify(board, title, body)
    return board


def _load() -> AnyBoard:
    """Load the board from the current directory, or exit with a friendly message."""
    try:
        return _load_board_at(None)
    except KanbaiError as exc:  # pragma: no cover - exercised via CLI tests
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


def _card_dict(card: Card) -> dict[str, object]:
    return card.model_dump(mode="json")


def _emit_json(data: object) -> None:
    """Print machine-readable JSON — always plain text.

    We use ``json.dumps`` (not rich's ``print_json``) so ``--json`` output stays parseable
    even when a color-forcing env var like ``FORCE_COLOR`` is set, which would otherwise make
    rich wrap the JSON in ANSI escape codes.
    """
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _emit_card(card: Card, as_json: bool, message: str | None = None) -> None:
    if as_json:
        _emit_json(_card_dict(card))
    elif message:
        console.print(message)


def _warn_over_wip(board: AnyBoard, column: str) -> None:
    """Warn (on stderr) when ``column`` is over its configured WIP limit — never blocks."""
    limit = board.config.wip_limit(column)
    if limit is None:
        return
    count = len(board.list_column(column))
    if count > limit:
        err_console.print(
            f"[yellow]![/yellow] Column '{column}' is over its WIP limit ({count}/{limit})."
        )


def _priority_cell(priority: Priority) -> str:
    style = _PRIORITY_STYLE[priority]
    return f"[{style}]{priority.value}[/{style}]"


def _render_column_table(column: str, cards: list[Card]) -> Table:
    table = Table(title=f"{column} ({len(cards)})", title_justify="left", expand=True)
    table.add_column("id", style="cyan", no_wrap=True)
    table.add_column("title")
    table.add_column("type", style="blue", no_wrap=True)
    table.add_column("pri", no_wrap=True)
    table.add_column("version", style="green", no_wrap=True)
    table.add_column("labels", style="magenta")
    for card in cards:
        table.add_row(
            card.id,
            card.title,
            card.type or "—",
            _priority_cell(card.priority),
            card.version or "—",
            ", ".join(card.labels),
        )
    return table


# --------------------------------------------------------------------------- commands


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
    name: str | None = typer.Option(None, "--name", help="Board name for config.toml."),
) -> None:
    """Scaffold a `.kanbai/` board and install the Claude Code integration.

    Safe to re-run: it only creates what is missing (use --force to overwrite).
    """
    try:
        result = scaffold.init_board(Path.cwd(), force=force, name=name)
    except OSError as exc:
        err_console.print(f"[red]error:[/red] could not create the board: {exc}")
        raise typer.Exit(code=1) from exc

    if result.created:
        console.print(f"[green]✓[/green] {APP_NAME} board at [cyan]{result.kanbai_dir}[/cyan]")
        for line in result.created:
            console.print(f"  [dim]created[/dim] {line}")
    else:
        console.print(
            f"[green]✓[/green] {APP_NAME} board already up to date at "
            f"[cyan]{result.kanbai_dir}[/cyan]"
        )

    if result.failed:
        err_console.print(
            "\n[yellow]![/yellow] Some Claude integration files could not be written "
            "(the board itself is fine):"
        )
        for path, reason in result.failed:
            err_console.print(f"  [dim]skipped[/dim] {path} [dim]({reason})[/dim]")
        err_console.print(
            "  This is usually a restricted environment (e.g. a command sandbox). "
            "Re-run [cyan]kanbai init[/cyan] from an unrestricted shell to install them."
        )

    console.print(
        "\nNext steps:\n"
        "  1. Allow the CLI for Claude without prompts by adding "
        '[cyan]Bash(kanbai *)[/cyan] to .claude/settings.json "permissions.allow".\n'
        '  2. Create your first card: [cyan]kanbai add "My first task"[/cyan]\n'
        f"  3. In Claude Code, ask it to work through the {APP_NAME} board."
    )


@app.command()
def add(  # noqa: PLR0913 - one option per card field
    title: str = typer.Argument(..., help="Card title."),
    description: str = typer.Option("", "--desc", "-d", help="Card description / body."),
    priority: Priority | None = typer.Option(None, "--priority", "-p", help="Card priority."),
    type: str | None = typer.Option(None, "--type", "-t", help="Card type."),  # noqa: A002
    version: str | None = typer.Option(None, "--version", "-v", help="Release version."),
    column: str | None = typer.Option(None, "--column", "-c", help="Target column."),
    labels: list[str] | None = typer.Option(None, "--label", "-l", help="Label (repeatable)."),
    deps: list[str] | None = typer.Option(None, "--dep", help="Blocking card id (repeatable)."),
    assignee: str | None = typer.Option(None, "--assignee", "-a", help="Assignee."),
    as_json: bool = typer.Option(False, "--json", help="Emit the created card as JSON."),
) -> None:
    """Create a new card (defaults to the backlog column)."""
    board = _load()
    card = board.add(
        title,
        description=description,
        priority=priority,
        type=type,
        version=version,
        column=column,
        labels=labels,
        deps=deps,
        assignee=assignee,
    )
    _emit_card(
        card,
        as_json,
        f"[green]✓[/green] Created [cyan]{card.id}[/cyan] in "
        f"[bold]{card.status}[/bold]: {card.title}",
    )
    _warn_over_wip(board, card.status)


@app.command(name="list")
def list_cards(
    column: str | None = typer.Argument(None, help="Only show this column."),
    type: str | None = typer.Option(None, "--type", "-t", help="Only show cards of this type."),  # noqa: A002
    as_json: bool = typer.Option(False, "--json", help="Emit the board as JSON."),
) -> None:
    """Show the board, a single column, or the ``archive``."""
    board = _load()

    def filtered(cards: list[Card]) -> list[Card]:
        return [c for c in cards if c.type == type] if type else cards

    if column is not None:
        cards = filtered(
            board.list_archive() if column == storage.ARCHIVE_DIRNAME else board.list_column(column)
        )
        if as_json:
            _emit_json([_card_dict(c) for c in cards])
        else:
            console.print(_render_column_table(column, cards))
        return

    data = {col: filtered(cards) for col, cards in board.board().items()}
    if as_json:
        _emit_json({c: [_card_dict(x) for x in cs] for c, cs in data.items()})
        return
    for col, cards in data.items():
        console.print(_render_column_table(col, cards))


@app.command()
def next(  # noqa: A001 - "next" mirrors the user-facing verb
    as_json: bool = typer.Option(False, "--json", help="Emit the next card as JSON."),
) -> None:
    """Print the next actionable card in the backlog."""
    board = _load()
    card = board.next()
    if card is None:
        if as_json:
            _emit_json(None)
        else:
            console.print("[dim]Nothing to do — the backlog is empty or fully blocked.[/dim]")
        raise typer.Exit(code=0)
    if as_json:
        _emit_json(_card_dict(card))
    else:
        body = f"\n\n{card.body}" if card.body else ""
        console.print(
            Panel(
                f"[bold]{card.title}[/bold]  ({_priority_cell(card.priority)}){body}",
                title=f"next → {card.id}",
                title_align="left",
            )
        )


@app.command()
def show(
    card_id: str = typer.Argument(..., help="Card id."),
    as_json: bool = typer.Option(False, "--json", help="Emit the card as JSON."),
) -> None:
    """Show the full details of a card."""
    board = _load()
    card = board.show(card_id)
    if as_json:
        _emit_json(_card_dict(card))
        return
    deps = ", ".join(card.deps) or "—"
    labels = ", ".join(card.labels) or "—"
    body = f"\n\n{card.body}" if card.body else ""
    console.print(
        Panel(
            f"[bold]{card.title}[/bold]\n"
            f"status: {card.status}   type: {card.type or '—'}   "
            f"priority: {_priority_cell(card.priority)}   order: {card.order}\n"
            f"labels: {labels}   deps: {deps}   assignee: {card.assignee or '—'}   "
            f"version: {card.version or '—'}"
            f"{body}",
            title=f"card {card.id}",
            title_align="left",
        )
    )


@app.command()
def move(
    card_id: str = typer.Argument(..., help="Card id."),
    column: str = typer.Argument(..., help="Destination column."),
    as_json: bool = typer.Option(False, "--json", help="Emit the moved card as JSON."),
) -> None:
    """Move a card to a column."""
    board = _load()
    card = board.move(card_id, column)
    _emit_card(
        card,
        as_json,
        f"[green]✓[/green] Moved [cyan]{card.id}[/cyan] → [bold]{card.status}[/bold]",
    )
    _warn_over_wip(board, card.status)


@app.command()
def start(
    card_id: str = typer.Argument(..., help="Card id."),
    as_json: bool = typer.Option(False, "--json", help="Emit the moved card as JSON."),
) -> None:
    """Move a card to the in-progress column."""
    board = _load()
    card = board.move(card_id, board.config.doing_column)
    _emit_card(
        card,
        as_json,
        f"[green]✓[/green] Started [cyan]{card.id}[/cyan] → [bold]{card.status}[/bold]",
    )
    _warn_over_wip(board, card.status)


@app.command()
def review(
    card_id: str = typer.Argument(..., help="Card id."),
    as_json: bool = typer.Option(False, "--json", help="Emit the moved card as JSON."),
) -> None:
    """Finish a card: move it to the review column to await approval (or straight to done
    on a board with no review stage, e.g. ``bypass_review`` is set)."""
    board = _load()
    review = board.config.review_column
    target = review or board.config.done_column
    card = board.move(card_id, target)
    suffix = " [dim](awaiting approval)[/dim]" if review is not None else ""
    _emit_card(
        card,
        as_json,
        f"[green]✓[/green] Finished [cyan]{card.id}[/cyan] → [bold]{card.status}[/bold]{suffix}",
    )
    _warn_over_wip(board, card.status)


@app.command()
def done(
    card_id: str = typer.Argument(..., help="Card id."),
    as_json: bool = typer.Option(False, "--json", help="Emit the moved card as JSON."),
) -> None:
    """Approve a card: move it to the done column."""
    board = _load()
    card = board.move(card_id, board.config.done_column)
    _emit_card(
        card,
        as_json,
        f"[green]✓[/green] Approved [cyan]{card.id}[/cyan] → [bold]{card.status}[/bold]",
    )
    _warn_over_wip(board, card.status)


@app.command()
def edit(  # noqa: PLR0913 - one option per editable card field
    card_id: str = typer.Argument(..., help="Card id."),
    title: str | None = typer.Option(None, "--title", help="New title."),
    description: str | None = typer.Option(None, "--desc", "-d", help="New description / body."),
    priority: Priority | None = typer.Option(None, "--priority", "-p", help="New priority."),
    type: str | None = typer.Option(None, "--type", "-t", help="New type."),  # noqa: A002
    version: str | None = typer.Option(None, "--version", "-v", help="New release version."),
    labels: list[str] | None = typer.Option(None, "--label", "-l", help="Replace labels."),
    deps: list[str] | None = typer.Option(None, "--dep", help="Replace blocking card ids."),
    assignee: str | None = typer.Option(None, "--assignee", "-a", help="New assignee."),
    order: int | None = typer.Option(None, "--order", help="New in-column order."),
    as_json: bool = typer.Option(False, "--json", help="Emit the edited card as JSON."),
) -> None:
    """Update fields on a card (only the options you pass change)."""
    board = _load()
    card = board.edit(
        card_id,
        title=title,
        description=description,
        priority=priority,
        type=type,
        version=version,
        labels=labels,
        deps=deps,
        assignee=assignee,
        order=order,
    )
    _emit_card(card, as_json, f"[green]✓[/green] Updated [cyan]{card.id}[/cyan]")


@app.command()
def archive(
    card_id: str = typer.Argument(..., help="Card id."),
    as_json: bool = typer.Option(False, "--json", help="Emit the archived card as JSON."),
) -> None:
    """Archive a card (moves it off the board into `.kanbai/archive/`)."""
    board = _load()
    card = board.archive(card_id)
    _emit_card(card, as_json, f"[green]✓[/green] Archived [cyan]{card.id}[/cyan]")


@app.command()
def restore(
    card_id: str = typer.Argument(..., help="Archived card id."),
    as_json: bool = typer.Option(False, "--json", help="Emit the restored card as JSON."),
) -> None:
    """Restore an archived card to the column it came from (or the backlog)."""
    board = _load()
    card = board.restore(card_id)
    _emit_card(
        card,
        as_json,
        f"[green]✓[/green] Restored [cyan]{card.id}[/cyan] → [bold]{card.status}[/bold]",
    )


@app.command()
def rm(
    card_id: str = typer.Argument(..., help="Card id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Delete a card permanently."""
    board = _load()
    card = board.show(card_id)
    if not yes:
        typer.confirm(f"Delete card {card.id} ({card.title})?", abort=True)
    board.remove(card_id)
    console.print(f"[green]✓[/green] Deleted [cyan]{card.id}[/cyan]")


@app.command(name="close-sprint")
def close_sprint(
    to_backlog: bool = typer.Option(
        False,
        "--to-backlog",
        help="Also move todo/doing/review cards back to the backlog.",
    ),
    version: str | None = typer.Option(
        None, "--version", "-v", help="Stamp every archived done card with this release version."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Close the current sprint: archive all done cards (optionally reset active columns)."""
    board = _load()
    if not yes:
        extra = " and move active cards to the backlog" if to_backlog else ""
        typer.confirm(f"Archive all done cards{extra}?", abort=True)
    try:
        result = board.new_sprint(reset_to_backlog=to_backlog, version=version)
    except KanbaiError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    message = f"[green]✓[/green] Closed sprint: archived {result['archived']} done card(s)"
    if to_backlog:
        message += f", moved {result['reset']} back to backlog"
    console.print(message)


@app.command()
def sort(
    column: str = typer.Argument(..., help="Column to sort."),
    by: str = typer.Option("id", "--by", help="Sort key: id, priority, type, or title."),
    desc: bool = typer.Option(False, "--desc", help="Sort descending."),
    as_json: bool = typer.Option(False, "--json", help="Emit the sorted column as JSON."),
) -> None:
    """Sort a column and persist the new card order."""
    board = _load()
    try:
        cards = board.sort_column(column, by, descending=desc)
    except KanbaiError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if as_json:
        _emit_json([_card_dict(c) for c in cards])
    else:
        suffix = " desc" if desc else ""
        console.print(f"[green]✓[/green] Sorted [bold]{column}[/bold] by {by}{suffix}")


@app.command()
def ui(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind."),
    port: int = typer.Option(8000, "--port", help="Port to bind."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open a browser."),
    poll: bool = typer.Option(
        False,
        "--poll",
        help="Poll for board changes instead of OS file events "
        "(use in sandboxes/containers where live updates don't fire).",
    ),
    reload: bool = typer.Option(
        False,
        "--reload",
        help="Auto-restart the server when the source changes (development only).",
    ),
) -> None:
    """Serve the board in a local web UI and open it in your browser."""
    board = _load()
    if isinstance(board, RemoteBoard):
        err_console.print(
            "[red]error:[/red] `kanbai ui` serves a local filesystem board and does not "
            "support hosted (remote) boards yet."
        )
        raise typer.Exit(code=1)
    # Imported lazily so the core CLI never requires the optional "ui" extra.
    try:
        from .web.server import serve  # noqa: PLC0415 - optional extra, imported on demand
    except ImportError as exc:
        err_console.print(
            '[red]error:[/red] the web UI needs the "ui" extra. Install it with '
            "[cyan]pip install 'kanbai[ui]'[/cyan] (or [cyan]uv add 'kanbai[ui]'[/cyan])."
        )
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]›[/green] {APP_NAME} UI at [cyan]http://{host}:{port}[/cyan]  "
        "[dim](Ctrl+C to stop)[/dim]"
    )
    serve(
        board,
        host=host,
        port=port,
        open_browser=not no_browser,
        force_polling=poll,
        reload=reload,
    )


# --------------------------------------------------------------------------- hosted

hosted_app = typer.Typer(
    name="hosted",
    help="Connect a board to a hosted kanbai_server and keep both sides in step.",
    add_completion=False,
)
app.add_typer(hosted_app, name="hosted")

_NOT_CONNECTED_MSG = (
    "Not connected to a hosted board. Run `kanbai hosted connect` first "
    "(or `kanbai hosted clone` to copy an existing hosted board here)."
)


def _sync_summary(label: str, result: hosted.SyncResult) -> str:
    return (
        f"[green]✓[/green] {label}: {result.created} created, {result.updated} updated"
        + (f", {result.deleted} deleted" if result.deleted else "")
        + (f", {result.kept} kept on the other side" if result.kept else "")
        + "."
    )


def _connected_project() -> tuple[Path, RemoteConfig]:
    """The local ``.kanbai/`` dir and its ``[server]`` config, or a :class:`KanbaiError`
    asking the user to ``kanbai hosted connect`` first."""
    kanbai_dir = storage.find_kanbai_dir()
    if kanbai_dir is None:
        raise KanbaiError("No local kanbai board found here.")
    remote_config = load_remote_config(kanbai_dir)
    if remote_config is None:
        raise KanbaiError(_NOT_CONNECTED_MSG)
    return kanbai_dir, remote_config


def _pick_remote_board(
    boards: list[dict[str, str]], wanted: str | None, *, allow_create: bool
) -> str | None:
    """The id of the hosted board to use, or ``None`` to create a new one (``allow_create``).

    ``wanted`` (an id or a name) wins; otherwise the only board is taken when creating is not
    an option, and in every other case the user is asked.
    """
    if wanted is not None:
        matches = [b for b in boards if b["id"] == wanted] or [
            b for b in boards if b["name"].lower() == wanted.lower()
        ]
        if len(matches) > 1:
            raise KanbaiError(f"{len(matches)} boards are named '{wanted}'; pass --board <id>.")
        if not matches:
            names = ", ".join(b["name"] for b in boards) or "none"
            raise KanbaiError(f"No hosted board '{wanted}' (available: {names}).")
        return matches[0]["id"]
    if not boards:
        if allow_create:
            console.print("This account has no hosted boards yet — creating one.")
            return None
        raise KanbaiError(
            "This account has no hosted boards yet. Create one with `hosted connect`."
        )
    if len(boards) == 1 and not allow_create:
        return boards[0]["id"]
    if allow_create:
        console.print("  0. [bold]New board[/bold] (created from this one)")
    for number, board in enumerate(boards, start=1):
        console.print(f"  {number}. {board['name']} [dim]({board['id']})[/dim]")
    low = 0 if allow_create else 1
    choice: int = typer.prompt("Board number", type=int)
    if not low <= choice <= len(boards):
        raise KanbaiError(f"Choose a number between {low} and {len(boards)}.")
    return None if choice == 0 else str(boards[choice - 1]["id"])


@hosted_app.command("connect")
def hosted_connect(
    url: str = typer.Option(..., "--url", help="Base URL of the hosted kanbai_server."),
    email: str = typer.Option(..., "--email", help="Account email."),
    password: str | None = typer.Option(
        None, "--password", help="Account password (prompted for if omitted)."
    ),
    board: str | None = typer.Option(
        None, "--board", help="Hosted board id or name to connect to."
    ),
    create: bool = typer.Option(
        False, "--create", help="Create a new hosted board from this one and connect to it."
    ),
) -> None:
    """Connect this project to a hosted board and save the connection in `config.toml`.

    Logs in and writes a `[server]` section (url, token, board id). With --board it connects
    to an existing hosted board, with --create it makes a new one from this board; with
    neither you are asked to choose. No cards are sent or fetched — that is what
    `kanbai hosted push` / `pull` do, and they need this connection first.
    """
    try:
        kanbai_dir = storage.find_kanbai_dir()
        if kanbai_dir is None:
            raise KanbaiError(
                "No local kanbai board found here. Run `kanbai init` first, "
                "or `kanbai hosted clone` to copy a hosted board."
            )
        existing = load_remote_config(kanbai_dir)
        if existing is not None:
            raise KanbaiError(
                f"Already connected to board {existing.board_id} on {existing.url}. "
                "Remove the [server] section from config.toml to connect somewhere else."
            )
        if create and board is not None:
            raise KanbaiError("Pass either --board or --create, not both.")
        secret = password if password is not None else typer.prompt("Password", hide_input=True)
        token = login(url, email, secret)
        board_id = (
            None
            if create
            else _pick_remote_board(list_remote_boards(url, token), board, allow_create=True)
        )
        if board_id is None:
            remote_config = hosted.create_hosted_board(kanbai_dir, url, token)
            action = "Created and connected to"
        else:
            remote_config = RemoteConfig(url=url, token=token, board_id=board_id)
            action = "Connected to"
        hosted.save_connection(kanbai_dir, remote_config)
    except (KanbaiError, RemoteAPIError) as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]✓[/green] {action} hosted board [cyan]{remote_config.board_id}[/cyan] "
        f"on [cyan]{remote_config.url}[/cyan]. This project now runs in hosted mode."
    )


@hosted_app.command("push")
def hosted_push(
    delete: bool = typer.Option(
        False, "--delete", help="Remove hosted cards that no longer exist locally."
    ),
    archived: bool = typer.Option(
        False, "--archived", help="Also sync archived cards (left out by default)."
    ),
) -> None:
    """Local wins: send this board's cards to the hosted board.

    Needs the connection from `kanbai hosted connect`. Cards only here are created with
    their local ids; cards on both sides are updated or moved to match local. Archived cards
    are left alone unless you pass --archived (then they are created, archived or restored
    on the server to match local).
    """
    try:
        kanbai_dir, remote_config = _connected_project()
        result = hosted.push_board(
            RemoteBoard(remote_config), kanbai_dir, delete=delete, archived=archived
        )
    except (KanbaiError, RemoteAPIError) as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(_sync_summary("push", result))


@hosted_app.command("pull")
def hosted_pull(
    delete: bool = typer.Option(
        False, "--delete", help="Remove local cards that no longer exist on the server."
    ),
    archived: bool = typer.Option(
        False, "--archived", help="Also sync archived cards (left out by default)."
    ),
) -> None:
    """Server wins: update this board's files to match the hosted board.

    Needs the connection from `kanbai hosted connect`. Cards on both sides take the server's
    version (moving the file when the column differs, so nothing is duplicated); cards only
    on the server are written locally. Archived cards are left alone unless you pass
    --archived.
    """
    try:
        kanbai_dir, remote_config = _connected_project()
        result = hosted.pull_board(
            RemoteBoard(remote_config), kanbai_dir, delete=delete, archived=archived
        )
    except (KanbaiError, RemoteAPIError) as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(_sync_summary("pull", result))


@hosted_app.command("clone")
def hosted_clone(
    url: str = typer.Option(..., "--url", help="Base URL of the hosted kanbai_server."),
    email: str = typer.Option(..., "--email", help="Account email."),
    password: str | None = typer.Option(
        None, "--password", help="Account password (prompted for if omitted)."
    ),
    board: str | None = typer.Option(
        None, "--board", help="Hosted board id or name (asked for if the account has several)."
    ),
    archived: bool = typer.Option(
        False, "--archived", help="Also sync archived cards (left out by default)."
    ),
) -> None:
    """Create a local board here from a hosted one, already connected.

    The one command that connects by itself, since there is no project to hold the
    connection yet: it copies the hosted board's config and its cards (--archived adds the
    archived ones) into a new `.kanbai/` and saves the `[server]` connection. Fails if a
    local board already exists here — use `kanbai hosted pull` to update that one.
    """
    try:
        root = Path.cwd()
        if (root / storage.KANBAI_DIRNAME).exists():
            raise KanbaiError(
                "A local kanbai board already exists here; use `kanbai hosted pull` to update it."
            )
        secret = password if password is not None else typer.prompt("Password", hide_input=True)
        token = login(url, email, secret)
        board_id = _pick_remote_board(list_remote_boards(url, token), board, allow_create=False)
        if board_id is None:  # pragma: no cover - allow_create=False never yields None
            raise KanbaiError("No hosted board selected.")
        result = hosted.clone_board(
            root, RemoteConfig(url=url, token=token, board_id=board_id), archived=archived
        )
    except (KanbaiError, RemoteAPIError) as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(_sync_summary("clone", result))


@hosted_app.command("diff")
def hosted_diff(
    as_json: bool = typer.Option(False, "--json", help="Emit the diff as JSON."),
    archived: bool = typer.Option(
        False, "--archived", help="Also compare archived cards (left out by default)."
    ),
) -> None:
    """Compare the local board against the hosted one configured in `[server]`.

    Read-only — makes no changes to either side. Exits 0 if the two boards match, 1 if any
    differences are found (cards only on one side, or shared ids with differing fields).
    """
    try:
        kanbai_dir = storage.find_kanbai_dir()
        remote_config = load_remote_config(kanbai_dir) if kanbai_dir is not None else None
        if kanbai_dir is None or remote_config is None:
            raise KanbaiError(
                "No [server] section configured — nothing to compare. "
                "Run `kanbai hosted connect` first."
            )
        board_diff = hosted.diff_boards(
            Board.load(kanbai_dir.parent), RemoteBoard(remote_config), archived=archived
        )
    except (KanbaiError, RemoteAPIError) as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if as_json:
        _emit_json(
            {
                "in_sync": board_diff.in_sync,
                "only_local": board_diff.only_local,
                "only_remote": board_diff.only_remote,
                "changed": [
                    {
                        "card_id": c.card_id,
                        "changes": [
                            {"field": ch.field, "local": ch.local, "remote": ch.remote}
                            for ch in c.changes
                        ],
                    }
                    for c in board_diff.changed
                ],
            }
        )
    else:
        _print_board_diff(board_diff)

    raise typer.Exit(code=0 if board_diff.in_sync else 1)


def _print_board_diff(board_diff: hosted.BoardDiff) -> None:
    if board_diff.in_sync:
        console.print("[green]✓[/green] Local and hosted boards are in sync.")
        return
    err_console.print("[yellow]![/yellow] Local and hosted boards differ:")
    if board_diff.only_local:
        err_console.print(f"  only local:  {', '.join(board_diff.only_local)}")
    if board_diff.only_remote:
        err_console.print(f"  only hosted: {', '.join(board_diff.only_remote)}")
    for card_diff in board_diff.changed:
        err_console.print(f"  [cyan]{card_diff.card_id}[/cyan] differs:")
        for change in card_diff.changes:
            err_console.print(
                f"    {change.field}: local={change.local!r} hosted={change.remote!r}"
            )


# --------------------------------------------------------------------------- hub (multi-board)

hub_app = typer.Typer(
    name="hub",
    help="Serve or manage the multi-board hub (~/.kanbai/boards.toml).",
    add_completion=False,
)
app.add_typer(hub_app, name="hub")


@hub_app.callback(invoke_without_command=True)
def hub_serve(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind."),
    port: int = typer.Option(8000, "--port", help="Port to bind."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open a browser."),
) -> None:
    """Serve all registered boards on one port (use the subcommands to manage the registry)."""
    if ctx.invoked_subcommand is not None:
        return
    boards = registry.load_boards()
    if not boards:
        err_console.print(
            "[yellow]![/yellow] No boards registered. Add one with "
            "[cyan]kanbai hub add <path>[/cyan]."
        )
        raise typer.Exit(code=1)
    try:
        from .web.server import serve_hub  # noqa: PLC0415 - optional extra, imported on demand
    except ImportError as exc:
        err_console.print(
            '[red]error:[/red] the hub needs the "ui" extra. Install it with '
            "[cyan]pip install 'kanbai[ui]'[/cyan]."
        )
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]›[/green] {APP_NAME} hub at [cyan]http://{host}:{port}[/cyan] "
        f"[dim]({len(boards)} board(s), Ctrl+C to stop)[/dim]"
    )
    # Pass the loader itself (not the already-resolved `boards`) so the hub re-reads the
    # registry per request and picks up boards added via `kanbai hub add` while it runs.
    serve_hub(registry.load_boards, host=host, port=port, open_browser=not no_browser)


@hub_app.command("add")
def hub_add(
    path: Path = typer.Argument(..., help="Path to a project containing a .kanbai board."),
) -> None:
    """Register a board in the hub."""
    try:
        registered, replaced = registry.add_board(path)
    except KanbaiError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    verb = "Updated" if replaced else "Registered"
    console.print(f"[green]✓[/green] {verb} board [cyan]{registered}[/cyan]")


@hub_app.command("list")
def hub_list(
    as_json: bool = typer.Option(False, "--json", help="Emit the registry as JSON."),
) -> None:
    """List the registered boards."""
    boards = registry.load_boards()
    if as_json:
        _emit_json(boards)
        return
    if not boards:
        console.print("[dim]No boards registered. Add one with `kanbai hub add <path>`.[/dim]")
        return
    table = Table(title="hub boards", title_justify="left")
    table.add_column("name", style="cyan", no_wrap=True)
    table.add_column("path")
    for name, location in boards.items():
        table.add_row(name, location)
    console.print(table)


@hub_app.command("remove")
def hub_remove(
    name: str = typer.Argument(..., help="Registered board name or path to the board directory."),
) -> None:
    """Remove a board from the hub."""
    try:
        resolved = registry.resolve_name(name)
        registry.remove_board(resolved)
    except KanbaiError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]✓[/green] Removed [cyan]{resolved}[/cyan]")


def _require_ui_extra() -> None:
    """Fail with a friendly message if the optional ``ui`` extra isn't installed."""
    try:
        import kanbai.web.server  # noqa: F401, PLC0415 - optional extra, checked on demand
    except ImportError as exc:
        err_console.print(
            '[red]error:[/red] the hub needs the "ui" extra. Install it with '
            "[cyan]pip install 'kanbai[ui]'[/cyan]."
        )
        raise typer.Exit(code=1) from exc


@hub_app.command("start")
def hub_start(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind."),
    port: int = typer.Option(8000, "--port", help="Port to bind."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open a browser."),
) -> None:
    """Start the hub as a detached background process."""
    if not registry.load_boards():
        err_console.print(
            "[yellow]![/yellow] No boards registered. Add one with "
            "[cyan]kanbai hub add <path>[/cyan]."
        )
        raise typer.Exit(code=1)
    _require_ui_extra()
    try:
        info = daemon.start(host, port)
    except KanbaiError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]✓[/green] Hub started (pid {info.pid}) at "
        f"[cyan]http://{info.host}:{info.port}[/cyan] "
        f"[dim](logs: {daemon.log_path()})[/dim]"
    )
    if not no_browser:
        _open_browser_when_ready(f"http://{info.host}:{info.port}")


def _open_browser_when_ready(url: str, *, timeout: float = 2.0) -> None:
    """Open ``url`` in a browser once it accepts connections, giving up after ``timeout``."""
    parsed = urlparse(url)
    host, port = parsed.hostname or "127.0.0.1", parsed.port or 80
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError), socket.create_connection((host, port), timeout=0.2):
            webbrowser.open(url)
            return
        time.sleep(0.1)


@hub_app.command("stop")
def hub_stop() -> None:
    """Stop the background hub daemon."""
    try:
        daemon.stop()
    except KanbaiError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print("[green]✓[/green] Hub stopped")


@hub_app.command("status")
def hub_status(as_json: bool = typer.Option(False, "--json", help="Emit status as JSON.")) -> None:
    """Check whether the hub daemon is running."""
    info = daemon.status()
    if as_json:
        _emit_json(
            {"running": info is not None}
            if info is None
            else {"running": True, "pid": info.pid, "host": info.host, "port": info.port}
        )
        return
    if info is None:
        console.print("[dim]○ not running[/dim]")
        return
    console.print(
        f"[green]●[/green] running (pid {info.pid}) at [cyan]http://{info.host}:{info.port}[/cyan]"
    )


@hub_app.command("logs")
def hub_logs(
    follow: bool = typer.Option(False, "--follow", "-f", help="Keep printing new log lines."),
) -> None:
    """Show (or follow) the hub daemon's log."""
    path = daemon.log_path()
    if not path.exists():
        err_console.print(
            f"[red]error:[/red] no log file at {path} — has the hub ever been started?"
        )
        raise typer.Exit(code=1)
    with path.open(encoding="utf-8") as handle:
        console.print(handle.read(), end="")
        if not follow:
            return
        with contextlib.suppress(KeyboardInterrupt):
            while True:
                line = handle.readline()
                if line:
                    console.print(line, end="")
                else:
                    time.sleep(0.5)


@app.command(name="notify-hook", hidden=True)
def notify_hook() -> None:
    """Claude Code `Notification` hook entrypoint, installed by `kanbai init` — not for humans.

    Reads the hook's JSON payload from stdin and, when `notification_type` means Claude is
    waiting on the user, fires the same notification channels configured in config.toml
    (native/ntfy) via `_notify()`. Every failure mode (malformed input, no board found at the
    payload's `cwd`, a notification backend raising) is a silent no-op — this command is
    invoked by Claude Code itself, so it must never exit non-zero or raise.
    """
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    if not isinstance(payload, dict):
        return
    if payload.get("notification_type") not in _WAITING_NOTIFICATION_TYPES:
        return

    cwd = payload.get("cwd")
    start = Path(cwd) if isinstance(cwd, str) and cwd else None
    try:
        board = _load_board_at(start)
    except KanbaiError:
        return

    title = f"{board.config.name}: Claude needs input"
    with contextlib.suppress(Exception):  # must never surface as a Claude Code hook error
        _notify(board, title, "Claude Code is waiting for you.")


if __name__ == "__main__":  # pragma: no cover
    app()
