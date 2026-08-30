"""Databricks serving-endpoint embedding client.

Reuses the WorkspaceClient() pattern from docintel_routes._ws() —
a process-wide cached client that avoids re-negotiating auth on every call.

Injectable *client* seam lets tests swap in a fake without any live endpoints:

    result = embed_texts(["hello"], client=fake_client)

When *client* is None (the production path) a WorkspaceClient() is constructed
lazily and cached for the process lifetime.

API shape (Foundation Models API embedding endpoints, e.g. databricks-gte-large-en):
    ws.serving_endpoints.query(name=model, input=texts)
    → response.data[i].embedding  (list[float])
"""
from __future__ import annotations

import os
import threading
from typing import Any, Optional

# ── Constants (overridable via env) ───────────────────────────────────────────

EMBED_DIM   = int(os.getenv("EMBED_DIM",   "1024"))
EMBED_BATCH = int(os.getenv("EMBED_BATCH", "32"))

# ── Process-wide WorkspaceClient cache ────────────────────────────────────────
# Mirrors the _ws()/_ws_client pattern from docintel_routes so auth is
# negotiated exactly once per process. This is the existing mechanism we reuse.

_ws_client: Optional[Any] = None
_ws_lock = threading.Lock()


def _default_client() -> Any:
    """Return (and cache) the process-wide WorkspaceClient."""
    global _ws_client
    if _ws_client is None:
        with _ws_lock:
            if _ws_client is None:
                from databricks.sdk import WorkspaceClient
                _ws_client = WorkspaceClient()
    return _ws_client


# ── Public API ─────────────────────────────────────────────────────────────────

def embed_texts(
    texts: list[str],
    *,
    model: str = os.getenv("EMBED_MODEL", "databricks-gte-large-en"),
    client: Optional[Any] = None,
) -> list[list[float]]:
    """Embed a list of texts via a Databricks Foundation Models API endpoint.

    Uses the FMAPI embedding call shape:
        ws.serving_endpoints.query(name=model, input=batch)
    and reads embeddings from response.data[i].embedding.

    Args:
        texts:  Strings to embed. Empty list returns [] immediately.
        model:  Serving endpoint name (default: $EMBED_MODEL or
                ``databricks-gte-large-en``).
        client: Injectable WorkspaceClient for tests; None → real client.

    Returns:
        List of float vectors — one per input, each of length EMBED_DIM.

    Raises:
        ValueError: If a returned vector has a dimension other than EMBED_DIM,
                    so a mis-configured model fails loudly rather than silently
                    inserting wrong-shaped data into pgvector.
    """
    if not texts:
        return []

    ws = client if client is not None else _default_client()

    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        response = ws.serving_endpoints.query(name=model, input=batch)

        for item in response.data:
            vec = list(item.embedding)
            if len(vec) != EMBED_DIM:
                raise ValueError(
                    f"embedding dimension mismatch: "
                    f"expected {EMBED_DIM}, got {len(vec)}"
                )
            all_embeddings.append(vec)

    return all_embeddings
