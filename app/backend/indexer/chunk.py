"""Text splitting into overlapping windows. Pure functions; no I/O.

chunk.split    — sliding-window chunker
chunk.chunk_id — deterministic, stable chunk identifier
"""
from __future__ import annotations

import hashlib


def split(text: str, *, size: int = 1200, overlap: int = 150) -> list[str]:
    """Slice *text* into overlapping windows of at most *size* characters.

    Adjacent windows share *overlap* characters at the boundary so semantic
    context is not cut off at chunk edges.  Empty text returns [].  If
    overlap >= size the window cannot advance and only one chunk is produced.
    """
    if not text:
        return []
    step = max(size - overlap, 1)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + size])
        if start + size >= len(text):
            break
        start += step
    return chunks


def chunk_id(external_document_id: str, ordinal: int) -> str:
    """Return a stable, deterministic hex ID for chunk *ordinal* of *doc*.

    Uses SHA-1 of "<external_document_id>:<ordinal>" — 40 hex chars,
    collision-free in practice for the cardinalities we expect.
    """
    key = f"{external_document_id}:{ordinal}"
    return hashlib.sha1(key.encode()).hexdigest()
