"""The words of the emails signing causes (Phase 8 LLD §7, §8, §12), in the shared layout."""

from __future__ import annotations

from signora.modules.notifications import EmailAction, RenderedEmail, render_layout


def declined_to_sender(
    *, name: str, document: str, reason: str, url: str
) -> tuple[str, RenderedEmail]:
    heading = f"{name} declined {document}"
    return heading, render_layout(
        heading=heading,
        paragraphs=[f"Their reason: {reason}", "The request is closed for everyone on it."],
        action=EmailAction("Open the envelope", url),
        footer="You can send it again from the envelope, corrected.",
    )


def declined_to_others(*, document: str) -> tuple[str, RenderedEmail]:
    heading = f"{document} was declined"
    return heading, render_layout(
        heading=heading,
        paragraphs=["Nothing more is needed from you. The link you were sent no longer works."],
        footer="Questions? Reply to this email.",
    )
