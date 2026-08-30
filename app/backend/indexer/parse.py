"""Text extraction from document bytes. Pure functions; no network.

Supported formats:
  .txt / .md   — UTF-8 decode
  .csv         — UTF-8 decode (preserves raw CSV text)
  .pdf         — pypdf if available; falls back to AI-parse seam (returns "")
  .docx        — python-docx if available; falls back silently (returns "")
  unknown      — returns "" (caller should set doc status to 'failed')
"""
from __future__ import annotations

import os


def extract_text(filename: str, content: bytes) -> str:
    """Return the plain text from *content* bytes of a document named *filename*.

    Routing is by file extension only — MIME types are not used so this stays
    a pure function with no I/O. Never raises; callers must treat "" as a
    signal to mark the document failed.
    """
    ext = os.path.splitext(filename)[1].lower()

    if ext in (".txt", ".md"):
        return content.decode("utf-8", errors="replace")

    if ext == ".csv":
        return content.decode("utf-8", errors="replace")

    if ext == ".pdf":
        try:
            import io
            from pypdf import PdfReader  # type: ignore
            reader = PdfReader(io.BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            return _ai_parse_seam(filename, content)
        except Exception:
            return ""

    if ext == ".docx":
        try:
            import io
            from docx import Document  # type: ignore
            doc = Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            return ""
        except Exception:
            return ""

    return ""


def _ai_parse_seam(filename: str, content: bytes) -> str:  # pragma: no cover
    """Seam for AI-based parsing (e.g. Databricks ai_parse_document).

    Not implemented here — returns "" so the caller can decide to fall
    back to the warehouse-based pipeline or mark the doc failed.
    """
    return ""
