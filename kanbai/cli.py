"""The ``kanbai`` command-line interface."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import APP_NAME, registry, scaffold, storage
from .board import Board
from .errors import KanbaiError
from .models import Card, Priority

app = typer.Typer(
    name="kanbai",
    help="A file-based Kanban board for Claude Code and other AI coding harnesses.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)

_PRIORITY_STYLE = {
    Priority.high: "bold red",
    Priority.medium: "yellow",
    Priority.low: "dim",
}


# --------------------------------------------------------------------------- helpers


def _load() -> Board:
    """Load the board or exit with a friendly message."""
    try:
        return Board.load()
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


def _warn_over_wip(board: Board, column: str) -> None:
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
    """Finish a card: move it to the review column to await approval."""
    board = _load()
    target = board.config.review_column or board.config.done_column
    card = board.move(card_id, target)
    _emit_card(
        card,
        as_json,
        f"[green]✓[/green] Finished [cyan]{card.id}[/cyan] → [bold]{card.status}[/bold] "
        "[dim](awaiting approval)[/dim]",
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


@app.command(name="new-sprint")
def new_sprint(
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
    """Start a new sprint: archive all done cards (optionally reset active columns)."""
    board = _load()
    if not yes:
        extra = " and move active cards to the backlog" if to_backlog else ""
        typer.confirm(f"Archive all done cards{extra}?", abort=True)
    result = board.new_sprint(reset_to_backlog=to_backlog, version=version)
    message = f"[green]✓[/green] New sprint: archived {result['archived']} done card(s)"
    if to_backlog:
        message += f", moved {result['reset']} back to backlog"
    console.print(message)


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
    serve_hub(boards, host=host, port=port, open_browser=not no_browser)


@hub_app.command("add")
def hub_add(
    path: Path = typer.Argument(..., help="Path to a project containing a .kanbai board."),
    name: str | None = typer.Option(
        None, "--name", help="Name for the board (default: the directory name)."
    ),
) -> None:
    """Register a board in the hub."""
    try:
        registered, replaced = registry.add_board(path, name)
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
def hub_remove(name: str = typer.Argument(..., help="Registered board name.")) -> None:
    """Remove a board from the hub."""
    try:
        registry.remove_board(name)
    except KanbaiError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]✓[/green] Removed [cyan]{name}[/cyan]")


if __name__ == "__main__":  # pragma: no cover
    app()
