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
EMBED_MODEL = os.getenv("DOCINTEL_EMBED_MODEL", "databricks-gte-large-en")

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


@router.get("/domains")
def list_spine_domains():
    return {"domains": [{"domain_id": d, "schema": s} for d, s in SCHEMA_BY_DOMAIN.items()]}


@router.post("/search")
def search(req: SearchRequest):
    """Endpoint-free semantic search: embed the query once, cosine over stored chunk vectors."""
    schema = _schema(req.domain_id)
    k = max(1, min(req.k, 25))
    q = _esc(req.question)
    sql = f"""
        WITH qy AS (SELECT CAST(ai_query('{EMBED_MODEL}', '{q}') AS ARRAY<FLOAT>) AS qv)
        SELECT doc_id, doc_type, source_file, chunk_to_retrieve,
               round(vector_cosine_similarity(embedding, qy.qv), 4) AS score
        FROM {CATALOG}.{schema}.gold_chunks, qy
        ORDER BY score DESC
        LIMIT {k}
    """
    return {"domain_id": req.domain_id, "question": req.question, "results": run_sql(sql)}


@router.get("/evidence")
def evidence(doc_id: str, domain_id: str = "supply_chain"):
    """Evidence trail for a document: type + source file, extracted fields, and source chunks."""
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
    return {"document": doc[0], "extracted_fields": fields, "source_chunks": chunks}
