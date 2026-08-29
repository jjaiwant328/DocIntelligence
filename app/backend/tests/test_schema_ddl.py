"""Tests for the pgvector-enabled schema DDL additions (Phase 1)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.schema as schema


def test_ddl_includes_pgvector_and_new_tables():
    joined = "\n".join(schema.DDL).lower()
    assert "create extension if not exists vector" in joined
    for t in ("sources", "external_documents", "document_chunks", "index_jobs", "use_cases"):
        assert f"create table if not exists {t}" in joined
    assert "vector(1024)" in joined
    assert "tsvector" in joined
    assert "using hnsw" in joined
    assert "using gin" in joined


class _FakeConn:
    def __init__(self): self.ran = []
    def execute(self, sql): self.ran.append(sql)


def test_ensure_schema_runs_all_statements():
    c = _FakeConn()
    schema.ensure_schema(c)
    assert len(c.ran) == len(schema.DDL)
