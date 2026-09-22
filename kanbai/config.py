"""Loading and rendering of the board configuration file."""

from __future__ import annotations

import sys
from pathlib import Path

from .models import BoardConfig, Priority

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib  # ty: ignore[unresolved-import]

CONFIG_FILENAME = "config.toml"


def load_config(kanbai_dir: Path) -> BoardConfig:
    """Load ``config.toml`` from a ``.kanbai/`` directory, falling back to defaults."""
    config_path = kanbai_dir / CONFIG_FILENAME
    if not config_path.exists():
        return BoardConfig()

    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    board = raw.get("board", {})
    defaults = raw.get("defaults", {})

    config = BoardConfig()
    name = board.get("name")
    if isinstance(name, str):
        config.name = name
    columns = board.get("columns")
    if isinstance(columns, list):
        config.columns = [str(column) for column in columns]
    priority = defaults.get("priority")
    if isinstance(priority, str):
        config.default_priority = Priority(priority)
    return config


def render_config(config: BoardConfig) -> str:
    """Render a :class:`BoardConfig` back to TOML text for ``kanbai init``."""
    columns = ", ".join(f'"{c}"' for c in config.columns)
    return (
        "[board]\n"
        f'name = "{config.name}"\n'
        f"columns = [{columns}]\n"
        "\n"
        "[defaults]\n"
        f'priority = "{config.default_priority.value}"\n'
    )
