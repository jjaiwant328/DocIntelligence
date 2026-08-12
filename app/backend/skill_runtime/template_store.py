"""Persistence for per-domain, user-built workflow templates.

Table `platform.workflow_templates`. Steps are stored as a JSON string
(`steps_json`) holding `[{id, skill, inputs_map}]`, mirroring the YAML template
shape so the engine can consume DB and file templates identically.

DB writes are best-effort at the call site; helpers here build SQL and parse rows.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable, Optional

CATALOG_DEFAULT = "jai_docintel"


def templates_table(catalog: str = CATALOG_DEFAULT) -> str:
    return f"{catalog}.platform.workflow_templates"


def ensure_templates_table(run_sql: Callable, catalog: str = CATALOG_DEFAULT) -> None:
    run_sql(f"""
        CREATE TABLE IF NOT EXISTS {templates_table(catalog)} (
            template_id      STRING,
            domain_id        STRING,
            name             STRING,
            description      STRING,
            version          STRING,
            status           STRING,
            approval_before  STRING,
            steps_json       STRING,
            created_by       STRING,
            created_at       TIMESTAMP,
            updated_at       TIMESTAMP
        ) USING DELTA
    """)


def _esc(s) -> str:
    return str(s).replace("'", "''")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def row_to_template(row: dict) -> dict:
    """Normalize a DB row into the engine's template dict shape."""
    try:
        steps = json.loads(row.get("steps_json") or "[]")
    except json.JSONDecodeError:
        steps = []
    return {
        "id": row.get("template_id"),
        "domain_id": row.get("domain_id"),
        "name": row.get("name"),
        "description": row.get("description"),
        "version": row.get("version") or "1.0",
        "status": row.get("status") or "active",
        "approval_before": row.get("approval_before") or None,
        "steps": steps,
        "source": "user",
    }


def list_templates(run_sql: Callable, domain_id: str,
                   catalog: str = CATALOG_DEFAULT) -> list:
    rows = run_sql(f"""
        SELECT template_id, domain_id, name, description, version, status,
               approval_before, steps_json
        FROM {templates_table(catalog)}
        WHERE domain_id = '{_esc(domain_id)}' AND status != 'archived'
        ORDER BY updated_at DESC
    """) or []
    return [row_to_template(r) for r in rows]


def get_template(run_sql: Callable, domain_id: str, template_id: str,
                 catalog: str = CATALOG_DEFAULT) -> Optional[dict]:
    rows = run_sql(f"""
        SELECT template_id, domain_id, name, description, version, status,
               approval_before, steps_json
        FROM {templates_table(catalog)}
        WHERE domain_id = '{_esc(domain_id)}' AND template_id = '{_esc(template_id)}'
              AND status != 'archived'
        LIMIT 1
    """) or []
    return row_to_template(rows[0]) if rows else None


def save_template(run_sql: Callable, domain_id: str, template_id: str, name: str,
                  steps: list, approval_before: Optional[str] = None,
                  description: str = "", version: str = "1.0",
                  created_by: str = "user", catalog: str = CATALOG_DEFAULT) -> dict:
    """Upsert: delete any existing row for (domain, template) then insert."""
    ensure_templates_table(run_sql, catalog)
    steps_json = _esc(json.dumps(steps))
    run_sql(f"""
        DELETE FROM {templates_table(catalog)}
        WHERE domain_id = '{_esc(domain_id)}' AND template_id = '{_esc(template_id)}'
    """)
    run_sql(f"""
        INSERT INTO {templates_table(catalog)} VALUES (
            '{_esc(template_id)}', '{_esc(domain_id)}', '{_esc(name)}',
            '{_esc(description)}', '{_esc(version)}', 'active',
            {("'" + _esc(approval_before) + "'") if approval_before else "NULL"},
            '{steps_json}', '{_esc(created_by)}',
            TIMESTAMP '{_now()}', TIMESTAMP '{_now()}')
    """)
    return {"template_id": template_id, "domain_id": domain_id, "status": "active"}


def delete_template(run_sql: Callable, domain_id: str, template_id: str,
                    catalog: str = CATALOG_DEFAULT) -> None:
    run_sql(f"""
        UPDATE {templates_table(catalog)} SET status = 'archived',
               updated_at = TIMESTAMP '{_now()}'
        WHERE domain_id = '{_esc(domain_id)}' AND template_id = '{_esc(template_id)}'
    """)
