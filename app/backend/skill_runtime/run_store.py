"""platform.workflow_runs — one summary row per workflow run, so the Executions
tab can group runs (and their actions/findings) by project/case.

Additive to skill_executions (which stays per-skill-invocation). Idempotent DDL,
best-effort write: a logging failure never breaks a run."""
from __future__ import annotations

from typing import Any, Callable, Optional

CATALOG_DEFAULT = "jai_docintel"


def runs_table(catalog: str = CATALOG_DEFAULT) -> str:
    return f"{catalog}.platform.workflow_runs"


def ensure_runs_table(run_sql: Callable[[str], Any],
                      catalog: str = CATALOG_DEFAULT) -> None:
    run_sql(f"""
        CREATE TABLE IF NOT EXISTS {runs_table(catalog)} (
            run_id           STRING,
            domain_id        STRING,
            project_id       STRING,
            template_id      STRING,
            template_version STRING,
            work_object_id   STRING,
            status           STRING,
            halted_at        STRING,
            step_count       INT,
            error_count      INT,
            created_at       TIMESTAMP,
            saved            BOOLEAN,
            label            STRING,
            run_json         STRING
        ) USING DELTA
    """)
    # add columns if the table pre-dates them. Databricks has no ADD COLUMN IF
    # NOT EXISTS, so add each individually and ignore the "already exists" error.
    for col, typ in [("saved", "BOOLEAN"), ("label", "STRING"), ("run_json", "STRING")]:
        try:
            run_sql(f"ALTER TABLE {runs_table(catalog)} ADD COLUMNS ({col} {typ})")
        except Exception:
            pass  # column already exists


def _lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _slim_run(run: dict) -> dict:
    """Trim a run for storage so the saved JSON stays small enough to come back
    INLINE from the SQL warehouse. Large result cells are returned via external
    links that the simple run_sql path does not fetch, so a bloated run_json would
    read back as empty. We keep the run summary + a compact per-step view."""
    import copy
    import json as _json
    r = {
        "template_id": run.get("template_id"),
        "template_version": run.get("template_version"),
        "domain": run.get("domain"),
        "status": run.get("status"),
        "work_object_id": run.get("work_object_id"),
        "halted_at": run.get("halted_at"),
        "steps": [],
    }
    for step in run.get("steps") or []:
        outs = step.get("outputs") or {}
        # cap each output value so a giant field can't blow the cell size
        compact = {}
        for k, v in outs.items():
            if k == "evidence":
                continue
            s = v if isinstance(v, (str, int, float, bool)) else _json.dumps(v)
            compact[k] = s[:600] if isinstance(s, str) and len(s) > 600 else s
        ev = [{"document_id": e.get("document_id", ""),
               "source_text": str(e.get("source_text", ""))[:160]}
              for e in (step.get("evidence") or [])[:6] if isinstance(e, dict)]
        r["steps"].append({
            "id": step.get("id"), "skill": step.get("skill"),
            "status": step.get("status"), "error": step.get("error"),
            "outputs": compact, "evidence": ev,
        })
    return copy.deepcopy(r)


def record_run(run_sql: Optional[Callable[[str], Any]], domain_id: str,
               project_id: str, run: dict, saved: bool = False,
               label: str = "", catalog: str = CATALOG_DEFAULT) -> str:
    """Persist a workflow run. When `saved`, also stores the full run_json so the
    execution can be re-opened later. Returns the run_id. Best-effort."""
    if run_sql is None:
        return ""
    import json as _json
    import uuid as _uuid
    steps = run.get("steps") or []
    err_count = sum(1 for s in steps if s.get("status") == "error")
    run_id = run.get("work_object_id") or f"run-{_uuid.uuid4().hex[:12]}"
    run_json = _json.dumps(_slim_run(run)) if saved else None
    try:
        ensure_runs_table(run_sql, catalog=catalog)
        run_sql(f"""
            INSERT INTO {runs_table(catalog)}
              (run_id, domain_id, project_id, template_id, template_version,
               work_object_id, status, halted_at, step_count, error_count,
               created_at, saved, label, run_json)
            VALUES (
                {_lit(run_id)}, {_lit(domain_id)}, {_lit(project_id)},
                {_lit(run.get('template_id'))}, {_lit(run.get('template_version'))},
                {_lit(run.get('work_object_id'))}, {_lit(run.get('status'))},
                {_lit(run.get('halted_at'))}, {len(steps)}, {err_count},
                current_timestamp(), {str(bool(saved)).lower()}, {_lit(label)},
                {_lit(run_json)}
            )
        """)
    except Exception as e:  # never break a run on logging failure
        print(f"[workflow_runs] record failed: {e}")
    return run_id


def list_runs(run_sql: Callable[[str], Any], domain_id: str,
              project_id: Optional[str] = None, saved_only: bool = False,
              catalog: str = CATALOG_DEFAULT, limit: int = 200) -> list:
    """Return run summaries for a domain, optionally filtered to one project."""
    where = f"WHERE domain_id = {_lit(domain_id)}"
    if project_id:
        where += f" AND project_id = {_lit(project_id)}"
    if saved_only:
        where += " AND saved = true"
    try:
        ensure_runs_table(run_sql, catalog=catalog)
        return run_sql(f"""
            SELECT run_id, domain_id, project_id, template_id, template_version,
                   work_object_id, status, halted_at, step_count, error_count,
                   created_at, saved, label
            FROM {runs_table(catalog)}
            {where}
            ORDER BY created_at DESC
            LIMIT {limit}
        """) or []
    except Exception as e:
        print(f"[workflow_runs] list failed: {e}")
        return []


def get_run(run_sql: Callable[[str], Any], run_id: str,
            catalog: str = CATALOG_DEFAULT) -> Optional[dict]:
    """Return the full stored run_json for a saved execution (or None)."""
    import json as _json
    try:
        rows = run_sql(f"""
            SELECT run_json FROM {runs_table(catalog)}
            WHERE run_id = {_lit(run_id)} AND run_json IS NOT NULL
            ORDER BY created_at DESC LIMIT 1
        """) or []
        if rows and rows[0].get("run_json"):
            return _json.loads(rows[0]["run_json"])
    except Exception as e:
        print(f"[workflow_runs] get_run failed: {e}")
    return None
