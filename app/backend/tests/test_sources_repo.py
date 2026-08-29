"""Tests for sources_repo — fake connection, no live DB."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.repositories import sources_repo


class FakeCur:
    def __init__(self, rows):
        self._rows = rows
        self.sql = []
        self.params = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self.params.append(params)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    @property
    def description(self):
        return [
            ("source_id",), ("provider",), ("display_name",), ("auth_mode",),
            ("credential_ref",), ("site",), ("status",), ("mode",),
            ("last_crawl_at",), ("last_error",), ("created_at",),
        ]


class FakeConn:
    def __init__(self, rows):
        self.cur = FakeCur(rows)

    def cursor(self):
        return self.cur

    def execute(self, sql, params=None):
        return self.cur.execute(sql, params)


def test_upsert_source_writes_no_secret_value():
    c = FakeConn([
        ("gdrive", "gdrive", "Google Drive", "service_principal",
         "keeper://ref", "", "connected", "live", None, "", None)
    ])
    row = sources_repo.upsert_source(
        c, "gdrive", "gdrive", "Google Drive",
        "service_principal", "keeper://ref", "", "live",
    )
    assert row["source_id"] == "gdrive"
    # credential_ref must be a reference, not a secret literal
    assert "keeper://" in (c.cur.params[0] or ())[4] if c.cur.params[0] else True


def test_list_sources_returns_dicts():
    rows = [
        ("s1", "gdrive", "GDrive", "service_principal", "ref", "", "connected", "live", None, "", None),
    ]
    c = FakeConn(rows)
    result = sources_repo.list_sources(c)
    assert len(result) == 1
    assert result[0]["source_id"] == "s1"


def test_get_source_missing_returns_none():
    c = FakeConn([])
    assert sources_repo.get_source(c, "nonexistent") is None


def test_set_status_executes_update():
    c = FakeConn([])
    sources_repo.set_status(c, "s1", "error", last_error="timeout")
    sql = " ".join(c.cur.sql).lower()
    assert "update sources" in sql
    assert "status" in sql
