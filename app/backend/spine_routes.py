"""Thin-spine API — endpoint-free search + evidence over the docintel_spine pipeline.

Additive: reads the new `template` / `template_cdd` medallion tables produced by
the `docintel_spine` Lakeflow pipeline. Does NOT touch existing routes. Retrieval
uses batch-embedded `gold_chunks` + `vector_cosine_similarity` — no Vector Search
endpoint, no serving endpoint.

  POST /api/spine/search    {question, domain_id, k}   → ranked chunks + scores
  GET  /api/spine/evidence  ?doc_id&domain_id          → doc, extracted fields, source chunks
  GET  /api/spine/domains                              → configured spine domains
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

router = APIRouter(prefix="/api/spine", tags=["spine"])

try:
    w = WorkspaceClient()
    warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID", "")
    print("✅ spine_routes: Databricks client ready")
except Exception as _e:  # pragma: no cover
    w = None
    warehouse_id = None
    print(f"⚠️ spine_routes: Databricks client failed: {_e}")

CATALOG = "jai_docintel"

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


def _esc(s: str) -> str:
    return (s or "").replace("'", "''")


def run_sql(sql: str, wait: str = "50s"):
    if not w or not warehouse_id:
        raise HTTPException(status_code=503, detail="Databricks not configured")
    result = w.statement_execution.execute_statement(statement=sql, warehouse_id=warehouse_id, wait_timeout=wait)
    state = result.status.state if result.status else None
    if state == StatementState.FAILED:
        raise HTTPException(status_code=500, detail=str(result.status.error))
    if state in (StatementState.PENDING, StatementState.RUNNING):
        import time

        time.sleep(3)
        result = w.statement_execution.get_statement(result.statement_id)
    rows = []
    if result.result and result.result.data_array:
        cols = [c.name for c in result.manifest.schema.columns]
        rows = [dict(zip(cols, row)) for row in result.result.data_array]
    return rows


class SearchRequest(BaseModel):
    question: str
    domain_id: str = "supply_chain"
    k: int = 5
    rerank: bool = True


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
        "doc_type": row.get("mime_type", ""),
        "source_file": row.get("path", ""),
        "chunk_to_retrieve": row.get("snippet", ""),
        "score": round(float(row.get("score", 0.0)), 4),
        "source": {"provider": "lakebase", "url": row.get("web_url", "")},
    }


@router.post("/search")
def search(req: SearchRequest):
    """Lakebase hybrid search over all ingested sources + OpenJev rerank."""
    _schema(req.domain_id)  # 404 unknown domain
    k = max(1, min(req.k, 25))
    cand = max(k, min(2 * k, RERANK_CANDIDATES)) if req.rerank else k
    rows = _backend().search(req.domain_id, None, req.question, k=cand)
    hits = [_to_hit(r) for r in rows]
    if req.rerank:
        hits = _rerank(req.question, hits)
    return {"domain_id": req.domain_id, "question": req.question, "results": hits[:k]}


@router.get("/evidence")
def evidence(doc_id: str, domain_id: str = "supply_chain", validate: bool = False):
    """Evidence trail for a document: type + source file, extracted fields, and source chunks.

    With validate=true, also runs the OpenJev judge over the document: a
    per-field correctness probability and a doc-type verification choice."""
    schema = _schema(domain_id)
    did = _esc(doc_id)
    doc = run_sql(
        f"SELECT doc_id, doc_type, source_file FROM {CATALOG}.{schema}.gold_documents WHERE doc_id = '{did}' LIMIT 1"
    )
    if not doc:
        raise HTTPException(status_code=404, detail=f"No document '{doc_id}' in {schema}")
    fields = run_sql(
        f"SELECT field_name, field_value FROM {CATALOG}.{schema}.gold_extracted_fields WHERE doc_id = '{did}' ORDER BY field_name"
    )
    chunks = run_sql(
        f"SELECT chunk_position, chunk_to_retrieve AS source_text FROM {CATALOG}.{schema}.gold_chunks WHERE doc_id = '{did}' ORDER BY chunk_position"
    )
    out = {"document": doc[0], "extracted_fields": fields, "source_chunks": chunks}
    if validate:
        out["validation"] = _validate(doc[0], fields, chunks, schema)
    return out


def _validate(doc: dict, fields: list[dict], chunks: list[dict], schema: str) -> dict:
    """Judge-validate one document's extraction; fail-open with an error field."""
    try:
        from judge import JudgeClient

        types = [r["doc_type"] for r in run_sql(
            f"SELECT DISTINCT doc_type FROM {CATALOG}.{schema}.gold_documents"
        ) if r.get("doc_type")]
        doc_text = "\n\n".join(c.get("source_text", "") for c in chunks[:6])
        return JudgeClient.from_workspace(w).validate_extraction(
            doc_text, doc.get("doc_type", ""), fields, types
        )
    except Exception as _e:  # pragma: no cover
        print(f"⚠️ judge validation skipped: {_e}")
        return {"error": str(_e)}
