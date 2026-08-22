"""Workflow-run persistence.

Every run is auto-saved, losslessly, to Lakebase (Postgres stores the full run
JSON and returns it whole on reopen — this is what fixes the old warehouse
external-links "reopen returns empty" bug). If Lakebase is unavailable we fall
back to a best-effort, BOUNDED warehouse insert (a multi-MB blob can't be
inlined into warehouse SQL), which is a degraded net only — reopen of a large
run via the fallback may be lossy, the Lakebase primary is not.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

CATALOG_DEFAULT = "jai_docintel"


def runs_table(catalog: str = CATALOG_DEFAULT) -> str:
    return f"{catalog}.platform.workflow_runs"


def ensure_runs_table(run_sql: Callable[[str], Any], catalog: str = CATALOG_DEFAULT) -> None:
    """Warehouse-side DDL, kept for the fallback path only (Lakebase owns the
    primary schema via db.schema)."""
    run_sql(f"""
        CREATE TABLE IF NOT EXISTS {runs_table(catalog)} (
            run_id STRING, domain_id STRING, project_id STRING, template_id STRING,
            template_version STRING, work_object_id STRING, status STRING,
            halted_at STRING, step_count INT, error_count INT,
            created_at TIMESTAMP, saved BOOLEAN, label STRING, run_json STRING
        ) USING DELTA
    """)


def _lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _slim_run(run: dict) -> dict:
    """BOUNDED run view for the warehouse fallback only (keeps the inline INSERT
    small). The Lakebase primary path stores the full run untouched."""
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
               project_id: str, run: dict, saved: bool = True,
               label: str = "", catalog: str = CATALOG_DEFAULT) -> str:
    """Persist a run. Always saves the FULL run to Lakebase; `saved` is retained
    for signature compatibility but ignored (every run is now saved)."""
    import json as _json
    import uuid as _uuid

    # Primary: Lakebase, full + lossless.
    try:
        from db import operational as opstore
        from db.lakebase import LakebaseUnavailable
        try:
            return opstore.record_run(domain_id=domain_id, project_id=project_id,
                                      run=run, label=label)
        except LakebaseUnavailable:
            pass
    except Exception as e:  # import or unexpected error → try warehouse
        print(f"[workflow_runs] Lakebase record failed, falling back: {e}")

    # Fallback: bounded warehouse insert.
    if run_sql is None:
        return run.get("work_object_id") or ""
    steps = run.get("steps") or []
    err_count = sum(1 for s in steps if s.get("status") == "error")
    run_id = run.get("work_object_id") or f"run-{_uuid.uuid4().hex[:12]}"
    run_json = _json.dumps(_slim_run(run))
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
                current_timestamp(), true, {_lit(label)}, {_lit(run_json)}
            )
        """)
    except Exception as e:
        print(f"[workflow_runs] warehouse record failed: {e}")
    return run_id


def list_runs(run_sql: Callable[[str], Any], domain_id: str,
              project_id: Optional[str] = None, saved_only: bool = False,
              catalog: str = CATALOG_DEFAULT, limit: int = 200) -> list:
    """Run summaries for a domain, optionally filtered to one project. `saved_only`
    is retained for compatibility but is a no-op (all runs are saved)."""
    try:
        from db import operational as opstore
        from db.lakebase import LakebaseUnavailable
        try:
            return opstore.list_runs(domain_id=domain_id, project_id=project_id, limit=limit)
        except LakebaseUnavailable:
            pass
    except Exception as e:
        print(f"[workflow_runs] Lakebase list failed, falling back: {e}")

    where = f"WHERE domain_id = {_lit(domain_id)}"
    if project_id:
        where += f" AND project_id = {_lit(project_id)}"
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
    """Return the full stored run for a run_id (Lakebase primary, lossless)."""
    import json as _json
    try:
        from db import operational as opstore
        from db.lakebase import LakebaseUnavailable
        try:
            return opstore.get_run(run_id=run_id)
        except LakebaseUnavailable:
            pass
    except Exception as e:
        print(f"[workflow_runs] Lakebase get_run failed, falling back: {e}")

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
