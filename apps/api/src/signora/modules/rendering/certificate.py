"""The certificate of completion (Phase 8 LLD §11): a separate PDF of who signed, how they proved
who they were, when, from where, and the documents' fingerprints. Pure apart from the PDF library:
data in, bytes out.

Laid out by hand, as a formal record is: a header, the envelope's summary as a grid of labels and
values, one row per signer and countersigner (who they are, their signature as signed, their
events), copies, the envelope's events, the fingerprints, and the disclosure each accepted. A row
never splits across pages; every page carries the envelope's ID and its number. O(people + events).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

import pymupdf

from signora.modules.rendering.draw import PAD_HEIGHT, PAD_WIDTH
from signora.modules.typesetting.fonts import font_path
from signora.modules.typesetting.mupdf import MUPDF_LOCK

PAGE_W, PAGE_H = 612.0, 792.0  # US Letter
MARGIN = 54.0
WIDTH = PAGE_W - 2 * MARGIN
TOP = MARGIN + 6
BOTTOM = PAGE_H - MARGIN - 18  # above the footer

INK = (0.1, 0.1, 0.1)
QUIET = (0.42, 0.42, 0.42)
RULE = (0.78, 0.78, 0.78)
BAND = (0.95, 0.95, 0.94)

REGULAR, BOLD, MONO = "liberation-sans", "liberation-sans-bold", "liberation-mono"
FONT_NAMES = {REGULAR: "R", BOLD: "B", MONO: "M"}
Color = tuple[float, float, float]


@dataclass(frozen=True)
class Signature:
    method: str  # typed or drawn
    text: str | None
    font: str | None
    strokes: Sequence[Sequence[tuple[int, int]]] | None
    signature_id: str
    adopted: str  # "Typed, Allura" or "Drawn"


@dataclass(frozen=True)
class Signed:
    """One signer or countersigner, with their events."""

    role: str  # "Signer · Client"
    name: str
    email: str
    verified_by: str  # "Email code", "Email link", "Signora sign-in"
    signature: Signature | None
    initials: Signature | None
    ip: str | None
    sent: str | None
    viewed: str | None
    signed: str | None
    consented: str | None
    disclosure_version: str | None


@dataclass(frozen=True)
class Copy:
    name: str
    email: str
    sent: str | None


@dataclass(frozen=True)
class Certificate:
    envelope_id: uuid.UUID
    title: str
    template: str
    pages: int
    signatures: int
    initials: int
    sent_by: str  # "Rosa Hale (rosa@haleward.example)"
    time_zone: str  # how every time on it is given ("America/Los_Angeles")
    people: list[Signed]
    copies: list[Copy]
    summary: list[tuple[str, str]]  # (event, when)
    original_sha256: str
    completed_sha256: str
    disclosures: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # version: text


class _Layout:
    """Pages and a pen moving down them. Text is wrapped by the font's own widths."""

    def __init__(self, envelope_id: uuid.UUID) -> None:
        self.doc = pymupdf.open()
        self.faces = {key: pymupdf.Font(fontfile=str(font_path(key))) for key in FONT_NAMES}
        self.envelope_id = str(envelope_id).upper()
        self.y = 0.0
        self.page = self._add_page()

    def _add_page(self) -> pymupdf.Page:
        page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        for key, name in FONT_NAMES.items():
            page.insert_font(fontname=name, fontfile=str(font_path(key)))
        self.y = TOP
        return page

    def room(self, height: float) -> None:
        """Start a new page unless ``height`` fits on this one."""
        if self.y + height > BOTTOM:
            self.page = self._add_page()

    def lines(self, words: str, width: float, size: float, font: str = REGULAR) -> list[str]:
        face = self.faces[font]
        out: list[str] = []
        for paragraph in words.split("\n"):
            line = ""
            for word in paragraph.split(" "):
                trial = f"{line} {word}".strip()
                if face.text_length(trial, fontsize=size) <= width or not line:
                    line = trial
                else:
                    out.append(line)
                    line = word
            # A single word wider than the column (a fingerprint) breaks between characters.
            while len(line) > 1 and face.text_length(line, fontsize=size) > width:
                cut = len(line)
                while cut > 1 and face.text_length(line[:cut], fontsize=size) > width:
                    cut -= 1
                out.append(line[:cut])
                line = line[cut:]
            out.append(line)
        return out

    def text(
        self,
        x: float,
        y: float,
        words: str,
        width: float,
        size: float = 9,
        font: str = REGULAR,
        color: Color = INK,
    ) -> float:
        """Wrapped text from (x, y) at its top; returns the height it took."""
        step = size * 1.35
        lines = self.lines(words, width, size, font)
        for index, line in enumerate(lines):
            self.page.insert_text(
                (x, y + size + index * step),
                line,
                fontname=FONT_NAMES[font],
                fontsize=size,
                color=color,
            )
        return len(lines) * step

    def height(self, words: str, width: float, size: float = 9, font: str = REGULAR) -> float:
        return len(self.lines(words, width, size, font)) * size * 1.35

    def rule(self, y: float, color: Color = RULE, width: float = 0.5) -> None:
        self.page.draw_line((MARGIN, y), (MARGIN + WIDTH, y), color=color, width=width)

    def heading(self, words: str) -> None:
        self.room(56)
        self.y += 16
        self.text(MARGIN, self.y, words.upper(), WIDTH, 8, BOLD, QUIET)
        self.y += 14
        self.rule(self.y, INK, 0.8)
        self.y += 4

    def footers(self) -> None:
        total = self.doc.page_count
        words = f"Signora · Certificate of Completion · Envelope ID {self.envelope_id}"
        for number in range(total):
            page = self.doc[number]
            foot = PAGE_H - MARGIN
            page.draw_line((MARGIN, foot), (MARGIN + WIDTH, foot), color=RULE, width=0.5)
            page.insert_text((MARGIN, foot + 14), words, fontname="R", fontsize=7, color=QUIET)
            mark = f"Page {number + 1} of {total}"
            x = MARGIN + WIDTH - self.faces[REGULAR].text_length(mark, fontsize=7)
            page.insert_text((x, foot + 14), mark, fontname="R", fontsize=7, color=QUIET)


def _signature(
    layout: _Layout, mark: Signature, x: float, y: float, width: float, height: float
) -> None:
    """A signature as signed, drawn as vectors in its box (the signed PDF's own rule)."""
    page = layout.page
    if mark.method == "drawn" and mark.strokes:
        scale = min(width / PAD_WIDTH, height / PAD_HEIGHT)
        dx = x + (width - PAD_WIDTH * scale) / 2
        dy = y + (height - PAD_HEIGHT * scale) / 2
        for stroke in mark.strokes:
            points = [pymupdf.Point(dx + px * scale, dy + py * scale) for px, py in stroke]
            if len(points) == 1:
                points.append(points[0] + (0.3, 0))
            page.draw_polyline(points, color=INK, width=max(0.8, 6 * scale), lineCap=1, lineJoin=1)
    elif mark.text and mark.font:
        page.insert_font(fontname="S", fontfile=str(font_path(mark.font)))
        face = pymupdf.Font(fontfile=str(font_path(mark.font)))
        size = min(height * 0.7, width * 0.95 / max(face.text_length(mark.text, fontsize=1), 0.01))
        left = x + (width - face.text_length(mark.text, fontsize=size)) / 2
        page.insert_text(
            (left, y + height * 0.72), mark.text, fontname="S", fontsize=size, color=INK
        )


def _grid(layout: _Layout, pairs: list[tuple[str, str]]) -> None:
    """Labels and values in two columns of pairs (the envelope's summary)."""
    gap = 24.0
    column = (WIDTH - gap) / 2
    label_w = 74.0
    for start in range(0, len(pairs), 2):
        row = pairs[start : start + 2]
        tall = max(layout.height(value, column - label_w) for _, value in row)
        layout.room(tall + 6)
        for index, (label, value) in enumerate(row):
            x = MARGIN + index * (column + gap)
            layout.text(x, layout.y, label, label_w - 6, 8, color=QUIET)
            layout.text(x + label_w, layout.y, value, column - label_w)
        layout.y += tall + 6


# The signer events table's columns: who (and how verified), their signature, their events.
WHO_W, SIGN_W, GAP = 150.0, 136.0, 12.0
EVENTS_W = WIDTH - WHO_W - SIGN_W - 2 * GAP
EVENT_LABEL = 54.0
SIG_BOX = (SIGN_W - 6, 44.0)


def _person(layout: _Layout, person: Signed) -> None:
    who: list[tuple[str, str, float, Color]] = [
        (person.name, BOLD, 9.5, INK),
        (person.email, REGULAR, 8.5, INK),
        (person.role, REGULAR, 8, QUIET),
        (f"Verified by: {person.verified_by}", REGULAR, 8, QUIET),
    ]
    events = [
        ("Sent", person.sent),
        ("Viewed", person.viewed),
        ("Signed", person.signed),
        ("Disclosure", f"Accepted {person.consented}" if person.consented else None),
        ("IP address", person.ip),
    ]
    marks = [mark for mark in (person.signature, person.initials) if mark is not None]

    def caption(mark: Signature) -> str:
        return f"{mark.adopted} · ID {mark.signature_id.upper()}"

    who_h = sum(layout.height(words, WHO_W, size, font) for words, font, size, _ in who)
    sign_h = sum(SIG_BOX[1] + 4 + layout.height(caption(m), SIGN_W, 7) + 8 for m in marks) or 12
    event_w = EVENTS_W - EVENT_LABEL
    events_h = sum(max(layout.height(v or "—", event_w, 8), 11) + 3 for _, v in events)
    tall = max(who_h, sign_h, events_h) + 16
    layout.room(tall)
    top = layout.y + 8

    y = top
    for words, font, size, color in who:
        y += layout.text(MARGIN, y, words, WHO_W, size, font, color)

    x = MARGIN + WHO_W + GAP
    y = top
    for mark in marks:
        box = pymupdf.Rect(x, y, x + SIG_BOX[0], y + SIG_BOX[1])
        layout.page.draw_rect(box, color=None, fill=BAND)
        _signature(layout, mark, x + 4, y + 2, SIG_BOX[0] - 8, SIG_BOX[1] - 4)
        y += SIG_BOX[1] + 4
        y += layout.text(x, y, caption(mark), SIGN_W, 7, color=QUIET) + 8
    if not marks:
        layout.text(x, y, "No signature: reviewed and approved", SIGN_W, 8, color=QUIET)

    x = MARGIN + WHO_W + SIGN_W + 2 * GAP
    y = top
    for label, value in events:
        layout.text(x, y, label, EVENT_LABEL - 4, 8, color=QUIET)
        y += max(layout.text(x + EVENT_LABEL, y, value or "—", event_w, 8), 11) + 3

    layout.y = top + tall - 8
    layout.rule(layout.y)


def _table_header(layout: _Layout, columns: list[tuple[str, float]]) -> None:
    layout.room(48)
    layout.y += 6
    x = MARGIN
    for words, width in columns:
        layout.text(x, layout.y, words.upper(), width - 6, 7, BOLD, QUIET)
        x += width
    layout.y += 14
    layout.rule(layout.y)


def _two_columns(layout: _Layout, rows: list[tuple[str, str]], right: float = 200.0) -> None:
    for left_words, right_words in rows:
        tall = max(layout.height(left_words, WIDTH - right - 10), layout.height(right_words, right))
        layout.room(tall + 12)
        layout.text(MARGIN, layout.y + 6, left_words, WIDTH - right - 10)
        layout.text(MARGIN + WIDTH - right, layout.y + 6, right_words, right)
        layout.y += tall + 12
        layout.rule(layout.y)


def certificate_pdf(data: Certificate) -> bytes:
    """The certificate as a PDF, as many letter pages as it takes."""
    with MUPDF_LOCK:
        layout = _Layout(data.envelope_id)
        try:
            # The mark: the name over a short heavy rule.
            layout.text(MARGIN, layout.y, "SIGNORA", 160, 10, BOLD)
            layout.page.draw_line(
                (MARGIN, layout.y + 15), (MARGIN + 22, layout.y + 15), color=INK, width=2
            )
            layout.y += 22
            layout.y += layout.text(MARGIN, layout.y, "Certificate of Completion", WIDTH, 22)
            layout.y += 4
            envelope = f"Envelope ID {str(data.envelope_id).upper()}"
            layout.y += layout.text(MARGIN, layout.y, envelope, WIDTH, 8.5, MONO, QUIET)
            layout.y += 8
            layout.rule(layout.y, INK, 1.0)
            layout.y += 12

            _grid(
                layout,
                [
                    ("Subject", data.title),
                    ("Status", "Completed"),
                    ("Template", data.template),
                    ("Sent by", data.sent_by),
                    ("Pages", str(data.pages)),
                    ("Time zone", data.time_zone),
                    ("Signatures", str(data.signatures)),
                    ("Initials", str(data.initials)),
                ],
            )

            layout.heading("Signer events")
            _table_header(
                layout,
                [("Signer", WHO_W + GAP), ("Signature", SIGN_W + GAP), ("Events", EVENTS_W)],
            )
            for person in data.people:
                _person(layout, person)

            if data.copies:
                layout.heading("Copy events")
                _table_header(layout, [("Receives a copy", WIDTH - 200), ("Sent", 200)])
                _two_columns(
                    layout,
                    [
                        (f"{c.name} ({c.email})", c.sent or "With the completed copy")
                        for c in data.copies
                    ],
                )

            layout.heading("Envelope events")
            _table_header(layout, [("Event", WIDTH - 200), ("Time", 200)])
            _two_columns(layout, list(data.summary))

            layout.room(130)  # the heading, its note and both fingerprints stay together
            layout.heading("Integrity")
            layout.y += 6
            note = "SHA-256 fingerprints: hash the file you hold and compare."
            layout.y += layout.text(MARGIN, layout.y, note, WIDTH, 8, color=QUIET) + 4
            fingerprints = (
                ("Original document", data.original_sha256),
                ("Completed document", data.completed_sha256),
            )
            for label, digest in fingerprints:
                tall = layout.height(digest, WIDTH - 120, 8, MONO)
                layout.room(tall + 6)
                layout.text(MARGIN, layout.y, label, 116, 8, color=QUIET)
                layout.y += layout.text(MARGIN + 120, layout.y, digest, WIDTH - 120, 8, MONO) + 6

            for version, paragraphs in data.disclosures.items():
                layout.heading("Electronic records and signatures disclosure")
                layout.y += 6
                layout.y += (
                    layout.text(
                        MARGIN,
                        layout.y,
                        f"Version {version}, as each person accepted it",
                        WIDTH,
                        8,
                        MONO,
                        QUIET,
                    )
                    + 6
                )
                for title, words in paragraphs:
                    tall = 12 + layout.height(words, WIDTH, 8.5)
                    layout.room(tall + 6)
                    layout.text(MARGIN, layout.y, title, WIDTH, 8.5, BOLD)
                    layout.y += 12
                    layout.y += layout.text(MARGIN, layout.y, words, WIDTH, 8.5) + 6

            layout.footers()
            layout.doc.subset_fonts()
            out: bytes = layout.doc.tobytes(garbage=3, deflate=True)
            return out
        finally:
            layout.doc.close()
