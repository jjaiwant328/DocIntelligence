"""External-documents CRUD against Lakebase. Tracks every file discovered by a
connector with its metadata, indexing state, and chunk count."""
from __future__ import annotations

import hashlib
from typing import Any, Optional


def stable_doc_id(provider: str, site: str, drive: str, item_id: str) -> str:
    """Deterministic, order-sensitive SHA-1 of the four-tuple.

    Produces a 40-char hex string that is stable across crawl runs so we can
    detect re-crawled files vs. new ones without scanning the full DB.
    """
    return hashlib.sha1("|".join((provider, site, drive, item_id)).encode()).hexdigest()


def _dicts(cur: Any) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def upsert_metadata(conn: Any, doc: dict) -> None:
    """Insert-or-update a document row. Sets status='discovered' on first
    insert; preserves existing status on conflict (caller can override by
    passing status explicitly in *doc*). The *included* flag is only set on
    first insert (defaults True) — a metadata re-crawl never clobbers a user's
    inclusion choice."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO external_documents (
            external_document_id, source_id, source_item_id, domain_id, project_id,
            parent_folder_id, path, name, mime_type, size_bytes,
            web_url, etag, content_hash, owner,
            source_created_at, source_modified_at, status, included,
            index_version, embedding_model, last_indexed_etag,
            chunk_count, last_error, updated_at
        )
        VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            COALESCE(%s,'discovered'),%s,%s,%s,%s,%s,%s, now()
        )
        ON CONFLICT (external_document_id) DO UPDATE SET
            source_id=EXCLUDED.source_id,
            source_item_id=EXCLUDED.source_item_id,
            parent_folder_id=EXCLUDED.parent_folder_id,
            path=EXCLUDED.path, name=EXCLUDED.name,
            mime_type=EXCLUDED.mime_type, size_bytes=EXCLUDED.size_bytes,
            web_url=EXCLUDED.web_url, etag=EXCLUDED.etag,
            content_hash=EXCLUDED.content_hash, owner=EXCLUDED.owner,
            source_created_at=EXCLUDED.source_created_at,
            source_modified_at=EXCLUDED.source_modified_at,
            last_error=EXCLUDED.last_error,
            updated_at=now()
        """,
        (
            doc.get("external_document_id"), doc.get("source_id"),
            doc.get("source_item_id", ""),
            doc.get("domain_id"), doc.get("project_id", ""),
            doc.get("parent_folder_id", ""), doc.get("path", ""),
            doc.get("name", ""), doc.get("mime_type", ""),
            doc.get("size_bytes", 0), doc.get("web_url", ""),
            doc.get("etag", ""), doc.get("content_hash", ""),
            doc.get("owner", ""),
            doc.get("source_created_at"), doc.get("source_modified_at"),
            doc.get("status"), doc.get("included", True),
            doc.get("index_version", 0), doc.get("embedding_model", ""),
            doc.get("last_indexed_etag", ""), doc.get("chunk_count", 0),
            doc.get("last_error", ""),
        ),
    )


def list_for_project(
    conn: Any,
    domain_id: str,
    project_id: str,
    statuses: Optional[list[str]] = None,
) -> list[dict]:
    cur = conn.cursor()
    if statuses:
        placeholders = ",".join(["%s"] * len(statuses))
        cur.execute(
            f"SELECT * FROM external_documents "
            f"WHERE domain_id=%s AND project_id=%s AND status IN ({placeholders}) "
            f"ORDER BY updated_at DESC",
            (domain_id, project_id, *statuses),
        )
    else:
        cur.execute(
            "SELECT * FROM external_documents "
            "WHERE domain_id=%s AND project_id=%s ORDER BY updated_at DESC",
            (domain_id, project_id),
        )
    return _dicts(cur)


def set_status(
    conn: Any,
    external_document_id: str,
    status: str,
    last_error: str = "",
) -> None:
    conn.execute(
        "UPDATE external_documents SET status=%s, last_error=%s, updated_at=now() "
        "WHERE external_document_id=%s",
        (status, last_error, external_document_id),
    )


def set_included(
    conn: Any,
    external_document_id: str,
    included: bool,
) -> None:
    """Persist the inclusion flag for a document (controls whether it is
    picked up by the indexer on the next Build/Refresh run)."""
    conn.execute(
        "UPDATE external_documents SET included=%s, updated_at=now() "
        "WHERE external_document_id=%s",
        (included, external_document_id),
    )


def mark_indexed(
    conn: Any,
    external_document_id: str,
    index_version: int,
    embedding_model: str,
    etag: str,
    chunk_count: int,
) -> None:
    conn.execute(
        """
        UPDATE external_documents SET
            status='indexed', index_version=%s, embedding_model=%s,
            last_indexed_etag=%s, chunk_count=%s, last_error='', updated_at=now()
        WHERE external_document_id=%s
        """,
        (index_version, embedding_model, etag, chunk_count, external_document_id),
    )


def ids_missing_from(
    conn: Any,
    domain_id: str,
    project_id: str,
    seen_ids: set[str],
) -> list[str]:
    """Return IDs of documents in the DB (for this domain/project) that are
    NOT in *seen_ids* — candidates for marking 'deleted' after a crawl."""
    cur = conn.cursor()
    cur.execute(
        "SELECT external_document_id FROM external_documents "
        "WHERE domain_id=%s AND project_id=%s AND status <> 'deleted'",
        (domain_id, project_id),
    )
    rows = _dicts(cur)
    return [r["external_document_id"] for r in rows
            if r["external_document_id"] not in seen_ids]
