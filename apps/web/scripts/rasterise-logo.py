"""The emails' logo as a PNG: public/email/signora-logo.svg (scripts/email-logo.mjs), trimmed to
the drawing and drawn 280 px wide, twice the 140 px the emails show it at. Run by `make email-logo`
with the API's Python, which has the PDF library that draws SVG."""

from pathlib import Path

import pymupdf
from PIL import Image

EMAIL = Path(__file__).resolve().parents[1] / "public" / "email"
WIDTH = 280
PAD = 6

page = pymupdf.open(stream=(EMAIL / "signora-logo.svg").read_bytes(), filetype="svg")[0]
pix = page.get_pixmap(matrix=pymupdf.Matrix(3, 3), alpha=True)
image = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
x0, y0, x1, y1 = image.getchannel("A").getbbox() or (0, 0, image.width, image.height)
image = image.crop((max(0, x0 - PAD), max(0, y0 - PAD), min(image.width, x1 + PAD), min(image.height, y1 + PAD)))
image = image.resize((WIDTH, round(image.height * WIDTH / image.width)), Image.LANCZOS)
image.save(EMAIL / "signora-logo.png", optimize=True)
print(EMAIL / "signora-logo.png", image.size)
