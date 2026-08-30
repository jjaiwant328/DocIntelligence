"""Tests for connectors_repo — fake connection, no live DB."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.schema as schema
from db.repositories import connectors_repo


# ── DDL assertions ─────────────────────────────────────────────────────────────

def test_ddl_has_connectors_no_secret_column():
    j = "\n".join(schema.DDL).lower()
    assert "create table if not exists connectors" in j
    assert "secret_ref" in j
    assert "client_secret" not in j   # secret never in the table


# ── Fake plumbing ──────────────────────────────────────────────────────────────

_COLS = [
    "provider", "display_name", "client_id", "redirect_uri",
    "scopes", "secret_ref", "status", "updated_by", "updated_at",
]


class FakeCur:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.sql: list = []
        self.params: list = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self.params.append(params)
        return self

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    @property
    def description(self):
        return [(c,) for c in _COLS]


class FakeConn:
    def __init__(self, rows=None):
        self.cur = FakeCur(rows)

    def cursor(self):
        return self.cur

    def execute(self, sql, params=None):
        return self.cur.execute(sql, params)


def _row(provider="gdrive", scopes=None):
    return (
        provider, "Google Drive", "client123", "https://example.com/callback",
        json.dumps(scopes or ["email"]),
        "docintel_connectors/gdrive_client_secret", "configured", "admin", None,
    )


# ── Repo tests ─────────────────────────────────────────────────────────────────

def test_upsert_stores_secret_ref_not_secret():
    c = FakeConn([_row()])
    result = connectors_repo.upsert_connector(
        c, "gdrive", "Google Drive", "client123",
        "https://example.com/callback", ["email"],
        "docintel_connectors/gdrive_client_secret", "configured", "admin",
    )
    assert result["provider"] == "gdrive"
    assert result["secret_ref"] == "docintel_connectors/gdrive_client_secret"


def test_upsert_no_client_secret_column_in_sql():
    c = FakeConn([_row()])
    connectors_repo.upsert_connector(
        c, "gdrive", "Google Drive", "client123",
        "https://x.com/cb", ["email"],
        "docintel_connectors/gdrive_client_secret", "configured", "admin",
    )
    sql_lower = " ".join(c.cur.sql).lower()
    assert "client_secret" not in sql_lower


def test_scopes_json_roundtrip():
    scopes = ["https://www.googleapis.com/auth/drive", "openid"]
    c = FakeConn([_row(scopes=scopes)])
    result = connectors_repo.upsert_connector(
        c, "gdrive", "Google Drive", "client123",
        "https://x.com/cb", scopes,
        "docintel_connectors/gdrive_client_secret", "configured", "admin",
    )
    # scopes column may be a list (psycopg JSONB) or JSON string (fake)
    got = result["scopes"]
    if isinstance(got, str):
        got = json.loads(got)
    assert got == scopes


def test_list_connectors_returns_dicts():
    rows = [_row("gdrive"), _row("sharepoint")]
    c = FakeConn(rows)
    result = connectors_repo.list_connectors(c)
    assert len(result) == 2
    assert result[0]["provider"] == "gdrive"


def test_get_connector_returns_none_when_missing():
    c = FakeConn([])
    assert connectors_repo.get_connector(c, "nonexistent") is None


def test_set_status_executes_update():
    c = FakeConn([])
    connectors_repo.set_status(c, "gdrive", "error")
    sql = " ".join(c.cur.sql).lower()
    assert "update connectors" in sql
    assert "status" in sql


def test_delete_connector_executes_delete():
    c = FakeConn([])
    connectors_repo.delete_connector(c, "gdrive")
    sql = " ".join(c.cur.sql).lower()
    assert "delete" in sql
    assert "connectors" in sql
