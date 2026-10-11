"""Connectors CRUD against Lakebase.

Stores OAuth connector config. The client_secret is NEVER a column — only
`secret_ref` (a pointer like `docintel_connectors/gdrive_client_secret`) is
persisted here. All secret writes go through secret_store.py.
"""
from __future__ import annotations

import json
from typing import Any, Optional


def _dicts(cur: Any) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def list_connectors(conn: Any) -> list[dict]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM connectors ORDER BY provider")
    return _dicts(cur)


def get_connector(conn: Any, provider: str) -> Optional[dict]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM connectors WHERE provider=%s", (provider,))
    rows = _dicts(cur)
    return rows[0] if rows else None


def upsert_connector(
    conn: Any,
    provider: str,
    display_name: str,
    client_id: str,
    redirect_uri: str,
    scopes: list,
    secret_ref: str,
    status: str,
    updated_by: str,
) -> dict:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO connectors
            (provider, display_name, client_id, redirect_uri, scopes,
             secret_ref, status, updated_by, updated_at)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, now())
        ON CONFLICT (provider) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            client_id    = EXCLUDED.client_id,
            redirect_uri = EXCLUDED.redirect_uri,
            scopes       = EXCLUDED.scopes,
            secret_ref   = EXCLUDED.secret_ref,
            status       = EXCLUDED.status,
            updated_by   = EXCLUDED.updated_by,
            updated_at   = now()
        """,
        (provider, display_name, client_id, redirect_uri,
         json.dumps(scopes), secret_ref, status, updated_by),
    )
    return get_connector(conn, provider)


def set_status(conn: Any, provider: str, status: str) -> None:
    conn.execute(
        "UPDATE connectors SET status=%s, updated_at=now() WHERE provider=%s",
        (status, provider),
    )


def delete_connector(conn: Any, provider: str) -> None:
    conn.execute("DELETE FROM connectors WHERE provider=%s", (provider,))
