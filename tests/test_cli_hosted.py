"""CLI-level tests for `kanbai hosted push` / `pull` / `clone` / `diff`."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx2 as httpx
import pytest
from kanbai import scaffold
from kanbai.board import Board
from kanbai.cli import app
from typer.testing import CliRunner

from test_remote_board import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    BOARD_ID,
    _FakeServer,
    patch_transport,
)

runner = CliRunner()
URL = "https://kanbai.example.com"


@pytest.fixture
def fake_server(monkeypatch: pytest.MonkeyPatch) -> _FakeServer:
    server = _FakeServer()
    patch_transport(monkeypatch, httpx.MockTransport(server.handle))
    return server


@pytest.fixture
def local_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    scaffold.init_board(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def empty_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "empty"
    target.mkdir()
    monkeypatch.chdir(target)
    return target


def _connect(*extra: str) -> object:
    """`hosted connect` to a brand-new hosted board (what most tests need as a starting point)."""
    return runner.invoke(
        app,
        [
            "hosted",
            "connect",
            "--url",
            URL,
            "--email",
            ADMIN_EMAIL,
            "--password",
            ADMIN_PASSWORD,
            "--create",
            *extra,
        ],
    )


def _board_id(project: Path) -> str:
    cfg_text = (project / ".kanbai" / "config.toml").read_text()
    return re.search(r'board_id = "([^"]+)"', cfg_text).group(1)  # type: ignore[union-attr]


def _add_remote_card(server: _FakeServer, board_id: str, title: str, card_id: str = "999") -> None:
    server.cards[board_id][card_id] = server._card_dict(  # noqa: SLF001
        board_id, id=card_id, title=title
    )


def _add_remote_board(server: _FakeServer, name: str) -> str:
    response = server._create_board({"name": name})  # noqa: SLF001
    return str(json.loads(response.content)["id"])


# --------------------------------------------------------------------------- connect


def _connect_args(*extra: str, password: bool = True) -> list[str]:
    args = ["hosted", "connect", "--url", URL, "--email", ADMIN_EMAIL]
    return [*args, *(["--password", ADMIN_PASSWORD] if password else []), *extra]


def test_connect_creates_a_hosted_board_and_saves_the_connection_without_sending_cards(
    local_project: Path, fake_server: _FakeServer
) -> None:
    Board.load(local_project).add("Not sent")

    result = runner.invoke(app, _connect_args("--create"))

    assert result.exit_code == 0, result.output
    config = (local_project / ".kanbai" / "config.toml").read_text()
    assert "[server]" in config
    assert f'url = "{URL}"' in config
    assert "token = " in config
    assert fake_server.cards[_board_id(local_project)] == {}
    assert "Created and connected" in result.output


def test_connect_to_an_existing_hosted_board_by_name_or_id(
    local_project: Path, fake_server: _FakeServer
) -> None:
    result = runner.invoke(app, _connect_args("--board", "remote BOARD"))

    assert result.exit_code == 0, result.output
    assert _board_id(local_project) == BOARD_ID
    assert fake_server.cards[BOARD_ID] == {}
    assert "Connected to" in result.output


def test_connect_prompts_for_the_password_when_omitted(
    local_project: Path, fake_server: _FakeServer
) -> None:
    result = runner.invoke(
        app, _connect_args("--create", password=False), input=f"{ADMIN_PASSWORD}\n"
    )

    assert result.exit_code == 0, result.output
    assert "[server]" in (local_project / ".kanbai" / "config.toml").read_text()


def test_connect_asks_which_board_and_offers_a_new_one(
    local_project: Path, fake_server: _FakeServer
) -> None:
    second = _add_remote_board(fake_server, "Second board")

    existing = runner.invoke(app, _connect_args(), input="2\n")

    assert existing.exit_code == 0, existing.output
    assert "0. New board" in existing.output
    assert _board_id(local_project) == second


def test_connect_menu_choice_zero_creates_a_new_board(
    local_project: Path, fake_server: _FakeServer
) -> None:
    result = runner.invoke(app, _connect_args(), input="0\n")

    assert result.exit_code == 0, result.output
    assert _board_id(local_project) not in {BOARD_ID}
    assert "Created and connected" in result.output


def test_connect_creates_a_board_when_the_account_has_none(
    local_project: Path, fake_server: _FakeServer
) -> None:
    fake_server.boards.clear()

    result = runner.invoke(app, _connect_args())

    assert result.exit_code == 0, result.output
    assert "no hosted boards yet" in result.output
    assert "Created and connected" in result.output


def test_connect_rejects_an_out_of_range_menu_choice(
    local_project: Path, fake_server: _FakeServer
) -> None:
    result = runner.invoke(app, _connect_args(), input="9\n")

    assert result.exit_code == 1
    assert "[server]" not in (local_project / ".kanbai" / "config.toml").read_text()


def test_connect_rejects_board_together_with_create(
    local_project: Path, fake_server: _FakeServer
) -> None:
    result = runner.invoke(app, _connect_args("--board", "x", "--create"))

    assert result.exit_code == 1
    assert "not both" in result.output


def test_connect_reports_an_unknown_board(local_project: Path, fake_server: _FakeServer) -> None:
    result = runner.invoke(app, _connect_args("--board", "nope"))

    assert result.exit_code == 1
    assert "No hosted board 'nope'" in result.output
    assert "[server]" not in (local_project / ".kanbai" / "config.toml").read_text()


def test_connect_fails_with_bad_credentials(local_project: Path, fake_server: _FakeServer) -> None:
    result = runner.invoke(
        app,
        ["hosted", "connect", "--url", URL, "--email", ADMIN_EMAIL, "--password", "wrong"],
    )

    assert result.exit_code == 1
    assert "error" in result.output.lower()
    assert "[server]" not in (local_project / ".kanbai" / "config.toml").read_text()


def test_connect_fails_without_a_local_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_server: _FakeServer
) -> None:
    monkeypatch.chdir(tmp_path)  # no .kanbai/ here

    result = runner.invoke(app, _connect_args("--create"))

    assert result.exit_code == 1
    assert "kanbai init" in result.output


def test_connect_refuses_to_replace_an_existing_connection(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()

    result = runner.invoke(app, _connect_args("--create"))

    assert result.exit_code == 1
    assert "Already connected" in result.output


# --------------------------------------------------------------------------- push


def test_push_requires_the_connection_and_points_to_connect(
    local_project: Path, fake_server: _FakeServer
) -> None:
    result = runner.invoke(app, ["hosted", "push"])

    assert result.exit_code == 1
    assert "hosted connect" in result.output


def test_push_no_longer_takes_credentials(local_project: Path, fake_server: _FakeServer) -> None:
    result = runner.invoke(app, ["hosted", "push", "--url", URL])

    assert result.exit_code == 2


def test_push_sends_the_local_cards(local_project: Path, fake_server: _FakeServer) -> None:
    Board.load(local_project).add("Local card")
    _connect()

    result = runner.invoke(app, ["hosted", "push"])

    assert result.exit_code == 0, result.output
    titles = [c["title"] for c in fake_server.cards[_board_id(local_project)].values()]
    assert titles == ["Local card"]
    assert "1 created" in result.output


def test_later_pushes_send_only_what_is_new(local_project: Path, fake_server: _FakeServer) -> None:
    Board.load(local_project).add("First")
    _connect()
    runner.invoke(app, ["hosted", "push"])
    Board.load(local_project).add("Second")

    result = runner.invoke(app, ["hosted", "push"])

    assert result.exit_code == 0, result.output
    assert "1 created" in result.output
    assert len(fake_server.cards[_board_id(local_project)]) == 2


def test_push_fails_without_a_local_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_server: _FakeServer
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["hosted", "push"])

    assert result.exit_code == 1


def test_push_delete_removes_hosted_cards_missing_locally(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    board_id = _board_id(local_project)
    _add_remote_card(fake_server, board_id, "Only on server")

    kept = runner.invoke(app, ["hosted", "push"])
    assert "1 kept on the other side" in kept.output
    assert "999" in fake_server.cards[board_id]

    result = runner.invoke(app, ["hosted", "push", "--delete"])

    assert result.exit_code == 0, result.output
    assert "999" not in fake_server.cards[board_id]
    assert "1 deleted" in result.output


def test_push_skips_archived_cards_unless_asked(
    local_project: Path, fake_server: _FakeServer
) -> None:
    board = Board.load(local_project)
    board.add("Active")
    shelved = board.add("Shelved")
    board.archive(shelved.id)
    _connect()
    board_id = _board_id(local_project)

    plain = runner.invoke(app, ["hosted", "push"])
    assert plain.exit_code == 0, plain.output
    assert set(fake_server.cards[board_id]) == {"001"}

    full = runner.invoke(app, ["hosted", "push", "--archived"])

    assert full.exit_code == 0, full.output
    assert fake_server.cards[board_id]["002"]["status"] == "archive"


# --------------------------------------------------------------------------- pull


def test_pull_requires_server_section(local_project: Path) -> None:
    result = runner.invoke(app, ["hosted", "pull"])

    assert result.exit_code == 1
    assert "error" in result.output.lower()
    assert "hosted connect" in result.output


def test_pull_writes_remote_cards_locally(local_project: Path, fake_server: _FakeServer) -> None:
    Board.load(local_project).add("Local card")
    _connect()
    runner.invoke(app, ["hosted", "push"])
    _add_remote_card(fake_server, _board_id(local_project), "Added remotely")

    result = runner.invoke(app, ["hosted", "pull"])

    assert result.exit_code == 0, result.output
    titles = {c.title for c in Board.load(local_project).list_column("backlog")}
    assert "Added remotely" in titles
    assert "1 created" in result.output


def test_pull_delete_removes_local_cards_missing_on_the_server(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    Board.load(local_project).add("Local only")

    kept = runner.invoke(app, ["hosted", "pull"])
    assert "1 kept on the other side" in kept.output

    result = runner.invoke(app, ["hosted", "pull", "--delete"])

    assert result.exit_code == 0, result.output
    assert not Board.load(local_project).list_column("backlog")
    assert "1 deleted" in result.output


# --------------------------------------------------------------------------- clone


def _clone(*extra: str, input_: str | None = None) -> object:
    args = ["hosted", "clone", "--url", URL, "--email", ADMIN_EMAIL, *extra]
    if input_ is None:
        args += ["--password", ADMIN_PASSWORD]
    return runner.invoke(app, args, input=input_)


def test_clone_creates_the_local_board_when_the_account_has_a_single_board(
    empty_dir: Path, fake_server: _FakeServer
) -> None:
    _add_remote_card(fake_server, BOARD_ID, "From the server", card_id="001")

    result = _clone()

    assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
    board = Board.load(empty_dir)
    assert board.config.name == "Remote board"
    assert [c.title for c in board.list_column("backlog")] == ["From the server"]
    assert f'board_id = "{BOARD_ID}"' in (empty_dir / ".kanbai" / "config.toml").read_text()
    assert "1 created" in result.output  # type: ignore[attr-defined]


def test_clone_prompts_for_the_password_when_omitted(
    empty_dir: Path, fake_server: _FakeServer
) -> None:
    result = _clone(input_=f"{ADMIN_PASSWORD}\n")

    assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
    assert (empty_dir / ".kanbai" / "config.toml").exists()


def test_clone_picks_among_several_boards_by_name_or_id(
    empty_dir: Path, fake_server: _FakeServer
) -> None:
    second = _add_remote_board(fake_server, "Second board")
    _add_remote_card(fake_server, second, "In the second", card_id="001")

    by_name = _clone("--board", "second BOARD")

    assert by_name.exit_code == 0, by_name.output  # type: ignore[attr-defined]
    assert Board.load(empty_dir).config.name == "Second board"
    assert f'board_id = "{second}"' in (empty_dir / ".kanbai" / "config.toml").read_text()


def test_clone_by_id(empty_dir: Path, fake_server: _FakeServer) -> None:
    _add_remote_board(fake_server, "Second board")

    result = _clone("--board", BOARD_ID)

    assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
    assert Board.load(empty_dir).config.name == "Remote board"


def test_clone_asks_which_board_when_there_are_several_and_none_is_given(
    empty_dir: Path, fake_server: _FakeServer
) -> None:
    _add_remote_board(fake_server, "Second board")

    result = _clone(input_=f"{ADMIN_PASSWORD}\n2\n")

    assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
    assert "1. Remote board" in result.output  # type: ignore[attr-defined]
    assert Board.load(empty_dir).config.name == "Second board"


def test_clone_rejects_an_out_of_range_choice(empty_dir: Path, fake_server: _FakeServer) -> None:
    _add_remote_board(fake_server, "Second board")

    result = _clone(input_=f"{ADMIN_PASSWORD}\n7\n")

    assert result.exit_code == 1  # type: ignore[attr-defined]
    assert not (empty_dir / ".kanbai").exists()


def test_clone_reports_unknown_and_ambiguous_boards(
    empty_dir: Path, fake_server: _FakeServer
) -> None:
    _add_remote_board(fake_server, "Twin")
    _add_remote_board(fake_server, "Twin")

    unknown = _clone("--board", "nope")
    ambiguous = _clone("--board", "twin")

    assert unknown.exit_code == 1  # type: ignore[attr-defined]
    assert "No hosted board 'nope'" in unknown.output  # type: ignore[attr-defined]
    assert ambiguous.exit_code == 1  # type: ignore[attr-defined]
    assert "--board <id>" in ambiguous.output  # type: ignore[attr-defined]
    assert not (empty_dir / ".kanbai").exists()


def test_clone_fails_when_a_local_board_already_exists(
    local_project: Path, fake_server: _FakeServer
) -> None:
    result = _clone()

    assert result.exit_code == 1  # type: ignore[attr-defined]
    assert "hosted pull" in result.output  # type: ignore[attr-defined]


def test_clone_fails_with_bad_credentials(empty_dir: Path, fake_server: _FakeServer) -> None:
    result = runner.invoke(
        app,
        ["hosted", "clone", "--url", URL, "--email", ADMIN_EMAIL, "--password", "wrong"],
    )

    assert result.exit_code == 1
    assert not (empty_dir / ".kanbai").exists()


def test_clone_fails_when_the_account_has_no_boards(
    empty_dir: Path, fake_server: _FakeServer
) -> None:
    fake_server.boards.clear()

    result = _clone()

    assert result.exit_code == 1  # type: ignore[attr-defined]
    assert "no hosted boards" in result.output  # type: ignore[attr-defined]


def test_a_cloned_project_stays_connected_for_pull_and_push(
    empty_dir: Path, fake_server: _FakeServer
) -> None:
    _clone()
    Board.load(empty_dir).add("Made after cloning")

    push = runner.invoke(app, ["hosted", "push"])
    pull = runner.invoke(app, ["hosted", "pull"])

    assert push.exit_code == 0, push.output
    assert pull.exit_code == 0, pull.output
    titles = [c["title"] for c in fake_server.cards[BOARD_ID].values()]
    assert "Made after cloning" in titles


# --------------------------------------------------------------------------- old commands gone


@pytest.mark.parametrize(
    "args",
    [
        ["sync", "pull"],
        ["sync", "push"],
        ["sync", "status"],
        ["hosted", "publish"],
        ["hosted", "download"],
    ],
)
def test_the_previous_commands_no_longer_exist(args: list[str]) -> None:
    result = runner.invoke(app, args)

    assert result.exit_code == 2


# --------------------------------------------------------------------------- diff


def test_hosted_diff_requires_server_section(local_project: Path) -> None:
    result = runner.invoke(app, ["hosted", "diff"])

    assert result.exit_code == 1
    assert "error" in result.output.lower()


def test_hosted_diff_exits_zero_when_in_sync(local_project: Path, fake_server: _FakeServer) -> None:
    Board.load(local_project).add("Local card")
    _connect()
    runner.invoke(app, ["hosted", "push"])

    result = runner.invoke(app, ["hosted", "diff"])

    assert result.exit_code == 0, result.output
    assert "in sync" in result.output.lower()


def test_hosted_diff_exits_one_and_reports_only_remote_card(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    _add_remote_card(fake_server, _board_id(local_project), "Added remotely")

    result = runner.invoke(app, ["hosted", "diff"])

    assert result.exit_code == 1
    assert "999" in result.output


def test_hosted_diff_json_output(local_project: Path, fake_server: _FakeServer) -> None:
    _connect()
    _add_remote_card(fake_server, _board_id(local_project), "Added remotely")

    result = runner.invoke(app, ["hosted", "diff", "--json"])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["in_sync"] is False
    assert data["only_remote"] == ["999"]
    assert data["only_local"] == []
    assert data["changed"] == []


# --------------------------------------------------------------------------- --archived


def _archived_on_server(fake_server: _FakeServer, board_id: str) -> None:
    fake_server.cards[board_id]["998"] = fake_server._card_dict(  # noqa: SLF001
        board_id, id="998", title="Shelved on server", status="archive", archived_from="backlog"
    )


def test_pull_skips_archived_cards_unless_asked(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    _archived_on_server(fake_server, _board_id(local_project))

    plain = runner.invoke(app, ["hosted", "pull"])
    assert plain.exit_code == 0, plain.output
    assert Board.load(local_project).list_archive() == []

    full = runner.invoke(app, ["hosted", "pull", "--archived"])

    assert full.exit_code == 0, full.output
    assert [c.title for c in Board.load(local_project).list_archive()] == ["Shelved on server"]


def test_clone_skips_archived_cards_unless_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_server: _FakeServer
) -> None:
    _archived_on_server(fake_server, BOARD_ID)
    plain_dir = tmp_path / "plain"
    full_dir = tmp_path / "full"
    plain_dir.mkdir()
    full_dir.mkdir()

    monkeypatch.chdir(plain_dir)
    assert _clone().exit_code == 0  # type: ignore[attr-defined]
    monkeypatch.chdir(full_dir)
    assert _clone("--archived").exit_code == 0  # type: ignore[attr-defined]

    assert Board.load(plain_dir).list_archive() == []
    assert [c.title for c in Board.load(full_dir).list_archive()] == ["Shelved on server"]


def test_diff_ignores_archived_cards_unless_asked(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    _archived_on_server(fake_server, _board_id(local_project))

    plain = runner.invoke(app, ["hosted", "diff"])
    full = runner.invoke(app, ["hosted", "diff", "--archived", "--json"])

    assert plain.exit_code == 0, plain.output
    assert full.exit_code == 1
    assert json.loads(full.output)["only_remote"] == ["998"]


# --------------------------------------------------------------------------- enable / disable


def test_disable_keeps_the_connection_and_enable_restores_it(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    before = (local_project / ".kanbai" / "config.toml").read_text()

    disabled = runner.invoke(app, ["hosted", "disable"])
    config_while_disabled = (local_project / ".kanbai" / "config.toml").read_text()
    enabled = runner.invoke(app, ["hosted", "enable"])

    assert disabled.exit_code == 0, disabled.output
    assert "enabled = false" in config_while_disabled
    for line in before.splitlines():
        if line.startswith(("url", "token", "board_id")):
            assert line in config_while_disabled
    assert enabled.exit_code == 0, enabled.output
    assert "enabled" not in (local_project / ".kanbai" / "config.toml").read_text()


def test_sync_commands_work_regardless_of_the_flag(
    local_project: Path, fake_server: _FakeServer
) -> None:
    Board.load(local_project).add("Local card")
    _connect()
    runner.invoke(app, ["hosted", "disable"])

    pushed = runner.invoke(app, ["hosted", "push"])
    pulled = runner.invoke(app, ["hosted", "pull"])
    diffed = runner.invoke(app, ["hosted", "diff"])

    assert pushed.exit_code == 0, pushed.output
    assert pulled.exit_code == 0, pulled.output
    assert diffed.exit_code == 0, diffed.output


def test_offline_work_syncs_while_still_disabled(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    runner.invoke(app, ["hosted", "disable"])
    created = runner.invoke(app, ["add", "Made offline", "--json"])

    pushed = runner.invoke(app, ["hosted", "push"])

    assert pushed.exit_code == 0, pushed.output
    remote = fake_server.cards[_board_id(local_project)]
    assert [c["title"] for c in remote.values()] == ["Made offline"]
    assert json.loads(created.output)["id"] in remote


def test_enable_and_disable_require_a_connection(
    local_project: Path, fake_server: _FakeServer
) -> None:
    for command in ("enable", "disable"):
        result = runner.invoke(app, ["hosted", command])

        assert result.exit_code == 1
        assert "hosted connect" in result.output


def test_status_reports_each_state(local_project: Path, fake_server: _FakeServer) -> None:
    assert "Not connected" in runner.invoke(app, ["hosted", "status"]).output
    _connect()
    assert "enabled" in runner.invoke(app, ["hosted", "status"]).output
    runner.invoke(app, ["hosted", "disable"])
    assert "disabled" in runner.invoke(app, ["hosted", "status"]).output
