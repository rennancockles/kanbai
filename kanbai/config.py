"""Loading and rendering of the board configuration file."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .models import BoardConfig, Priority

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib  # ty: ignore[unresolved-import]

CONFIG_FILENAME = "config.toml"
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _apply_notifications(config: BoardConfig, notifications: dict[str, object]) -> None:
    native = notifications.get("native")
    if isinstance(native, bool):
        config.notifications_native = native
    ntfy_topic = notifications.get("ntfy_topic")
    if isinstance(ntfy_topic, str):
        config.notifications_ntfy_topic = ntfy_topic


def load_config(kanbai_dir: Path) -> BoardConfig:
    """Load ``config.toml`` from a ``.kanbai/`` directory, falling back to defaults."""
    config_path = kanbai_dir / CONFIG_FILENAME
    if not config_path.exists():
        return BoardConfig()

    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    board = raw.get("board", {})
    defaults = raw.get("defaults", {})
    wip = raw.get("wip", {})
    types = raw.get("types", {})

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
    if isinstance(wip, dict):
        config.wip = {str(col): int(limit) for col, limit in wip.items() if isinstance(limit, int)}
    available_types = types.get("available")
    if isinstance(available_types, list):
        config.types = [str(t) for t in available_types]
    colors = types.get("colors")
    if isinstance(colors, dict):
        config.type_colors = {
            str(t): str(c) for t, c in colors.items() if _HEX_COLOR_RE.match(str(c))
        }
    _apply_notifications(config, raw.get("notifications", {}))
    return config


def render_config(config: BoardConfig) -> str:
    """Render a :class:`BoardConfig` back to TOML text for ``kanbai init``."""
    columns = ", ".join(f'"{c}"' for c in config.columns)
    types = ", ".join(f'"{t}"' for t in config.types)
    return (
        "[board]\n"
        f'name = "{config.name}"\n'
        f"columns = [{columns}]\n"
        "\n"
        "[defaults]\n"
        f'priority = "{config.default_priority.value}"\n'
        "\n"
        "[types]\n"
        f"available = [{types}]\n"
        "\n"
        "# Optional hex color overrides for the UI badge, per type (default is a\n"
        "# built-in color for the types above, or gray for anything else).\n"
        "# [types.colors]\n"
        '# bug = "#ff0000"\n'
        "\n"
        "# Optional work-in-progress limits per column (warn when exceeded).\n"
        "# [wip]\n"
        "# doing = 3\n"
        "\n"
        "# Native desktop notifications (when a card reaches review/done, or the sprint runs\n"
        "# out of actionable cards) are on by default; disable them here if you don't want\n"
        "# them. Set ntfy_topic to also push to https://ntfy.sh — a public server with no\n"
        "# auth, so pick a topic name that's not easily guessable.\n"
        "# [notifications]\n"
        "# native = false\n"
        '# ntfy_topic = "my-kanbai-topic"\n'
    )
