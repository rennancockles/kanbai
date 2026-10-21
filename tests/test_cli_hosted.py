"""CLI-level tests for `kanbai hosted push` / `pull` / `clone` / `diff`."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx2 as httpx
import pytest
from kanbai import cli, credentials, hosted, registry, scaffold
from kanbai.board import Board
from kanbai.cli import app
from kanbai.config import load_remote_config
from typer.testing import CliRunner

from test_remote_board import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    ADMIN_TOKEN,
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
def tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the confirmation prompt believe a person is at the keyboard."""
    monkeypatch.setattr(cli, "_interactive", lambda: True)


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
    result = runner.invoke(app, ["hosted", "push", "-y"])

    assert result.exit_code == 1
    assert "hosted connect" in result.output


def test_push_no_longer_takes_credentials(local_project: Path, fake_server: _FakeServer) -> None:
    result = runner.invoke(app, ["hosted", "push", "-y", "--url", URL])

    assert result.exit_code == 2


def test_push_sends_the_local_cards(local_project: Path, fake_server: _FakeServer) -> None:
    Board.load(local_project).add("Local card")
    _connect()

    result = runner.invoke(app, ["hosted", "push", "-y"])

    assert result.exit_code == 0, result.output
    titles = [c["title"] for c in fake_server.cards[_board_id(local_project)].values()]
    assert titles == ["Local card"]
    assert "1 created" in result.output


def test_later_pushes_send_only_what_is_new(local_project: Path, fake_server: _FakeServer) -> None:
    Board.load(local_project).add("First")
    _connect()
    runner.invoke(app, ["hosted", "push", "-y"])
    Board.load(local_project).add("Second")

    result = runner.invoke(app, ["hosted", "push", "-y"])

    assert result.exit_code == 0, result.output
    assert "1 created" in result.output
    assert len(fake_server.cards[_board_id(local_project)]) == 2


def test_push_fails_without_a_local_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_server: _FakeServer
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["hosted", "push", "-y"])

    assert result.exit_code == 1


def test_push_delete_removes_hosted_cards_missing_locally(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    board_id = _board_id(local_project)
    _add_remote_card(fake_server, board_id, "Only on server")

    kept = runner.invoke(app, ["hosted", "push", "-y"])
    assert "1 kept on the other side" in kept.output
    assert "999" in fake_server.cards[board_id]

    result = runner.invoke(app, ["hosted", "push", "-y", "--delete"])

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

    plain = runner.invoke(app, ["hosted", "push", "-y"])
    assert plain.exit_code == 0, plain.output
    assert set(fake_server.cards[board_id]) == {"001"}

    full = runner.invoke(app, ["hosted", "push", "-y", "--archived"])

    assert full.exit_code == 0, full.output
    assert fake_server.cards[board_id]["002"]["status"] == "archive"


# --------------------------------------------------------------------------- pull


def test_pull_requires_server_section(local_project: Path) -> None:
    result = runner.invoke(app, ["hosted", "pull", "-y"])

    assert result.exit_code == 1
    assert "error" in result.output.lower()
    assert "hosted connect" in result.output


def test_pull_writes_remote_cards_locally(local_project: Path, fake_server: _FakeServer) -> None:
    Board.load(local_project).add("Local card")
    _connect()
    runner.invoke(app, ["hosted", "push", "-y"])
    _add_remote_card(fake_server, _board_id(local_project), "Added remotely")

    result = runner.invoke(app, ["hosted", "pull", "-y"])

    assert result.exit_code == 0, result.output
    titles = {c.title for c in Board.load(local_project).list_column("backlog")}
    assert "Added remotely" in titles
    assert "1 created" in result.output


def test_pull_delete_removes_local_cards_missing_on_the_server(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    Board.load(local_project).add("Local only")

    kept = runner.invoke(app, ["hosted", "pull", "-y"])
    assert "1 kept on the other side" in kept.output

    result = runner.invoke(app, ["hosted", "pull", "-y", "--delete"])

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

    push = runner.invoke(app, ["hosted", "push", "-y"])
    pull = runner.invoke(app, ["hosted", "pull", "-y"])

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
    runner.invoke(app, ["hosted", "push", "-y"])

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

    plain = runner.invoke(app, ["hosted", "pull", "-y"])
    assert plain.exit_code == 0, plain.output
    assert Board.load(local_project).list_archive() == []

    full = runner.invoke(app, ["hosted", "pull", "-y", "--archived"])

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

    pushed = runner.invoke(app, ["hosted", "push", "-y"])
    pulled = runner.invoke(app, ["hosted", "pull", "-y"])
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

    pushed = runner.invoke(app, ["hosted", "push", "-y"])

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


# --------------------------------------------------------------------------- --all


@pytest.fixture
def hub_boards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_server: _FakeServer
) -> dict[str, Path]:
    """Three boards in the hub registry: `alpha` (connected), `beta` (never connected) and
    `gamma` (connected to a hosted board that does not exist), with cwd outside all of them."""
    monkeypatch.setenv("KANBAI_HOME", str(tmp_path / "home"))
    projects = {}
    for name in ("alpha", "beta", "gamma"):
        project = tmp_path / name
        scaffold.init_board(project, name=name)
        registry.add_board(project)
        projects[name] = project
    Board.load(projects["alpha"]).add("Alpha card")
    monkeypatch.chdir(projects["alpha"])
    _connect()
    gamma_cfg = projects["gamma"] / ".kanbai" / "config.toml"
    gamma_cfg.write_text(
        gamma_cfg.read_text()
        + f'\n[server]\nurl = "{URL}"\ntoken = "tok"\nboard_id = "does-not-exist"\n'
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return projects


def test_push_all_syncs_connected_boards_and_reports_the_rest(
    hub_boards: dict[str, Path], fake_server: _FakeServer
) -> None:
    result = runner.invoke(app, ["hosted", "push", "-y", "--all"])

    assert result.exit_code == 1  # gamma failed
    titles = [c["title"] for c in fake_server.cards[_board_id(hub_boards["alpha"])].values()]
    assert titles == ["Alpha card"]
    assert re.search(r"alpha\s*│\s*ok\s*│\s*1 created", result.output)
    assert re.search(r"beta\s*│\s*skipped\s*│\s*not connected", result.output)
    assert re.search(r"gamma\s*│\s*failed", result.output)


def test_push_all_exits_zero_when_nothing_failed(
    hub_boards: dict[str, Path], fake_server: _FakeServer
) -> None:
    registry.remove_board("gamma")

    result = runner.invoke(app, ["hosted", "push", "-y", "--all"])

    assert result.exit_code == 0, result.output


def _titles(project: Path) -> set[str]:
    return {c.title for cards in Board.load(project).board().values() for c in cards}


def test_pull_all_previews_every_board_and_confirms_once(
    hub_boards: dict[str, Path], fake_server: _FakeServer, tty: None
) -> None:
    registry.remove_board("gamma")
    _add_remote_card(fake_server, _board_id(hub_boards["alpha"]), "From server")

    declined = runner.invoke(app, ["hosted", "pull", "--all"], input="n\n")
    assert declined.exit_code == 0, declined.output
    assert "alpha:" in declined.output and "create 1 card: 999" in declined.output
    assert "Aborted" in declined.output
    assert "From server" not in _titles(hub_boards["alpha"])

    confirmed = runner.invoke(app, ["hosted", "pull", "--all"], input="y\n")
    assert confirmed.exit_code == 0, confirmed.output
    assert "From server" in _titles(hub_boards["alpha"])


def test_pull_all_with_yes_applies_without_asking(
    hub_boards: dict[str, Path], fake_server: _FakeServer
) -> None:
    registry.remove_board("gamma")
    _add_remote_card(fake_server, _board_id(hub_boards["alpha"]), "From server")

    result = runner.invoke(app, ["hosted", "pull", "--all", "-y"])

    assert result.exit_code == 0, result.output
    assert "will change" not in result.output
    assert "From server" in _titles(hub_boards["alpha"])


def test_push_all_previews_and_needs_a_terminal_or_yes(
    hub_boards: dict[str, Path], fake_server: _FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry.remove_board("gamma")
    board_id = _board_id(hub_boards["alpha"])

    refused = runner.invoke(app, ["hosted", "push", "--all"])
    assert refused.exit_code == 1
    assert "create 1 card: 001" in refused.output and "--yes" in refused.output
    assert not fake_server.cards.get(board_id)

    monkeypatch.setattr(cli, "_interactive", lambda: True)
    declined = runner.invoke(app, ["hosted", "push", "--all"], input="n\n")
    assert declined.exit_code == 0 and not fake_server.cards.get(board_id)
    accepted = runner.invoke(app, ["hosted", "push", "--all"], input="y\n")
    assert accepted.exit_code == 0, accepted.output
    assert [c["title"] for c in fake_server.cards[board_id].values()] == ["Alpha card"]


def test_all_without_yes_does_not_ask_when_no_board_has_changes(
    hub_boards: dict[str, Path], fake_server: _FakeServer
) -> None:
    registry.remove_board("gamma")
    assert runner.invoke(app, ["hosted", "push", "--all", "-y"]).exit_code == 0

    result = runner.invoke(app, ["hosted", "push", "--all"])

    assert result.exit_code == 0, result.output
    assert "will change" not in result.output


def test_diff_all_json_lists_each_board(
    hub_boards: dict[str, Path], fake_server: _FakeServer
) -> None:
    result = runner.invoke(app, ["hosted", "diff", "--all", "--json"])

    assert result.exit_code == 1
    by_board = {row["board"]: row for row in json.loads(result.output)}
    assert by_board["alpha"]["status"] == "differs"  # local card not pushed yet
    assert by_board["beta"]["status"] == "skipped"
    assert by_board["gamma"]["status"] == "failed"


def test_all_with_an_empty_registry_is_a_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_server: _FakeServer
) -> None:
    monkeypatch.setenv("KANBAI_HOME", str(tmp_path / "home"))

    result = runner.invoke(app, ["hosted", "push", "-y", "--all"])

    assert result.exit_code == 0
    assert "No boards registered" in result.output


def test_all_skips_remaining_boards_once_a_host_is_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KANBAI_HOME", str(tmp_path / "home"))
    fake_server = _FakeServer()
    down_requests: list[str] = []

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "down.example.com":
            down_requests.append(request.url.path)
            return httpx.Response(403, text="<html>blocked by firewall</html>")
        return fake_server.handle(request)

    patch_transport(monkeypatch, httpx.MockTransport(route))
    for name in ("a1", "a2", "b"):
        project = tmp_path / name
        scaffold.init_board(project, name=name)
        registry.add_board(project)
    for name in ("a1", "a2"):
        cfg = tmp_path / name / ".kanbai" / "config.toml"
        cfg.write_text(
            cfg.read_text()
            + '\n[server]\nurl = "https://down.example.com"\ntoken = "tok"\nboard_id = "x"\n'
        )
    monkeypatch.chdir(tmp_path / "b")
    _connect()

    outcomes = {o.name: o for o in hosted.sync_all(registry.load_boards(), "push")}

    assert outcomes["a1"].status == "failed"
    assert "VPN, firewall or proxy" in outcomes["a1"].message
    assert outcomes["a2"].status == "skipped"
    assert "unreachable" in outcomes["a2"].message
    assert outcomes["b"].status == "ok"
    assert len(down_requests) == 1  # only a1 touched the dead host


# --------------------------------------------------------------------------- login


def _login_args(*extra: str, password: str = ADMIN_PASSWORD) -> list[str]:
    return ["hosted", "login", "--email", ADMIN_EMAIL, "--password", password, *extra]


def test_login_renews_only_the_token(local_project: Path, fake_server: _FakeServer) -> None:
    _connect()
    cfg_path = local_project / ".kanbai" / "config.toml"
    cfg_path.write_text(cfg_path.read_text().replace(ADMIN_TOKEN, "stale-token"))
    runner.invoke(app, ["hosted", "disable"])
    before = load_remote_config(local_project / ".kanbai")
    assert before is not None
    assert before.token == "stale-token"

    result = runner.invoke(app, _login_args())

    assert result.exit_code == 0, result.output
    after = load_remote_config(local_project / ".kanbai")
    assert after is not None
    assert after.token == ADMIN_TOKEN
    assert (after.url, after.board_id) == (before.url, before.board_id)
    assert after.enabled is False  # the enable/disable state survives


def test_login_with_bad_credentials_keeps_the_old_token(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    before = (local_project / ".kanbai" / "config.toml").read_text()

    result = runner.invoke(app, _login_args(password="wrong"))

    assert result.exit_code == 1
    assert "Invalid email or password" in result.output
    assert (local_project / ".kanbai" / "config.toml").read_text() == before


def test_login_requires_a_connection(local_project: Path, fake_server: _FakeServer) -> None:
    result = runner.invoke(app, _login_args())

    assert result.exit_code == 1
    assert "hosted connect" in result.output


def test_login_inside_a_project_also_saves_the_token_globally(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()

    result = runner.invoke(app, _login_args())

    assert result.exit_code == 0, result.output
    assert credentials.load_token(URL) == ADMIN_TOKEN


def test_login_with_url_works_from_any_directory_and_fixes_every_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_server: _FakeServer
) -> None:
    projects = []
    for name in ("one", "two"):
        project = tmp_path / name
        scaffold.init_board(project, name=name)
        cfg = project / ".kanbai" / "config.toml"
        cfg.write_text(
            cfg.read_text() + f'\n[server]\nurl = "{URL}"\ntoken = "stale"\nboard_id = "x"\n'
        )
        projects.append(project)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = runner.invoke(app, _login_args("--url", URL))

    assert result.exit_code == 0, result.output
    for project in projects:
        remote = load_remote_config(project / ".kanbai")
        assert remote is not None
        assert remote.token == ADMIN_TOKEN  # global token wins over the stale file token
        assert 'token = "stale"' in (project / ".kanbai" / "config.toml").read_text()


def test_global_token_takes_precedence_over_the_project_token(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    credentials.save_token(URL, "global-token")

    remote = load_remote_config(local_project / ".kanbai")

    assert remote is not None
    assert remote.token == "global-token"


def test_a_server_without_a_global_token_keeps_using_the_project_token(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    credentials.save_token("https://other.example", "other-token")

    remote = load_remote_config(local_project / ".kanbai")

    assert remote is not None
    assert remote.token == ADMIN_TOKEN


def test_login_url_for_another_server_leaves_the_project_token_alone(
    local_project: Path, fake_server: _FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    _connect()
    before = (local_project / ".kanbai" / "config.toml").read_text()

    result = runner.invoke(app, _login_args("--url", "https://other.example"))

    assert result.exit_code == 0, result.output
    assert (local_project / ".kanbai" / "config.toml").read_text() == before
    assert credentials.load_token("https://other.example") == ADMIN_TOKEN


def test_login_without_a_project_or_url_explains_both_ways_out(
    empty_dir: Path, fake_server: _FakeServer
) -> None:
    result = runner.invoke(app, _login_args())

    assert result.exit_code == 1
    assert "hosted connect" in result.output
    assert "--url" in result.output


def test_login_with_bad_credentials_saves_nothing_globally(
    empty_dir: Path, fake_server: _FakeServer
) -> None:
    result = runner.invoke(app, _login_args("--url", URL, password="wrong"))

    assert result.exit_code == 1
    assert credentials.load_token(URL) is None


def test_a_fresh_connect_is_not_overridden_by_an_older_global_token(
    local_project: Path, fake_server: _FakeServer
) -> None:
    credentials.save_token(URL, "older-global-token")

    _connect()

    remote = load_remote_config(local_project / ".kanbai")
    assert remote is not None
    assert remote.token == ADMIN_TOKEN
    assert credentials.load_token(URL) == ADMIN_TOKEN


def test_all_reports_an_expired_token_with_the_login_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KANBAI_HOME", str(tmp_path / "home"))
    patch_transport(
        monkeypatch,
        httpx.MockTransport(lambda request: httpx.Response(401, json={"detail": "Token expired"})),
    )
    project = tmp_path / "old"
    scaffold.init_board(project, name="old")
    registry.add_board(project)
    cfg = project / ".kanbai" / "config.toml"
    cfg.write_text(cfg.read_text() + f'\n[server]\nurl = "{URL}"\ntoken = "old"\nboard_id = "x"\n')

    (outcome,) = hosted.sync_all(registry.load_boards(), "push")

    assert outcome.status == "failed"
    assert "kanbai hosted login" in outcome.message


def test_push_with_settings_sends_the_board_settings(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    config_path = local_project / ".kanbai" / "config.toml"
    config_path.write_text(
        config_path.read_text().replace('# category = "Work"\n', 'category = "Work"\n', 1)
    )

    plain = runner.invoke(app, ["hosted", "push", "-y"])
    with_settings = runner.invoke(app, ["hosted", "push", "-y", "--settings"])
    again = runner.invoke(app, ["hosted", "push", "-y", "--settings"])

    assert plain.exit_code == 0 and "settings" not in plain.output
    assert with_settings.exit_code == 0, with_settings.output
    assert "settings updated: category" in with_settings.output
    assert "settings already in sync" in again.output
    boards = [b for b in fake_server.boards.values() if b.get("category") == "Work"]
    assert len(boards) == 1


def test_pull_with_settings_updates_config_toml(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    remote_id = load_remote_config(local_project / ".kanbai").board_id  # type: ignore[union-attr]
    fake_server.boards[remote_id]["category"] = "Home"

    plain = runner.invoke(app, ["hosted", "pull", "-y"])
    with_settings = runner.invoke(app, ["hosted", "pull", "-y", "--settings"])

    assert plain.exit_code == 0 and "settings" not in plain.output
    assert with_settings.exit_code == 0, with_settings.output
    assert "settings updated: category" in with_settings.output
    config_text = (local_project / ".kanbai" / "config.toml").read_text()
    assert 'category = "Home"' in config_text
    assert load_remote_config(local_project / ".kanbai") is not None


def test_push_settings_to_an_old_server_fails_with_a_clear_message(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    config_path = local_project / ".kanbai" / "config.toml"
    config_path.write_text(
        config_path.read_text().replace('# category = "Work"\n', 'category = "Work"\n', 1)
    )
    fake_server.supports_settings = False

    result = runner.invoke(app, ["hosted", "push", "-y", "--settings"])

    assert result.exit_code == 1
    assert "update kanbai_server" in result.output


# --------------------------------------------------------------------------- confirmation


def test_push_without_yes_shows_the_changes_and_refuses_without_a_terminal(
    local_project: Path, fake_server: _FakeServer
) -> None:
    Board.load(local_project).add("Local card")
    _connect()

    result = runner.invoke(app, ["hosted", "push"])

    assert result.exit_code == 1
    assert "will change the hosted board" in result.output
    assert "create 1 card: 001" in result.output
    assert "--yes" in result.output
    assert not fake_server.cards.get(_board_id(local_project))


def test_push_applies_after_confirmation(
    local_project: Path, fake_server: _FakeServer, tty: None
) -> None:
    Board.load(local_project).add("Local card")
    _connect()

    result = runner.invoke(app, ["hosted", "push"], input="y\n")

    assert result.exit_code == 0, result.output
    assert "Apply these changes?" in result.output and "1 created" in result.output
    titles = [c["title"] for c in fake_server.cards[_board_id(local_project)].values()]
    assert titles == ["Local card"]


def test_push_declined_changes_nothing_and_exits_cleanly(
    local_project: Path, fake_server: _FakeServer, tty: None
) -> None:
    Board.load(local_project).add("Local card")
    _connect()

    result = runner.invoke(app, ["hosted", "push"], input="n\n")

    assert result.exit_code == 0, result.output
    assert "Aborted; nothing was changed." in result.output and "created" not in result.output
    assert not fake_server.cards.get(_board_id(local_project))


def test_push_with_yes_applies_at_once_without_previewing(
    local_project: Path, fake_server: _FakeServer, tty: None
) -> None:
    Board.load(local_project).add("Local card")
    _connect()

    result = runner.invoke(app, ["hosted", "push", "--yes"])

    assert result.exit_code == 0, result.output
    assert "will change" not in result.output and "Apply" not in result.output
    assert "1 created" in result.output


def test_push_with_nothing_to_change_does_not_ask(
    local_project: Path, fake_server: _FakeServer
) -> None:
    Board.load(local_project).add("Local card")
    _connect()
    runner.invoke(app, ["hosted", "push", "-y"])

    result = runner.invoke(app, ["hosted", "push"])

    assert result.exit_code == 0, result.output
    assert "will change" not in result.output and "0 created, 0 updated" in result.output


def test_push_preview_shows_hosted_value_then_the_local_one(
    local_project: Path, fake_server: _FakeServer, tty: None
) -> None:
    card = Board.load(local_project).add("Old title")
    _connect()
    runner.invoke(app, ["hosted", "push", "-y"])
    Board.load(local_project).edit(card.id, title="New title")

    result = runner.invoke(app, ["hosted", "push"], input="n\n")

    assert "update 1 card" in result.output
    assert f"{card.id} title: 'Old title' -> 'New title'" in result.output


def test_push_delete_preview_lists_the_cards_to_remove(
    local_project: Path, fake_server: _FakeServer, tty: None
) -> None:
    _connect()
    board_id = _board_id(local_project)
    _add_remote_card(fake_server, board_id, "Only on server")

    kept = runner.invoke(app, ["hosted", "push"])
    deleting = runner.invoke(app, ["hosted", "push", "--delete"], input="y\n")

    assert kept.exit_code == 0 and "will change" not in kept.output
    assert "delete 1 card: 999" in deleting.output
    assert "999" not in fake_server.cards[board_id]


def test_push_settings_preview_lists_the_setting_changes(
    local_project: Path, fake_server: _FakeServer, tty: None
) -> None:
    _connect()
    config_path = local_project / ".kanbai" / "config.toml"
    config_path.write_text(
        config_path.read_text().replace('# category = "Work"\n', 'category = "Work"\n', 1)
    )

    declined = runner.invoke(app, ["hosted", "push", "--settings"], input="n\n")

    assert "update settings:" in declined.output and "category:" in declined.output
    assert "'Work'" in declined.output
    assert not [b for b in fake_server.boards.values() if b.get("category") == "Work"]

    applied = runner.invoke(app, ["hosted", "push", "--settings"], input="y\n")
    assert "settings updated: category" in applied.output


def test_pull_preview_shows_local_value_then_the_hosted_one(
    local_project: Path, fake_server: _FakeServer, tty: None
) -> None:
    card = Board.load(local_project).add("Local title")
    _connect()
    runner.invoke(app, ["hosted", "push", "-y"])
    board_id = _board_id(local_project)
    fake_server.cards[board_id][card.id]["title"] = "Hosted title"
    _add_remote_card(fake_server, board_id, "Added remotely")

    declined = runner.invoke(app, ["hosted", "pull"], input="n\n")

    assert declined.exit_code == 0, declined.output
    assert "will change your local board" in declined.output
    assert "create 1 card: 999" in declined.output
    assert f"{card.id} title: 'Local title' -> 'Hosted title'" in declined.output
    assert Board.load(local_project).show(card.id).title == "Local title"

    confirmed = runner.invoke(app, ["hosted", "pull"], input="y\n")
    assert confirmed.exit_code == 0, confirmed.output
    assert Board.load(local_project).show(card.id).title == "Hosted title"


def test_pull_without_yes_refuses_without_a_terminal(
    local_project: Path, fake_server: _FakeServer
) -> None:
    _connect()
    _add_remote_card(fake_server, _board_id(local_project), "Added remotely")

    result = runner.invoke(app, ["hosted", "pull"])

    assert result.exit_code == 1 and "--yes" in result.output
    assert not Board.load(local_project).list_column("backlog")


def test_pull_settings_preview_lists_the_hosted_values(
    local_project: Path, fake_server: _FakeServer, tty: None
) -> None:
    _connect()
    remote_id = load_remote_config(local_project / ".kanbai").board_id  # type: ignore[union-attr]
    fake_server.boards[remote_id]["category"] = "Home"

    declined = runner.invoke(app, ["hosted", "pull", "--settings"], input="n\n")

    assert "update settings:" in declined.output and "'Home'" in declined.output
    assert 'category = "Home"' not in (local_project / ".kanbai" / "config.toml").read_text()
