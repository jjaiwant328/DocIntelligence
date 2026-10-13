"""Thin-spine API — Lakebase search + evidence over all ingested sources.

Search runs Lakebase hybrid retrieval (pgvector cosine + tsvector FTS fused via
RRF) over every ingested source, with an optional OpenJev judge rerank of the
top candidates. Evidence is assembled from Lakebase extracted_fields and
document_chunks, with a source_url for open-at-source. Does NOT touch existing
routes.

  POST /api/spine/search    {question, domain_id, k}   → ranked chunks + scores
  GET  /api/spine/evidence  ?doc_id&domain_id          → doc, extracted fields, source chunks
  GET  /api/spine/domains                              → configured spine domains
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from databricks.sdk import WorkspaceClient

from db import lakebase
from db.repositories import chunks_repo, extracted_fields_repo

router = APIRouter(prefix="/api/spine", tags=["spine"])

try:
    w = WorkspaceClient()
    print("✅ spine_routes: Databricks client ready")
except Exception as _e:  # pragma: no cover
    w = None
    print(f"⚠️ spine_routes: Databricks client failed: {_e}")

# domain_id → medallion schema produced by the spine pipeline
SCHEMA_BY_DOMAIN = {
    "supply_chain": "template",
    "compliance_due_diligence": "template_cdd",
}


def _schema(domain_id: str) -> str:
    schema = SCHEMA_BY_DOMAIN.get(domain_id)
    if not schema:
        raise HTTPException(status_code=404, detail=f"Unknown spine domain '{domain_id}'")
    return schema


class SearchRequest(BaseModel):
    question: str
    domain_id: str = "supply_chain"
    k: int = 5
    rerank: bool = True
    doc_set_id: str = ""


RERANK_CANDIDATES = int(os.getenv("DOCINTEL_RERANK_CANDIDATES", "10"))


def _rerank(question: str, rows: list[dict]) -> list[dict]:
    """Judge-rerank candidates with OpenJev; fail-open to vector order."""
    if not rows:
        return rows
    try:
        from judge import JudgeClient

        jc = JudgeClient.from_workspace(w)
        for r in rows:
            r["judge_score"] = round(jc.relevance(question, r.get("chunk_to_retrieve", "")), 4)
        return sorted(rows, key=lambda r: r["judge_score"], reverse=True)
    except Exception as _e:  # pragma: no cover
        print(f"⚠️ judge rerank skipped: {_e}")
        return rows


@router.get("/domains")
def list_spine_domains():
    return {"domains": [{"domain_id": d, "schema": s} for d, s in SCHEMA_BY_DOMAIN.items()]}


def _backend():
    from search.lakebase_search import LakebaseSearch
    return LakebaseSearch()


def _to_hit(row: dict) -> dict:
    return {
        "doc_id": row["external_document_id"],
        "doc_type": row.get("doc_type") or row.get("mime_type", ""),
        "source_file": row.get("path", ""),
        "chunk_to_retrieve": row.get("snippet", ""),
        "score": round(float(row.get("score", 0.0)), 4),
        "source": {"provider": "lakebase", "url": row.get("web_url", "")},
    }


def _doc_set_ids(conn, set_id: str) -> list[str]:
    """Resolve a doc-set to member document ids (pinned or query-defined)."""
    from db.repositories import doc_sets_repo

    s = doc_sets_repo.get(conn, set_id)
    if not s:
        raise HTTPException(status_code=404, detail=f"no doc-set '{set_id}'")
    if s["kind"] == "pinned":
        return doc_sets_repo.pinned_ids(conn, set_id)
    from doc_set_routes import _resolve_query_set

    fj = s["filter_json"]
    if isinstance(fj, str):
        import json

        fj = json.loads(fj)
    return [d["external_document_id"] for d in _resolve_query_set(conn, fj)]


@router.post("/search")
def search(req: SearchRequest):
    """Lakebase hybrid search over all ingested sources + OpenJev rerank.

    Optional doc_set_id narrows candidates to the set's members (pinned or
    query-resolved) before rerank."""
    _schema(req.domain_id)  # 404 unknown domain
    k = max(1, min(req.k, 25))
    cand = max(k, min(2 * k, RERANK_CANDIDATES)) if req.rerank else k
    doc_ids = None
    if req.doc_set_id:
        with lakebase.connection() as conn:
            doc_ids = _doc_set_ids(conn, req.doc_set_id)
        if not doc_ids:
            return {"domain_id": req.domain_id, "question": req.question, "results": []}
    rows = _backend().search(req.domain_id, None, req.question, k=cand, doc_ids=doc_ids)
    hits = [_to_hit(r) for r in rows]
    if req.rerank:
        hits = _rerank(req.question, hits)
    return {"domain_id": req.domain_id, "question": req.question, "results": hits[:k]}


def _lakebase_doc(doc_id: str, domain_id: str) -> dict | None:
    with lakebase.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT external_document_id, mime_type, path, web_url, name, doc_type "
            "FROM external_documents WHERE external_document_id=%s AND domain_id=%s",
            (doc_id, domain_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"external_document_id": row[0], "mime_type": row[1],
            "path": row[2], "web_url": row[3], "name": row[4], "doc_type": row[5]}


@router.get("/evidence")
def evidence(doc_id: str, domain_id: str = "supply_chain", validate: bool = False):
    """Evidence trail from Lakebase: doc, extracted fields, source chunks, source URL.

    With validate=true, also runs the OpenJev judge over the document: a
    per-field correctness probability and a doc-type verification choice."""
    _schema(domain_id)
    doc = _lakebase_doc(doc_id, domain_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"No document '{doc_id}' in {domain_id}")
    with lakebase.connection() as conn:
        fields = extracted_fields_repo.list_for_doc(conn, doc_id)
        chunks = chunks_repo.list_for_doc(conn, doc_id)
    out = {
        "document": {"doc_id": doc_id,
                     "doc_type": doc.get("doc_type") or doc.get("mime_type", ""),
                     "source_file": doc["path"], "source_url": doc["web_url"]},
        "extracted_fields": fields,
        "source_chunks": [{"chunk_position": c["ordinal"], "source_text": c["snippet"]}
                          for c in chunks],
    }
    if validate:
        out["validation"] = _validate(
            {"doc_type": out["document"]["doc_type"]}, fields, out["source_chunks"], domain_id)
    return out


def _validate(doc: dict, fields: list[dict], chunks: list[dict], domain_id: str) -> dict:
    """Judge-validate one document's extraction; fail-open with an error field."""
    try:
        from judge import JudgeClient

        with lakebase.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT doc_type FROM external_documents WHERE domain_id=%s",
                (domain_id,),
            )
            types = [r[0] for r in cur.fetchall() if r[0]]
        doc_text = "\n\n".join(c.get("source_text", "") for c in chunks[:6])
        return JudgeClient.from_workspace(w).validate_extraction(
            doc_text, doc.get("doc_type", ""), fields, types
        )
    except Exception as _e:  # pragma: no cover
        print(f"⚠️ judge validation skipped: {_e}")
        return {"error": str(_e)}
