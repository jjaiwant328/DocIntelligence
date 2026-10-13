import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.repositories import extracted_fields_repo as r


class FakeCursor:
    def __init__(self, rows=()):
        self.queries, self.params, self._rows = [], [], list(rows)
    def execute(self, q, p=None):
        self.queries.append(q); self.params.append(p)
    def fetchall(self):
        return self._rows
    @property
    def description(self):
        cols = ["field_name", "field_value", "page", "bbox", "source_text", "confidence"]
        return [(c,) for c in cols]


class FakeConn:
    def __init__(self, rows=()):
        self.cur = FakeCursor(rows)
    def cursor(self):
        return self.cur


def test_replace_for_doc_deletes_then_inserts():
    conn = FakeConn()
    n = r.replace_for_doc(conn, "doc1", [
        {"field_name": "total", "field_value": "$1,100", "page": 1,
         "bbox": [0.1, 0.2, 0.3, 0.4], "source_text": "Total: $1,100"},
    ])
    assert n == 1
    assert "DELETE FROM extracted_fields" in conn.cur.queries[0]
    assert "INSERT INTO extracted_fields" in conn.cur.queries[1]


def test_list_for_doc_maps_rows():
    conn = FakeConn(rows=[("total", "$1,100", 1, [0.1]*4, "Total: $1,100", 0.9)])
    out = r.list_for_doc(conn, "doc1")
    assert out[0]["field_name"] == "total"
    assert out[0]["confidence"] == 0.9
