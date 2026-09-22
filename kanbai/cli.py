"""The ``kanbai`` command-line interface."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import APP_NAME, scaffold
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


def _emit_card(card: Card, as_json: bool, message: str | None = None) -> None:
    if as_json:
        console.print_json(data=_card_dict(card))
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
    table.add_column("pri", no_wrap=True)
    table.add_column("labels", style="magenta")
    for card in cards:
        table.add_row(
            card.id,
            card.title,
            _priority_cell(card.priority),
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
def add(
    title: str = typer.Argument(..., help="Card title."),
    description: str = typer.Option("", "--desc", "-d", help="Card description / body."),
    priority: Priority | None = typer.Option(None, "--priority", "-p", help="Card priority."),
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
    as_json: bool = typer.Option(False, "--json", help="Emit the board as JSON."),
) -> None:
    """Show the board, or a single column."""
    board = _load()
    if column is not None:
        cards = board.list_column(column)
        if as_json:
            console.print_json(data=[_card_dict(c) for c in cards])
        else:
            console.print(_render_column_table(column, cards))
        return

    data = board.board()
    if as_json:
        console.print_json(data={c: [_card_dict(x) for x in cs] for c, cs in data.items()})
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
            console.print_json(data=None)
        else:
            console.print("[dim]Nothing to do — the backlog is empty or fully blocked.[/dim]")
        raise typer.Exit(code=0)
    if as_json:
        console.print_json(data=_card_dict(card))
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
        console.print_json(data=_card_dict(card))
        return
    deps = ", ".join(card.deps) or "—"
    labels = ", ".join(card.labels) or "—"
    body = f"\n\n{card.body}" if card.body else ""
    console.print(
        Panel(
            f"[bold]{card.title}[/bold]\n"
            f"status: {card.status}   priority: {_priority_cell(card.priority)}   "
            f"order: {card.order}\n"
            f"labels: {labels}   deps: {deps}   assignee: {card.assignee or '—'}"
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
def edit(
    card_id: str = typer.Argument(..., help="Card id."),
    title: str | None = typer.Option(None, "--title", help="New title."),
    description: str | None = typer.Option(None, "--desc", "-d", help="New description / body."),
    priority: Priority | None = typer.Option(None, "--priority", "-p", help="New priority."),
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
            "[red]error:[/red] the web UI needs the \"ui\" extra. Install it with "
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


if __name__ == "__main__":  # pragma: no cover
    app()
