"""One-shot backfill: spine medallion tables (template/template_cdd) → Lakebase.

Idempotent: docs upsert on external_document_id, chunks/fields use
replace_for_doc. Vectors are carried over — no re-embedding.

Run:  python scripts/backfill_spine_to_lakebase.py [--domain supply_chain]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

from db import lakebase
from db import schema as _schema
from db.repositories import external_docs_repo, chunks_repo, extracted_fields_repo

CATALOG = "jai_docintel"
SCHEMA_BY_DOMAIN = {
    "supply_chain": "template",
    "compliance_due_diligence": "template_cdd",
}


def _doc_row(domain_id: str, r: dict) -> dict:
    return {
        "external_document_id": r["doc_id"],
        "source_id": "uc_volume",
        "source_item_id": r["doc_id"],
        "domain_id": domain_id,
        "project_id": "default",
        "parent_folder_id": "",
        "path": r.get("source_file", ""),
        "name": r["doc_id"],
        "mime_type": "text/plain",
        "size_bytes": 0,
        "web_url": r.get("source_file", ""),
        "etag": "",
        "content_hash": "",
        "owner": "backfill",
        "source_created_at": None,
        "source_modified_at": None,
        "status": "indexed",
        "included": True,
        "doc_type": r.get("doc_type", ""),
    }


def _field_row(doc_id: str, r: dict) -> dict:
    return {"field_name": r["field_name"], "field_value": r.get("field_value", ""),
            "page": r.get("page"), "bbox": r.get("bbox"),
            "source_text": r.get("source_text", ""), "confidence": None}


def _parse_embedding(v):
    """SQL statement-execution returns ARRAY columns as JSON strings, and the
    array elements themselves may be quoted numbers — normalize to floats."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return None
    if isinstance(v, (list, tuple)):
        try:
            return [float(x) for x in v]
        except (TypeError, ValueError):
            return None
    return None


def _chunk_row(domain_id: str, doc_id: str, r: dict) -> dict:
    return {
        "chunk_id": f"{doc_id}:{r.get('chunk_position', 0)}",
        "external_document_id": doc_id,
        "domain_id": domain_id,
        "project_id": "default",
        "ordinal": r.get("chunk_position", 0),
        "location": "",
        "snippet": r.get("chunk_to_retrieve", ""),
        "embedding": _parse_embedding(r.get("embedding")),
    }


def _sql(w, warehouse_id: str, stmt: str) -> list[dict]:
    res = w.statement_execution.execute_statement(
        statement=stmt, warehouse_id=warehouse_id, wait_timeout="50s")
    while res.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        res = w.statement_execution.get_statement(res.statement_id)
    if res.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"warehouse read failed: {res.status.error}")
    cols = [c.name for c in res.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (res.result.data_array or [])]


def backfill_domain(w, warehouse_id: str, domain_id: str) -> dict:
    schema = SCHEMA_BY_DOMAIN[domain_id]
    docs = _sql(w, warehouse_id, f"SELECT doc_id, doc_type, source_file FROM {CATALOG}.{schema}.gold_documents")
    counts = {"docs": 0, "fields": 0, "chunks": 0}
    with lakebase.connection() as conn:
        for d in docs:
            did = d["doc_id"]
            row = _doc_row(domain_id, d)
            external_docs_repo.upsert_metadata(conn, row)
            # upsert_metadata's fixed column list has no doc_type — set it directly.
            cur = conn.cursor()
            cur.execute(
                "UPDATE external_documents SET doc_type=%s WHERE external_document_id=%s",
                (row["doc_type"], did),
            )
            counts["docs"] += 1
            fields = _sql(w, warehouse_id,
                f"SELECT * FROM {CATALOG}.{schema}.gold_extracted_fields WHERE doc_id = '{did}'")
            counts["fields"] += extracted_fields_repo.replace_for_doc(
                conn, did, [_field_row(did, f) for f in fields])
            chunks = _sql(w, warehouse_id,
                f"SELECT * FROM {CATALOG}.{schema}.gold_chunks WHERE doc_id = '{did}' ORDER BY chunk_position")
            counts["chunks"] += chunks_repo.replace_chunks(
                conn, did, [_chunk_row(domain_id, did, c) for c in chunks])
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", choices=list(SCHEMA_BY_DOMAIN), default=None)
    args = ap.parse_args()
    w = WorkspaceClient()
    warehouse_id = os.environ["DATABRICKS_WAREHOUSE_ID"]
    with lakebase.connection() as conn:
        _schema.ensure_schema(conn)
    domains = [args.domain] if args.domain else list(SCHEMA_BY_DOMAIN)
    for domain_id in domains:
        counts = backfill_domain(w, warehouse_id, domain_id)
        print(f"{domain_id}: {counts}")


if __name__ == "__main__":
    main()
