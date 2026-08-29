"""Tests for chunks_repo — verifies RRF hybrid search SQL structure."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.repositories import chunks_repo


_CHUNK_COLS = [
    "chunk_id", "external_document_id", "name", "path", "web_url",
    "mime_type", "status", "ordinal", "location", "snippet", "score",
]


class FakeCur:
    def __init__(self, rows=None):
        self._rows = rows or []
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
        return [(c,) for c in _CHUNK_COLS]


class FakeConn:
    def __init__(self, rows=None):
        self.cur = FakeCur(rows or [])

    def cursor(self):
        return self.cur

    def execute(self, sql, params=None):
        return self.cur.execute(sql, params)


def test_hybrid_search_uses_vector_and_fts_and_project_filter():
    c = FakeConn(rows=[])
    chunks_repo.hybrid_search(
        c, "supplier_performance", "p1",
        [0.1] * 1024, "late delivery", k=5,
    )
    sql = " ".join(c.cur.sql).lower()
    assert "<=>" in sql and "plainto_tsquery" in sql
    assert "project_id" in sql


def test_hybrid_search_passes_vector_as_literal():
    c = FakeConn(rows=[])
    chunks_repo.hybrid_search(c, "d1", "p1", [0.5] * 1024, "query", k=3)
    # params tuple should contain the vector literal string
    params = c.cur.params[0]
    assert params is not None
    vec_params = [p for p in params if isinstance(p, str) and p.startswith("[")]
    assert len(vec_params) >= 1
    assert "0.500000" in vec_params[0]


def test_replace_chunks_deletes_then_inserts():
    c = FakeConn()
    chunks = [
        {
            "chunk_id": "c1", "ordinal": 0, "location": "p1",
            "snippet": "hello world", "embedding": [0.1] * 1024,
            "domain_id": "d1", "project_id": "proj1",
            "source_version": "v1", "index_version": 1,
        }
    ]
    n = chunks_repo.replace_chunks(c, "doc1", chunks)
    sql = " ".join(c.cur.sql).lower()
    assert "delete from document_chunks" in sql
    assert "insert into document_chunks" in sql
    assert n == 1


def test_delete_for_doc_returns_rowcount():
    c = FakeConn()
    c.cur._rows = []
    chunks_repo.delete_for_doc(c, "doc1")
    sql = " ".join(c.cur.sql).lower()
    assert "delete from document_chunks" in sql
