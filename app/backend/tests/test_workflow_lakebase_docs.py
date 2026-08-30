"""Test that /workflow-run sources its doc set from Lakebase external_documents
when indexed docs exist, and falls back to the legacy parsed_documents path
when no indexed external docs are available.

All tests are offline — live Databricks is never contacted.
"""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skill_routes  # noqa: E402
from db import operational as opstore  # noqa: E402
from workflow_engine.engine import WorkflowRun  # noqa: E402


# ── capturing engine — records docs= received by engine.run() ────────────────

class CapturingEngine:
    def __init__(self, *a, **k):
        self.last_docs = None

    def run(self, template, domain, inputs, docs=None, params=None):
        self.last_docs = docs
        return WorkflowRun(
            template_id=template, template_version="1.0",
            domain=domain, status="completed",
        )


# ── common patches for the /workflow-run handler ─────────────────────────────

def _patch_common(monkeypatch, engine):
    """Patch all live-Databricks pieces in skill_routes and inject our engine."""
    monkeypatch.setattr(skill_routes, "build_live_context", lambda pid: object())
    monkeypatch.setattr(skill_routes, "Dispatcher", lambda *a, **k: object())
    monkeypatch.setattr(skill_routes, "WorkflowEngine", lambda *a, **k: engine)
    monkeypatch.setattr(skill_routes, "ensure_table", lambda *a, **k: None)

    class FakeLogger:
        def __init__(self, *a, **k): self.run_sql = lambda q: None
    monkeypatch.setattr(skill_routes, "ExecutionLogger", FakeLogger)

    fake_routes = types.ModuleType("docintel_routes")
    fake_routes.run_sql = lambda q, timeout_secs=50: []
    fake_routes.CATALOG = "test_catalog"
    fake_routes._get_domain_schemas = lambda pid: {"schema_raw": "raw_schema"}
    sys.modules["docintel_routes"] = fake_routes
    return fake_routes


# ── tests ─────────────────────────────────────────────────────────────────────

def test_workflow_run_sources_docs_from_lakebase_external_docs(monkeypatch):
    """When a project has 2 indexed external docs the engine receives docs= with
    2 entries in {doc_id, doc_type, text} shape."""
    engine = CapturingEngine()
    _patch_common(monkeypatch, engine)

    ext_docs = [
        {"external_document_id": "extdoc-a", "domain_id": "d1", "project_id": "p1",
         "mime_type": "application/pdf", "name": "report.pdf", "status": "indexed"},
        {"external_document_id": "extdoc-b", "domain_id": "d1", "project_id": "p1",
         "mime_type": "text/plain", "name": "notes.txt", "status": "indexed"},
    ]
    chunks = {
        "extdoc-a": [{"chunk_id": "c1", "ordinal": 0, "snippet": "Chunk A1"},
                     {"chunk_id": "c2", "ordinal": 1, "snippet": "Chunk A2"}],
        "extdoc-b": [{"chunk_id": "c3", "ordinal": 0, "snippet": "Chunk B1"}],
    }

    monkeypatch.setattr(skill_routes.opstore, "list_docs_for_project",
                        lambda domain_id, project_id, statuses=None: ext_docs)
    monkeypatch.setattr(skill_routes.opstore, "list_chunks_for_doc",
                        lambda eid: chunks.get(eid, []))

    req = skill_routes.WorkflowRunRequest(
        template="due_diligence", domain_id="d1", project="p1")
    result = asyncio.run(skill_routes.workflow_run(req))

    assert engine.last_docs is not None, "engine.run must receive docs="
    assert len(engine.last_docs) == 2, f"expected 2 docs, got {len(engine.last_docs)}"

    by_id = {d["doc_id"]: d for d in engine.last_docs}
    assert "extdoc-a" in by_id and "extdoc-b" in by_id

    doc_a = by_id["extdoc-a"]
    assert "doc_id" in doc_a and "doc_type" in doc_a and "text" in doc_a
    assert doc_a["doc_type"] == "application/pdf"
    assert "Chunk A1" in doc_a["text"] and "Chunk A2" in doc_a["text"]

    doc_b = by_id["extdoc-b"]
    assert "Chunk B1" in doc_b["text"]


def test_resolve_doc_set_returns_correct_shape(monkeypatch):
    """Each item from _resolve_doc_set has doc_id, doc_type, and text."""
    monkeypatch.setattr(skill_routes.opstore, "list_docs_for_project",
                        lambda domain_id, project_id, statuses=None: [
                            {"external_document_id": "doc-x", "domain_id": "d1",
                             "project_id": "p1", "mime_type": "text/html",
                             "name": "page.html", "status": "indexed"},
                        ])
    monkeypatch.setattr(skill_routes.opstore, "list_chunks_for_doc",
                        lambda eid: [{"chunk_id": "cx1", "ordinal": 0,
                                      "snippet": "Some content"}])

    result = skill_routes._resolve_doc_set("d1", "p1")
    assert len(result) == 1
    item = result[0]
    assert item["doc_id"] == "doc-x"
    assert item["doc_type"] == "text/html"
    assert "Some content" in item["text"]


def test_resolve_doc_set_falls_back_to_legacy_when_no_indexed_docs(monkeypatch):
    """When no indexed external docs exist, _resolve_doc_set falls back to the
    legacy parsed_documents path via _project_doc_ids + _fetch_doc_rows."""
    monkeypatch.setattr(skill_routes.opstore, "list_docs_for_project",
                        lambda domain_id, project_id, statuses=None: [])
    # Make doc_ids_for_project return a legacy doc_id (tags store path).
    monkeypatch.setattr(skill_routes.opstore, "doc_ids_for_project",
                        lambda domain_id, project_id: ["legacy-doc-1"])

    legacy_row = {"doc_id": "legacy-doc-1", "doc_type": "permit", "text": "legacy text"}
    fake_routes = types.ModuleType("docintel_routes_legacy")
    fake_routes.run_sql = lambda q, timeout_secs=50: [legacy_row]
    fake_routes.CATALOG = "test_catalog"
    fake_routes._get_domain_schemas = lambda pid: {"schema_raw": "raw_schema"}

    result = skill_routes._resolve_doc_set("d1", "p1", routes=fake_routes)
    assert len(result) == 1
    assert result[0]["doc_id"] == "legacy-doc-1"


def test_list_for_doc_in_chunks_repo():
    """list_for_doc queries document_chunks by external_document_id ordered by ordinal."""
    from db.repositories import chunks_repo

    _COLS = ["chunk_id", "external_document_id", "ordinal", "location", "snippet"]

    class FakeCur:
        def __init__(self):
            self.sql = []; self.params = []
        def execute(self, sql, params=None):
            self.sql.append(sql); self.params.append(params)
        def fetchall(self):
            return [("c1", "doc-x", 0, "p1", "hello world")]
        @property
        def description(self):
            return [(c,) for c in _COLS]

    class FakeConn:
        def __init__(self): self.cur = FakeCur()
        def cursor(self): return self.cur

    c = FakeConn()
    rows = chunks_repo.list_for_doc(c, "doc-x")
    sql = " ".join(c.cur.sql).lower()
    assert "document_chunks" in sql
    assert "external_document_id" in sql
    assert "order by ordinal" in sql
    assert len(rows) == 1
    assert rows[0]["snippet"] == "hello world"
    assert rows[0]["external_document_id"] == "doc-x"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except Exception as e:
            import traceback
            failed += 1; print(f"FAIL {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
