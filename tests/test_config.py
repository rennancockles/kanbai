"""Tests for column-role resolution on BoardConfig."""

from __future__ import annotations

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
