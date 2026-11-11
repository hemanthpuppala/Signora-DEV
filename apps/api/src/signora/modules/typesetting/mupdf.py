"""One caller in MuPDF at a time. The library is not made for threads, and the API answers
requests on several: a font's widths (a send's fit check) and a PDF's text sizes (an approval) are
read under this lock, so two requests are never inside it together. The calls are short: O(len)
for a width, one pass over a PDF's words for its sizes.

Reentrant: drawing a signed PDF (rendering, Phase 8) holds it for the whole document and measures
each value's width inside, on the same thread; another thread still waits for the whole render."""

from __future__ import annotations

import threading

MUPDF_LOCK = threading.RLock()
