"""Document ↔ project tag CRUD against Lakebase. Idempotent via ON CONFLICT
(the Lakehouse path used delete-then-insert to avoid duplicate rows)."""
from __future__ import annotations

from typing import Any


def add_tag(
    conn: Any,
    *,
    domain_id: str,
    project_id: str,
    doc_id: str,
    tagged_by: str = "app_user",
) -> None:
    conn.execute(
        """
        INSERT INTO document_project_tags
          (domain_id, doc_id, project_id, scope, source, tagged_by, tagged_at)
        VALUES (%s, %s, %s, 'project', 'manual', %s, now())
        ON CONFLICT (domain_id, project_id, doc_id) DO NOTHING
        """,
        (domain_id, doc_id, project_id, tagged_by),
    )


def remove_tag(conn: Any, *, domain_id: str, project_id: str, doc_id: str) -> None:
    conn.execute(
        "DELETE FROM document_project_tags "
        "WHERE domain_id = %s AND project_id = %s AND doc_id = %s",
        (domain_id, project_id, doc_id),
    )


def doc_ids_for_project(conn: Any, *, domain_id: str, project_id: str) -> list[str]:
    cur = conn.execute(
        "SELECT doc_id FROM document_project_tags "
        "WHERE domain_id = %s AND project_id = %s ORDER BY tagged_at DESC",
        (domain_id, project_id),
    )
    return [r[0] for r in cur.fetchall()]
