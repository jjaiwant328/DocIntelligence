import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.repositories import doc_sets_repo as r


class FakeCursor:
    def __init__(self, rows=()):
        self.queries, self.params, self._rows = [], [], list(rows)
    def execute(self, q, p=None):
        self.queries.append(q); self.params.append(p)
    def fetchall(self):
        return self._rows
    @property
    def description(self):
        cols = ["id", "domain_id", "name", "kind", "filter_json", "created_at"]
        return [(c,) for c in cols[:len(self._rows[0])]] if self._rows else []


class FakeConn:
    def __init__(self, rows=()):
        self.cur = FakeCursor(rows)
    def cursor(self):
        return self.cur


def test_create_inserts_pinned_set():
    conn = FakeConn()
    r.create(conn, "s1", "supply_chain", "Q3 suppliers", "pinned", {})
    q = conn.cur.queries[0]
    assert "INSERT INTO doc_sets" in q
    assert conn.cur.params[0][:4] == ("s1", "supply_chain", "Q3 suppliers", "pinned")


def test_pin_and_pinned_ids():
    conn = FakeConn(rows=[("d1",), ("d2",)])
    r.pin(conn, "s1", "d1")
    assert "INSERT INTO doc_set_members" in conn.cur.queries[0]
    ids = r.pinned_ids(conn, "s1")
    assert ids == ["d1", "d2"]
