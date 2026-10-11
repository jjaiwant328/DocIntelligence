"""Index-job tracking against Lakebase. Maintains queued/running/done state
and accumulates per-job counters (discovered, embedded, skipped, etc.)."""
from __future__ import annotations

from typing import Any, Optional


def _dicts(cur: Any) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def create_job(
    conn: Any,
    job_id: str,
    domain_id: str,
    project_id: str,
    scope: str,
    scope_ref: str,
    requested_by: str,
) -> dict:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO index_jobs (job_id, domain_id, project_id, scope,
                                scope_ref, requested_by, status)
        VALUES (%s,%s,%s,%s,%s,%s,'queued')
        ON CONFLICT (job_id) DO NOTHING
        """,
        (job_id, domain_id, project_id, scope, scope_ref, requested_by),
    )
    return get_job(conn, job_id)


def get_job(conn: Any, job_id: str) -> Optional[dict]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM index_jobs WHERE job_id=%s", (job_id,))
    rows = _dicts(cur)
    return rows[0] if rows else None


def list_jobs(conn: Any, domain_id: str, project_id: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM index_jobs WHERE domain_id=%s AND project_id=%s "
        "ORDER BY started_at DESC NULLS LAST",
        (domain_id, project_id),
    )
    return _dicts(cur)


def start(conn: Any, job_id: str) -> None:
    conn.execute(
        "UPDATE index_jobs SET status='running', started_at=now() "
        "WHERE job_id=%s",
        (job_id,),
    )


def bump(conn: Any, job_id: str, **counts: int) -> None:
    """Accumulate counter columns (discovered, embedded, skipped, deleted,
    failed) by the given amounts using additive SET col = col + %s."""
    _ALLOWED = {"discovered", "embedded", "skipped", "deleted", "failed"}
    sets = []
    params = []
    for col, val in counts.items():
        if col not in _ALLOWED:
            continue
        sets.append(f"{col} = {col} + %s")
        params.append(int(val))
    if not sets:
        return
    params.append(job_id)
    conn.execute(
        f"UPDATE index_jobs SET {', '.join(sets)} WHERE job_id=%s",
        tuple(params),
    )


def finish(conn: Any, job_id: str, status: str, error_summary: str = "") -> None:
    conn.execute(
        "UPDATE index_jobs SET status=%s, finished_at=now(), error_summary=%s "
        "WHERE job_id=%s",
        (status, error_summary, job_id),
    )
