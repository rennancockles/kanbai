"""Tests for kanbai.hosted: connect, push (local -> hosted), pull and clone (hosted -> local)."""

from __future__ import annotations

from pathlib import Path

import httpx2 as httpx
import pytest
from kanbai import hosted, scaffold
from kanbai.board import Board
from kanbai.config import RemoteConfig, load_config, load_remote_config
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


def test_push_and_pull_carry_the_notice(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    board = Board.load(local_project)
    sent = board.add("Already passed on", notice="Tell Ana")
    board.edit(sent.id, notice_sent=True)
    pending = board.add("Pending", notice="Tell Bob")
    remote_config = _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    remote = RemoteBoard(remote_config)

    on_server = {c.title: c for c in remote.list_column("backlog")}
    assert (on_server["Already passed on"].notice, on_server["Already passed on"].notice_sent) == (
        "Tell Ana",
        True,
    )
    assert (on_server["Pending"].notice, on_server["Pending"].notice_sent) == ("Tell Bob", False)

    remote.edit(pending.id, notice="Tell Carol")
    assert hosted.diff_boards(board, remote).changed[0].changes[0].field == "notice"
    hosted.pull_board(remote, kanbai_dir)
    pulled = Board.load(local_project).show(pending.id)
    assert (pulled.notice, pulled.notice_sent) == ("Tell Carol", False)

    board.edit(pending.id, notice="Tell Dave")
    hosted.push_board(remote, kanbai_dir)
    assert remote.show(pending.id).notice == "Tell Dave"


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


def test_push_restores_a_sprint_card_that_is_archived_on_the_server_only(
    local_project: Path,
) -> None:
    card = Board.load(local_project).add("Archived remotely", column="todo")
    kanbai_dir, remote = _connect(local_project)
    remote.archive(card.id)

    result = hosted.push_board(remote, kanbai_dir)

    assert (result.created, result.updated, result.deleted) == (0, 1, 0)
    assert _remote_cards(remote) == {card.id: "todo"}


def test_push_fixes_the_origin_column_of_a_card_archived_on_both_sides(
    local_project: Path,
) -> None:
    card = Board.load(local_project).add("Shipped", column="done")
    Board.load(local_project).archive(card.id)
    kanbai_dir, remote = _connect(local_project)
    remote.add("Shipped", card_id=card.id, column="backlog")
    remote.archive(card.id)

    result = hosted.push_board(remote, kanbai_dir)

    assert result.updated == 1
    assert [(c.id, c.archived_from) for c in remote.list_archive()] == [(card.id, "done")]
    assert hosted.diff_boards(Board.load(local_project), remote).in_sync
    assert hosted.push_board(remote, kanbai_dir).updated == 0


def test_push_archives_a_server_card_that_is_archived_locally(local_project: Path) -> None:
    card = Board.load(local_project).add("Archived locally", column="todo")
    kanbai_dir, remote = _connect(local_project)
    Board.load(local_project).archive(card.id)

    result = hosted.push_board(remote, kanbai_dir)

    assert (result.created, result.updated, result.deleted) == (0, 1, 0)
    assert _remote_cards(remote) == {card.id: "archive"}


def test_push_delete_never_removes_a_server_card_that_is_archived_locally(
    local_project: Path,
) -> None:
    card = Board.load(local_project).add("Archived locally", column="todo")
    kanbai_dir, remote = _connect(local_project)
    Board.load(local_project).archive(card.id)

    result = hosted.push_board(remote, kanbai_dir, delete=True)

    assert result.deleted == 0
    assert _remote_cards(remote) == {card.id: "archive"}


def test_pull_archives_a_local_card_that_is_archived_on_the_server(local_project: Path) -> None:
    card = Board.load(local_project).add("Archived remotely", column="todo")
    kanbai_dir, remote = _connect(local_project)
    remote.archive(card.id)

    result = hosted.pull_board(remote, kanbai_dir, delete=True)

    assert (result.updated, result.deleted) == (1, 0)
    board = Board.load(local_project)
    assert board.list_column("todo") == []
    assert [c.id for c in board.list_archive()] == [card.id]


def test_pull_restores_a_local_archived_card_that_is_active_on_the_server(
    local_project: Path,
) -> None:
    card = Board.load(local_project).add("Archived locally", column="todo")
    kanbai_dir, remote = _connect(local_project)
    Board.load(local_project).archive(card.id)

    result = hosted.pull_board(remote, kanbai_dir)

    assert result.updated == 1
    board = Board.load(local_project)
    assert [c.id for c in board.list_column("todo")] == [card.id]
    assert board.list_archive() == []  # moved, not duplicated


def test_pull_does_not_create_an_archived_card_that_only_exists_on_the_server(
    local_project: Path,
) -> None:
    kanbai_dir, remote = _connect(local_project)
    shelved = remote.add("Shelved", column="done")
    remote.archive(shelved.id)

    result = hosted.pull_board(remote, kanbai_dir)

    assert result.created == 0
    assert Board.load(local_project).list_archive() == []


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


def _publish_and_edit_local_config(
    local_project: Path, *replacements: tuple[str, str]
) -> tuple[RemoteConfig, Path]:
    """Publish the board, then change local settings by filling in the config's placeholders."""
    kanbai_dir = local_project / ".kanbai"
    remote_config = _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    config_path = kanbai_dir / "config.toml"
    text = config_path.read_text()
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new, 1)
    config_path.write_text(text)
    return remote_config, kanbai_dir


_CATEGORY = ('# category = "Work"\n', 'category = "Work"\n')
_WIP = ("# [wip]\n# doing = 3\n", "[wip]\ndoing = 2\nnowhere = 4\n")
_BYPASS = ("# bypass_review = true\n", "bypass_review = true\n")
_NTFY = (
    '# [notifications]\n# native = false\n# ntfy_topic = "my-kanbai-topic"\n',
    '[notifications]\nnative = false\nntfy_topic = "my-topic"\n',
)


def test_push_settings_sends_the_changed_local_settings_to_the_server(
    local_project: Path, fake_server: _FakeServer
) -> None:
    remote_config, kanbai_dir = _publish_and_edit_local_config(
        local_project, _CATEGORY, _WIP, _BYPASS, _NTFY
    )
    remote = RemoteBoard(remote_config)

    changed = hosted.push_settings(remote, kanbai_dir)

    assert changed == [
        "category",
        "wip",
        "bypass_review",
        "notifications_native",
        "notifications_ntfy_topic",
    ]
    board = fake_server.boards[remote_config.board_id]
    assert board["category"] == "Work"
    assert board["wip"] == {"doing": 2}
    assert board["bypass_review"] is True
    assert (board["notifications_native"], board["notifications_ntfy_topic"]) == (False, "my-topic")
    assert board["columns"] == ["backlog", "todo", "doing", "review", "done"]


def test_push_settings_changes_nothing_when_already_in_sync(
    local_project: Path, fake_server: _FakeServer
) -> None:
    remote_config, kanbai_dir = _publish_and_edit_local_config(local_project, _CATEGORY, _WIP)
    remote = RemoteBoard(remote_config)
    hosted.push_settings(remote, kanbai_dir)

    assert hosted.push_settings(RemoteBoard(remote_config), kanbai_dir) == []


def test_push_settings_explains_when_the_server_is_too_old(
    local_project: Path, fake_server: _FakeServer
) -> None:
    remote_config, kanbai_dir = _publish_and_edit_local_config(local_project, _CATEGORY)
    fake_server.supports_settings = False

    with pytest.raises(RemoteAPIError, match="update kanbai_server"):
        hosted.push_settings(RemoteBoard(remote_config), kanbai_dir)


def test_pull_settings_rewrites_the_local_settings_and_keeps_the_connection_and_columns(
    local_project: Path, fake_server: _FakeServer
) -> None:
    kanbai_dir = local_project / ".kanbai"
    remote_config = _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    board = fake_server.boards[remote_config.board_id]
    board.update(
        {
            "name": "Renamed on the host",
            "category": "Home",
            "types": ["idea", "bug"],
            "type_colors": {"idea": "#00ff00"},
            "wip": {"doing": 3},
            "bypass_review": True,
            "default_priority": "high",
            "notifications_native": False,
            "notifications_ntfy_topic": "from-host",
        }
    )

    changed = hosted.pull_settings(RemoteBoard(remote_config), kanbai_dir)

    assert set(changed) == {
        "name",
        "category",
        "types",
        "type_colors",
        "wip",
        "bypass_review",
        "default_priority",
        "notifications_native",
        "notifications_ntfy_topic",
    }
    config = load_config(kanbai_dir)
    assert (config.name, config.category, config.types) == (
        "Renamed on the host",
        "Home",
        ["idea", "bug"],
    )
    assert (config.type_colors, config.wip) == ({"idea": "#00ff00"}, {"doing": 3})
    assert (config.bypass_review, config.default_priority.value) == (True, "high")
    assert (config.notifications_native, config.notifications_ntfy_topic) == (False, "from-host")
    assert config.columns == ["backlog", "todo", "doing", "review", "done"]
    assert load_remote_config(kanbai_dir) == remote_config
    assert hosted.pull_settings(RemoteBoard(remote_config), kanbai_dir) == []


def test_pull_settings_leaves_the_file_alone_when_nothing_differs(
    local_project: Path, fake_server: _FakeServer
) -> None:
    kanbai_dir = local_project / ".kanbai"
    remote_config = _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    before = (kanbai_dir / "config.toml").read_text()

    assert hosted.pull_settings(RemoteBoard(remote_config), kanbai_dir) == []

    assert (kanbai_dir / "config.toml").read_text() == before


def test_sync_all_with_settings_reports_what_changed(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _publish_and_edit_local_config(local_project, _CATEGORY)

    outcomes = hosted.sync_all({"proj": str(local_project)}, "push", settings=True)
    without = hosted.sync_all({"proj": str(local_project)}, "push")

    assert outcomes[0].settings == ["category"]
    assert without[0].settings is None


# --------------------------------------------------------------------------- plan_board / plan_all


def _remote_titles(remote: RemoteBoard) -> list[str]:
    return sorted(c.title for col in remote.columns for c in remote.list_column(col))


def test_plan_push_predicts_what_push_does_without_changing_anything(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    board = Board.load(local_project)
    shared = board.add("Shared")
    remote = RemoteBoard(
        _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    )
    board.edit(shared.id, title="Renamed locally")
    new = board.add("Only local")
    only_remote = remote.add("Only hosted", card_id="900")
    before = _remote_titles(remote)

    plan = hosted.plan_board(remote, kanbai_dir, "push")

    assert plan.create == [new.id]
    assert [d.card_id for d in plan.update] == [shared.id]
    assert [(c.field, c.local, c.remote) for c in plan.update[0].changes] == [
        ("title", "Renamed locally", "Shared")
    ]
    assert (plan.delete, plan.kept, plan.settings) == ([], [only_remote.id], None)
    assert _remote_titles(remote) == before
    result = hosted.push_board(remote, kanbai_dir)
    assert (result.created, result.updated, result.kept) == (1, 1, 1)


def test_plan_pull_predicts_what_pull_does_without_changing_anything(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    board = Board.load(local_project)
    shared = board.add("Shared")
    remote = RemoteBoard(
        _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    )
    remote.edit(shared.id, title="Renamed on server")
    new = remote.add("Only hosted", card_id="900")
    only_local = board.add("Only local")

    plan = hosted.plan_board(remote, kanbai_dir, "pull", delete=True)

    assert plan.create == [new.id]
    assert [d.card_id for d in plan.update] == [shared.id]
    assert (plan.delete, plan.kept) == ([only_local.id], [])
    assert Board.load(local_project).show(shared.id).title == "Shared"
    result = hosted.pull_board(remote, kanbai_dir, delete=True)
    assert (result.created, result.updated, result.deleted) == (1, 1, 1)


def test_plan_without_delete_lists_the_other_sides_extras_as_kept(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    remote = RemoteBoard(
        _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    )
    extra = remote.add("Only hosted", card_id="900")

    pushing = hosted.plan_board(remote, kanbai_dir, "push", delete=True)
    pulling = hosted.plan_board(remote, kanbai_dir, "pull")

    assert pushing.delete == [extra.id] and pushing.has_changes
    assert pulling.create == [extra.id] and pulling.kept == []


def test_plan_of_boards_in_sync_has_no_changes(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    Board.load(local_project).add("Card")
    remote = RemoteBoard(
        _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    )

    for action in ("push", "pull"):
        plan = hosted.plan_board(remote, kanbai_dir, action, settings=True)  # type: ignore[arg-type]
        assert not plan.has_changes
        assert plan.settings == []


def test_plan_settings_keeps_the_local_hosted_orientation(local_project: Path) -> None:
    remote_config, kanbai_dir = _publish_and_edit_local_config(local_project, _CATEGORY)
    remote = RemoteBoard(remote_config)

    pushing = hosted.plan_board(remote, kanbai_dir, "push", settings=True)
    pulling = hosted.plan_board(remote, kanbai_dir, "pull", settings=True)

    for plan in (pushing, pulling):
        assert plan.settings is not None
        (change,) = plan.settings
        assert (change.field, change.local) == ("category", "Work")
        assert change.remote != "Work"
    assert hosted.plan_board(remote, kanbai_dir, "push").settings is None


def test_plan_pull_delete_ignores_local_cards_pull_cannot_remove(local_project: Path) -> None:
    kanbai_dir = local_project / ".kanbai"
    board = Board.load(local_project)
    shelved = board.add("Shelved")
    board.archive(shelved.id)
    remote = RemoteBoard(
        _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    )

    plan = hosted.plan_board(remote, kanbai_dir, "pull", delete=True, archived=True)
    result = hosted.pull_board(remote, kanbai_dir, delete=True, archived=True)

    assert len(plan.delete) == result.deleted


def test_plan_all_reports_each_board_and_never_changes_one(
    local_project: Path, tmp_path: Path
) -> None:
    kanbai_dir = local_project / ".kanbai"
    Board.load(local_project).add("Card")
    remote = RemoteBoard(
        _publish(kanbai_dir, "https://kanbai.example.com", ADMIN_EMAIL, ADMIN_PASSWORD)
    )
    Board.load(local_project).add("Not pushed yet")
    loose = tmp_path / "loose"
    loose.mkdir()
    scaffold.init_board(loose)
    before = _remote_titles(remote)

    outcomes = hosted.plan_all({"proj": str(local_project), "loose": str(loose)}, "push")

    by_name = {o.name: o for o in outcomes}
    assert by_name["loose"].status == "skipped"
    plan = by_name["proj"].plan
    assert by_name["proj"].status == "ok" and plan is not None
    assert len(plan.create) == 1
    assert _remote_titles(remote) == before
