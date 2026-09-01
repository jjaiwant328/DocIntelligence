# In-App OBO Managed-Drive Connector — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let the deployed app crawl a user's Google Drive via the managed `system.ai.google_drive` MCP **on-behalf-of the signed-in user**, indexing text files into Lakebase (pgvector + reference rows, no UC volume copy) — no Google OAuth client, no elevated credentials.

**Architecture:** A new `gdrive_managed` source provider. A request-scoped OBO token (forwarded user token → RFC-8693 exchange for an `ai-gateway` token) drives a `DatabricksMCPClient` against the AI-Gateway MCP; an async adapter presents the `mcp_sources`-compatible surface so the **existing** `run_index_job` pipeline (crawl→parse→chunk→embed→store) is reused unchanged with injected deps. Lakebase writes and embedding stay in the app/SP context.

**Tech Stack:** FastAPI, Databricks SDK, `databricks-mcp` + `mcp>=1.13,<2.0`, psycopg/pgvector Lakebase, Next.js/TS.

**Spec:** `docs/superpowers/specs/2026-08-31-managed-drive-obo-connector-design.md`

## Global Constraints
- Backend under `app/backend/`; offline tests in `.venv-test`: `cd app/backend && ../../.venv-test/bin/python -m pytest tests/<f> -v`.
- **Tokens (forwarded or exchanged) must NEVER be logged, persisted, or returned in any response.** The token seam lives only in `obo.py`.
- Managed MCP is **text-only**: index `text/plain`, `text/csv`, `text/markdown`, and Google-native doc/sheet/slides; PDFs/binaries are crawled as reference rows but skipped for content.
- Managed AI-Gateway MCP URL: `https://adb-4101016551133680.0.azuredatabricks.net/ai-gateway/mcp-services/system.ai.google_drive?o=4101016551133680`. Workspace host: `https://adb-4101016551133680.0.azuredatabricks.net`.
- Token exchange requires `requested_token_type` (omitting it → HTTP 400). Scope requested: `ai-gateway`. Authenticate the exchange with the app SP creds from env `DATABRICKS_CLIENT_ID`/`DATABRICKS_CLIENT_SECRET`.
- The `DatabricksMCPClient` is synchronous (owns its event loop) — call it only from threads, never awaited directly; async adapter methods wrap it with `asyncio.to_thread`.
- `.venv-test` has `mcp 1.8.1` and no `databricks-mcp`; unit tests must NOT import `databricks_mcp` or `DatabricksMCPClient` (keep those behind lazy imports / injected seams).
- Commit per task, scoped `git add`, trailer `Co-authored-by: Isaac <no-reply@databricks.com>`.

## File Structure
- Create `app/backend/obo.py` — OBO token helper (extract + exchange).
- Modify `app/backend/indexer/managed_gdrive.py` — add `AsyncManagedDriveSource` + `make_managed_call_tool` (keeps existing sync adapter + mappers).
- Modify `app/backend/requirements.txt` — `mcp>=1.13,<2.0` + `databricks-mcp` (already edited in-tree; commit it here).
- Modify `app/backend/source_routes.py` — `POST /api/sources/{id}/managed-crawl` + seams `_build_managed_source`, `_run_index_job`.
- Modify `app/frontend/src/app/sources/page.tsx` — `gdrive_managed` provider option + folder-id field + Connect & Crawl.
- Modify `app/backend/app.py`, delete `app/backend/_obo_probe.py`, revert `app/backend/app.yaml` scope block — remove the throwaway spike probe.
- Tests: `tests/test_obo.py`, extend `tests/test_managed_gdrive.py`, extend `tests/test_source_routes.py` (or create if absent).

---

## Task 1: OBO token helper (`obo.py`)
**Files:** Create `app/backend/obo.py`; Test `tests/test_obo.py`.

**Interfaces produced:**
- `user_ai_gateway_token(request, *, exchanger=None) -> str` — reads `x-forwarded-access-token`; raises `fastapi.HTTPException(401)` if absent; returns an `ai-gateway`-scoped token via `exchanger` (default `_exchange_token`).
- `_exchange_token(subject_token, *, post=None) -> str` — POSTs the RFC-8693 exchange; `post` injectable (default `requests.post`).

- [ ] **Step 1: Failing tests** — `tests/test_obo.py`:
```python
import types
import pytest
import obo

class FakeReq:
    def __init__(self, headers): self.headers = headers

def test_missing_header_raises_401():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        obo.user_ai_gateway_token(FakeReq({}))
    assert ei.value.status_code == 401

def test_uses_exchanger_and_returns_token():
    seen = {}
    def fake_exch(subject, **kw):
        seen["subject"] = subject
        return "AI_GW_TOKEN"
    tok = obo.user_ai_gateway_token(FakeReq({"x-forwarded-access-token": "USER_TOK"}),
                                    exchanger=fake_exch)
    assert tok == "AI_GW_TOKEN"
    assert seen["subject"] == "USER_TOK"

def test_exchange_payload_shape():
    captured = {}
    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"access_token": "X"}
    def fake_post(url, data=None, auth=None, timeout=None):
        captured["url"] = url; captured["data"] = data; captured["auth"] = auth
        return Resp()
    out = obo._exchange_token("USER_TOK", post=fake_post)
    assert out == "X"
    assert captured["data"]["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert captured["data"]["subject_token"] == "USER_TOK"
    assert captured["data"]["requested_token_type"] == "urn:ietf:params:oauth:token-type:access_token"
    assert captured["data"]["scope"] == "ai-gateway"
    assert captured["url"].endswith("/oidc/v1/token")
```
- [ ] **Step 2: Run → fail** (`ModuleNotFoundError: obo`).
- [ ] **Step 3: Implement** `app/backend/obo.py`:
```python
"""On-behalf-of-user token helper for calling managed AI-Gateway MCP services.

The Databricks Apps proxy forwards the user's token as X-Forwarded-Access-Token.
We exchange it (RFC 8693) for an `ai-gateway`-scoped token using the app service
principal's client credentials, and use THAT to call system.ai.* MCP services as
the user. Tokens are never logged, persisted, or returned.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from fastapi import HTTPException

WORKSPACE_HOST = os.getenv(
    "DATABRICKS_HOST", "https://adb-4101016551133680.0.azuredatabricks.net"
).rstrip("/")


def _exchange_token(subject_token: str, *, post: Optional[Callable] = None) -> str:
    """Exchange a forwarded user token for an ai-gateway-scoped access token."""
    if post is None:
        import requests
        post = requests.post
    resp = post(
        f"{WORKSPACE_HOST}/oidc/v1/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": subject_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "scope": "ai-gateway",
        },
        auth=(os.environ.get("DATABRICKS_CLIENT_ID", ""),
              os.environ.get("DATABRICKS_CLIENT_SECRET", "")),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def user_ai_gateway_token(request, *, exchanger: Optional[Callable] = None) -> str:
    """Return an ai-gateway token for the request's user, or raise 401."""
    tok = request.headers.get("x-forwarded-access-token")
    if not tok:
        raise HTTPException(status_code=401,
                            detail="this action requires user authorization")
    return (exchanger or _exchange_token)(tok)
```
- [ ] **Step 4: Run → pass** (`pytest tests/test_obo.py -v`).
- [ ] **Step 5: Commit** `feat(obo): user on-behalf-of ai-gateway token helper`.

## Task 2: Async managed-Drive adapter + client factory
**Files:** Modify `app/backend/indexer/managed_gdrive.py`; Modify `app/backend/requirements.txt`; Test extend `tests/test_managed_gdrive.py`.

**Interfaces produced:**
- `class AsyncManagedDriveSource(call_tool, root_folder_id)` with `async list_children(source, folder_id="") -> list[dict]` and `async fetch_document(source, doc_ref) -> dict` (`{content_b64, filename}`), mapping via existing `map_search_item`.
- `make_managed_call_tool(ai_gateway_token) -> Callable[[str, dict], dict]` — builds a `DatabricksMCPClient` with an isolated user-token `Config(auth_type="pat")`; returns a sync `call_tool` that JSON-parses the response. (Lazy-imports `databricks_mcp`.)

- [ ] **Step 1: Failing tests** — append to `tests/test_managed_gdrive.py`:
```python
import asyncio, base64
from indexer.managed_gdrive import AsyncManagedDriveSource

def test_async_list_children_maps_and_queries_root():
    calls = []
    def fake(tool, args):
        calls.append((tool, args))
        return {"items": [{"id":"F1","name":"a.txt","mimeType":"text/plain"}]}
    src = AsyncManagedDriveSource(fake, root_folder_id="ROOT")
    out = asyncio.run(src.list_children("gdrive_managed", ""))
    assert calls[0][0] == "google_drive_search"
    assert "'ROOT' in parents" in calls[0][1]["query"]
    assert out[0]["item_id"] == "F1"

def test_async_fetch_document_b64():
    def fake(tool, args):
        assert args["file_id"] == "F1"
        return {"name":"a.txt","content":"hi"}
    src = AsyncManagedDriveSource(fake, root_folder_id="ROOT")
    r = asyncio.run(src.fetch_document("gdrive_managed", "F1"))
    assert base64.b64decode(r["content_b64"]).decode() == "hi"
    assert r["filename"] == "a.txt"
```
- [ ] **Step 2: Run → fail** (`ImportError: AsyncManagedDriveSource`).
- [ ] **Step 3: Implement** — append to `app/backend/indexer/managed_gdrive.py`:
```python
import asyncio
import json as _json


class AsyncManagedDriveSource:
    """Async, mcp_sources-compatible adapter over the managed Drive MCP.

    `call_tool(tool, args) -> dict` is a SYNC callable (DatabricksMCPClient runs
    its own event loop); each async method offloads it via asyncio.to_thread so
    it composes with the async indexer pipeline.
    """
    def __init__(self, call_tool, root_folder_id: str):
        self._call = call_tool
        self._root = root_folder_id

    async def list_children(self, source: str = "", folder_id: str = "") -> list:
        parent = folder_id or self._root
        resp = await asyncio.to_thread(
            self._call, "google_drive_search",
            {"query": f"'{parent}' in parents and trashed = false", "max_results": 200},
        )
        items = resp.get("items", []) if isinstance(resp, dict) else []
        return [map_search_item(it) for it in items]

    async def fetch_document(self, source: str, doc_ref: str) -> dict:
        resp = await asyncio.to_thread(self._call, "google_file_download", {"file_id": doc_ref})
        if not isinstance(resp, dict) or resp.get("error_code"):
            code = resp.get("error_code") if isinstance(resp, dict) else resp
            raise ValueError(f"cannot download {doc_ref}: {code}")
        content = resp.get("content", "")
        raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        return {"content_b64": base64.b64encode(raw).decode("ascii"),
                "filename": resp.get("name", doc_ref)}


_MANAGED_URL = ("https://adb-4101016551133680.0.azuredatabricks.net"
                "/ai-gateway/mcp-services/system.ai.google_drive?o=4101016551133680")


def make_managed_call_tool(ai_gateway_token: str):
    """Build a sync call_tool bound to the managed MCP, authed as the user."""
    from databricks_mcp import DatabricksMCPClient
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.core import Config
    cfg = Config(host="https://adb-4101016551133680.0.azuredatabricks.net",
                 token=ai_gateway_token, auth_type="pat")
    mc = DatabricksMCPClient(server_url=_MANAGED_URL, workspace_client=WorkspaceClient(config=cfg))

    def call_tool(tool: str, args: dict) -> dict:
        r = mc.call_tool(tool, args)
        joined = "".join(getattr(c, "text", "") for c in (getattr(r, "content", []) or []))
        return _json.loads(joined) if joined else {}

    return call_tool
```
- [ ] **Step 4: Ensure `requirements.txt`** contains (already edited in-tree — verify):
```
mcp>=1.13.0,<2.0.0
databricks-mcp
```
- [ ] **Step 5: Run → pass** (`pytest tests/test_managed_gdrive.py -v`, all incl. the 6 existing).
- [ ] **Step 6: Commit** `feat(sources): async managed-Drive adapter + OBO MCP client` (add `indexer/managed_gdrive.py`, `requirements.txt`, `tests/test_managed_gdrive.py`).

## Task 3: `managed-crawl` route wiring
**Files:** Modify `app/backend/source_routes.py`; Test extend `tests/test_source_routes.py`.

**Interfaces consumed:** `obo.user_ai_gateway_token` (T1); `AsyncManagedDriveSource`, `make_managed_call_tool` (T2); existing `indexer.crawl.crawl_source`, `indexer.pipeline.run_index_job`, `opstore.create_index_job`, `lakebase.connection`.

**Interfaces produced:**
- `POST /api/sources/{source_id}/managed-crawl` (body `CrawlRequest`: `domain_id, project_id, root_folder`) → `{job_id, summary}`. `root_folder` is the Drive folder id.
- Seams: `_build_managed_source(token, folder_id) -> AsyncManagedDriveSource`; `async _run_index_job(**kwargs) -> dict`.

- [ ] **Step 1: Failing test** — append to `tests/test_source_routes.py` (TestClient; monkeypatch seams):
```python
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
    class FakeAdapter: pass
    monkeypatch.setattr(source_routes, "_build_managed_source",
                        lambda token, folder: captured.setdefault("built", (token, folder)) or FakeAdapter())
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
    assert r.json()["summary"]["embedded"] == 3
    assert captured["built"] == ("AI_GW", "FOLDER")
    assert captured["deps"] is not None   # managed deps injected

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
```
- [ ] **Step 2: Run → fail** (404: route missing).
- [ ] **Step 3: Implement** — in `app/backend/source_routes.py`: add `from fastapi import Request` to the fastapi import, `import obo`, and:
```python
def _build_managed_source(token: str, folder_id: str):
    """Seam: build the async managed-Drive adapter from an OBO token."""
    from indexer.managed_gdrive import AsyncManagedDriveSource, make_managed_call_tool
    return AsyncManagedDriveSource(make_managed_call_tool(token), root_folder_id=folder_id)


async def _run_index_job(**kwargs):
    """Seam so tests can monkeypatch the pipeline entry point."""
    from indexer.pipeline import run_index_job
    return await run_index_job(**kwargs)


@router.post("/sources/{source_id}/managed-crawl")
async def managed_crawl_route(source_id: str, req: CrawlRequest, request: Request):
    """OBO crawl+index for a managed source: reads the user's Drive via the
    managed MCP on-behalf-of the caller, indexes text files into Lakebase."""
    row = opstore.get_source(source_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"source '{source_id}' not found")
    if row.get("provider") != "gdrive_managed":
        raise HTTPException(status_code=400,
                            detail=f"source '{source_id}' is not a managed source")

    token = obo.user_ai_gateway_token(request)          # 401 if no forwarded token
    adapter = _build_managed_source(token, req.root_folder)

    from indexer.crawl import crawl_source
    from indexer.pipeline import PipelineDeps

    async def _managed_crawl(**kw):
        return await crawl_source(**{**kw, "mcp": adapter})

    deps = PipelineDeps(crawl_fn=_managed_crawl, fetch_fn=adapter.fetch_document)

    job_id = str(uuid.uuid4())
    opstore.create_index_job(job_id, req.domain_id, req.project_id, "project", "", "app_user")
    with lakebase.connection() as conn:
        summary = await _run_index_job(
            job_id=job_id, source_id=source_id, provider=row["provider"],
            domain_id=req.domain_id, project_id=req.project_id,
            scope="project", scope_ref="", deps=deps, conn=conn,
        )
    return {"job_id": job_id, "summary": summary}
```
Note: `PipelineDeps` import inside the route is fine; the test monkeypatches `_run_index_job` so the real pipeline never runs offline. `_build_managed_source` is monkeypatched so `databricks_mcp` is never imported in tests.
- [ ] **Step 4: Run → pass** (`pytest tests/test_source_routes.py -v`; then full suite `pytest -q`).
- [ ] **Step 5: Commit** `feat(sources): managed-crawl route (OBO → Lakebase index)`.

## Task 4: Frontend — managed Drive connect & crawl
**Files:** Modify `app/frontend/src/app/sources/page.tsx`. Verify `cd app/frontend && npm run build` clean (ignoreBuildErrors on → match API shapes).

- [ ] **Step 1** — Add `gdrive_managed` to the provider `<select>` in the register form: `<option value="gdrive_managed">Google Drive (managed — no setup)</option>`.
- [ ] **Step 2** — Add a per-source **folder id** input + **Connect & Crawl** button shown when `src.provider === "gdrive_managed"`. Its handler:
```tsx
async function managedCrawl(sourceId: string, folderId: string) {
  if (!project?.project_id) { setMsg("Select a project first."); return; }
  setCrawling(c => ({ ...c, [sourceId]: true })); setMsg(null);
  try {
    const r = await apiCall<{ job_id: string; summary: { embedded: number; skipped: number; failed: number } }>(
      `/api/sources/${sourceId}/managed-crawl`,
      { method: "POST", body: JSON.stringify({ domain_id: domain.domain_id, project_id: project.project_id, root_folder: folderId }) },
    );
    setMsg(`Indexed ${r.summary.embedded} file(s), skipped ${r.summary.skipped} (PDFs are listed but not yet indexed).`);
    fetchSources();
  } catch (e) {
    const m = e instanceof Error ? e.message : String(e);
    setMsg(m.includes("401") ? "Authorize the app for AI Gateway access, then retry." : m);
  } finally {
    setCrawling(c => ({ ...c, [sourceId]: false }));
  }
}
```
(Store the folder-id per source in a `Record<string,string>` state, e.g. `managedFolder`.)
- [ ] **Step 3** — `npm run build` clean.
- [ ] **Step 4: Commit** `feat(ui): managed Google Drive connect & crawl`.

## Task 5: Remove the throwaway OBO spike probe
**Files:** Modify `app/backend/app.py` (remove the `_obo_probe` registration block); Delete `app/backend/_obo_probe.py`; Modify `app/backend/app.yaml` (remove the `user_api_scopes:` block added during the spike — the scope lives at the control plane, not in app.yaml).

- [ ] **Step 1** — Delete `app/backend/_obo_probe.py`; remove the `try: from _obo_probe import ...` block in `app.py`; remove the `user_api_scopes:` block from `app.yaml`.
- [ ] **Step 2: Verify** offline: `cd app/backend && ../../.venv-test/bin/python -c "import app; assert not any(getattr(r,'path','')=='/api/_obo_probe' for r in app.app.routes); print('probe gone, app imports clean')"`.
- [ ] **Step 3: Commit** `chore: remove throwaway OBO spike probe`.

## Task 6: Deploy + live smoke (controller; auto-approved)
**Files:** none (ops).
- [ ] **Step 1** — Confirm `user_api_scopes` includes `ai-gateway`: `databricks apps get docintel-supply-chain -p jai-az-ws` → `effective_user_api_scopes`. (Already set; re-apply via `databricks apps update docintel-supply-chain --json '{"user_api_scopes":["ai-gateway"]}' -p jai-az-ws` if missing.)
- [ ] **Step 2** — `bash app/deploy.sh` (main app). Confirm `/_health` shows all routes loaded.
- [ ] **Step 3** — Register the managed source: `POST /api/sources` `{source_id:"gdrive_managed", provider:"gdrive_managed", display_name:"Google Drive (managed)", auth_mode:"obo", mode:"live"}` (curl with `databricks auth token -p jai-az-ws` bearer).
- [ ] **Step 4** — Live smoke: `POST /api/sources/gdrive_managed/managed-crawl` `{domain_id:"compliance_due_diligence", project_id:"gdrive_obo", root_folder:"12sSEQcg-1TtC9C8ewfpomsTRknChwyGq"}` → expect `summary.embedded>=3`; then `POST /api/search` for the project returns the trio with Drive `web_url`; `GET /api/inventory` shows the rows. (Bearer forwards → app OBO exchange → ai-gateway → managed MCP.)

---

## Self-Review
- **Spec coverage:** obo.py→T1; async adapter + deps→T2; route wiring→T3; UI→T4; probe cleanup→T5; ops scope+deploy+smoke→T6. Data model unchanged (reuses external_documents/document_chunks). Security (token seam, no-log, auth_type=pat)→T1/T2.
- **Placeholders:** none; all code is concrete.
- **Type consistency:** `user_ai_gateway_token(request, *, exchanger=None)->str` (T1) consumed in T3; `AsyncManagedDriveSource(call_tool, root_folder_id)` + `make_managed_call_tool(token)` (T2) consumed by `_build_managed_source` (T3); `list_children(source, folder_id="")` / `fetch_document(source, doc_ref)` match `crawl_source`'s `mcp` + `PipelineDeps.fetch_fn` call shapes; `CrawlRequest.root_folder` = Drive folder id, passed as adapter `root_folder_id`.
- **Offline-test safety:** `databricks_mcp`/`DatabricksMCPClient` only behind `make_managed_call_tool` (lazy) and `_build_managed_source` (monkeypatched in tests) — no unit test imports them; `.venv-test`'s mcp 1.8.1 is untouched.
