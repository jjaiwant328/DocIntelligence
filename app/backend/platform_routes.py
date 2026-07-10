"""
platform_routes.py — Multi-Domain Platform API

Endpoints:
  GET  /api/platform/domains               — list all domains
  POST /api/platform/domains               — create a new domain (wizard step 6)
  GET  /api/platform/domains/{domain_id}   — get a single domain config
  PUT  /api/platform/domains/{domain_id}   — update domain config (wizard steps 1-5)
  POST /api/platform/setup/suggest-labels  — AI-suggest classification labels
  POST /api/platform/setup/suggest-schema  — AI-suggest extraction schema fields
  POST /api/platform/setup/initialize      — provision UC schema + volume via job
  POST /api/platform/setup/activate        — mark domain active
  GET  /api/platform/pipeline-runs/{domain_id}  — list recent pipeline runs for a domain
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

router = APIRouter(prefix="/api/platform", tags=["platform"])

# ── Shared Databricks client ──────────────────────────────────────────────────

try:
    w = WorkspaceClient()
    warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID", "")
    print("✅ platform_routes: Databricks client ready")
except Exception as _e:
    w = None
    warehouse_id = None
    print(f"⚠️ platform_routes: Databricks client failed: {_e}")

CATALOG  = "jai_docintel"
PLATFORM = "platform"

# ── SQL helper ────────────────────────────────────────────────────────────────

def run_sql(sql: str, wait: str = "50s"):
    if not w or not warehouse_id:
        raise HTTPException(status_code=503, detail="Databricks not configured")
    result = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=warehouse_id, wait_timeout=wait
    )
    state = result.status.state if result.status else None
    if state == StatementState.FAILED:
        raise HTTPException(status_code=500, detail=str(result.status.error))
    if state in (StatementState.PENDING, StatementState.RUNNING):
        # Poll once more
        import time; time.sleep(3)
        result = w.statement_execution.get_statement(result.statement_id)
    rows = []
    if result.result and result.result.data_array:
        cols = [c.name for c in result.manifest.schema.columns]
        rows = [dict(zip(cols, row)) for row in result.result.data_array]
    return rows

# ── Pydantic models ───────────────────────────────────────────────────────────

class DomainCreateRequest(BaseModel):
    domain_id: str
    name: str
    description: str = ""
    schema_raw: str = ""
    schema_ont: str = ""
    schema_vec: str = ""
    schema_agt: str = ""
    volume_docs: str = "documents"
    classification_labels: str = "{}"
    extraction_schemas: str = "{}"
    entity_types: str = "[]"
    agent_system_prompt: str = ""
    analytics_config: str = "{}"
    suggested_questions: str = "[]"

class DomainUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    schema_raw: Optional[str] = None
    schema_ont: Optional[str] = None
    schema_vec: Optional[str] = None
    schema_agt: Optional[str] = None
    classification_labels: Optional[str] = None
    extraction_schemas: Optional[str] = None
    entity_types: Optional[str] = None
    agent_system_prompt: Optional[str] = None
    analytics_config: Optional[str] = None
    suggested_questions: Optional[str] = None

class SuggestLabelsRequest(BaseModel):
    domain_name: str
    domain_description: str

class SuggestSchemaRequest(BaseModel):
    domain_name: str
    doc_type_label: str
    doc_type_description: str

class InitializeRequest(BaseModel):
    domain_id: str

class ActivateRequest(BaseModel):
    domain_id: str

# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def _esc(s: str) -> str:
    """Escape single quotes for SQL strings."""
    return s.replace("'", "\\'")

def _schema_name_for(domain_id: str, purpose: str) -> str:
    """
    Compute default schema name for a new domain.
    supply_chain uses the legacy split-schema layout.
    All other domains use a single schema = domain_id.
    """
    if domain_id == "supply_chain":
        return {"raw": "raw", "ont": "ontology", "vec": "vectors", "agt": "agents"}[purpose]
    return domain_id  # single schema per domain

# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/domains")
def list_domains():
    """Return all domain configs with summary counts."""
    try:
        domains = run_sql(f"""
            SELECT domain_id, name, description, status,
                   schema_raw, schema_ont,
                   created_at, updated_at
            FROM {CATALOG}.{PLATFORM}.domain_configs
            ORDER BY created_at
        """)
    except Exception as e:
        # Platform schema may not exist yet (before 00_platform_setup runs)
        return {"domains": [], "total": 0, "warning": str(e)}

    for d in domains:
        # Attach doc count for each domain
        try:
            cnt_rows = run_sql(f"""
                SELECT COUNT(*) AS cnt FROM {CATALOG}.{d['schema_raw']}.parsed_documents
            """)
            d["doc_count"] = cnt_rows[0]["cnt"] if cnt_rows else 0
        except Exception:
            d["doc_count"] = 0
        # Stringify timestamps
        for ts_col in ("created_at", "updated_at"):
            if d.get(ts_col):
                d[ts_col] = str(d[ts_col])

    return {"domains": domains, "total": len(domains)}


@router.get("/domains/{domain_id}")
def get_domain(domain_id: str):
    """Return full config for a single domain."""
    rows = run_sql(f"""
        SELECT * FROM {CATALOG}.{PLATFORM}.domain_configs
        WHERE domain_id = '{_esc(domain_id)}'
        LIMIT 1
    """)
    if not rows:
        raise HTTPException(status_code=404, detail=f"Domain '{domain_id}' not found")
    d = rows[0]
    for ts_col in ("created_at", "updated_at"):
        if d.get(ts_col):
            d[ts_col] = str(d[ts_col])
    return d


@router.post("/domains")
def create_domain(req: DomainCreateRequest):
    """Create a new domain config row (called from wizard step 6)."""
    # Derive default schema names
    schema_raw = req.schema_raw or _schema_name_for(req.domain_id, "raw")
    schema_ont = req.schema_ont or _schema_name_for(req.domain_id, "ont")
    schema_vec = req.schema_vec or _schema_name_for(req.domain_id, "vec")
    schema_agt = req.schema_agt or _schema_name_for(req.domain_id, "agt")

    now = _now()
    run_sql(f"""
        INSERT INTO {CATALOG}.{PLATFORM}.domain_configs
        VALUES (
            '{_esc(req.domain_id)}',
            '{_esc(req.name)}',
            '{_esc(req.description)}',
            'configuring',
            '{_esc(schema_raw)}', '{_esc(schema_ont)}',
            '{_esc(schema_vec)}', '{_esc(schema_agt)}',
            '{_esc(req.volume_docs)}',
            '{_esc(req.classification_labels)}',
            '{_esc(req.extraction_schemas)}',
            '{_esc(req.entity_types)}',
            '{_esc(req.agent_system_prompt)}',
            '{_esc(req.analytics_config)}',
            '{_esc(req.suggested_questions)}',
            TIMESTAMP '{now}',
            TIMESTAMP '{now}'
        )
    """)
    return {"success": True, "domain_id": req.domain_id, "status": "configuring"}


@router.put("/domains/{domain_id}")
def update_domain(domain_id: str, req: DomainUpdateRequest):
    """Partial update for wizard steps 1-5."""
    sets = []
    for field, val in req.dict(exclude_none=True).items():
        col = field  # field names match column names
        sets.append(f"{col} = '{_esc(str(val))}'")
    if not sets:
        return {"success": True, "message": "No fields to update"}
    sets.append(f"updated_at = TIMESTAMP '{_now()}'")
    run_sql(f"""
        UPDATE {CATALOG}.{PLATFORM}.domain_configs
        SET {', '.join(sets)}
        WHERE domain_id = '{_esc(domain_id)}'
    """)
    return {"success": True, "domain_id": domain_id}


@router.post("/setup/suggest-labels")
def suggest_labels(req: SuggestLabelsRequest):
    """
    Call DBRX to suggest classification labels for a new domain.
    Returns a JSON object: { label_key: description, ... }
    """
    prompt = _esc(
        f"You are helping configure a Document Intelligence platform for '{req.domain_name}'. "
        f"Domain description: {req.domain_description}. "
        "List 6-10 document types that are commonly found in this domain. "
        "Return ONLY a valid JSON object where each key is a snake_case label name "
        "and each value is a one-sentence description suitable for an AI document classifier. "
        "Example: {\"contract\": \"A legal agreement ...\", \"invoice\": \"...\"}"
    )
    rows = run_sql(f"""
        SELECT ai_query(
            'databricks-meta-llama-3-3-70b-instruct',
            '{prompt}'
        ) AS response
    """)
    raw = rows[0]["response"] if rows else "{}"
    # Try to parse the response as JSON
    try:
        # Extract JSON block if wrapped in markdown
        import re
        match = re.search(r'\{.*\}', str(raw), re.DOTALL)
        labels = json.loads(match.group(0)) if match else {}
    except Exception:
        labels = {}
    return {"labels": labels, "raw_response": str(raw)}


@router.post("/setup/suggest-schema")
def suggest_schema(req: SuggestSchemaRequest):
    """
    Call DBRX to suggest extraction fields for a doc type.
    Returns a JSON schema object: { field_name: {type, description}, ... }
    """
    prompt = _esc(
        f"You are configuring extraction for document type '{req.doc_type_label}' "
        f"in the '{req.domain_name}' domain. "
        f"Document description: {req.doc_type_description}. "
        "List 5-8 structured fields that should be extracted from this document type. "
        "Return ONLY a valid JSON object where each key is a snake_case field name "
        "and each value is an object with 'type' (always 'string') and 'description'. "
        'Example: {"contract_number": {"type": "string", "description": "Reference number"}}'
    )
    rows = run_sql(f"""
        SELECT ai_query(
            'databricks-meta-llama-3-3-70b-instruct',
            '{prompt}'
        ) AS response
    """)
    raw = rows[0]["response"] if rows else "{}"
    try:
        import re
        match = re.search(r'\{.*\}', str(raw), re.DOTALL)
        schema = json.loads(match.group(0)) if match else {}
    except Exception:
        schema = {}
    return {"schema": schema, "raw_response": str(raw)}


SETUP_DOMAIN_JOB_NAME = "DocIntelligence — Setup New Domain"

@router.post("/setup/initialize")
def initialize_domain(req: InitializeRequest):
    """
    Provision the UC schema and volume for a new domain by triggering the
    docintel_setup_domain job with the domain_id as a job-level parameter.
    """
    if not w:
        raise HTTPException(status_code=503, detail="Databricks not configured")
    try:
        # Target the setup job by its exact name
        jobs = list(w.jobs.list(name=SETUP_DOMAIN_JOB_NAME))
        job_id = jobs[0].job_id if jobs else None

        # Fallback: find any job containing the setup keyword
        if not job_id:
            for j in w.jobs.list(name="DocIntelligence"):
                name = (j.settings.name or "") if j.settings else ""
                if "Setup" in name or "setup" in name:
                    job_id = j.job_id
                    break

        if job_id:
            run = w.jobs.run_now(
                job_id=job_id,
                job_parameters={"domain_id": req.domain_id},
            )
            run_id = run.run_id
        else:
            run_id = None

        # Update status
        run_sql(f"""
            UPDATE {CATALOG}.{PLATFORM}.domain_configs
            SET status = 'configuring', updated_at = TIMESTAMP '{_now()}'
            WHERE domain_id = '{_esc(req.domain_id)}'
        """)
        return {"success": True, "domain_id": req.domain_id, "run_id": run_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/setup/activate")
def activate_domain(req: ActivateRequest):
    """Mark a domain as active after the setup pipeline succeeds."""
    run_sql(f"""
        UPDATE {CATALOG}.{PLATFORM}.domain_configs
        SET status = 'active', updated_at = TIMESTAMP '{_now()}'
        WHERE domain_id = '{_esc(req.domain_id)}'
    """)
    return {"success": True, "domain_id": req.domain_id, "status": "active"}


@router.get("/pipeline-runs/{domain_id}")
def get_pipeline_runs(domain_id: str):
    """List recent pipeline runs for a domain."""
    try:
        rows = run_sql(f"""
            SELECT run_id, job_run_id, status, triggered_by,
                   CAST(started_at AS STRING) AS started_at,
                   CAST(finished_at AS STRING) AS finished_at,
                   error_msg
            FROM {CATALOG}.{PLATFORM}.pipeline_runs
            WHERE domain_id = '{_esc(domain_id)}'
            ORDER BY started_at DESC
            LIMIT 20
        """)
        return {"runs": rows, "total": len(rows)}
    except Exception:
        return {"runs": [], "total": 0}
