"""Warehouse-independent tests for the additive thin-spine routes."""
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import spine_routes as s


def test_domain_schema_mapping():
    assert s._schema("supply_chain") == "template"
    assert s._schema("compliance_due_diligence") == "template_cdd"


def test_unknown_domain_raises_404():
    with pytest.raises(HTTPException) as ei:
        s._schema("does_not_exist")
    assert ei.value.status_code == 404


def test_sql_escaping():
    assert s._esc("O'Brien") == "O''Brien"


def test_list_domains_shape():
    out = s.list_spine_domains()
    ids = {d["domain_id"] for d in out["domains"]}
    assert {"supply_chain", "compliance_due_diligence"} <= ids


def test_search_uses_lakebase_backend(monkeypatch):
    hits = [{"chunk_id": "c1", "external_document_id": "a.txt", "name": "a.txt",
             "path": "/v/a.txt", "web_url": "https://drive/x", "mime_type": "text/plain",
             "status": "indexed", "ordinal": 0, "location": "", "snippet": "hello",
             "score": 0.5}]

    class FakeBackend:
        def search(self, domain_id, project_id, query, k=10, folder="", types=None):
            assert project_id is None
            return hits

    monkeypatch.setattr(s, "_backend", lambda: FakeBackend())
    monkeypatch.setattr(s, "_rerank", lambda q, rows: rows)
    out = s.search(s.SearchRequest(question="q", domain_id="supply_chain", k=3))
    r = out["results"][0]
    assert r["doc_id"] == "a.txt"
    assert r["chunk_to_retrieve"] == "hello"
    assert r["source"] == {"provider": "lakebase", "url": "https://drive/x"}


def test_search_empty_corpus_returns_empty(monkeypatch):
    class FakeBackend:
        def search(self, *a, **k):
            return []

    monkeypatch.setattr(s, "_backend", lambda: FakeBackend())
    monkeypatch.setattr(s, "_rerank", lambda q, rows: rows)
    out = s.search(s.SearchRequest(question="q", domain_id="supply_chain", k=3))
    assert out["results"] == []


def test_search_rerank_widens_candidate_limit(monkeypatch):
    """With rerank on, the backend pulls 2k candidates (capped) for the judge."""
    captured = {}

    class FakeBackend:
        def search(self, domain_id, project_id, query, k=10, folder="", types=None):
            captured["k"] = k
            return []

    monkeypatch.setattr(s, "_backend", lambda: FakeBackend())
    monkeypatch.setattr(s, "_rerank", lambda q, rows: rows)
    out = s.search(s.SearchRequest(question="temp excursion", domain_id="supply_chain", k=3))
    assert captured["k"] == 6
    assert out["results"] == []


def test_rerank_orders_by_judge_score(monkeypatch):
    rows = [
        {"doc_id": "a", "chunk_to_retrieve": "alpha"},
        {"doc_id": "b", "chunk_to_retrieve": "beta"},
    ]

    class FakeJudge:
        scores = {"alpha": 0.1, "beta": 0.9}

        @classmethod
        def from_workspace(cls, w):
            return cls()

        def relevance(self, question, chunk):
            return self.scores[chunk]

    monkeypatch.setitem(sys.modules, "judge", type(sys)("judge"))
    sys.modules["judge"].JudgeClient = FakeJudge
    out = s._rerank("q", rows)
    assert [r["doc_id"] for r in out] == ["b", "a"]
    assert out[0]["judge_score"] == 0.9


def test_rerank_fails_open(monkeypatch):
    rows = [{"doc_id": "a", "chunk_to_retrieve": "alpha"}]

    class BoomJudge:
        @classmethod
        def from_workspace(cls, w):
            raise RuntimeError("judge down")

    monkeypatch.setitem(sys.modules, "judge", type(sys)("judge"))
    sys.modules["judge"].JudgeClient = BoomJudge
    assert s._rerank("q", rows) == rows
