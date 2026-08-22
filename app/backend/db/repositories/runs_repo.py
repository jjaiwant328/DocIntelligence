"""Workflow-run persistence against Lakebase. Stores the FULL run JSON (no
truncation) — Postgres returns large cells directly, so reopen is lossless.
This is what fixes the warehouse external-links "reopen returns empty" bug."""
from __future__ import annotations

import json
from typing import Any, Optional


def _summary_cols() -> list[str]:
    return ["run_id", "domain_id", "project_id", "template_id", "template_version",
            "work_object_id", "status", "halted_at", "step_count", "error_count",
            "created_at", "label"]


def record_run(conn: Any, *, domain_id: str, project_id: str, run: dict,
               label: str = "") -> str:
    import uuid as _uuid

    steps = run.get("steps") or []
    err_count = sum(1 for s in steps if s.get("status") == "error")
    run_id = run.get("work_object_id") or f"run-{_uuid.uuid4().hex[:12]}"
    run_json = json.dumps(run, default=str)  # FULL run, lossless
    conn.execute(
        """
        INSERT INTO workflow_runs
          (run_id, domain_id, project_id, template_id, template_version,
           work_object_id, status, halted_at, step_count, error_count,
           created_at, label, run_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now(), %s, %s::jsonb)
        ON CONFLICT (run_id) DO UPDATE SET
          status=EXCLUDED.status, halted_at=EXCLUDED.halted_at,
          step_count=EXCLUDED.step_count, error_count=EXCLUDED.error_count,
          label=EXCLUDED.label, run_json=EXCLUDED.run_json
        """,
        (run_id, domain_id, project_id or "", run.get("template_id") or "",
         run.get("template_version") or "", run.get("work_object_id") or "",
         run.get("status") or "", run.get("halted_at") or "", len(steps), err_count,
         label, run_json),
    )
    return run_id


def list_runs(conn: Any, *, domain_id: str, project_id: Optional[str] = None,
              limit: int = 200) -> list[dict]:
    cols = _summary_cols()
    sql = f"SELECT {', '.join(cols)} FROM workflow_runs WHERE domain_id = %s"
    params: list[Any] = [domain_id]
    if project_id:
        sql += " AND project_id = %s"
        params.append(project_id)
    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)
    cur = conn.execute(sql, tuple(params))
    out = []
    for row in cur.fetchall():
        d = dict(zip(cols, row))
        # keep the JSON-friendly shape the frontend already expects
        d["saved"] = True
        out.append(d)
    return out


def get_run(conn: Any, run_id: str) -> Optional[dict]:
    cur = conn.execute("SELECT run_json FROM workflow_runs WHERE run_id = %s", (run_id,))
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    val = row[0]
    # psycopg returns JSONB as a parsed object already; tolerate a str too.
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return None
    return val
