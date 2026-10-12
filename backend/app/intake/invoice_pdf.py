"""A supplier invoice PDF -> its text, with pypdf (decision 034: permissive licence).

Only PDFs with real text are supported: an invoice that is just a scanned picture has no
text to read, and is refused with a clear message instead of being guessed at.
"""

import re
from io import BytesIO

from pypdf import PageObject, PdfReader
from pypdf.errors import PdfReadError

from app.intake.errors import IntakeError

MAX_PAGES = 20  # an invoice, not a catalogue


def pdf_text(content: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise IntakeError("encrypted_pdf", "The PDF is password-protected.")
        pages = reader.pages
        if len(pages) > MAX_PAGES:
            raise IntakeError(
                "too_many_pages", f"Invoices of more than {MAX_PAGES} pages aren't supported."
            )
        # Layout mode keeps each table row on one line, as printed ("1  FR PVC Wire ...  20
        # 1,620.00  32,400.00"). The default puts every cell on its own line, and a model
        # rebuilding the table from that once read "90m" (from the name) as the quantity.
        text = "\n".join(_page_text(page) for page in pages)
    except (PdfReadError, ValueError, OSError, KeyError) as exc:
        raise IntakeError("unreadable_file", "The file could not be read as a PDF.") from exc
    text = _compact(text)
    if len(text.strip()) < 20:
        raise IntakeError(
            "no_text",
            "The PDF has no readable text (probably a scanned picture). Ask the supplier for "
            "the digital invoice.",
        )
    return text


def _page_text(page: PageObject) -> str:
    """Layout mode first; a page with no content stream (a blank or scanned page) makes it
    raise, so fall back to plain extraction, and to nothing."""
    for mode in ("layout", "plain"):
        try:
            return page.extract_text(extraction_mode=mode) or ""
        except (KeyError, ValueError):
            continue
    return ""


def _compact(text: str) -> str:
    """Fewer characters for the model to read, same layout: long runs of spaces become three,
    and blank lines are dropped."""
    lines = (re.sub(r" {3,}", "   ", line.rstrip()) for line in text.splitlines())
    return "\n".join(line for line in lines if line.strip())
