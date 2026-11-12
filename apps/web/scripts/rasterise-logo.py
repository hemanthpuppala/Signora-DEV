"""The emails' logo as a PNG: public/email/signora-logo.svg (scripts/email-logo.mjs), trimmed to
the drawing and drawn 280 px wide, twice the 140 px the emails show it at. Run by `make email-logo`
with the API's Python, which has the PDF library that draws SVG.

The white logo sits on its own black tile, part of the image: some email apps repaint an email's
background (Gmail's turns a dark email light) but never an image, so a logo on a transparent
background can vanish. On the emails' own black the tile is unseen."""

from pathlib import Path

import pymupdf
from PIL import Image

EMAIL = Path(__file__).resolve().parents[1] / "public" / "email"
WIDTH = 280
PAD = 6
TILE_PAD = 14  # px of the tile around the drawing, at the 2x size

page = pymupdf.open(stream=(EMAIL / "signora-logo.svg").read_bytes(), filetype="svg")[0]
pix = page.get_pixmap(matrix=pymupdf.Matrix(3, 3), alpha=True)
image = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
x0, y0, x1, y1 = image.getchannel("A").getbbox() or (0, 0, image.width, image.height)
image = image.crop((max(0, x0 - PAD), max(0, y0 - PAD), min(image.width, x1 + PAD), min(image.height, y1 + PAD)))
inner = WIDTH - 2 * TILE_PAD
image = image.resize((inner, round(image.height * inner / image.width)), Image.LANCZOS)
tile = Image.new("RGBA", (WIDTH, image.height + 2 * TILE_PAD), (0, 0, 0, 255))
tile.alpha_composite(image, (TILE_PAD, TILE_PAD))
image = tile.convert("RGB")
image.save(EMAIL / "signora-logo.png", optimize=True)
print(EMAIL / "signora-logo.png", image.size)
