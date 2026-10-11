"""Central DDL for the app's Lakebase (Postgres) operational schema.

One place that owns every operational table's shape — replaces the scattered
`CREATE TABLE IF NOT EXISTS` calls across the codebase. `ensure_schema(conn)` is
idempotent and cheap; repositories call it lazily on first use.

P1 tables: projects, document_project_tags (mirror the columns the app already
uses in the Lakehouse so route logic barely changes). Later phases add
workflow_runs, workflow_templates, skill_executions, actions here.
"""
from __future__ import annotations

from typing import Any

# Ordered so referenced tables exist first. All in the connection's search_path
# schema (default `app`).
DDL: list[str] = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS projects (
        project_id    TEXT        NOT NULL,
        domain_id     TEXT        NOT NULL,
        name          TEXT        NOT NULL,
        municipality  TEXT        NOT NULL DEFAULT '',
        state         TEXT        NOT NULL DEFAULT '',
        address       TEXT        NOT NULL DEFAULT '',
        parcel_id     TEXT        NOT NULL DEFAULT '',
        status        TEXT        NOT NULL DEFAULT 'Active',
        created_by    TEXT        NOT NULL DEFAULT '',
        owner         TEXT        NOT NULL DEFAULT '',
        collaborators JSONB       NOT NULL DEFAULT '[]'::jsonb,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (domain_id, project_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_project_tags (
        domain_id  TEXT        NOT NULL,
        doc_id     TEXT        NOT NULL,
        project_id TEXT        NOT NULL,
        scope      TEXT        NOT NULL DEFAULT 'project',
        source     TEXT        NOT NULL DEFAULT 'manual',
        tagged_by  TEXT        NOT NULL DEFAULT '',
        tagged_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (domain_id, project_id, doc_id)
    )
    """,
    # One summary row per workflow run. run_json holds the FULL execution
    # (steps/outputs/evidence) — Postgres returns large cells directly, so unlike
    # the warehouse there is no truncation and no external-links read bug.
    """
    CREATE TABLE IF NOT EXISTS workflow_runs (
        run_id           TEXT        PRIMARY KEY,
        domain_id        TEXT        NOT NULL,
        project_id       TEXT        NOT NULL DEFAULT '',
        template_id      TEXT        NOT NULL DEFAULT '',
        template_version TEXT        NOT NULL DEFAULT '',
        work_object_id   TEXT        NOT NULL DEFAULT '',
        status           TEXT        NOT NULL DEFAULT '',
        halted_at        TEXT        NOT NULL DEFAULT '',
        step_count       INT         NOT NULL DEFAULT 0,
        error_count      INT         NOT NULL DEFAULT 0,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        label            TEXT        NOT NULL DEFAULT '',
        run_json         JSONB
    )
    """,
    # Per-skill-invocation observability (ADR-007). Adds domain/project so the
    # Executions tab can scope skill detail without a cross-store join.
    """
    CREATE TABLE IF NOT EXISTS skill_executions (
        execution_id   TEXT        PRIMARY KEY,
        skill_id       TEXT        NOT NULL DEFAULT '',
        skill_version  TEXT        NOT NULL DEFAULT '',
        workflow_id    TEXT        NOT NULL DEFAULT '',
        work_object_id TEXT        NOT NULL DEFAULT '',
        domain_id      TEXT        NOT NULL DEFAULT '',
        project_id     TEXT        NOT NULL DEFAULT '',
        start_time     TIMESTAMPTZ,
        end_time       TIMESTAMPTZ,
        status         TEXT        NOT NULL DEFAULT '',
        error          TEXT        NOT NULL DEFAULT '',
        model          TEXT        NOT NULL DEFAULT '',
        evidence_count INT         NOT NULL DEFAULT 0,
        inputs_digest  TEXT        NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sources (
        source_id      TEXT PRIMARY KEY,
        provider       TEXT NOT NULL,
        display_name   TEXT NOT NULL DEFAULT '',
        auth_mode      TEXT NOT NULL DEFAULT 'service_principal',
        credential_ref TEXT NOT NULL DEFAULT '',
        site           TEXT NOT NULL DEFAULT '',
        status         TEXT NOT NULL DEFAULT 'disconnected',
        mode           TEXT NOT NULL DEFAULT 'live',
        last_crawl_at  TIMESTAMPTZ,
        last_error     TEXT NOT NULL DEFAULT '',
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS external_documents (
        external_document_id TEXT PRIMARY KEY,
        source_id      TEXT NOT NULL,
        source_item_id TEXT NOT NULL DEFAULT '',
        domain_id      TEXT NOT NULL,
        project_id     TEXT NOT NULL DEFAULT '',
        parent_folder_id TEXT NOT NULL DEFAULT '',
        path           TEXT NOT NULL DEFAULT '',
        name           TEXT NOT NULL DEFAULT '',
        mime_type      TEXT NOT NULL DEFAULT '',
        size_bytes     BIGINT NOT NULL DEFAULT 0,
        web_url        TEXT NOT NULL DEFAULT '',
        etag           TEXT NOT NULL DEFAULT '',
        content_hash   TEXT NOT NULL DEFAULT '',
        owner          TEXT NOT NULL DEFAULT '',
        source_created_at  TIMESTAMPTZ,
        source_modified_at TIMESTAMPTZ,
        status         TEXT NOT NULL DEFAULT 'discovered',
        included       BOOLEAN NOT NULL DEFAULT true,
        index_version  INT NOT NULL DEFAULT 0,
        embedding_model TEXT NOT NULL DEFAULT '',
        last_indexed_etag TEXT NOT NULL DEFAULT '',
        chunk_count    INT NOT NULL DEFAULT 0,
        last_error     TEXT NOT NULL DEFAULT '',
        updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # Backfill the native source reference on deployments created before the
    # connector-first redesign (ensure_schema ignores "already exists").
    "ALTER TABLE external_documents ADD COLUMN IF NOT EXISTS source_item_id TEXT NOT NULL DEFAULT ''",
    """
    CREATE TABLE IF NOT EXISTS document_chunks (
        chunk_id       TEXT PRIMARY KEY,
        external_document_id TEXT NOT NULL,
        domain_id      TEXT NOT NULL,
        project_id     TEXT NOT NULL DEFAULT '',
        ordinal        INT NOT NULL DEFAULT 0,
        location       TEXT NOT NULL DEFAULT '',
        snippet        TEXT NOT NULL DEFAULT '',
        embedding      vector(1024),
        tsv            tsvector,
        source_version TEXT NOT NULL DEFAULT '',
        index_version  INT NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS index_jobs (
        job_id        TEXT PRIMARY KEY,
        domain_id     TEXT NOT NULL,
        project_id    TEXT NOT NULL DEFAULT '',
        scope         TEXT NOT NULL DEFAULT 'project',
        scope_ref     TEXT NOT NULL DEFAULT '',
        requested_by  TEXT NOT NULL DEFAULT '',
        status        TEXT NOT NULL DEFAULT 'queued',
        discovered    INT NOT NULL DEFAULT 0,
        embedded      INT NOT NULL DEFAULT 0,
        skipped       INT NOT NULL DEFAULT 0,
        deleted       INT NOT NULL DEFAULT 0,
        failed        INT NOT NULL DEFAULT 0,
        started_at    TIMESTAMPTZ,
        finished_at   TIMESTAMPTZ,
        error_summary TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS use_cases (
        use_case_id   TEXT PRIMARY KEY,
        name          TEXT NOT NULL DEFAULT '',
        status        TEXT NOT NULL DEFAULT 'active',
        classification_labels JSONB NOT NULL DEFAULT '{}'::jsonb,
        extraction_schemas    JSONB NOT NULL DEFAULT '{}'::jsonb,
        entity_types          JSONB NOT NULL DEFAULT '[]'::jsonb,
        agent_system_prompt   TEXT NOT NULL DEFAULT '',
        suggested_questions   JSONB NOT NULL DEFAULT '[]'::jsonb,
        enabled_skills        JSONB NOT NULL DEFAULT '[]'::jsonb,
        reconciliation        JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_projects_domain ON projects (domain_id)",
    "CREATE INDEX IF NOT EXISTS idx_tags_domain_project ON document_project_tags (domain_id, project_id)",
    "CREATE INDEX IF NOT EXISTS idx_tags_domain_doc ON document_project_tags (domain_id, doc_id)",
    "CREATE INDEX IF NOT EXISTS idx_runs_domain_project ON workflow_runs (domain_id, project_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_skillexec_workflow ON skill_executions (workflow_id, start_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_extdocs_scope ON external_documents (domain_id, project_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_scope ON document_chunks (domain_id, project_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks (external_document_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_hnsw ON document_chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON document_chunks USING gin (tsv)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_scope ON index_jobs (domain_id, project_id, status)",
    # App-managed connector credentials (Task 1). Secrets live in Databricks secret
    # scopes; only the ref pointer is stored here — client_secret is NEVER a column.
    """
    CREATE TABLE IF NOT EXISTS connectors (
        provider      TEXT        PRIMARY KEY,
        display_name  TEXT        NOT NULL DEFAULT '',
        client_id     TEXT        NOT NULL DEFAULT '',
        redirect_uri  TEXT        NOT NULL DEFAULT '',
        scopes        JSONB       NOT NULL DEFAULT '[]'::jsonb,
        secret_ref    TEXT        NOT NULL DEFAULT '',
        status        TEXT        NOT NULL DEFAULT 'unconfigured',
        updated_by    TEXT        NOT NULL DEFAULT '',
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
]


def ensure_schema(conn: Any) -> None:
    """Create every operational table/index if missing. Idempotent and
    best-effort per statement (matches the codebase's ensure_table idiom).

    Statements are resilient because tables backfilled by an admin are owned by
    that admin, not the app service principal — so `CREATE INDEX IF NOT EXISTS`
    on them raises "must be owner" even though the index already exists. The SP
    has full DML via GRANT, and it still creates+owns any *new* tables. We ignore
    "already exists" / "must be owner" and re-raise anything genuinely wrong.
    """
    _IGNORABLE = ("already exists", "must be owner", "duplicate")
    for stmt in DDL:
        try:
            conn.execute(stmt)
        except Exception as e:
            msg = str(e).lower()
            if any(tok in msg for tok in _IGNORABLE):
                continue
            raise
