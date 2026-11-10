"""One caller in MuPDF at a time. The library is not made for threads, and the API answers
requests on several: a font's widths (a send's fit check) and a PDF's text sizes (an approval) are
read under this lock, so two requests are never inside it together. The calls are short: O(len)
for a width, one pass over a PDF's words for its sizes."""

from __future__ import annotations

import threading

MUPDF_LOCK = threading.Lock()
