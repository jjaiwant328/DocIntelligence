"""Tests for chunks_repo — verifies RRF hybrid search SQL structure,
replace_chunks atomicity, and folder/types filter wiring."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from db.repositories import chunks_repo


_CHUNK_COLS = [
    "chunk_id", "external_document_id", "name", "path", "web_url",
    "mime_type", "status", "ordinal", "location", "snippet", "score",
]


# ── FakeConn helpers ──────────────────────────────────────────────────────────

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


class _FakeTransaction:
    """Snapshot the SQL log on enter; restore it (simulating rollback) on exc."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        self._snap_sql = list(self._conn.cur.sql)
        self._snap_params = list(self._conn.cur.params)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            # Simulate rollback: undo all SQL issued inside this transaction
            self._conn.cur.sql[:] = self._snap_sql
            self._conn.cur.params[:] = self._snap_params
            self._conn._rolled_back = True
        return False  # never suppress the exception


class FakeConn:
    def __init__(self, rows=None):
        self.cur = FakeCur(rows or [])
        self._rolled_back = False

    def cursor(self):
        return self.cur

    def execute(self, sql, params=None):
        return self.cur.execute(sql, params)

    def transaction(self):
        return _FakeTransaction(self)


# ── existing tests (unchanged behaviour) ──────────────────────────────────────

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


# ── Fix 2: atomicity ──────────────────────────────────────────────────────────

def test_replace_chunks_rolls_back_on_insert_failure():
    """A mid-loop insert failure must not leave the doc chunk-less.

    The transaction rolls back both the DELETE and any partial inserts, so the
    pre-existing chunks are not lost.
    """
    class _FailOnSecondInsert(FakeCur):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._insert_count = 0

        def execute(self, sql, params=None):
            super().execute(sql, params)
            if "INSERT INTO document_chunks" in sql:
                self._insert_count += 1
                if self._insert_count >= 2:
                    raise RuntimeError("simulated DB error on second insert")

    c = FakeConn()
    c.cur = _FailOnSecondInsert()

    chunks = [
        {
            "chunk_id": "c1", "ordinal": 0, "location": "p1",
            "snippet": "first", "embedding": [0.1] * 1024,
            "domain_id": "d1", "project_id": "p1",
            "source_version": "v1", "index_version": 1,
        },
        {
            "chunk_id": "c2", "ordinal": 1, "location": "p2",
            "snippet": "second — this insert will fail",
            "embedding": [0.2] * 1024,
            "domain_id": "d1", "project_id": "p1",
            "source_version": "v1", "index_version": 1,
        },
    ]

    with pytest.raises(RuntimeError):
        chunks_repo.replace_chunks(c, "doc1", chunks)

    # The transaction was rolled back: DELETE and partial inserts were undone
    assert c._rolled_back is True
    delete_calls = [s for s in c.cur.sql if "delete" in s.lower()]
    assert len(delete_calls) == 0, "DELETE must have been rolled back"


# ── Fix 3: folder + types filters ─────────────────────────────────────────────

def test_hybrid_search_applies_folder_filter():
    c = FakeConn(rows=[])
    chunks_repo.hybrid_search(
        c, "d1", "p1", [0.1] * 1024, "query", k=5,
        folder="/sales/q4/",
    )
    sql = " ".join(c.cur.sql).lower()
    assert "like" in sql
    # folder% must appear in the params
    flat_params = [p for tup in c.cur.params if tup for p in tup]
    assert "/sales/q4/%" in flat_params


def test_hybrid_search_applies_types_filter():
    c = FakeConn(rows=[])
    chunks_repo.hybrid_search(
        c, "d1", "p1", [0.1] * 1024, "query", k=5,
        types=["application/pdf"],
    )
    sql = " ".join(c.cur.sql).lower()
    assert "= any(" in sql
    flat_params = [p for tup in c.cur.params if tup for p in tup]
    assert ["application/pdf"] in flat_params


def test_hybrid_search_omits_filters_when_not_provided():
    c = FakeConn(rows=[])
    chunks_repo.hybrid_search(c, "d1", "p1", [0.1] * 1024, "query")
    sql = " ".join(c.cur.sql).lower()
    assert "like" not in sql
    assert "= any(" not in sql
