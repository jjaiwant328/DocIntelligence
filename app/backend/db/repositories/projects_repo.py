"""Projects CRUD against Lakebase. Returns dicts shaped like the existing
`platform.projects` rows so route code is a near drop-in. Parameterized queries
throughout (the Lakehouse path built raw f-string SQL)."""
from __future__ import annotations

import json
from typing import Any, Optional


def _row_to_project(row: tuple, cols: list[str]) -> dict:
    d = dict(zip(cols, row))
    collab = d.get("collaborators")
    if isinstance(collab, str):
        try:
            collab = json.loads(collab)
        except Exception:
            collab = []
    d["collaborators"] = collab or []
    d["owner"] = d.get("owner") or ""
    return d


def list_projects(conn: Any, domain_id: str) -> list[dict]:
    cols = ["project_id", "name", "municipality", "state", "status", "owner", "collaborators"]
    cur = conn.execute(
        f"SELECT {', '.join(cols)} FROM projects "
        "WHERE domain_id = %s AND status <> '__marker__' "
        "ORDER BY updated_at DESC NULLS LAST",
        (domain_id,),
    )
    return [_row_to_project(r, cols) for r in cur.fetchall()]


def name_exists(conn: Any, domain_id: str, name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM projects WHERE domain_id = %s AND status <> '__marker__' "
        "AND lower(trim(name)) = lower(%s) LIMIT 1",
        (domain_id, name.strip()),
    )
    return cur.fetchone() is not None


def create_project(
    conn: Any,
    *,
    domain_id: str,
    project_id: str,
    name: str,
    municipality: str = "",
    state: str = "",
    owner: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO projects
          (project_id, domain_id, name, municipality, state, address, parcel_id,
           status, created_by, created_at, updated_at, owner, collaborators)
        VALUES (%s, %s, %s, %s, %s, '', '', 'Active', %s, now(), now(), %s, '[]'::jsonb)
        ON CONFLICT (domain_id, project_id) DO NOTHING
        """,
        (project_id, domain_id, name, municipality, state, owner, owner),
    )


def update_members(
    conn: Any,
    *,
    domain_id: str,
    project_id: str,
    owner: Optional[str] = None,
    collaborators: Optional[list] = None,
) -> None:
    sets = ["updated_at = now()"]
    params: list[Any] = []
    if owner is not None:
        sets.append("owner = %s")
        params.append(owner)
    if collaborators is not None:
        clean = [str(c).strip() for c in collaborators if str(c).strip()]
        sets.append("collaborators = %s::jsonb")
        params.append(json.dumps(clean))
    params.extend([domain_id, project_id])
    conn.execute(
        f"UPDATE projects SET {', '.join(sets)} WHERE domain_id = %s AND project_id = %s",
        tuple(params),
    )


def delete_project(conn: Any, *, domain_id: str, project_id: str) -> None:
    """Delete a project and cascade its document tags."""
    conn.execute(
        "DELETE FROM projects WHERE domain_id = %s AND project_id = %s",
        (domain_id, project_id),
    )
    conn.execute(
        "DELETE FROM document_project_tags WHERE domain_id = %s AND project_id = %s",
        (domain_id, project_id),
    )
