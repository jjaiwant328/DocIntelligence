"""Tests for /api/doc-sets — pinned + query-defined document sets."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import doc_set_routes as d
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client():
    app = FastAPI()
    app.include_router(d.router)
    return TestClient(app)


class _FakeLB:
    from contextlib import contextmanager

    def __init__(self, conn=None):
        self._conn = conn if conn is not None else object()

    from contextlib import contextmanager

    @contextmanager
    def connection(self):
        yield self._conn


def test_create_pinned_set(monkeypatch):
    created = {}
    monkeypatch.setattr(d.doc_sets_repo, "create",
                        lambda conn, **kw: created.update(kw) or {"id": kw["set_id"], **kw})
    monkeypatch.setattr(d, "lakebase", _FakeLB())
    resp = _client().post("/api/doc-sets", json={
        "domain_id": "supply_chain", "name": "Q3", "kind": "pinned"})
    assert resp.status_code == 200
    assert created["kind"] == "pinned"
    assert resp.json()["id"]


def test_create_rejects_bad_kind(monkeypatch):
    monkeypatch.setattr(d, "lakebase", _FakeLB())
    resp = _client().post("/api/doc-sets", json={
        "domain_id": "supply_chain", "name": "X", "kind": "bogus"})
    assert resp.status_code == 400


def test_query_set_resolve_empty_match(monkeypatch):
    monkeypatch.setattr(d.doc_sets_repo, "get", lambda conn, sid: {
        "id": sid, "kind": "query",
        "filter_json": {"source_ids": ["nope"], "doc_types": [], "text": "", "labels": []}})

    class FakeCur:
        def execute(self, q, p=None):
            self.q = q
        def fetchall(self):
            return []
        @property
        def description(self):
            return []

    class FakeConn:
        def cursor(self):
            return FakeCur()

    monkeypatch.setattr(d, "lakebase", _FakeLB(FakeConn()))
    resp = _client().get("/api/doc-sets/s1/docs")
    assert resp.status_code == 200
    assert resp.json()["documents"] == []


def test_pin_into_query_set_rejected(monkeypatch):
    monkeypatch.setattr(d.doc_sets_repo, "get", lambda conn, sid: {
        "id": sid, "kind": "query", "filter_json": {}})
    monkeypatch.setattr(d, "lakebase", _FakeLB())
    resp = _client().post("/api/doc-sets/s1/pin", json={"doc_ids": ["d1"]})
    assert resp.status_code == 400


def test_pin_and_unpin(monkeypatch):
    pinned = []
    monkeypatch.setattr(d.doc_sets_repo, "get", lambda conn, sid: {
        "id": sid, "kind": "pinned", "filter_json": {}})
    monkeypatch.setattr(d.doc_sets_repo, "pin",
                        lambda conn, sid, did: pinned.append(did))
    monkeypatch.setattr(d, "lakebase", _FakeLB())
    client = _client()
    resp = client.post("/api/doc-sets/s1/pin", json={"doc_ids": ["d1", "d2"]})
    assert resp.status_code == 200
    assert resp.json()["pinned"] == 2
    assert pinned == ["d1", "d2"]
