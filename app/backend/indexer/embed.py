"""Databricks serving-endpoint embedding client.

Reuses the WorkspaceClient() pattern from docintel_routes._ws() —
a process-wide cached client that avoids re-negotiating auth on every call.

Injectable *client* seam lets tests swap in a fake without any live endpoints:

    result = embed_texts(["hello"], client=fake_client)

When *client* is None (the production path) a WorkspaceClient() is constructed
lazily and cached for the process lifetime.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Optional

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
    """Embed a list of texts via a Databricks model-serving endpoint.

    Args:
        texts:  Strings to embed. Empty list returns [] immediately.
        model:  Serving endpoint name (default: $EMBED_MODEL or
                ``databricks-gte-large-en``).
        client: Injectable WorkspaceClient for tests; None → real client.

    Returns:
        List of float vectors — one per input, each of length EMBED_DIM
        (default 1024 for gte-large-en).
    """
    if not texts:
        return []

    ws = client if client is not None else _default_client()

    records = [{"input": t} for t in texts]
    response = ws.serving_endpoints.query(name=model, dataframe_records=records)

    # The Databricks SDK returns predictions as a list of lists.
    predictions = response.predictions
    return [list(vec) for vec in predictions]
