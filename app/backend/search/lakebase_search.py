"""LakebaseSearch — SearchBackend implementation backed by pgvector + FTS.

Embeds the query via embed.embed_texts then delegates to
chunks_repo.hybrid_search for RRF-fused results.

All dependencies are injectable for offline testing.
"""
from __future__ import annotations

from typing import Any, Callable, Optional


class LakebaseSearch:
    """SearchBackend that uses Lakebase pgvector + FTS hybrid search.

    Args:
        embed_fn:    Callable (list[str]) -> list[list[float]].
                     Defaults to indexer.embed.embed_texts.
        chunks_repo: Module or object with a hybrid_search method.
                     Defaults to db.repositories.chunks_repo.
        lakebase:    Module with a connection() context manager.
                     Defaults to db.lakebase.
    """

    def __init__(
        self,
        embed_fn: Optional[Callable] = None,
        chunks_repo: Optional[Any] = None,
        lakebase: Optional[Any] = None,
    ):
        if embed_fn is None:
            from indexer import embed as _embed
            self._embed_fn: Callable = _embed.embed_texts
        else:
            self._embed_fn = embed_fn

        if chunks_repo is None:
            from db.repositories import chunks_repo as _cr
            self._chunks_repo = _cr
        else:
            self._chunks_repo = chunks_repo

        if lakebase is None:
            from db import lakebase as _lb
            self._lakebase = _lb
        else:
            self._lakebase = lakebase

    def search(
        self,
        domain_id: str,
        project_id: str,
        query: str,
        k: int = 10,
        folder: str = "",
        types: Optional[list[str]] = None,
    ) -> list[dict]:
        """Embed *query* once then run hybrid search, returning up to *k* results."""
        # Embed the query (single text → single vector)
        vectors = self._embed_fn([query])
        query_embedding = vectors[0]

        with self._lakebase.connection() as conn:
            return self._chunks_repo.hybrid_search(
                conn,
                domain_id,
                project_id,
                query_embedding,
                query,
                k=k,
                folder=folder,
                types=types,
            )
