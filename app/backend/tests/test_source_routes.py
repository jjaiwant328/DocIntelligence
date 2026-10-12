"""Tests for /api/sources and /api/inventory routes.

All live dependencies (opstore, crawl_source) are monkeypatched so no
Lakebase or MCP server is needed.
"""
import asyncio
import os
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mcp_sources as _mcp_module
import source_routes
from db.repositories import external_docs_repo as _ext_repo
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client():
    app = FastAPI()
    app.include_router(source_routes.router)
    return TestClient(app, raise_server_exceptions=True)


# ── POST /api/sources — credential_ref validation ─────────────────────────────

def test_post_sources_rejects_raw_secret(monkeypatch):
    """A non-empty credential_ref that is not a reference form must return 400."""
    monkeypatch.setattr(source_routes.opstore, "upsert_source",
                        lambda *a, **k: {"source_id": "gdrive"})
    client = _make_client()
    resp = client.post("/api/sources", json={
        "source_id": "gdrive",
        "provider": "gdrive",
        "display_name": "My Drive",
        "credential_ref": "hunter2",        # raw secret — must be rejected
    })
    assert resp.status_code == 400
    detail = resp.json()["detail"].lower()
    assert "secret" in detail or "reference" in detail


def test_post_sources_rejects_non_keeper_nonempty_cred(monkeypatch):
    monkeypatch.setattr(source_routes.opstore, "upsert_source",
                        lambda *a, **k: {"source_id": "s"})
    client = _make_client()
    resp = client.post("/api/sources", json={
        "source_id": "s", "provider": "gdrive", "display_name": "X",
        "credential_ref": "plain_token_value",
    })
    assert resp.status_code == 400


def test_post_sources_accepts_keeper_reference(monkeypatch):
    monkeypatch.setattr(source_routes.opstore, "upsert_source",
                        lambda *a, **k: {"source_id": "gdrive"})
    client = _make_client()
    resp = client.post("/api/sources", json={
        "source_id": "gdrive",
        "provider": "gdrive",
        "display_name": "My Drive",
        "credential_ref": "keeper://path/to/oauth_token",
    })
    assert resp.status_code == 200
    assert resp.json()["source"]["source_id"] == "gdrive"


def test_post_sources_accepts_empty_credential_ref(monkeypatch):
    monkeypatch.setattr(source_routes.opstore, "upsert_source",
                        lambda *a, **k: {"source_id": "gdrive"})
    client = _make_client()
    resp = client.post("/api/sources", json={
        "source_id": "gdrive",
        "provider": "gdrive",
        "display_name": "My Drive",
        "credential_ref": "",
    })
    assert resp.status_code == 200


def test_post_sources_accepts_missing_credential_ref(monkeypatch):
    """credential_ref is optional; omitting it is the same as empty."""
    monkeypatch.setattr(source_routes.opstore, "upsert_source",
                        lambda *a, **k: {"source_id": "gdrive"})
    client = _make_client()
    resp = client.post("/api/sources", json={
        "source_id": "gdrive",
        "provider": "gdrive",
        "display_name": "My Drive",
    })
    assert resp.status_code == 200


# ── GET /api/sources ──────────────────────────────────────────────────────────

def test_get_sources_returns_list(monkeypatch):
    monkeypatch.setattr(source_routes.opstore, "list_sources",
                        lambda: [{"source_id": "gdrive", "provider": "gdrive"}])
    client = _make_client()
    resp = client.get("/api/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    assert data["sources"][0]["source_id"] == "gdrive"


def test_get_sources_returns_empty_list(monkeypatch):
    monkeypatch.setattr(source_routes.opstore, "list_sources", lambda: [])
    client = _make_client()
    resp = client.get("/api/sources")
    assert resp.status_code == 200
    assert resp.json()["sources"] == []


# ── GET /api/sources/{id}/auth-url ────────────────────────────────────────────

def test_get_auth_url_delegates_to_mcp_sources(monkeypatch):
    monkeypatch.setattr(source_routes.opstore, "get_source",
                        lambda sid: {"source_id": sid, "provider": "gdrive"})
    monkeypatch.setattr(source_routes.mcp_sources, "auth_url",
                        lambda source: f"https://example.com/auth/{source}")
    client = _make_client()
    resp = client.get("/api/sources/gdrive/auth-url")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://example.com/auth/gdrive"


def test_get_auth_url_rejects_managed_source(monkeypatch):
    """gdrive_managed authenticates OBO at crawl time — no OAuth URL exists."""
    monkeypatch.setattr(source_routes.opstore, "get_source",
                        lambda sid: {"source_id": sid, "provider": "gdrive_managed"})
    def _boom(source):
        raise AssertionError("must not forward managed sources to the MCP server")
    monkeypatch.setattr(source_routes.mcp_sources, "auth_url", _boom)
    client = _make_client()
    resp = client.get("/api/sources/gdrive_managed/auth-url")
    assert resp.status_code == 400
    assert "Connect & Crawl" in resp.json()["detail"]


# ── POST /api/sources/{id}/crawl ──────────────────────────────────────────────

def test_post_crawl_returns_counts(monkeypatch):
    """High-level contract test: checks response shape when crawl is mocked."""
    async def _fake_crawl(**kwargs):
        return {"discovered": 5, "folders": 2, "seen_ids": {"a", "b", "c", "d", "e"}}

    # The route now looks up the source and opens a connection before calling
    # _crawl_source; both must be mocked so the test stays fully offline.
    monkeypatch.setattr(source_routes.opstore, "get_source",
                        lambda sid: {"source_id": sid, "provider": "gdrive",
                                     "display_name": "Drive", "auth_mode": "",
                                     "credential_ref": "", "site": "", "mode": "live"})

    @contextmanager
    def _fake_connection():
        yield object()

    monkeypatch.setattr(source_routes.lakebase, "connection", _fake_connection)
    monkeypatch.setattr(source_routes, "_crawl_source", _fake_crawl)

    client = _make_client()
    resp = client.post("/api/sources/gdrive/crawl", json={
        "domain_id": "d1",
        "project_id": "p1",
        "root_folder": "",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["discovered"] == 5
    assert data["folders"] == 2
    assert data["source_id"] == "gdrive"
    assert len(data["seen_ids"]) == 5


# ── GET /api/inventory ────────────────────────────────────────────────────────

def test_get_inventory_returns_documents(monkeypatch):
    docs = [
        {"external_document_id": "doc1", "name": "report.pdf", "status": "discovered"},
        {"external_document_id": "doc2", "name": "plan.pdf", "status": "indexed"},
    ]
    monkeypatch.setattr(source_routes.opstore, "list_docs_for_project",
                        lambda *a, **k: docs)
    client = _make_client()
    resp = client.get("/api/inventory?domain_id=d1&project_id=p1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["domain_id"] == "d1"
    assert data["project_id"] == "p1"
    assert data["documents"][0]["external_document_id"] == "doc1"


def test_get_inventory_includes_status_counts(monkeypatch):
    docs = [
        {"external_document_id": "a", "status": "discovered"},
        {"external_document_id": "b", "status": "indexed"},
        {"external_document_id": "c", "status": "indexed"},
    ]
    monkeypatch.setattr(source_routes.opstore, "list_docs_for_project",
                        lambda *a, **k: docs)
    client = _make_client()
    resp = client.get("/api/inventory?domain_id=d1&project_id=p1")
    counts = resp.json()["status_counts"]
    assert counts["discovered"] == 1
    assert counts["indexed"] == 2


def test_get_inventory_empty(monkeypatch):
    monkeypatch.setattr(source_routes.opstore, "list_docs_for_project",
                        lambda *a, **k: [])
    client = _make_client()
    resp = client.get("/api/inventory?domain_id=d1&project_id=p1")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ── POST /api/sources/{id}/crawl — lower-seam tests ──────────────────────────

def test_crawl_route_404_when_source_not_registered(monkeypatch):
    """Route must return 404 when source_id is not in the operational store."""
    monkeypatch.setattr(source_routes.opstore, "get_source", lambda sid: None)
    client = _make_client()
    resp = client.post("/api/sources/unknown/crawl",
                       json={"domain_id": "d1", "project_id": "p1"})
    assert resp.status_code == 404


def test_crawl_route_uses_registered_provider_not_source_id(monkeypatch):
    """Route must look up source.provider from opstore; source_id ≠ provider
    must never corrupt stable_doc_id by using source_id as the provider."""
    _SENTINEL_CONN = object()

    @contextmanager
    def _fake_connection():
        yield _SENTINEL_CONN

    monkeypatch.setattr(source_routes.lakebase, "connection", _fake_connection)
    monkeypatch.setattr(
        source_routes.opstore, "get_source",
        lambda sid: {"source_id": "my-drive", "provider": "gdrive",
                     "display_name": "Work Drive", "auth_mode": "",
                     "credential_ref": "", "site": "", "mode": "live"},
    )

    # list_children returns one file at the root, no subfolders.
    async def _fake_list_children(source, folder_id=""):
        return [{"item_id": "file1", "name": "doc.pdf", "is_folder": False,
                 "path": "/doc.pdf", "mime_type": "application/pdf",
                 "size": 100, "web_url": "http://x", "etag": "e1",
                 "modified_at": None, "owner": ""}]

    monkeypatch.setattr(_mcp_module, "list_children", _fake_list_children)

    # Capture what provider crawl_source passed to stable_doc_id.
    providers_seen: list[str] = []
    _orig_stable = _ext_repo.stable_doc_id

    def _recording_stable(provider, site, drive, item_id):
        providers_seen.append(provider)
        return _orig_stable(provider, site, drive, item_id)

    monkeypatch.setattr(_ext_repo, "stable_doc_id", _recording_stable)

    upserted: list[dict] = []
    monkeypatch.setattr(_ext_repo, "upsert_metadata",
                        lambda conn, doc: upserted.append(doc))

    client = _make_client()
    resp = client.post("/api/sources/my-drive/crawl",
                       json={"domain_id": "d1", "project_id": "p1", "root_folder": ""})

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source_id"] == "my-drive"
    assert data["discovered"] == 1
    assert len(upserted) == 1
    # The provider forwarded to stable_doc_id must be the registered one.
    assert providers_seen == ["gdrive"], (
        f"stable_doc_id was called with provider={providers_seen!r}; "
        "expected ['gdrive'] (the registered provider, not source_id)"
    )


# ── POST /api/index-jobs ──────────────────────────────────────────────────────

def test_post_index_jobs_returns_job_id(monkeypatch):
    """POST /api/index-jobs must create a job row and return {job_id}."""
    monkeypatch.setattr(source_routes.opstore, "create_index_job",
                        lambda *a, **k: None)

    # Monkeypatch the background task executor so it doesn't hit Lakebase
    bg_calls: list[dict] = []

    def _fake_bg_task(*args, **kwargs):
        bg_calls.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(source_routes, "_run_index_job_task", _fake_bg_task)
    # Also stub the source lookup used by the route
    monkeypatch.setattr(source_routes.opstore, "get_source",
                        lambda sid: {"source_id": sid, "provider": "gdrive",
                                     "display_name": "Drive", "auth_mode": "",
                                     "credential_ref": "", "site": "", "mode": "live"})

    client = _make_client()
    resp = client.post("/api/index-jobs", json={
        "source_id": "gdrive",
        "domain_id": "d1",
        "project_id": "p1",
        "scope": "project",
        "scope_ref": "",
    })
    assert resp.status_code == 200
    data = resp.json()
    # Route generates a UUID job_id; just assert it is present and non-empty
    assert "job_id" in data
    assert data["job_id"]  # non-empty string


def test_post_index_jobs_enqueues_background_task(monkeypatch):
    """The background task must be enqueued (called) after the response."""
    job_row = {"job_id": "job-bg-1", "status": "queued"}
    monkeypatch.setattr(source_routes.opstore, "create_index_job",
                        lambda *a, **k: job_row)
    monkeypatch.setattr(source_routes.opstore, "get_source",
                        lambda sid: {"source_id": sid, "provider": "gdrive",
                                     "display_name": "Drive", "auth_mode": "",
                                     "credential_ref": "", "site": "", "mode": "live"})

    bg_calls: list[dict] = []

    def _fake_bg_task(*args, **kwargs):
        bg_calls.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(source_routes, "_run_index_job_task", _fake_bg_task)

    client = _make_client()
    client.post("/api/index-jobs", json={
        "source_id": "gdrive",
        "domain_id": "d1",
        "project_id": "p1",
        "scope": "project",
        "scope_ref": "",
    })
    # Background task runs synchronously in TestClient
    assert len(bg_calls) == 1


def test_post_index_jobs_404_when_source_not_found(monkeypatch):
    """Must return 404 if source_id not registered."""
    monkeypatch.setattr(source_routes.opstore, "get_source", lambda sid: None)
    client = _make_client()
    resp = client.post("/api/index-jobs", json={
        "source_id": "missing",
        "domain_id": "d1",
        "project_id": "p1",
        "scope": "project",
        "scope_ref": "",
    })
    assert resp.status_code == 404


# ── GET /api/index-jobs/{job_id} ──────────────────────────────────────────────

def test_get_index_job_returns_job_row(monkeypatch):
    job = {"job_id": "j1", "status": "running", "embedded": 3}
    monkeypatch.setattr(source_routes.opstore, "get_index_job",
                        lambda jid: job)
    client = _make_client()
    resp = client.get("/api/index-jobs/j1")
    assert resp.status_code == 200
    assert resp.json()["job"]["job_id"] == "j1"


def test_get_index_job_404_when_not_found(monkeypatch):
    monkeypatch.setattr(source_routes.opstore, "get_index_job", lambda jid: None)
    client = _make_client()
    resp = client.get("/api/index-jobs/missing")
    assert resp.status_code == 404


# ── GET /api/index-jobs ───────────────────────────────────────────────────────

def test_list_index_jobs_returns_list(monkeypatch):
    jobs = [{"job_id": "j1"}, {"job_id": "j2"}]
    monkeypatch.setattr(source_routes.opstore, "list_index_jobs",
                        lambda d, p: jobs)
    client = _make_client()
    resp = client.get("/api/index-jobs?domain_id=d1&project_id=p1")
    assert resp.status_code == 200
    assert len(resp.json()["jobs"]) == 2


# ── POST /api/search ──────────────────────────────────────────────────────────

def test_post_search_returns_results(monkeypatch):
    results = [{"chunk_id": "c1", "snippet": "hello", "score": 0.9}]
    monkeypatch.setattr(source_routes, "_search_backend",
                        lambda: type("B", (), {"search": staticmethod(
                            lambda *a, **k: results
                        )})())
    client = _make_client()
    resp = client.post("/api/search", json={
        "domain_id": "d1",
        "project_id": "p1",
        "query": "hello world",
    })
    assert resp.status_code == 200
    assert resp.json()["results"] == results


# ── PATCH /api/documents/{external_document_id}/included ─────────────────────

def test_patch_included_calls_set_doc_included(monkeypatch):
    """PATCH must delegate to opstore.set_doc_included with the correct args."""
    calls: list[tuple] = []

    def _fake_set_included(doc_id: str, included: bool) -> None:
        calls.append((doc_id, included))

    monkeypatch.setattr(source_routes.opstore, "set_doc_included", _fake_set_included)
    client = _make_client()

    resp = client.patch(
        "/api/documents/doc-abc-123/included",
        json={"included": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["external_document_id"] == "doc-abc-123"
    assert data["included"] is False
    assert calls == [("doc-abc-123", False)], (
        f"set_doc_included called with {calls!r}; expected [('doc-abc-123', False)]"
    )


def test_patch_included_true(monkeypatch):
    """Toggling to True also round-trips correctly."""
    calls: list[tuple] = []
    monkeypatch.setattr(source_routes.opstore, "set_doc_included",
                        lambda doc_id, included: calls.append((doc_id, included)))
    client = _make_client()
    resp = client.patch("/api/documents/doc-xyz/included", json={"included": True})
    assert resp.status_code == 200
    assert resp.json()["included"] is True
    assert calls == [("doc-xyz", True)]


def test_post_search_passes_optional_params(monkeypatch):
    calls: list[dict] = []

    def _fake_search(domain_id, project_id, query, k=10, folder="", types=None):
        calls.append({"k": k, "folder": folder, "types": types})
        return []

    monkeypatch.setattr(source_routes, "_search_backend",
                        lambda: type("B", (), {"search": staticmethod(_fake_search)})())
    client = _make_client()
    client.post("/api/search", json={
        "domain_id": "d1",
        "project_id": "p1",
        "query": "q",
        "k": 5,
        "folder": "/reports/",
        "types": ["application/pdf"],
    })
    assert calls[0]["k"] == 5
    assert calls[0]["folder"] == "/reports/"
    assert calls[0]["types"] == ["application/pdf"]


# ── POST /api/sources/{id}/managed-crawl ─────────────────────────────────────

def test_managed_crawl_injects_obo_and_runs(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import source_routes, obo
    app = FastAPI(); app.include_router(source_routes.router)

    monkeypatch.setattr(source_routes.opstore, "get_source",
                        lambda sid: {"provider": "gdrive_managed"})
    monkeypatch.setattr(source_routes.opstore, "create_index_job",
                        lambda *a, **k: None)
    monkeypatch.setattr(obo, "user_ai_gateway_token", lambda req: "AI_GW")
    captured = {}
    class FakeAdapter:
        fetch_document = None
    monkeypatch.setattr(source_routes, "_build_managed_source",
                        lambda token, folder: captured.update({"built": (token, folder)}) or FakeAdapter())
    class _Conn:
        def __enter__(self): return object()
        def __exit__(self, *a): return False
    monkeypatch.setattr(source_routes.lakebase, "connection", lambda: _Conn())
    async def fake_run(**kwargs):
        captured["deps"] = kwargs.get("deps")
        return {"embedded": 3, "skipped": 4, "failed": 0}
    monkeypatch.setattr(source_routes, "_run_index_job", fake_run)

    r = TestClient(app).post("/api/sources/gd/managed-crawl",
                             json={"domain_id":"d","project_id":"p","root_folder":"FOLDER"})
    assert r.status_code == 200
    data = r.json()
    assert data["summary"]["embedded"] == 3
    assert captured["built"] == ("AI_GW", "FOLDER")
    assert captured["deps"] is not None   # managed deps injected
    # skipped_binary must be present and be an int (0 when _managed_crawl is
    # bypassed by the fake _run_index_job, but the key must always be returned)
    assert "skipped_binary" in data
    assert isinstance(data["skipped_binary"], int)


def test_managed_crawl_401_without_forwarded_token(monkeypatch):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    import source_routes, obo
    app = FastAPI(); app.include_router(source_routes.router)
    monkeypatch.setattr(source_routes.opstore, "get_source",
                        lambda sid: {"provider": "gdrive_managed"})
    def raise401(req): raise HTTPException(status_code=401, detail="need auth")
    monkeypatch.setattr(obo, "user_ai_gateway_token", raise401)
    r = TestClient(app).post("/api/sources/gd/managed-crawl",
                             json={"domain_id":"d","project_id":"p","root_folder":"F"})
    assert r.status_code == 401
