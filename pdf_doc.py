"""PDF helpers for Hermes Agent — detect, download, and extract text from Telegram PDFs."""

import io
from pathlib import Path

from pypdf import PdfReader

# Chars of extracted text kept for Q&A injection, so normal conversation
# history is not flooded with a full document.
MAX_QA_CTX = 50_000


def is_pdf(doc: dict) -> bool:
    """Return True when a Telegram document is a PDF.

    Telegram sometimes reports application/octet-stream for PDFs, so fall
    back to the filename suffix.
    """
    mime = (doc.get("mime_type") or "").lower()
    name = (doc.get("file_name") or "").lower()
    return mime == "application/pdf" or name.endswith(".pdf")


def extract_text_from_pdf_bytes(data: bytes) -> str:
    """Extract all text from a PDF.

    Returns "" when the PDF has no extractable text (e.g. scanned images).
    Raises ValueError on malformed/corrupt input so callers can surface one
    friendly error type.
    """
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as e:
        raise ValueError(f"Could not parse PDF: {e}") from e
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            # A single bad page should not abort the whole document.
            continue
    return "\n\n".join(pages).strip()


def truncate(text: str, limit: int = MAX_QA_CTX) -> str:
    """Trim text to `limit` chars, cutting on a word boundary."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    idx = cut.rfind(" ")
    if idx > limit // 2:
        cut = cut[:idx]
    return cut + "\n…[truncated]"
