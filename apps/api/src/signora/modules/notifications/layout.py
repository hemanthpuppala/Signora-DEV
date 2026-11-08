"""The one email layout every module uses (Phase 2 LLD §1a.2).

Callers own the words; this gives them a plain, accessible text part and a matching HTML part in
the design system's black and white. Jinja2 autoescaping makes caller text safe in HTML.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from jinja2 import Environment, PackageLoader, StrictUndefined

_env = Environment(
    loader=PackageLoader("signora.modules.notifications", "templates"),
    autoescape=True,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)
_HTML = _env.get_template("layout.html")


@dataclass(frozen=True)
class EmailAction:
    label: str
    url: str


@dataclass(frozen=True)
class RenderedEmail:
    text: str
    html: str


def render_layout(
    *,
    heading: str,
    paragraphs: Sequence[str],
    action: EmailAction | None = None,
    footer: str | None = None,
) -> RenderedEmail:
    """Text and HTML parts with the same content. Inputs are plain text, never HTML."""
    lines = [heading, "", *(f"{p}\n" for p in paragraphs)]
    if action is not None:
        lines += [f"{action.label}: {action.url}", ""]
    if footer:
        lines += ["--", footer, ""]
    html = _HTML.render(heading=heading, paragraphs=paragraphs, action=action, footer=footer)
    return RenderedEmail(text="\n".join(lines).rstrip() + "\n", html=html)
