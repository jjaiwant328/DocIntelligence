"""Document-chunks CRUD + RRF hybrid search against Lakebase.

replace_chunks atomically deletes old chunks for a document then bulk-inserts
the new set, setting tsv via to_tsvector so FTS is always up to date.
hybrid_search fuses vector (cosine) and FTS (ts_rank) rankings via
Reciprocal Rank Fusion (RRF) and returns the top-k results with metadata.
"""
from __future__ import annotations

from typing import Any, Optional


def _dicts(cur: Any) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _vec_literal(v: list[float]) -> str:
    """Format a float list as a pgvector literal string: '[x,y,...]'."""
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


# ── write helpers ─────────────────────────────────────────────────────────────

def delete_for_doc(conn: Any, external_document_id: str) -> int:
    """Delete all chunks for a document. Returns rowcount (best-effort)."""
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM document_chunks WHERE external_document_id=%s",
        (external_document_id,),
    )
    return getattr(cur, "rowcount", 0) or 0


def replace_chunks(conn: Any, external_document_id: str, chunks: list[dict]) -> int:
    """Atomically replace all chunks for a document.

    Deletes existing rows then inserts the new set. Sets tsv via
    to_tsvector('english', snippet) so FTS is always current.

    Returns the number of inserted rows.
    """
    # Delete phase
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM document_chunks WHERE external_document_id=%s",
        (external_document_id,),
    )
    # Insert phase
    n = 0
    for ch in chunks:
        vec_lit = _vec_literal(ch["embedding"]) if ch.get("embedding") else None
        cur.execute(
            """
            INSERT INTO document_chunks (
                chunk_id, external_document_id, domain_id, project_id,
                ordinal, location, snippet,
                embedding, tsv,
                source_version, index_version
            )
            VALUES (
                %s,%s,%s,%s,%s,%s,%s,
                %s::vector,
                to_tsvector('english', %s),
                %s,%s
            )
            """,
            (
                ch["chunk_id"], external_document_id,
                ch.get("domain_id", ""), ch.get("project_id", ""),
                ch.get("ordinal", 0), ch.get("location", ""), ch.get("snippet", ""),
                vec_lit,
                ch.get("snippet", ""),
                ch.get("source_version", ""), ch.get("index_version", 0),
            ),
        )
        n += 1
    return n


# ── hybrid search ─────────────────────────────────────────────────────────────

def hybrid_search(
    conn: Any,
    domain_id: str,
    project_id: str,
    query_embedding: list[float],
    query_text: str,
    k: int = 10,
    folder: str = "",
    types: Optional[list[str]] = None,
) -> list[dict]:
    """RRF-fused vector + FTS hybrid search.

    Returns [{chunk_id, external_document_id, name, path, web_url,
              mime_type, status, ordinal, location, snippet, score}].
    """
    cur = conn.cursor()
    sql = """
    WITH vec AS (
        SELECT chunk_id, external_document_id,
               ROW_NUMBER() OVER (ORDER BY embedding <=> %s::vector) AS rnk
        FROM document_chunks
        WHERE domain_id=%s AND project_id=%s AND embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector LIMIT 50
    ),
    kw AS (
        SELECT chunk_id, external_document_id,
               ROW_NUMBER() OVER (
                   ORDER BY ts_rank(tsv, plainto_tsquery('english', %s)) DESC
               ) AS rnk
        FROM document_chunks
        WHERE domain_id=%s AND project_id=%s
          AND tsv @@ plainto_tsquery('english', %s)
        LIMIT 50
    ),
    fused AS (
        SELECT chunk_id, external_document_id,
               SUM(1.0/(60+rnk)) AS score
        FROM (SELECT * FROM vec UNION ALL SELECT * FROM kw) u
        GROUP BY chunk_id, external_document_id
    )
    SELECT c.chunk_id, c.external_document_id, d.name, d.path, d.web_url,
           d.mime_type, d.status, c.ordinal, c.location, c.snippet, f.score
    FROM fused f
    JOIN document_chunks c ON c.chunk_id=f.chunk_id
    JOIN external_documents d ON d.external_document_id=f.external_document_id
    ORDER BY f.score DESC LIMIT %s
    """
    ql = _vec_literal(query_embedding)
    cur.execute(
        sql,
        (ql, domain_id, project_id, ql,
         query_text, domain_id, project_id, query_text, k),
    )
    return _dicts(cur)
