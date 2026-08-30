"""Incremental change detection for indexed documents. Pure logic; no I/O.

classify   — compare a DB row (existing) to a freshly-crawled metadata dict
             (seen) and return the action required: new|changed|unchanged|deleted|inaccessible

plan_scope — given the current seen_docs list from a crawl, determine which
             docs need re-indexing and which should be deleted.
"""
from __future__ import annotations

from typing import Any, Optional


def classify(existing: Optional[dict], seen: Optional[dict]) -> str:
    """Classify the state of a document given its DB snapshot and crawl snapshot.

    Args:
        existing: The row from the DB (None if the document has never been indexed).
        seen:     The metadata returned by the crawler (None if unreachable).

    Returns:
        One of: "new" | "changed" | "unchanged" | "deleted" | "inaccessible"
    """
    if existing is None and seen is None:
        return "inaccessible"

    if existing is None:
        # Not in DB → needs to be indexed for the first time
        return "new"

    if seen is None:
        # In DB but cannot be retrieved from the source
        return "deleted"

    # Both present — compare fingerprints.
    # Etag is the primary signal (provider-supplied); content_hash is secondary.
    etag_existing = existing.get("etag") or ""
    etag_seen     = seen.get("etag") or ""

    if etag_existing and etag_existing == etag_seen:
        return "unchanged"

    # If both have no etag, fall back to content_hash
    if not etag_existing and not etag_seen:
        hash_existing = existing.get("content_hash") or ""
        hash_seen     = seen.get("content_hash") or ""
        if hash_existing and hash_existing == hash_seen:
            return "unchanged"

    return "changed"


def plan_scope(
    conn: Any,
    domain_id: str,
    project_id: str,
    seen_docs: list[dict],
    repo: Any,
) -> dict:
    """Determine which documents need indexing, deletion, or can be skipped.

    Args:
        conn:        Open Lakebase connection (forwarded to repo calls).
        domain_id:   Domain scope.
        project_id:  Project scope.
        seen_docs:   Documents returned by the latest crawl; each dict must
                     have at minimum "external_document_id", "etag",
                     "content_hash".
        repo:        external_docs_repo (or compatible fake). Must implement
                     ``list_for_project`` and ``ids_missing_from``.

    Returns:
        {
          "to_index": [doc_id, ...],   # docs that need (re-)embedding
          "to_delete": [doc_id, ...],  # docs in DB but no longer in source
          "skipped": int,              # unchanged docs that were left alone
        }
    """
    # Index existing DB docs by ID for O(1) lookup
    existing_by_id: dict[str, dict] = {
        d["external_document_id"]: d
        for d in repo.list_for_project(conn, domain_id, project_id)
    }

    seen_ids: set[str] = {d["external_document_id"] for d in seen_docs}

    to_index: list[str] = []
    skipped: int = 0

    for seen in seen_docs:
        doc_id   = seen["external_document_id"]
        existing = existing_by_id.get(doc_id)
        action   = classify(existing, seen)

        if action in ("new", "changed"):
            to_index.append(doc_id)
        elif action == "unchanged":
            skipped += 1
        # "deleted" / "inaccessible" for items in seen_docs is rare and
        # handled by the caller; ids_missing_from covers true deletions.

    to_delete: list[str] = repo.ids_missing_from(conn, domain_id, project_id, seen_ids)

    return {"to_index": to_index, "to_delete": to_delete, "skipped": skipped}
