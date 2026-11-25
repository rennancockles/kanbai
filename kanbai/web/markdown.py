"""Safe Markdown rendering for card bodies shown in the web UI."""

from __future__ import annotations

from typing import Any

from markdown_it import MarkdownIt
from markupsafe import Markup

_SAFE_SCHEMES = ("http://", "https://")


class _SafeMarkdownIt(MarkdownIt):
    def validateLink(self, url: str) -> bool:  # noqa: N802 - overrides the library's name
        return url.strip().lower().startswith(_SAFE_SCHEMES)


def _open_link_in_new_tab(self: Any, tokens: Any, idx: int, options: Any, env: Any) -> str:
    token = tokens[idx]
    token.attrSet("target", "_blank")
    token.attrSet("rel", "noopener noreferrer")
    return str(self.renderToken(tokens, idx, options, env))


def _build() -> MarkdownIt:
    # Raw HTML stays off (it is shown as text), images are not loaded (no remote content from
    # a card body) and only http(s) links are clickable. A single newline is a line break so
    # cards written one item per line keep reading the way they did as plain text.
    md = _SafeMarkdownIt("commonmark", {"html": False, "breaks": True}).enable("table")
    md.disable("image")
    md.add_render_rule("link_open", _open_link_in_new_tab)
    return md


_MD = _build()


def render_markdown(text: str) -> Markup:
    """Render ``text`` as sanitized HTML, ready to drop into a template."""
    return Markup(_MD.render(text))  # noqa: S704 - html input is disabled, output is escaped
