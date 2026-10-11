"""Tests for kanbai.hosted: connect, push (local -> hosted), pull and clone (hosted -> local)."""

from __future__ import annotations

from pathlib import Path

import httpx2 as httpx
import pytest
from kanbai import hosted, scaffold
from kanbai.board import Board
from kanbai.config import RemoteConfig, load_remote_config
from kanbai.errors import KanbaiError, RemoteAPIError
from kanbai.remote_board import RemoteBoard, login

from test_remote_board import ADMIN_EMAIL, ADMIN_PASSWORD, _FakeServer, patch_transport


@pytest.fixture
def fake_server() -> _FakeServer:
    return _FakeServer()


@pytest.fixture(autouse=True)
def _patched_transport(fake_server: _FakeServer, monkeypatch: pytest.MonkeyPatch) -> None:
    patch_transport(monkeypatch, httpx.MockTransport(fake_server.handle))


@pytest.fixture
def local_project(tmp_path: Path) -> Path:
    scaffold.init_board(tmp_path, name="Local project")
    return tmp_path


def _publish(
    kanbai_dir: Path, url: str, email: str, password: str, *, archived: bool = False
) -> RemoteConfig:
    """Connect the board to a new hosted board and push it (the connect + first push flow)."""
    token = login(url, email, password)
    remote_config = hosted.create_hosted_board(kanbai_dir, url, token)
    hosted.save_connection(kanbai_dir, remote_config)
    hosted.push_board(RemoteBoard(remote_config), kanbai_dir, archived=archived)
    return remote_config


def test_publish_uploads_every_card_and_writes_server_section(local_project: Path) -> None:
    board = Board.load(local_project)
    board.add("First card", priority="high")
    board.add("Second card")

    remote_config = _publish(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )

    remote = RemoteBoard(remote_config)
    assert [c.title for c in remote.list_column("backlog")] == ["First card", "Second card"]
    cfg_text = (local_project / ".kanbai" / "config.toml").read_text()
    assert "[server]" in cfg_text
    assert remote_config.board_id in cfg_text
    assert remote_config.token in cfg_text


def test_republishing_overwrites_the_server_section_instead_of_duplicating_it(
    local_project: Path,
) -> None:
    _publish(local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)

    second_remote_config = _publish(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )

    cfg_text = (local_project / ".kanbai" / "config.toml").read_text()
    assert cfg_text.count("[server]") == 1
    assert second_remote_config.board_id in cfg_text
    assert load_remote_config(local_project / ".kanbai") == second_remote_config


def test_publish_preserves_dependency_ids(local_project: Path) -> None:
    board = Board.load(local_project)
    blocker = board.add("Blocker")
    board.add("Blocked", deps=[blocker.id])

    remote_config = _publish(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )

    remote = RemoteBoard(remote_config)
    blocked_card = next(c for c in remote.list_column("backlog") if c.title == "Blocked")
    blocker_card = next(c for c in remote.list_column("backlog") if c.title == "Blocker")
    assert blocked_card.deps == [blocker_card.id]


def test_publish_preserves_archived_cards_and_their_column(local_project: Path) -> None:
    board = Board.load(local_project)
    card = board.add("To archive", column="todo")
    board.archive(card.id)

    remote_config = _publish(
        local_project / ".kanbai",
        "https://kanbai.example.com",
        ADMIN_EMAIL,
        ADMIN_PASSWORD,
        archived=True,
    )

    remote = RemoteBoard(remote_config)
    archived = remote.list_archive()
    assert [c.title for c in archived] == ["To archive"]
    assert archived[0].archived_from == "todo"


def test_publish_keeps_local_ids_when_there_are_gaps_and_archived_cards(
    local_project: Path,
) -> None:
    board = Board.load(local_project)
    board.add("First")
    removed = board.add("Removed")
    archived = board.add("Archived")
    blocked = board.add("Blocked", deps=[archived.id])
    board.remove(removed.id)
    board.archive(archived.id)

    remote_config = _publish(
        local_project / ".kanbai",
        "https://kanbai.example.com",
        ADMIN_EMAIL,
        ADMIN_PASSWORD,
        archived=True,
    )

    remote = RemoteBoard(remote_config)
    remote_ids = {c.id for col in remote.columns for c in remote.list_column(col)}
    assert remote_ids == {"001", blocked.id}
    assert [c.id for c in remote.list_archive()] == [archived.id]
    assert next(c for c in remote.list_column("backlog") if c.id == blocked.id).deps == [
        archived.id
    ]


def test_publish_fails_clearly_when_server_ignores_explicit_card_ids(
    local_project: Path, fake_server: _FakeServer
) -> None:
    fake_server.ignores_card_ids = True
    board = Board.load(local_project)
    board.add("First")
    board.add("Second")
    board.remove("001")

    with pytest.raises(RemoteAPIError, match="explicit card ids"):
        _publish(
            local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
        )


def test_publish_uploads_the_local_board_config(local_project: Path) -> None:
    remote_config = _publish(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )

    remote = RemoteBoard(remote_config)
    assert remote.config.name == "Local project"


def test_publish_sends_the_board_category(local_project: Path) -> None:
    config_path = local_project / ".kanbai" / "config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("[board]", '[board]\ncategory = "Work"', 1),
        encoding="utf-8",
    )

    remote_config = _publish(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )

    assert RemoteBoard(remote_config).config.category == "Work"


def test_publish_raises_on_bad_credentials(local_project: Path) -> None:
    with pytest.raises(RemoteAPIError):
        _publish(local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, "wrong")


def test_clone_writes_every_card_locally(local_project: Path) -> None:
    remote_config = _publish(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )
    remote = RemoteBoard(remote_config)
    remote.add("Uploaded directly", column="todo")

    download_dir = local_project / "downloaded"
    result = hosted.clone_board(download_dir, remote_config)

    assert result.created == 1
    downloaded = Board.load(download_dir)
    assert [c.title for c in downloaded.list_column("todo")] == ["Uploaded directly"]


def test_clone_includes_archived_cards(local_project: Path) -> None:
    remote_config = _publish(
        local_project / ".kanbai",
        "https://kanbai.example.com",
        ADMIN_EMAIL,
        ADMIN_PASSWORD,
        archived=True,
    )
    remote = RemoteBoard(remote_config)
    card = remote.add("Will be archived")
    remote.archive(card.id)

    download_dir = local_project / "downloaded"
    hosted.clone_board(download_dir, remote_config, archived=True)

    downloaded = Board.load(download_dir)
    assert [c.title for c in downloaded.list_archive()] == ["Will be archived"]


def test_round_trip_push_then_clone_preserves_cards_and_deps(local_project: Path) -> None:
    board = Board.load(local_project)
    blocker = board.add("Blocker", priority="high", labels=["urgent"])
    board.add("Blocked", deps=[blocker.id], column="todo")

    remote_config = _publish(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )

    download_dir = local_project / "downloaded"
    hosted.clone_board(download_dir, remote_config)
    downloaded = Board.load(download_dir)

    downloaded_blocker = next(
        c for col in downloaded.columns for c in downloaded.list_column(col) if c.title == "Blocker"
    )
    downloaded_blocked = next(
        c for col in downloaded.columns for c in downloaded.list_column(col) if c.title == "Blocked"
    )
    assert downloaded_blocker.priority.value == "high"
    assert downloaded_blocker.labels == ["urgent"]
    assert downloaded_blocked.deps == [downloaded_blocker.id]


def test_diff_boards_reports_in_sync_right_after_publish(local_project: Path) -> None:
    board = Board.load(local_project)
    board.add("A card")

    remote_config = _publish(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )
    remote = RemoteBoard(remote_config)

    diff = hosted.diff_boards(board, remote)

    assert diff.in_sync
    assert diff.only_local == []
    assert diff.only_remote == []
    assert diff.changed == []


def test_diff_boards_detects_card_only_on_remote(local_project: Path) -> None:
    board = Board.load(local_project)
    remote_config = _publish(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )
    remote = RemoteBoard(remote_config)
    added = remote.add("Added remotely")

    diff = hosted.diff_boards(board, remote)

    assert not diff.in_sync
    assert diff.only_remote == [added.id]
    assert diff.only_local == []


def test_diff_boards_detects_card_only_on_local(local_project: Path) -> None:
    board = Board.load(local_project)
    remote_config = _publish(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )
    remote = RemoteBoard(remote_config)
    added = board.add("Added locally")

    diff = hosted.diff_boards(board, remote)

    assert not diff.in_sync
    assert diff.only_local == [added.id]
    assert diff.only_remote == []


def test_diff_boards_detects_differing_fields_on_shared_card(local_project: Path) -> None:
    board = Board.load(local_project)
    card = board.add("Original title", priority="low")
    remote_config = _publish(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )
    remote = RemoteBoard(remote_config)
    remote_card = next(c for c in remote.list_column("backlog") if c.title == "Original title")
    remote.edit(remote_card.id, title="Changed remotely", priority="high")

    diff = hosted.diff_boards(board, remote)

    assert not diff.in_sync
    assert len(diff.changed) == 1
    card_diff = diff.changed[0]
    assert card_diff.card_id == card.id
    changed_fields = {c.field for c in card_diff.changes}
    assert changed_fields == {"title", "priority"}


def test_diff_boards_ignores_order_and_timestamps(local_project: Path) -> None:
    board = Board.load(local_project)
    board.add("First")
    board.add("Second")
    remote_config = _publish(
        local_project / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )
    remote = RemoteBoard(remote_config)

    # Sorting changes `order` on the hosted side without changing any compared field.
    remote.sort_column("backlog", "title", descending=True)

    diff = hosted.diff_boards(board, remote)

    assert diff.in_sync


# --------------------------------------------------------------------------- pull_board


def test_pull_writes_remote_cards_locally(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    remote_config = _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    remote = RemoteBoard(remote_config)
    remote.add("New on server")

    result = hosted.pull_board(remote, kanbai_dir)

    board = Board.load(local_project)
    titles = [c.title for col in board.columns for c in board.list_column(col)]
    assert "New on server" in titles
    assert result.created == 1


def test_pull_moves_local_card_when_column_differs(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    board = Board.load(local_project)
    card = board.add("Will move")
    remote_config = _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    remote = RemoteBoard(remote_config)
    remote_card = next(c for c in remote.list_column("backlog") if c.title == "Will move")
    remote.move(remote_card.id, "todo")

    result = hosted.pull_board(remote, kanbai_dir)

    board = Board.load(local_project)
    todo_ids = [c.id for c in board.list_column("todo")]
    assert card.id in todo_ids
    assert result.updated == 1


def test_pull_keeps_local_only_cards_without_delete(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    board = Board.load(local_project)
    card = board.add("Local only")
    remote_config = _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    remote = RemoteBoard(remote_config)
    # Remove the card from the remote so it's only local.
    remote_card = next(c for c in remote.list_column("backlog") if c.title == "Local only")
    remote.remove(remote_card.id)

    result = hosted.pull_board(remote, kanbai_dir, delete=False)

    board = Board.load(local_project)
    all_ids = [c.id for col in board.columns for c in board.list_column(col)]
    assert card.id in all_ids
    assert result.kept == 1
    assert result.deleted == 0


def test_pull_deletes_local_only_cards_with_delete(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    board = Board.load(local_project)
    card = board.add("Local only")
    remote_config = _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    remote = RemoteBoard(remote_config)
    remote_card = next(c for c in remote.list_column("backlog") if c.title == "Local only")
    remote.remove(remote_card.id)

    result = hosted.pull_board(remote, kanbai_dir, delete=True)

    board = Board.load(local_project)
    all_ids = [c.id for col in board.columns for c in board.list_column(col)]
    assert card.id not in all_ids
    assert result.deleted == 1
    assert result.kept == 0


# --------------------------------------------------------------------------- push_board


def test_push_creates_local_only_cards_on_server(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    remote_config = _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    remote = RemoteBoard(remote_config)
    board = Board.load(local_project)
    board.add("Created locally")

    result = hosted.push_board(remote, kanbai_dir)

    remote_titles = [c.title for col in remote.columns for c in remote.list_column(col)]
    assert "Created locally" in remote_titles
    assert result.created == 1


def test_push_keeps_local_ids_so_a_following_pull_creates_no_duplicates(
    local_project: Path,
) -> None:
    kanbai_dir = local_project / ".kanbai"
    remote_config = _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    remote = RemoteBoard(remote_config)
    board = Board.load(local_project)
    first = board.add("Created locally")
    board.add("Depends on first", deps=[first.id])

    hosted.push_board(remote, kanbai_dir)
    hosted.pull_board(remote, kanbai_dir)

    remote_cards = {c.id: c for col in remote.columns for c in remote.list_column(col)}
    assert remote_cards[first.id].title == "Created locally"
    assert [c.deps for c in remote_cards.values() if c.title == "Depends on first"] == [[first.id]]
    local = Board.load(local_project)
    local_titles = [c.title for col in local.columns for c in local.list_column(col)]
    assert sorted(local_titles) == ["Created locally", "Depends on first"]
    assert hosted.diff_boards(local, remote).in_sync


def test_push_moves_remote_card_when_column_differs(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    board = Board.load(local_project)
    card = board.add("Will move")
    remote_config = _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    remote = RemoteBoard(remote_config)
    # Move locally to todo, then push.
    board.move(card.id, "todo")

    result = hosted.push_board(remote, kanbai_dir)

    remote_card = next(
        c for col in remote.columns for c in remote.list_column(col) if c.id == card.id
    )
    assert remote_card.status == "todo"
    assert result.updated == 1


def test_push_keeps_remote_only_cards_without_delete(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    remote_config = _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    remote = RemoteBoard(remote_config)
    remote_card = remote.add("Remote only")

    result = hosted.push_board(remote, kanbai_dir, delete=False)

    remote_ids = [c.id for col in remote.columns for c in remote.list_column(col)]
    assert remote_card.id in remote_ids
    assert result.kept == 1
    assert result.deleted == 0


def test_push_deletes_remote_only_cards_with_delete(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    remote_config = _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    remote = RemoteBoard(remote_config)
    remote_card = remote.add("Remote only")

    result = hosted.push_board(remote, kanbai_dir, delete=True)

    remote_ids = [c.id for col in remote.columns for c in remote.list_column(col)]
    assert remote_card.id not in remote_ids
    assert result.deleted == 1
    assert result.kept == 0


# --------------------------------------------------------------------------- connect / push / clone


def _remote_cards(remote: RemoteBoard) -> dict[str, str]:
    cards = {c.id: c.status for col in remote.columns for c in remote.list_column(col)}
    cards.update({c.id: c.status for c in remote.list_archive()})
    return cards


def test_creating_and_saving_the_connection_sends_no_cards(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    Board.load(local_project).add("Not sent yet")

    remote_config = hosted.create_hosted_board(
        kanbai_dir,
        "https://kanbai.example.com",
        login("https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD),
    )
    hosted.save_connection(kanbai_dir, remote_config)

    assert load_remote_config(kanbai_dir) == remote_config
    assert _remote_cards(RemoteBoard(remote_config)) == {}


def test_creating_a_hosted_board_fails_without_a_local_board(tmp_path: Path) -> None:
    with pytest.raises(KanbaiError):
        hosted.create_hosted_board(tmp_path / ".kanbai", "https://kanbai.example.com", "token")


def test_save_connection_replaces_a_previous_server_section(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    hosted.save_connection(kanbai_dir, RemoteConfig(url="https://a", token="t1", board_id="b1"))
    hosted.save_connection(kanbai_dir, RemoteConfig(url="https://b", token="t2", board_id="b2"))

    assert load_remote_config(kanbai_dir) == RemoteConfig(
        url="https://b", token="t2", board_id="b2"
    )
    assert (kanbai_dir / "config.toml").read_text().count("[server]") == 1


def test_push_twice_changes_nothing_the_second_time(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    board = Board.load(local_project)
    blocker = board.add("Blocker", column="todo")
    board.add("Blocked", deps=[blocker.id])
    archived = board.add("Done long ago")
    board.archive(archived.id)
    remote_config = _publish(
        kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD, archived=True
    )

    result = hosted.push_board(RemoteBoard(remote_config), kanbai_dir, archived=True)

    assert (result.created, result.updated, result.deleted, result.kept) == (0, 0, 0, 0)


def test_push_sends_archived_cards_and_keeps_them_archived(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    board = Board.load(local_project)
    card = board.add("Shelved", column="todo")
    board.archive(card.id)

    remote_config = _publish(
        kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD, archived=True
    )

    remote = RemoteBoard(remote_config)
    assert [(c.id, c.archived_from) for c in remote.list_archive()] == [(card.id, "todo")]
    assert hosted.diff_boards(Board.load(local_project), remote, archived=True).in_sync


def test_push_archives_a_card_that_was_archived_locally_after_the_first_push(
    local_project: Path,
) -> None:
    kanbai_dir = local_project / ".kanbai"
    card = Board.load(local_project).add("Later archived")
    remote = RemoteBoard(
        _publish(
            kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD, archived=True
        )
    )
    Board.load(local_project).archive(card.id)

    result = hosted.push_board(remote, kanbai_dir, archived=True)

    assert result.updated == 1
    assert _remote_cards(remote) == {card.id: "archive"}


def test_push_restores_a_card_archived_on_the_server_but_active_locally(
    local_project: Path,
) -> None:
    kanbai_dir = local_project / ".kanbai"
    card = Board.load(local_project).add("Back from the archive", column="todo")
    remote = RemoteBoard(
        _publish(
            kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD, archived=True
        )
    )
    remote.archive(card.id)

    result = hosted.push_board(remote, kanbai_dir, archived=True)

    assert result.updated == 1
    assert _remote_cards(remote) == {card.id: "todo"}


def test_push_edits_cards_whose_fields_changed_locally(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    card = Board.load(local_project).add("Old title")
    remote = RemoteBoard(
        _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    )
    Board.load(local_project).edit(card.id, title="New title", labels=["x"])

    result = hosted.push_board(remote, kanbai_dir)

    assert result.updated == 1
    assert remote.show(card.id).title == "New title"
    assert remote.show(card.id).labels == ["x"]


def test_clone_copies_the_board_config_and_connects_the_new_project(tmp_path: Path) -> None:
    source = tmp_path / "source"
    scaffold.init_board(source, name="Shared")
    config_path = source / ".kanbai" / "config.toml"
    text = config_path.read_text(encoding="utf-8")
    text = text.replace("[board]", '[board]\ncategory = "Work"\nbypass_review = true', 1)
    text += '\n[wip]\ndoing = 2\n\n[types.colors]\nbug = "#ff0000"\n'
    config_path.write_text(text, encoding="utf-8")
    remote_config = _publish(
        source / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD
    )

    target = tmp_path / "target"
    hosted.clone_board(target, remote_config)

    cloned = Board.load(target).config
    assert cloned.name == "Shared"
    assert cloned.category == "Work"
    assert cloned.bypass_review is True
    assert cloned.wip == {"doing": 2}
    assert cloned.type_colors == {"bug": "#ff0000"}
    assert load_remote_config(target / ".kanbai") == remote_config


def test_clone_then_push_round_trips_without_changes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    scaffold.init_board(source)
    board = Board.load(source)
    first = board.add("One", column="todo")
    board.add("Two", deps=[first.id])
    old = board.add("Old")
    board.archive(old.id)
    remote_config = _publish(
        source / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD, archived=True
    )

    target = tmp_path / "target"
    hosted.clone_board(target, remote_config, archived=True)
    result = hosted.push_board(RemoteBoard(remote_config), target / ".kanbai", archived=True)

    assert (result.created, result.updated) == (0, 0)
    assert hosted.diff_boards(Board.load(target), RemoteBoard(remote_config), archived=True).in_sync


# --------------------------------------------------------------------------- archived policy


def _connect(local_project: Path) -> tuple[Path, RemoteBoard]:
    kanbai_dir = local_project / ".kanbai"
    remote_config = _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    return kanbai_dir, RemoteBoard(remote_config)


def test_push_leaves_archived_cards_out_by_default(local_project: Path) -> None:
    board = Board.load(local_project)
    board.add("Active")
    shelved = board.add("Shelved")
    board.archive(shelved.id)

    _, remote = _connect(local_project)

    assert _remote_cards(remote) == {"001": "backlog"}


def test_pull_leaves_archived_cards_out_by_default(local_project: Path) -> None:
    kanbai_dir, remote = _connect(local_project)
    card = remote.add("Archived on the server")
    remote.archive(card.id)

    result = hosted.pull_board(remote, kanbai_dir)

    assert (result.created, result.updated) == (0, 0)
    assert Board.load(local_project).list_archive() == []
    assert hosted.pull_board(remote, kanbai_dir, archived=True).created == 1
    assert [c.title for c in Board.load(local_project).list_archive()] == ["Archived on the server"]


def test_push_leaves_a_card_alone_when_it_is_archived_on_the_server_only(
    local_project: Path,
) -> None:
    card = Board.load(local_project).add("Archived remotely", column="todo")
    kanbai_dir, remote = _connect(local_project)
    remote.archive(card.id)

    result = hosted.push_board(remote, kanbai_dir)

    assert (result.created, result.updated, result.deleted, result.kept) == (0, 0, 0, 0)
    assert _remote_cards(remote) == {card.id: "archive"}


def test_push_delete_does_not_remove_the_server_twin_of_a_locally_archived_card(
    local_project: Path,
) -> None:
    card = Board.load(local_project).add("Archived locally", column="todo")
    kanbai_dir, remote = _connect(local_project)
    Board.load(local_project).archive(card.id)

    result = hosted.push_board(remote, kanbai_dir, delete=True)

    assert result.deleted == 0
    assert _remote_cards(remote) == {card.id: "todo"}


def test_pull_delete_does_not_remove_the_local_twin_of_a_server_archived_card(
    local_project: Path,
) -> None:
    card = Board.load(local_project).add("Archived remotely", column="todo")
    kanbai_dir, remote = _connect(local_project)
    remote.archive(card.id)

    result = hosted.pull_board(remote, kanbai_dir, delete=True)

    assert result.deleted == 0
    assert [c.id for c in Board.load(local_project).list_column("todo")] == [card.id]


def test_push_archived_overrides_the_default_and_syncs_the_archive_state(
    local_project: Path,
) -> None:
    card = Board.load(local_project).add("Archived remotely", column="todo")
    kanbai_dir, remote = _connect(local_project)
    remote.archive(card.id)

    result = hosted.push_board(remote, kanbai_dir, archived=True)

    assert result.updated == 1
    assert _remote_cards(remote) == {card.id: "todo"}


def test_diff_ignores_archived_cards_by_default(local_project: Path) -> None:
    board = Board.load(local_project)
    shelved = board.add("Shelved")
    board.archive(shelved.id)
    _, remote = _connect(local_project)

    default = hosted.diff_boards(Board.load(local_project), remote)
    with_archived = hosted.diff_boards(Board.load(local_project), remote, archived=True)

    assert default.in_sync
    assert with_archived.only_local == [shelved.id]


def test_clone_leaves_archived_cards_out_by_default(tmp_path: Path) -> None:
    source = tmp_path / "source"
    scaffold.init_board(source)
    board = Board.load(source)
    board.add("Active")
    shelved = board.add("Shelved")
    board.archive(shelved.id)
    remote_config = _publish(
        source / ".kanbai", "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD, archived=True
    )

    plain = tmp_path / "plain"
    full = tmp_path / "full"
    hosted.clone_board(plain, remote_config)
    hosted.clone_board(full, remote_config, archived=True)

    assert Board.load(plain).list_archive() == []
    assert [c.title for c in Board.load(full).list_archive()] == ["Shelved"]
