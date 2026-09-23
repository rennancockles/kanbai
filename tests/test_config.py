"""Tests for column-role resolution and WIP config on BoardConfig."""

from __future__ import annotations

from pathlib import Path

from kanbai import scaffold
from kanbai.config import load_config, render_config
from kanbai.models import BoardConfig


def test_default_columns_include_review() -> None:
    config = BoardConfig()
    assert config.columns == ["backlog", "todo", "doing", "review", "done"]


def test_roles_resolve_by_known_name() -> None:
    config = BoardConfig()
    assert config.add_column == "backlog"
    assert config.sprint_column == "todo"
    assert config.doing_column == "doing"
    assert config.review_column == "review"
    assert config.done_column == "done"


def test_review_absent_without_a_review_column() -> None:
    config = BoardConfig(columns=["backlog", "todo", "doing", "done"])
    assert config.review_column is None
    # The other roles still resolve to their known names.
    assert config.doing_column == "doing"
    assert config.done_column == "done"
    assert config.sprint_column == "todo"


def test_roles_fall_back_positionally_for_custom_names() -> None:
    config = BoardConfig(columns=["ideas", "wip", "shipped"])
    assert config.add_column == "ideas"  # first column
    assert config.doing_column == "wip"  # one before the end
    assert config.done_column == "shipped"  # last
    assert config.review_column is None


def test_wip_limit_lookup() -> None:
    config = BoardConfig(wip={"doing": 3})
    assert config.wip_limit("doing") == 3
    assert config.wip_limit("todo") is None  # no limit configured


def test_load_config_reads_wip_section(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    cfg = tmp_path / ".kanbai" / "config.toml"
    cfg.write_text(cfg.read_text() + "\n[wip]\ndoing = 3\ntodo = 8\n")
    config = load_config(tmp_path / ".kanbai")
    assert config.wip == {"doing": 3, "todo": 8}


def test_config_without_wip_has_no_limits() -> None:
    assert BoardConfig().wip == {}


def test_default_types() -> None:
    assert BoardConfig().types == ["feature", "bug", "refactor", "chore", "docs", "spike"]


def test_load_config_reads_types_section(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    cfg = tmp_path / ".kanbai" / "config.toml"
    text = cfg.read_text().replace(
        'available = ["feature", "bug", "refactor", "chore", "docs", "spike"]',
        'available = ["custom-a", "custom-b"]',
    )
    cfg.write_text(text)
    config = load_config(tmp_path / ".kanbai")
    assert config.types == ["custom-a", "custom-b"]


def test_render_config_includes_types() -> None:
    text = render_config(BoardConfig())
    assert '[types]\navailable = ["feature", "bug", "refactor", "chore", "docs", "spike"]' in text


def test_default_type_colors_are_empty() -> None:
    assert BoardConfig().type_colors == {}


def test_load_config_reads_type_colors(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    cfg = tmp_path / ".kanbai" / "config.toml"
    cfg.write_text(cfg.read_text() + '\n[types.colors]\nbug = "#ff0000"\nspec = "#00ffaa"\n')
    config = load_config(tmp_path / ".kanbai")
    assert config.type_colors == {"bug": "#ff0000", "spec": "#00ffaa"}


def test_load_config_ignores_invalid_hex_colors(tmp_path: Path) -> None:
    scaffold.init_board(tmp_path)
    cfg = tmp_path / ".kanbai" / "config.toml"
    cfg.write_text(cfg.read_text() + '\n[types.colors]\nbug = "not-a-color"\nchore = "#abc123"\n')
    config = load_config(tmp_path / ".kanbai")
    assert config.type_colors == {"chore": "#abc123"}
