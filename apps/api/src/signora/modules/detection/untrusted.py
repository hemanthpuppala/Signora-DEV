"""Text from the document or its uploader, made safe to put in the AI's message (LLD §3.5).

Our markers (⟦f8⟧) and our tags (<document>, </fields>, …) must be the only ones the AI sees, so
they cannot be faked by the text they enclose: marker brackets are removed and our tag names are
neutralised in every untrusted string (document text, field names, tooltips, values, option words,
the uploader's instructions).
"""

from __future__ import annotations

import re

MARKER_BRACKETS = str.maketrans("", "", "⟦⟧")
OUR_TAGS = re.compile(
    r"<\s*/?\s*(document|fields|uploader_instructions|current_name|write_name_and_description)\b[^>]*>",
    re.IGNORECASE,
)


def clean(text: str) -> str:
    """The same text without our marker brackets, its look-alikes of our tags made harmless."""
    without_markers = text.translate(MARKER_BRACKETS)
    # Single angle quotation marks (U+2039, U+203A): the tag still reads, but is no longer a tag.
    return OUR_TAGS.sub(
        lambda m: m.group(0).replace("<", "\u2039").replace(">", "\u203a"), without_markers
    )
