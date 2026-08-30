"""Tests for /api/connectors routes.

All live dependencies (opstore, secret_store) are monkeypatched so no
Lakebase or Databricks secret API is needed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import connector_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client():
    app = FastAPI()
    app.include_router(connector_routes.router)
    return TestClient(app, raise_server_exceptions=True)


_SAMPLE_ROW = {
    "provider": "gdrive",
    "display_name": "Google Drive",
    "client_id": "abc123xyz",
    "redirect_uri": "https://example.com/oauth/gdrive/callback",
    "scopes": ["email"],
    "secret_ref": "docintel_connectors/gdrive_client_secret",
    "status": "configured",
    "updated_by": "user",
}


# ── POST /api/connectors — with client_secret ─────────────────────────────────

def test_post_with_client_secret_calls_put(monkeypatch):
    put_calls = []

    def _fake_put(provider, client_id, client_secret, redirect_uri, scopes, *, client=None):
        put_calls.append({"provider": provider, "secret": client_secret})
        return f"docintel_connectors/{provider}_client_secret"

    monkeypatch.setattr(connector_routes.secret_store, "put_connector_credentials", _fake_put)
    monkeypatch.setattr(connector_routes.opstore, "upsert_connector",
                        lambda **k: _SAMPLE_ROW)

    c = _make_client()
    resp = c.post("/api/connectors", json={
        "provider": "gdrive",
        "display_name": "Google Drive",
        "client_id": "abc123",
        "client_secret": "SHH",
        "redirect_uri": "https://x.com/cb",
        "scopes": ["email"],
    })
    assert resp.status_code == 200
    assert len(put_calls) == 1


def test_post_with_client_secret_response_has_no_secret(monkeypatch):
    monkeypatch.setattr(connector_routes.secret_store, "put_connector_credentials",
                        lambda *a, **k: "docintel_connectors/gdrive_client_secret")
    monkeypatch.setattr(connector_routes.opstore, "upsert_connector",
                        lambda **k: _SAMPLE_ROW)

    c = _make_client()
    resp = c.post("/api/connectors", json={
        "provider": "gdrive",
        "client_id": "abc123",
        "client_secret": "SHH",
    })
    assert resp.status_code == 200
    body_str = str(resp.json())
    assert "SHH" not in body_str
    assert "client_secret" not in resp.json().get("connector", {})
    assert "secret_ref" not in resp.json().get("connector", {})


# ── POST /api/connectors — without client_secret ─────────────────────────────

def test_post_without_client_secret_does_not_call_put(monkeypatch):
    put_calls = []

    monkeypatch.setattr(connector_routes.secret_store, "put_connector_credentials",
                        lambda *a, **k: put_calls.append(a) or "ref")
    monkeypatch.setattr(connector_routes.opstore, "get_connector",
                        lambda p: {"secret_ref": "old_ref", "status": "configured"})
    monkeypatch.setattr(connector_routes.opstore, "upsert_connector",
                        lambda **k: _SAMPLE_ROW)

    c = _make_client()
    resp = c.post("/api/connectors", json={
        "provider": "gdrive",
        "client_id": "abc123",
    })
    assert resp.status_code == 200
    assert len(put_calls) == 0, "put must NOT be called when client_secret is absent"


def test_post_without_client_secret_preserves_existing_ref(monkeypatch):
    """When client_secret is absent, the existing secret_ref must be forwarded to upsert."""
    upsert_calls = []

    monkeypatch.setattr(connector_routes.secret_store, "put_connector_credentials",
                        lambda *a, **k: "new_ref")
    monkeypatch.setattr(connector_routes.opstore, "get_connector",
                        lambda p: {"secret_ref": "old_ref", "status": "configured"})

    def _capture_upsert(**k):
        upsert_calls.append(k)
        return _SAMPLE_ROW

    monkeypatch.setattr(connector_routes.opstore, "upsert_connector", _capture_upsert)

    c = _make_client()
    c.post("/api/connectors", json={"provider": "gdrive", "client_id": "abc"})
    assert upsert_calls[0]["secret_ref"] == "old_ref"


# ── GET /api/connectors ───────────────────────────────────────────────────────

def test_get_connectors_returns_no_secret_ref(monkeypatch):
    monkeypatch.setattr(connector_routes.opstore, "list_connectors",
                        lambda: [_SAMPLE_ROW])
    c = _make_client()
    resp = c.get("/api/connectors")
    assert resp.status_code == 200
    for item in resp.json()["connectors"]:
        assert "secret_ref" not in item
        assert "client_secret" not in item


def test_get_connectors_strips_full_client_id(monkeypatch):
    """Full client_id must not appear in GET response."""
    row = dict(_SAMPLE_ROW, client_id="full_secret_client_id_xyz")
    monkeypatch.setattr(connector_routes.opstore, "list_connectors", lambda: [row])
    c = _make_client()
    resp = c.get("/api/connectors")
    body_str = str(resp.json())
    assert "full_secret_client_id_xyz" not in body_str


def test_get_connectors_returns_client_id_last4(monkeypatch):
    row = dict(_SAMPLE_ROW, client_id="abc123xyz")
    monkeypatch.setattr(connector_routes.opstore, "list_connectors", lambda: [row])
    c = _make_client()
    resp = c.get("/api/connectors")
    item = resp.json()["connectors"][0]
    assert "client_id_last4" in item
    assert item["client_id_last4"] == "3xyz"


def test_get_connectors_empty(monkeypatch):
    monkeypatch.setattr(connector_routes.opstore, "list_connectors", lambda: [])
    c = _make_client()
    resp = c.get("/api/connectors")
    assert resp.status_code == 200
    assert resp.json()["connectors"] == []


# ── DELETE /api/connectors/{provider} ────────────────────────────────────────

def test_delete_connector_calls_facade_and_secret_delete(monkeypatch):
    facade_calls = []
    secret_calls = []

    monkeypatch.setattr(connector_routes.opstore, "delete_connector",
                        lambda p: facade_calls.append(p))
    monkeypatch.setattr(connector_routes.secret_store, "delete_connector_credentials",
                        lambda p, **k: secret_calls.append(p))

    c = _make_client()
    resp = c.delete("/api/connectors/gdrive")
    assert resp.status_code == 200
    assert facade_calls == ["gdrive"]
    assert secret_calls == ["gdrive"]


def test_delete_returns_provider_and_deleted_flag(monkeypatch):
    monkeypatch.setattr(connector_routes.opstore, "delete_connector", lambda p: None)
    monkeypatch.setattr(connector_routes.secret_store, "delete_connector_credentials",
                        lambda p, **k: None)
    c = _make_client()
    resp = c.delete("/api/connectors/sharepoint")
    data = resp.json()
    assert data["provider"] == "sharepoint"
    assert data["deleted"] is True


# ── GET /api/connectors/{provider}/authorize-url ─────────────────────────────

def test_authorize_url_contains_provider_and_path(monkeypatch):
    monkeypatch.setenv("DOCINTEL_MCP_SOURCES_URL", "https://sources.example.com")
    c = _make_client()
    resp = c.get("/api/connectors/gdrive/authorize-url")
    assert resp.status_code == 200
    data = resp.json()
    assert "auth_url" in data
    assert "gdrive" in data["auth_url"]
    assert "/oauth/" in data["auth_url"]
    assert "/start" in data["auth_url"]


def test_authorize_url_uses_sources_env(monkeypatch):
    monkeypatch.setenv("DOCINTEL_MCP_SOURCES_URL", "https://my-sources.databricksapps.com")
    c = _make_client()
    resp = c.get("/api/connectors/gdrive/authorize-url")
    data = resp.json()
    assert data["auth_url"].startswith("https://my-sources.databricksapps.com")
