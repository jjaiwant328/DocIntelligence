"""Tests for external_docs_repo — fake connection, no live DB."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.repositories import external_docs_repo as r


# ── stable_doc_id ─────────────────────────────────────────────────────────────

def test_stable_doc_id_is_deterministic_and_distinct():
    a = r.stable_doc_id("gdrive", "", "d1", "item1")
    b = r.stable_doc_id("gdrive", "", "d1", "item1")
    c = r.stable_doc_id("gdrive", "", "d1", "item2")
    assert a == b and a != c and len(a) == 40


def test_stable_doc_id_is_order_sensitive():
    x = r.stable_doc_id("gdrive", "site1", "d1", "item1")
    y = r.stable_doc_id("item1", "d1", "site1", "gdrive")
    assert x != y


# ── FakeConn helpers ──────────────────────────────────────────────────────────

_DOC_COLS = [
    "external_document_id", "source_id", "domain_id", "project_id",
    "parent_folder_id", "path", "name", "mime_type", "size_bytes",
    "web_url", "etag", "content_hash", "owner",
    "source_created_at", "source_modified_at",
    "status", "included", "index_version", "embedding_model",
    "last_indexed_etag", "chunk_count", "last_error", "updated_at",
]


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
        return [(c,) for c in _DOC_COLS]


class FakeConn:
    def __init__(self, rows=None):
        self.cur = FakeCur(rows or [])

    def cursor(self):
        return self.cur

    def execute(self, sql, params=None):
        return self.cur.execute(sql, params)


# ── tests ─────────────────────────────────────────────────────────────────────

def test_upsert_metadata_executes_insert():
    c = FakeConn()
    r.upsert_metadata(c, {
        "external_document_id": "doc1",
        "source_id": "src1",
        "domain_id": "d1",
        "project_id": "p1",
        "name": "file.pdf",
    })
    sql = " ".join(c.cur.sql).lower()
    assert "insert into external_documents" in sql
    assert "on conflict" in sql


def test_list_for_project_filters_by_domain_project():
    row = tuple(["doc1"] + ["x"] * (len(_DOC_COLS) - 1))
    c = FakeConn([row])
    results = r.list_for_project(c, "d1", "p1")
    assert len(results) == 1
    sql = " ".join(c.cur.sql).lower()
    assert "domain_id" in sql and "project_id" in sql


def test_set_status_executes_update():
    c = FakeConn()
    r.set_status(c, "doc1", "indexed")
    sql = " ".join(c.cur.sql).lower()
    assert "update external_documents" in sql


def test_mark_indexed_executes_update():
    c = FakeConn()
    r.mark_indexed(c, "doc1", index_version=2, embedding_model="e5",
                   etag="abc", chunk_count=5)
    sql = " ".join(c.cur.sql).lower()
    assert "update external_documents" in sql
    assert "chunk_count" in sql


def test_ids_missing_from_returns_ids_not_in_seen():
    # Simulate DB returning doc1 and doc2; seen only has doc1 → doc2 is missing
    c = FakeConn([("doc1",), ("doc2",)])
    # Override description for this specific cursor
    c.cur._rows = [("doc1",), ("doc2",)]

    class _IDCur(FakeCur):
        @property
        def description(self):
            return [("external_document_id",)]

    c.cur = _IDCur([("doc1",), ("doc2",)])
    missing = r.ids_missing_from(c, "d1", "p1", seen_ids={"doc1"})
    assert "doc2" in missing
    assert "doc1" not in missing
