"""SQL-shape tests for chunks_repo.hybrid_search project-optional filtering."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.repositories import chunks_repo


class FakeCursor:
    def __init__(self):
        self.sql, self.params = "", ()

    def execute(self, q, p=None):
        self.sql, self.params = q, p

    def fetchall(self):
        return []

    @property
    def description(self):
        return []


class FakeConn:
    def __init__(self):
        self.cur = FakeCursor()

    def cursor(self):
        return self.cur


def test_hybrid_search_without_project_omits_project_filter():
    conn = FakeConn()
    chunks_repo.hybrid_search(conn, "supply_chain", None, [0.1] * 1024, "invoice", k=3)
    assert "project_id=%s" not in conn.cur.sql
    assert "domain_id=%s" in conn.cur.sql


def test_hybrid_search_with_project_keeps_filter():
    conn = FakeConn()
    chunks_repo.hybrid_search(conn, "supply_chain", "default", [0.1] * 1024, "invoice", k=3)
    assert conn.cur.sql.count("project_id=%s") == 2  # vec + kw CTEs
