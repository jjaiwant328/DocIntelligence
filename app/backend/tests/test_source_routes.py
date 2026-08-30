"""Tests for /api/sources and /api/inventory routes.

All live dependencies (opstore, crawl_source) are monkeypatched so no
Lakebase or MCP server is needed.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import source_routes
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
    monkeypatch.setattr(source_routes.mcp_sources, "auth_url",
                        lambda source: f"https://example.com/auth/{source}")
    client = _make_client()
    resp = client.get("/api/sources/gdrive/auth-url")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://example.com/auth/gdrive"


# ── POST /api/sources/{id}/crawl ──────────────────────────────────────────────

def test_post_crawl_returns_counts(monkeypatch):
    async def _fake_crawl(**kwargs):
        return {"discovered": 5, "folders": 2, "seen_ids": {"a", "b", "c", "d", "e"}}

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
