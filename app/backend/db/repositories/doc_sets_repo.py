"""doc_sets + doc_set_members: pinned and query-defined document sets."""
from __future__ import annotations
import json
from typing import Any, Optional

_COLS = ["id", "domain_id", "name", "kind", "filter_json", "created_at"]


def _dicts(cur: Any) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def create(conn: Any, set_id: str, domain_id: str, name: str, kind: str, filter_json: dict) -> dict:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO doc_sets (id, domain_id, name, kind, filter_json) VALUES (%s,%s,%s,%s,%s)",
        (set_id, domain_id, name, kind, json.dumps(filter_json or {})),
    )
    return {"id": set_id, "domain_id": domain_id, "name": name, "kind": kind,
            "filter_json": filter_json or {}}


def list_for_domain(conn: Any, domain_id: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        f"SELECT {', '.join(_COLS)} FROM doc_sets WHERE domain_id=%s ORDER BY created_at",
        (domain_id,),
    )
    return _dicts(cur)


def get(conn: Any, set_id: str) -> Optional[dict]:
    cur = conn.cursor()
    cur.execute(f"SELECT {', '.join(_COLS)} FROM doc_sets WHERE id=%s", (set_id,))
    rows = _dicts(cur)
    return rows[0] if rows else None


def delete(conn: Any, set_id: str) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM doc_sets WHERE id=%s", (set_id,))


def pin(conn: Any, set_id: str, doc_id: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO doc_set_members (doc_set_id, doc_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (set_id, doc_id),
    )


def unpin(conn: Any, set_id: str, doc_id: str) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM doc_set_members WHERE doc_set_id=%s AND doc_id=%s", (set_id, doc_id))


def pinned_ids(conn: Any, set_id: str) -> list[str]:
    cur = conn.cursor()
    cur.execute("SELECT doc_id FROM doc_set_members WHERE doc_set_id=%s ORDER BY pinned_at", (set_id,))
    return [row[0] for row in cur.fetchall()]
