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

from dataclasses import dataclass, field
from pathlib import Path

from . import scaffold, storage
from .board import Board
from .config import CONFIG_FILENAME, RemoteConfig
from .models import Card
from .remote_board import RemoteBoard, create_remote_board

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
    )
    without_server = _remove_section(existing, "server").rstrip("\n")
    new_text = f"{without_server}\n\n{section}" if without_server else section
    config_path.write_text(new_text, encoding="utf-8")


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
class _Cards:
    """The cards of both sides that a sync or diff should look at."""

    local: dict[str, Card]
    remote: dict[str, Card]


def _collect(board: Board, remote: RemoteBoard, *, archived: bool) -> _Cards:
    """Both sides' cards, by id.

    With ``archived`` the archives are included. Without it a card archived on *either* side
    is left out of *both*, so it is never created, overwritten or deleted by a sync — which is
    what keeps ``--delete`` from removing the active twin of a card archived on the other side.
    """
    local = {c.id: c for column in board.columns for c in board.list_column(column)}
    other = {c.id: c for column in remote.columns for c in remote.list_column(column)}
    local_archived = {c.id: c for c in board.list_archive()}
    remote_archived = {c.id: c for c in remote.list_archive()}
    if archived:
        return _Cards(local={**local, **local_archived}, remote={**other, **remote_archived})
    skipped = local_archived.keys() | remote_archived.keys()
    return _Cards(
        local={i: c for i, c in local.items() if i not in skipped},
        remote={i: c for i, c in other.items() if i not in skipped},
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


def _diff_card(local_card: Card, remote_card: Card) -> CardDiff:
    changes = [
        FieldChange(field=name, local=getattr(local_card, name), remote=getattr(remote_card, name))
        for name in _COMPARED_FIELDS
        if getattr(local_card, name) != getattr(remote_card, name)
    ]
    return CardDiff(card_id=local_card.id, changes=changes)
