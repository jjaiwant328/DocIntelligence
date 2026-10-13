"""Agent grounding: doc context must come from the Lakebase hybrid search."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import docintel_routes as dr


def test_agent_doc_context_uses_lakebase(monkeypatch):
    calls = {}

    class FakeBackend:
        def search(self, domain_id, project_id, query, k=10, **kw):
            calls["args"] = (domain_id, project_id, query, k)
            return [{"external_document_id": "a.txt", "mime_type": "text/plain",
                     "snippet": "hello world", "web_url": "https://drive/x",
                     "name": "a.txt", "path": "/v/a.txt", "status": "indexed",
                     "chunk_id": "c1", "ordinal": 0, "location": "", "score": 0.9}]

    monkeypatch.setattr(dr, "_agent_search_backend", lambda: FakeBackend())
    ctx, cited = dr._agent_doc_context("invoice terms", "compliance_due_diligence")
    assert "hello world" in ctx
    assert cited == ["a.txt"]
    assert calls["args"][1] is None


def test_agent_doc_context_fails_open(monkeypatch):
    class BoomBackend:
        def search(self, *a, **k):
            raise RuntimeError("lakebase down")

    monkeypatch.setattr(dr, "_agent_search_backend", lambda: BoomBackend())
    ctx, cited = dr._agent_doc_context("q", "supply_chain")
    assert ctx == "" and cited == []
