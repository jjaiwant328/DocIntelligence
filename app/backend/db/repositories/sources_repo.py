"""Sources CRUD against Lakebase. Stores connector config (no secret values —
credential_ref holds a reference such as keeper://... only)."""
from __future__ import annotations

from typing import Any, Optional


def _dicts(cur: Any) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def list_sources(conn: Any) -> list[dict]:
    """Return all sources WITHOUT credential_ref — that field must never travel
    over the wire to the frontend (it may hold a keeper:// reference)."""
    cur = conn.cursor()
    cur.execute(
        "SELECT source_id, provider, display_name, auth_mode, site, status, "
        "mode, last_crawl_at, last_error, created_at "
        "FROM sources ORDER BY created_at"
    )
    return _dicts(cur)


def get_source(conn: Any, source_id: str) -> Optional[dict]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM sources WHERE source_id=%s", (source_id,))
    rows = _dicts(cur)
    return rows[0] if rows else None


def upsert_source(
    conn: Any,
    source_id: str,
    provider: str,
    display_name: str,
    auth_mode: str,
    credential_ref: str,
    site: str,
    mode: str,
) -> dict:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO sources (source_id, provider, display_name, auth_mode,
                             credential_ref, site, mode)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (source_id) DO UPDATE SET
            provider=EXCLUDED.provider, display_name=EXCLUDED.display_name,
            auth_mode=EXCLUDED.auth_mode, credential_ref=EXCLUDED.credential_ref,
            site=EXCLUDED.site, mode=EXCLUDED.mode
        """,
        (source_id, provider, display_name, auth_mode, credential_ref, site, mode),
    )
    return get_source(conn, source_id)


def set_status(conn: Any, source_id: str, status: str, last_error: str = "") -> None:
    conn.execute(
        "UPDATE sources SET status=%s, last_error=%s WHERE source_id=%s",
        (status, last_error, source_id),
    )
