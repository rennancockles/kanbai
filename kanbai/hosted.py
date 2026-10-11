"""Onboarding and sync between local (filesystem) and hosted (kanbai_server) boards.

``publish_board`` uploads a local ``.kanbai/`` board to a hosted account and switches the
project into remote mode (see ``kanbai.remote_board``); ``download_board`` writes a hosted
board's cards back to local files without leaving remote mode (the ``[server]`` section
stays — removing it to fully return to self-hosted is a manual step, by design).

``sync_pull`` / ``sync_push`` reconcile the two boards by card ID, avoiding the
duplication that ``download_board`` causes when a card exists on both sides but in
different columns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import storage
from .board import Board
from .config import CONFIG_FILENAME, RemoteConfig
from .models import Card
from .remote_board import RemoteBoard, create_remote_board, login

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


def publish_board(kanbai_dir: Path, url: str, email: str, password: str) -> RemoteConfig:
    """Upload the local board at ``kanbai_dir`` to a new hosted board, then switch this
    project into remote mode by writing ``[server]`` into its ``config.toml``.

    Cards keep their local ids as long as they upload in ascending id order (the hosted API
    always assigns the next sequential id) — this holds for a board that was never edited by
    hand into a non-contiguous id sequence, which is the expectation for a filesystem board.
    Dependency ids are rewritten if the hosted upload ever diverges from the local id.
    """
    board = Board.load(kanbai_dir.parent)
    token = login(url, email, password)
    remote_config = create_remote_board(url, token, board.config)
    remote = RemoteBoard(remote_config)

    id_map: dict[str, str] = {}
    for column in board.columns:
        for card in board.list_column(column):
            id_map[card.id] = _upload_card(remote, card, column=column).id
    for card in board.list_archive():
        landing_column = card.archived_from or board.config.add_column
        uploaded = _upload_card(remote, card, column=landing_column)
        id_map[card.id] = remote.archive(uploaded.id).id

    _rewrite_deps(remote, board, id_map)
    _write_server_section(kanbai_dir, remote_config)
    return remote_config


def _upload_card(remote: RemoteBoard, card: Card, *, column: str) -> Card:
    return remote.add(
        card.title,
        description=card.body,
        priority=card.priority,
        type=card.type,
        version=card.version,
        column=column,
        labels=card.labels,
        assignee=card.assignee,
    )


def _rewrite_deps(remote: RemoteBoard, board: Board, id_map: dict[str, str]) -> None:
    """Set each uploaded card's ``deps``, remapped through ``id_map``.

    Deps are applied only after every card is uploaded (see :func:`publish_board`), since a
    card can depend on one that uploads after it — ``id_map`` isn't complete until then.
    """
    local_cards = [c for column in board.columns for c in board.list_column(column)]
    local_cards += board.list_archive()
    for card in local_cards:
        if not card.deps:
            continue
        remote.edit(id_map[card.id], deps=[id_map.get(dep, dep) for dep in card.deps])


def _write_server_section(kanbai_dir: Path, remote: RemoteConfig) -> None:
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


@dataclass(frozen=True)
class SyncResult:
    """Summary of a :func:`sync_pull` or :func:`sync_push` operation."""

    upserted: int  # cards written/updated on the winning side
    moved: int  # cards that changed column during the sync
    created: int  # brand-new cards added to the server (push only)
    deleted: int  # cards removed with ``--delete``
    kept: int  # cards on the losing side preserved (no ``--delete``)


def sync_pull(remote: RemoteBoard, kanbai_dir: Path, *, delete: bool = False) -> SyncResult:
    """Server wins: update local files to match the hosted board.

    Cards present on both sides are moved to the remote column when it differs, fixing
    the duplication that ``download_board`` causes. Cards only on the server are written
    locally; cards only local are kept (or removed with ``delete=True``).
    """
    board = Board.load(kanbai_dir.parent)
    all_local = {c.id: c for col in board.columns for c in board.list_column(col)}
    all_local.update({c.id: c for c in board.list_archive()})

    remote_cards: dict[str, Card] = {}
    for col in remote.columns:
        for card in remote.list_column(col):
            remote_cards[card.id] = card
    for card in remote.list_archive():
        remote_cards[card.id] = card

    upserted = 0
    moved = 0
    for card in remote_cards.values():
        local_card = all_local.get(card.id)
        if local_card is not None and local_card.status != card.status:
            old = storage.find_card_path(kanbai_dir, board.columns, card.id)
            if old:
                storage.delete_card_file(old[0])
            moved += 1
        storage.write_card(kanbai_dir, card)
        upserted += 1

    only_local = set(all_local) - set(remote_cards)
    deleted = 0
    if delete:
        for card_id in only_local:
            found = storage.find_card_path(kanbai_dir, board.columns, card_id)
            if found:
                storage.delete_card_file(found[0])
                deleted += 1

    return SyncResult(
        upserted=upserted,
        moved=moved,
        created=0,
        deleted=deleted,
        kept=len(only_local) - deleted,
    )


def sync_push(remote: RemoteBoard, kanbai_dir: Path, *, delete: bool = False) -> SyncResult:
    """Local wins: update the hosted board to match local files.

    Cards present on both sides are edited and moved to the local column when it differs.
    Cards only local are created on the server (the server assigns a new ID for these).
    Cards only on the server are preserved (or removed with ``delete=True``).

    Note: archived local cards are not pushed — only active-column cards are synced.
    """
    board = Board.load(kanbai_dir.parent)
    local_cards = {c.id: c for col in board.columns for c in board.list_column(col)}

    remote_cards: dict[str, Card] = {}
    for col in remote.columns:
        for card in remote.list_column(col):
            remote_cards[card.id] = card

    upserted = 0
    moved = 0
    created = 0
    for card_id, local_card in local_cards.items():
        if card_id in remote_cards:
            remote.edit(
                card_id,
                title=local_card.title,
                description=local_card.body,
                priority=local_card.priority,
                type=local_card.type,
                version=local_card.version,
                labels=local_card.labels,
                deps=local_card.deps,
                assignee=local_card.assignee,
            )
            if remote_cards[card_id].status != local_card.status:
                remote.move(card_id, local_card.status)
                moved += 1
            upserted += 1
        else:
            remote.add(
                local_card.title,
                description=local_card.body,
                priority=local_card.priority,
                type=local_card.type,
                version=local_card.version,
                column=local_card.status,
                labels=local_card.labels,
                deps=local_card.deps,
                assignee=local_card.assignee,
            )
            created += 1

    only_remote = set(remote_cards) - set(local_cards)
    deleted = 0
    if delete:
        for card_id in only_remote:
            remote.remove(card_id)
            deleted += 1

    return SyncResult(
        upserted=upserted,
        moved=moved,
        created=created,
        deleted=deleted,
        kept=len(only_remote) - deleted,
    )


def download_board(remote: RemoteBoard, kanbai_dir: Path) -> int:
    """Write every card on the hosted board ``remote`` into local files under ``kanbai_dir``.

    Returns the number of cards written. Leaves ``[server]`` in ``config.toml`` untouched —
    fully returning to self-hosted mode requires removing that section by hand.
    """
    kanbai_dir.mkdir(parents=True, exist_ok=True)
    all_cards = [c for column in remote.columns for c in remote.list_column(column)]
    all_cards += remote.list_archive()
    for card in all_cards:
        storage.write_card(kanbai_dir, card)
    return len(all_cards)


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


def diff_boards(local: Board, remote: RemoteBoard) -> BoardDiff:
    """Compare every card on ``local`` against its hosted counterpart on ``remote``.

    Read-only: makes no changes to either board. Cards are matched by id; ``_COMPARED_FIELDS``
    lists which fields count toward a difference (position and timestamps are excluded as
    noise — two independently-maintained copies will never agree on those).
    """
    local_cards = {c.id: c for col in local.columns for c in local.list_column(col)}
    local_cards.update({c.id: c for c in local.list_archive()})
    remote_cards = {c.id: c for col in remote.columns for c in remote.list_column(col)}
    remote_cards.update({c.id: c for c in remote.list_archive()})

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
