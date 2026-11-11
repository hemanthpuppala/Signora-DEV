"""The certificate of completion (Phase 8 LLD §11): a separate PDF of who signed, how they proved
who they were, when, from where, and the documents' fingerprints. Pure apart from the PDF library:
data in, bytes out. O(people + their events), laid out over as many pages as it takes.
"""

from __future__ import annotations

import html
import io
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

import pymupdf

from signora.modules.rendering.draw import PAD_HEIGHT, PAD_WIDTH
from signora.modules.typesetting.fonts import font_path
from signora.modules.typesetting.mupdf import MUPDF_LOCK

PAGE = pymupdf.paper_rect("letter")
MARGIN = 54  # points: three quarters of an inch
AREA = pymupdf.Rect(PAGE.x0 + MARGIN, PAGE.y0 + MARGIN, PAGE.x1 - MARGIN, PAGE.y1 - MARGIN)
SIGNATURE_BOX = (240, 72)  # points: how big a signature is shown


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

    role: str  # "Signer" or "Countersigner", and the party ("Signer · Client")
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


CSS = """
@font-face { font-family: body; src: url(body.ttf); }
* { font-family: body; }
body { font-size: 9pt; color: #1a1a1a; }
h1 { font-size: 18pt; font-weight: normal; margin: 0 0 4pt 0; }
h2 { font-size: 11pt; font-weight: bold; margin: 14pt 0 4pt 0; border-bottom: 0.5pt solid #999; }
h3 { font-size: 10pt; margin: 10pt 0 2pt 0; }
p { margin: 2pt 0; }
table { width: 100%; border-collapse: collapse; }
td { padding: 2pt 4pt 2pt 0; vertical-align: top; }
td.k { width: 30%; color: #555; }
.quiet { color: #555; }
.mono { font-family: body; font-size: 8pt; }
"""


def _png(signature: Signature) -> bytes:
    """A signature as a small picture, drawn as the signed PDF draws it."""
    width, height = SIGNATURE_BOX
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=width, height=height)
        if signature.method == "drawn" and signature.strokes:
            scale = min(width / PAD_WIDTH, height / PAD_HEIGHT)
            dx = (width - PAD_WIDTH * scale) / 2
            dy = (height - PAD_HEIGHT * scale) / 2
            for stroke in signature.strokes:
                points = [pymupdf.Point(dx + x * scale, dy + y * scale) for x, y in stroke]
                if len(points) == 1:
                    points.append(points[0] + (0.3, 0))
                page.draw_polyline(
                    points, color=(0.1, 0.1, 0.1), width=max(1.0, 6 * scale), lineCap=1, lineJoin=1
                )
        elif signature.text and signature.font:
            page.insert_font(fontname="S", fontfile=str(font_path(signature.font)))
            size = height * 0.6
            face = pymupdf.Font(fontfile=str(font_path(signature.font)))
            size = min(size, width * 0.95 / max(face.text_length(signature.text, fontsize=1), 0.01))
            x = (width - face.text_length(signature.text, fontsize=size)) / 2
            page.insert_text(
                (x, height * 0.72),
                signature.text,
                fontname="S",
                fontsize=size,
                color=(0.1, 0.1, 0.1),
            )
        png: bytes = page.get_pixmap(dpi=150, alpha=True).tobytes("png")
        return png
    finally:
        doc.close()


def _row(key: str, value: str | None) -> str:
    return f'<tr><td class="k">{html.escape(key)}</td><td>{html.escape(value or "—")}</td></tr>'


def _html(data: Certificate, images: dict[str, str]) -> str:
    out = [
        "<h1>Certificate of completion</h1>",
        f'<p class="quiet">Signora envelope ID: {html.escape(str(data.envelope_id).upper())}</p>',
        "<table>",
        _row("Title", data.title),
        _row("Template", data.template),
        _row("Pages", str(data.pages)),
        _row("Signatures", str(data.signatures)),
        _row("Initials", str(data.initials)),
        _row("Sent by", data.sent_by),
        _row("Status", "Completed"),
        _row("Times are in", data.time_zone),
        "</table>",
        "<h2>Signer and countersigner events</h2>",
    ]
    for index, person in enumerate(data.people):
        out += [f"<h3>{html.escape(person.role)}: {html.escape(person.name)}</h3>", "<table>"]
        out.append(_row("Email", person.email))
        out.append(_row("Verified by", person.verified_by))
        for label, mark, key in (
            ("Signature", person.signature, f"s{index}"),
            ("Initials", person.initials, f"i{index}"),
        ):
            if mark is None:
                continue
            picture = f'<img src="{images[key]}" width="{SIGNATURE_BOX[0] * 0.6}"/>'
            words = f"{html.escape(mark.adopted)} · Signature ID {mark.signature_id.upper()}"
            out.append(f'<tr><td class="k">{label}</td><td>{picture}<br/>{words}</td></tr>')
        out += [
            _row("Signed from", person.ip),
            _row("Sent", person.sent),
            _row("Viewed", person.viewed),
            _row("Signed", person.signed),
            _row(
                "Electronic records",
                f"Accepted {person.consented} ({person.disclosure_version})"
                if person.consented
                else None,
            ),
            "</table>",
        ]
    if data.copies:
        out += ["<h2>Copies</h2>", "<table>"]
        out += [
            _row(f"{copy.name} ({copy.email})", f"Sent {copy.sent}" if copy.sent else "To be sent")
            for copy in data.copies
        ]
        out.append("</table>")
    out += [
        "<h2>Envelope summary</h2>",
        "<table>",
        *(_row(event, when) for event, when in data.summary),
        "</table>",
    ]
    out += [
        "<h2>Integrity</h2>",
        "<p>SHA-256 fingerprints. Hash the file you hold and compare.</p>",
        "<table>",
        _row("Original document", data.original_sha256),
        _row("Completed document", data.completed_sha256),
        "</table>",
    ]
    for version, paragraphs in data.disclosures.items():
        out.append(
            f"<h2>Electronic records and signatures disclosure ({html.escape(version)})</h2>"
        )
        out += [
            f"<p><b>{html.escape(title)}.</b> {html.escape(words)}</p>"
            for title, words in paragraphs
        ]
    return "".join(out)


def certificate(data: Certificate) -> bytes:
    """The certificate as a PDF, as many letter pages as it takes."""
    with MUPDF_LOCK:
        archive = pymupdf.Archive()
        archive.add(font_path("liberation-sans").read_bytes(), "body.ttf")
        images: dict[str, str] = {}
        for index, person in enumerate(data.people):
            for key, mark in ((f"s{index}", person.signature), (f"i{index}", person.initials)):
                if mark is not None:
                    images[key] = f"{key}.png"
                    archive.add(_png(mark), images[key])
        story = pymupdf.Story(html=_html(data, images), archive=archive, user_css=CSS)
        buffer = io.BytesIO()
        writer = pymupdf.DocumentWriter(buffer)
        more = 1
        while more:
            device = writer.begin_page(PAGE)
            more, _ = story.place(AREA)
            story.draw(device)
            writer.end_page()
        writer.close()
        return buffer.getvalue()
