"""Use-cases CRUD against Lakebase. Stores per-domain configuration (labels,
extraction schemas, prompts, etc.)."""
from __future__ import annotations

import json
from typing import Any, Optional


def _dicts(cur: Any) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def list_use_cases(conn: Any) -> list[dict]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM use_cases ORDER BY created_at")
    return _dicts(cur)


def get_use_case(conn: Any, use_case_id: str) -> Optional[dict]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM use_cases WHERE use_case_id=%s", (use_case_id,))
    rows = _dicts(cur)
    return rows[0] if rows else None


def upsert_use_case(conn: Any, use_case_id: str, **fields) -> dict:
    """Insert or update a use_case row. JSON-encodes dict/list fields."""
    name = fields.get("name", "")
    status = fields.get("status", "active")

    def _j(val, default):
        if val is None:
            return json.dumps(default)
        if isinstance(val, (dict, list)):
            return json.dumps(val)
        return val

    classification_labels = _j(fields.get("classification_labels"), {})
    extraction_schemas = _j(fields.get("extraction_schemas"), {})
    entity_types = _j(fields.get("entity_types"), [])
    agent_system_prompt = fields.get("agent_system_prompt", "")
    suggested_questions = _j(fields.get("suggested_questions"), [])
    enabled_skills = _j(fields.get("enabled_skills"), [])
    reconciliation = _j(fields.get("reconciliation"), {})

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO use_cases (use_case_id, name, status,
            classification_labels, extraction_schemas, entity_types,
            agent_system_prompt, suggested_questions, enabled_skills,
            reconciliation)
        VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s::jsonb)
        ON CONFLICT (use_case_id) DO UPDATE SET
            name=EXCLUDED.name, status=EXCLUDED.status,
            classification_labels=EXCLUDED.classification_labels,
            extraction_schemas=EXCLUDED.extraction_schemas,
            entity_types=EXCLUDED.entity_types,
            agent_system_prompt=EXCLUDED.agent_system_prompt,
            suggested_questions=EXCLUDED.suggested_questions,
            enabled_skills=EXCLUDED.enabled_skills,
            reconciliation=EXCLUDED.reconciliation,
            updated_at=now()
        """,
        (use_case_id, name, status,
         classification_labels, extraction_schemas, entity_types,
         agent_system_prompt, suggested_questions, enabled_skills, reconciliation),
    )
    return get_use_case(conn, use_case_id)
