"""Connect, push, pull and clone between local (filesystem) and hosted (kanbai_server) boards.

A project is *connected* when its ``config.toml`` has a ``[server]`` section, written by
:func:`save_connection` (switching it into remote mode, see ``kanbai.remote_board``);
:func:`create_hosted_board` provisions a new hosted board from the local one to connect to.
Every other function here assumes the connection exists.

:func:`push_board` (local wins) and :func:`pull_board` (server wins) are the only two ways
cards move between the sides. Both work by card id and never duplicate. Archived cards are
left out unless ``archived=True``. ``clone_board`` creates a local board from a hosted one;
:func:`diff_boards` compares the two read-only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from . import credentials, scaffold, storage, sync_state
from .board import Board
from .config import CONFIG_FILENAME, RemoteConfig, load_config, load_remote_config, render_config
from .errors import HostUnreachableError, KanbaiError, RemoteAPIError
from .models import BoardConfig, Card
from .remote_board import SETTINGS, RemoteBoard, create_remote_board

#: Card fields compared by :func:`diff_boards`. Excludes ``id`` (the comparison key),
#: ``order`` (position noise, not meaningful content), and ``created``/``updated``
#: (timestamps that differ by nature between two independently-written copies).
_COMPARED_FIELDS = (
    "title",
    "status",
    "priority",
    "type",
    "version",
    "labels",
    "deps",
    "assignee",
    "archived_from",
    "body",
)


def save_connection(kanbai_dir: Path, remote: RemoteConfig) -> None:
    """Write (or overwrite) ``[server]`` in ``config.toml``, replacing a prior section from
    an earlier publish rather than appending a second, conflicting one."""
    config_path = kanbai_dir / CONFIG_FILENAME
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    section = (
        "[server]\n"
        f'url = "{remote.url}"\n'
        f'token = "{remote.token}"\n'
        f'board_id = "{remote.board_id}"\n'
    ) + ("" if remote.enabled else "enabled = false\n")
    without_server = _remove_section(existing, "server").rstrip("\n")
    new_text = f"{without_server}\n\n{section}" if without_server else section
    config_path.write_text(new_text, encoding="utf-8")
    credentials.refresh_token(remote.url, remote.token)


NOT_CONNECTED_MSG = (
    "Not connected to a hosted board. Run `kanbai hosted connect` first "
    "(or `kanbai hosted clone` to copy an existing hosted board here)."
)


def set_enabled(kanbai_dir: Path, enabled: bool) -> RemoteConfig:
    """Switch hosted mode on or off, keeping the saved connection (url, token, board id).

    Raises :class:`KanbaiError` when the project is not connected. Returns the new config.
    """
    remote = load_remote_config(kanbai_dir)
    if remote is None:
        raise KanbaiError(NOT_CONNECTED_MSG)
    updated = replace(remote, enabled=enabled)
    save_connection(kanbai_dir, updated)
    return updated


def renew_token(kanbai_dir: Path, token: str) -> RemoteConfig:
    """Replace the saved access token, keeping url, board id and the enabled flag.

    Raises :class:`KanbaiError` when the project is not connected. Returns the new config.
    """
    remote = load_remote_config(kanbai_dir)
    if remote is None:
        raise KanbaiError(NOT_CONNECTED_MSG)
    updated = replace(remote, token=token)
    save_connection(kanbai_dir, updated)
    return updated


def _remove_section(toml_text: str, name: str) -> str:
    """Drop a top-level ``[name]`` table and its body (up to the next ``[...]`` or EOF)."""
    lines = toml_text.splitlines(keepends=True)
    kept: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped == f"[{name}]":
            skipping = True
            continue
        if skipping and stripped.startswith("[") and stripped.endswith("]"):
            skipping = False
        if not skipping:
            kept.append(line)
    return "".join(kept)


def _extract_section(toml_text: str, name: str) -> str:
    """The top-level ``[name]`` table with its body (up to the next ``[...]``), or ``""``."""
    kept: list[str] = []
    inside = False
    for line in toml_text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped == f"[{name}]":
            inside = True
        elif inside and stripped.startswith("[") and stripped.endswith("]"):
            break
        if inside:
            kept.append(line)
    return "".join(kept)


def _settings_view(config: BoardConfig, columns: list[str]) -> dict[str, object]:
    """The syncable settings of ``config``; WIP limits only count for columns that exist on
    the other side (``columns``), since the server drops the rest."""
    view = {name: getattr(config, name) for name in SETTINGS}
    view["wip"] = {col: limit for col, limit in config.wip.items() if col in columns}
    return view


def _differing_settings(source: BoardConfig, target: BoardConfig) -> list[str]:
    """Names of the settings whose value in ``source`` is not what ``target`` has."""
    wanted = _settings_view(source, target.columns)
    current = _settings_view(target, target.columns)
    return [name for name in SETTINGS if wanted[name] != current[name]]


def push_settings(remote: RemoteBoard, kanbai_dir: Path) -> list[str]:
    """Local wins: make the hosted board's settings (not its columns) match ``config.toml``.

    Returns the names of the settings that changed on the server (empty when already in sync).
    """
    local = load_config(kanbai_dir)
    changed = _differing_settings(local, remote.config)
    if changed:
        remote.update_settings(local)
    return changed


def pull_settings(remote: RemoteBoard, kanbai_dir: Path) -> list[str]:
    """Server wins: make ``config.toml``'s settings (not its columns) match the hosted board.

    Rewrites the config from the settings, so comments in the file are not kept; the
    ``[server]`` connection is. Returns the names of the settings that changed locally.
    """
    local = load_config(kanbai_dir)
    changed = _differing_settings(remote.config, local)
    if not changed:
        return []
    merged = local.model_copy(update=_settings_view(remote.config, local.columns))
    config_path = kanbai_dir / CONFIG_FILENAME
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    server = _extract_section(existing, "server").strip("\n")
    text = render_config(merged).rstrip("\n") + "\n"
    config_path.write_text(f"{text}\n{server}\n" if server else text, encoding="utf-8")
    return changed


def create_hosted_board(kanbai_dir: Path, url: str, token: str) -> RemoteConfig:
    """Provision a new hosted board matching the local board at ``kanbai_dir``.

    Only creates the board (no cards are sent) and returns how to reach it; the caller
    decides whether to :func:`save_connection`. ``token`` comes from ``remote_board.login``.
    """
    config = Board.load(kanbai_dir.parent).config
    return create_remote_board(url, token, config)


@dataclass(frozen=True)
class SyncResult:
    """What a :func:`push_board` or :func:`pull_board` changed on the receiving side."""

    created: int  # cards that did not exist there yet
    updated: int  # cards that existed but differed (fields, column or archived state)
    deleted: int  # cards only on the receiving side, removed with ``delete=True``
    kept: int  # cards only on the receiving side, left alone


@dataclass(frozen=True)
class SyncPlan:
    """What a push or pull is about to change on the receiving side, computed read-only.

    ``create`` and ``delete`` are card ids, ``update`` holds the field-level changes of the
    cards present on both sides, ``kept`` the ids only on the receiving side that are left
    alone. ``settings`` is ``None`` when the board settings are not part of the sync.
    """

    create: list[str]
    update: list[CardDiff]
    delete: list[str]
    kept: list[str]
    settings: list[FieldChange] | None = None

    @property
    def has_changes(self) -> bool:
        return bool(self.create or self.update or self.delete or self.settings)


@dataclass(frozen=True)
class _Cards:
    """The cards of both sides that a sync or diff should look at."""

    local: dict[str, Card]
    remote: dict[str, Card]


def _collect(board: Board, remote: RemoteBoard, *, archived: bool) -> _Cards:
    """Both sides' cards, by id.

    With ``archived`` the archives are included. Without it an archived card is only synced
    when the other side also has that id (active or archived): a card active on one side and
    archived on the other is therefore moved to match, but an archived card that exists on one
    side only is never created, overwritten or deleted. That also keeps ``--delete`` from
    removing the active twin of a card archived on the other side.
    """
    local = {c.id: c for column in board.columns for c in board.list_column(column)}
    other = {c.id: c for column in remote.columns for c in remote.list_column(column)}
    local_archived = {c.id: c for c in board.list_archive()}
    remote_archived = {c.id: c for c in remote.list_archive()}
    if not archived:
        local_ids = local.keys() | local_archived.keys()
        remote_ids = other.keys() | remote_archived.keys()
        local_archived = {i: c for i, c in local_archived.items() if i in remote_ids}
        remote_archived = {i: c for i, c in remote_archived.items() if i in local_ids}
    return _Cards(
        local={**local, **local_archived},
        remote={**other, **remote_archived},
    )


def push_board(
    remote: RemoteBoard, kanbai_dir: Path, *, delete: bool = False, archived: bool = False
) -> SyncResult:
    """Local wins: make the hosted board match the local files.

    Cards only local are created on the server keeping their local id (so deps and ids
    never diverge); cards on both sides are updated, moved or archived to match local.
    Cards only on the server are kept, or removed with ``delete=True``. Archived cards are
    only synced with ``archived=True`` (see :func:`_collect`).
    """
    board = Board.load(kanbai_dir.parent)
    cards = _collect(board, remote, archived=archived)
    local, existing = cards.local, cards.remote

    created = updated = 0
    for card_id in sorted(local):
        card = local[card_id]
        current = existing.get(card_id)
        if current is None:
            _create_remote(remote, card, board.config.add_column)
            created += 1
        elif _diff_card(card, current).changes:
            _update_remote(remote, card, current)
            updated += 1

    # Deps go last: a card can depend on one that is only created later in this loop.
    for card_id, card in local.items():
        current = existing.get(card_id)
        if card.deps != (current.deps if current is not None else []):
            remote.edit(card_id, deps=card.deps)

    only_remote = set(existing) - set(local)
    if delete:
        for card_id in only_remote:
            remote.remove(card_id)
    sync_state.clear_out_of_sync(kanbai_dir)
    return SyncResult(
        created=created,
        updated=updated,
        deleted=len(only_remote) if delete else 0,
        kept=0 if delete else len(only_remote),
    )


def _create_remote(remote: RemoteBoard, card: Card, add_column: str) -> None:
    archived = card.status == storage.ARCHIVE_DIRNAME
    uploaded = remote.add(
        card.title,
        card_id=card.id,
        description=card.body,
        priority=card.priority,
        type=card.type,
        version=card.version,
        column=(card.archived_from or add_column) if archived else card.status,
        labels=card.labels,
        assignee=card.assignee,
    )
    if archived:
        remote.archive(uploaded.id)


def _update_remote(remote: RemoteBoard, card: Card, current: Card) -> None:
    remote.edit(
        card.id,
        title=card.title,
        description=card.body,
        priority=card.priority,
        type=card.type,
        version=card.version,
        labels=card.labels,
        assignee=card.assignee,
    )
    if card.status == current.status:
        return
    if card.status == storage.ARCHIVE_DIRNAME:
        remote.archive(card.id)
        return
    status = current.status
    if status == storage.ARCHIVE_DIRNAME:
        status = remote.restore(card.id).status
    if status != card.status:
        remote.move(card.id, card.status)


def pull_board(
    remote: RemoteBoard, kanbai_dir: Path, *, delete: bool = False, archived: bool = False
) -> SyncResult:
    """Server wins: make the local files match the hosted board.

    Cards on both sides are overwritten with the server's version (moving the file when the
    column differs, so a card is never duplicated); cards only on the server are written
    locally. Cards only local are kept, or removed with ``delete=True``. Archived cards are
    only synced with ``archived=True`` (see :func:`_collect`).
    """
    board = Board.load(kanbai_dir.parent)
    cards = _collect(board, remote, archived=archived)
    local, incoming = cards.local, cards.remote

    created = updated = 0
    for card in incoming.values():
        current = local.get(card.id)
        if current is None:
            created += 1
        else:
            if _diff_card(current, card).changes:
                updated += 1
            if current.status != card.status:
                old = storage.find_card_path(kanbai_dir, board.columns, card.id)
                if old:
                    storage.delete_card_file(old[0])
        storage.write_card(kanbai_dir, card)

    only_local = set(local) - set(incoming)
    deleted = 0
    if delete:
        for card_id in only_local:
            found = storage.find_card_path(kanbai_dir, board.columns, card_id)
            if found:
                storage.delete_card_file(found[0])
                deleted += 1
    sync_state.clear_out_of_sync(kanbai_dir)
    return SyncResult(
        created=created, updated=updated, deleted=deleted, kept=len(only_local) - deleted
    )


def clone_board(root: Path, remote_config: RemoteConfig, *, archived: bool = False) -> SyncResult:
    """Create a local board under ``root`` from the hosted board ``remote_config`` points at.

    The local board starts from the hosted board's config, gets a ``[server]`` section (so
    the project keeps talking to the same hosted board) and receives its cards (the archived
    ones too with ``archived=True``).
    """
    remote = RemoteBoard(remote_config)
    scaffold.init_board(root, config=remote.config)
    kanbai_dir = root / storage.KANBAI_DIRNAME
    save_connection(kanbai_dir, remote_config)
    return pull_board(remote, kanbai_dir, archived=archived)


@dataclass(frozen=True)
class FieldChange:
    """One field that differs between the local and hosted copy of a card."""

    field: str
    local: object
    remote: object


@dataclass(frozen=True)
class CardDiff:
    """Field-level differences for a card id present on both sides."""

    card_id: str
    changes: list[FieldChange] = field(default_factory=list)


@dataclass(frozen=True)
class BoardDiff:
    """The result of comparing a local board against its hosted counterpart.

    ``only_local``/``only_remote`` are card ids present on just one side; ``changed`` holds a
    :class:`CardDiff` for every id present on both sides with at least one differing field.
    """

    only_local: list[str]
    only_remote: list[str]
    changed: list[CardDiff]

    @property
    def in_sync(self) -> bool:
        """``True`` when the two boards have exactly the same cards and field values."""
        return not (self.only_local or self.only_remote or self.changed)


def diff_boards(local: Board, remote: RemoteBoard, *, archived: bool = False) -> BoardDiff:
    """Compare every card on ``local`` against its hosted counterpart on ``remote``.

    Archived cards are only compared with ``archived=True``, matching what push/pull sync.

    Read-only: makes no changes to either board. Cards are matched by id; ``_COMPARED_FIELDS``
    lists which fields count toward a difference (position and timestamps are excluded as
    noise — two independently-maintained copies will never agree on those).
    """
    cards = _collect(local, remote, archived=archived)
    local_cards, remote_cards = cards.local, cards.remote

    only_local = sorted(local_cards.keys() - remote_cards.keys())
    only_remote = sorted(remote_cards.keys() - local_cards.keys())

    changed: list[CardDiff] = []
    for card_id in sorted(local_cards.keys() & remote_cards.keys()):
        card_diff = _diff_card(local_cards[card_id], remote_cards[card_id])
        if card_diff.changes:
            changed.append(card_diff)

    return BoardDiff(only_local=only_local, only_remote=only_remote, changed=changed)


def plan_board(
    remote: RemoteBoard,
    kanbai_dir: Path,
    action: Literal["push", "pull"],
    *,
    delete: bool = False,
    archived: bool = False,
    settings: bool = False,
) -> SyncPlan:
    """What :func:`push_board` / :func:`pull_board` (and the settings sync, with ``settings``)
    would change right now, without changing anything on either side.

    The FieldChange of a card or setting keeps its local/hosted orientation; the receiving
    side is the hosted one for a push and the local one for a pull.
    """
    board = Board.load(kanbai_dir.parent)
    board_diff = diff_boards(board, remote, archived=archived)
    pushing = action == "push"
    create, only_receiving = (
        (board_diff.only_local, board_diff.only_remote)
        if pushing
        else (board_diff.only_remote, board_diff.only_local)
    )
    if delete and not pushing:
        # pull_board only removes what it finds among the local columns' files.
        only_receiving = [
            card_id
            for card_id in only_receiving
            if storage.find_card_path(kanbai_dir, board.columns, card_id)
        ]
    return SyncPlan(
        create=create,
        update=board_diff.changed,
        delete=only_receiving if delete else [],
        kept=[] if delete else only_receiving,
        settings=_plan_settings(remote, kanbai_dir, pushing=pushing) if settings else None,
    )


def _plan_settings(remote: RemoteBoard, kanbai_dir: Path, *, pushing: bool) -> list[FieldChange]:
    local = load_config(kanbai_dir)
    source, target = (local, remote.config) if pushing else (remote.config, local)
    wanted = _settings_view(source, target.columns)
    current = _settings_view(target, target.columns)
    return [
        FieldChange(
            field=name,
            local=wanted[name] if pushing else current[name],
            remote=current[name] if pushing else wanted[name],
        )
        for name in _differing_settings(source, target)
    ]


def _diff_card(local_card: Card, remote_card: Card) -> CardDiff:
    changes = [
        FieldChange(field=name, local=getattr(local_card, name), remote=getattr(remote_card, name))
        for name in _COMPARED_FIELDS
        if getattr(local_card, name) != getattr(remote_card, name)
    ]
    return CardDiff(card_id=local_card.id, changes=changes)


SyncAction = Literal["push", "pull", "diff"]


@dataclass(frozen=True)
class BoardOutcome:
    """What :func:`sync_all` did for one board: ``ok`` (synced / in sync), ``differs`` (diff
    only), ``failed`` (``message`` says why) or ``skipped`` (not connected)."""

    name: str
    status: Literal["ok", "differs", "failed", "skipped"]
    result: SyncResult | None = None
    message: str = ""
    settings: list[str] | None = None  # settings that changed, when settings were synced
    plan: SyncPlan | None = None  # set by :func:`plan_all`


def sync_all(
    boards: dict[str, str],
    action: SyncAction,
    *,
    delete: bool = False,
    archived: bool = False,
    settings: bool = False,
) -> list[BoardOutcome]:
    """Run push, pull or diff on every ``{name: project path}`` board with a ``[server]``.

    A board that is not connected is skipped, and one that fails (network, auth, unreadable
    files) is reported without stopping the others. Once a server proves unreachable, the
    remaining boards on that same url are skipped instead of each waiting out the timeout.
    ``delete`` and ``settings`` (also sync the board settings) only apply to push/pull.
    """
    return _for_each_board(
        boards,
        lambda name, kanbai_dir, remote_config: _sync_one(
            name, kanbai_dir, remote_config, action, delete, archived, settings
        ),
    )


def plan_all(
    boards: dict[str, str],
    action: Literal["push", "pull"],
    *,
    delete: bool = False,
    archived: bool = False,
    settings: bool = False,
) -> list[BoardOutcome]:
    """Like :func:`sync_all` for push/pull, but read-only: each ``ok`` outcome carries the
    :class:`SyncPlan` of what the sync would change on that board."""

    def plan(name: str, kanbai_dir: Path, remote_config: RemoteConfig) -> BoardOutcome:
        found = plan_board(
            RemoteBoard(remote_config),
            kanbai_dir,
            action,
            delete=delete,
            archived=archived,
            settings=settings,
        )
        return BoardOutcome(name, "ok", plan=found)

    return _for_each_board(boards, plan)


def _for_each_board(
    boards: dict[str, str],
    work: Callable[[str, Path, RemoteConfig], BoardOutcome],
) -> list[BoardOutcome]:
    outcomes: list[BoardOutcome] = []
    unreachable: dict[str, str] = {}  # server url -> name of the board that found it down
    for name, path in sorted(boards.items()):
        kanbai_dir = Path(path) / storage.KANBAI_DIRNAME
        try:
            remote_config = load_remote_config(kanbai_dir)
            if remote_config is None:
                outcomes.append(BoardOutcome(name, "skipped", message="not connected"))
                continue
            url = remote_config.url.rstrip("/")
            if url in unreachable:
                message = f"server unreachable (skipped after '{unreachable[url]}' failed)"
                outcomes.append(BoardOutcome(name, "skipped", message=message))
                continue
            outcomes.append(work(name, kanbai_dir, remote_config))
        except HostUnreachableError as exc:
            unreachable[url] = name
            outcomes.append(BoardOutcome(name, "failed", message=str(exc)))
        except (KanbaiError, RemoteAPIError, OSError, ValueError) as exc:
            outcomes.append(BoardOutcome(name, "failed", message=str(exc)))
    return outcomes


def _sync_one(
    name: str,
    kanbai_dir: Path,
    remote_config: RemoteConfig,
    action: SyncAction,
    delete: bool,
    archived: bool,
    settings: bool,
) -> BoardOutcome:
    remote = RemoteBoard(remote_config)
    if action == "push":
        result = push_board(remote, kanbai_dir, delete=delete, archived=archived)
        changed = push_settings(remote, kanbai_dir) if settings else None
        return BoardOutcome(name, "ok", result, settings=changed)
    if action == "pull":
        result = pull_board(remote, kanbai_dir, delete=delete, archived=archived)
        changed = pull_settings(remote, kanbai_dir) if settings else None
        return BoardOutcome(name, "ok", result, settings=changed)
    board_diff = diff_boards(Board.load(kanbai_dir.parent), remote, archived=archived)
    if board_diff.in_sync:
        return BoardOutcome(name, "ok", message="in sync")
    message = (
        f"{len(board_diff.only_local)} only local, {len(board_diff.only_remote)} only hosted, "
        f"{len(board_diff.changed)} changed"
    )
    return BoardOutcome(name, "differs", message=message)
