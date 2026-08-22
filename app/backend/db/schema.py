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
    "CREATE INDEX IF NOT EXISTS idx_projects_domain ON projects (domain_id)",
    "CREATE INDEX IF NOT EXISTS idx_tags_domain_project ON document_project_tags (domain_id, project_id)",
    "CREATE INDEX IF NOT EXISTS idx_tags_domain_doc ON document_project_tags (domain_id, doc_id)",
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
