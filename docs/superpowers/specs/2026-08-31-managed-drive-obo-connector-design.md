# In-App OBO Managed-Drive Connector — Design

**Date:** 2026-08-31
**Status:** Approved for planning
**Builds on:** connector-first Lakebase redesign (`2026-08-29-lakebase-connector-first-redesign-design.md`), connector-credentials (`2026-08-30-connector-credentials-design.md`).

## Goal

Let the deployed DocIntelligence app crawl a user's **personal Google Drive**
and index it into Lakebase (pgvector + reference metadata, **no UC volume copy**)
**on-behalf-of the signed-in user**, using the Databricks-managed
`system.ai.google_drive` AI-Gateway MCP — with **no Google OAuth client and no
elevated credentials**. This is the "app connects to your Drive" experience that
the self-managed OAuth connector could not provide for users without Google
Cloud Console access.

## Background — why this works (spike-proven 2026-08-31)

The self-managed OAuth connector requires a Google Cloud OAuth client, which the
target user cannot create. The managed `system.ai.google_drive` MCP needs no such
client but is **user-identity scoped** — it only sees a user's Drive when called
with that user's Databricks token. The app runs as a service principal, so it
must call the MCP **on-behalf-of** the user.

A live spike on `docintel-supply-chain` (jai-az-ws) proved the full chain end to
end (`obo_managed_mcp: "ok"`, returned the user's DocIntel folder). The recipe:

1. **App scope:** set `user_api_scopes=["ai-gateway"]` on the app via
   `databricks apps update --json` (the `app.yaml` top-level key is **ignored** —
   control-plane only; workspace allowlist `allowedAppsUserApiScopes` is `*`).
2. **Forwarded token:** Databricks Apps forwards `X-Forwarded-Access-Token`; once
   the scope is set it carries `ai-gateway`.
3. **Token exchange (robust path):** POST `/oidc/v1/token`,
   `grant_type=urn:ietf:params:oauth:grant-type:token-exchange`,
   `subject_token=<forwarded token>`,
   `subject_token_type=…:access_token`,
   `requested_token_type=…:access_token` (**required** — omitting it 400s),
   `scope=ai-gateway`, authenticated with the app SP creds
   (`DATABRICKS_CLIENT_ID`/`DATABRICKS_CLIENT_SECRET`, already in-env) → returns a
   clean `ai-gateway`-scoped access token.
4. **MCP client:** `mcp>=1.13,<2.0` speaks the AI-Gateway protocol (`2025-06-18`)
   and still exposes the 1.x `streamablehttp_client` import that `mcp_sources`
   uses (renamed only in 2.0). `databricks-mcp` provides `DatabricksMCPClient`.
   Verified live: with this pin all existing routes still load and `mcp_server`
   still mounts.
5. **Call:** `DatabricksMCPClient(server_url=<managed url>, workspace_client=
   WorkspaceClient(Config(host=…, token=<ai-gateway token>, auth_type="pat")))`.
   `auth_type="pat"` isolates the user token from the app SP env creds (otherwise
   the SDK errors "more than one authorization method configured"). The client is
   **synchronous** (runs its own event loop internally).

## Architecture

OBO is used **only** for the Drive read. Lakebase writes and embedding stay in
the app/SP context, unchanged. The connector-first indexer is reused wholesale.

```
Browser (user)                Backend (app SP)                 Databricks
  Sources page  ── crawl ──►  source_routes                     control plane
                              │  obo.user_ai_gateway_token(req)  ──► /oidc/v1/token
                              │      (exchange forwarded token)  ◄──  ai-gateway token
                              │  ManagedDriveSource(obo_token)   ──► AI-Gateway MCP
                              │      list_children / fetch       ◄──  user's Drive
                              │  run_index_job(crawl_fn, fetch_fn injected)
                              │      parse → chunk → embed        ──► model serving (SP)
                              └──   store vectors + refs          ──► Lakebase (SP)
```

### Components & interfaces

1. **`app/backend/obo.py`** — OBO token helper.
   - `user_ai_gateway_token(request, *, exchanger=None) -> str`
     - Read `request.headers["x-forwarded-access-token"]`; raise `HTTPException(401)`
       ("this action requires user authorization") if absent.
     - Exchange it (per recipe §3) for an `ai-gateway` token; return that token.
     - `exchanger` is injectable (a callable doing the HTTP POST) so tests use a
       fake and never hit the network. Default posts to
       `f"{WORKSPACE_HOST}/oidc/v1/token"` with `requests`.
     - **Never logs the forwarded or exchanged token.**
   - `WORKSPACE_HOST` from env (`DATABRICKS_HOST`) with the app's known host as
     fallback.

2. **`app/backend/indexer/managed_gdrive.py`** — extend the existing adapter
   (keep the pure mappers `map_search_item`, `is_text_readable`, and the sync
   `ManagedDriveSource` used by the standalone runner). Add an **async** in-app
   variant so it plugs into the async pipeline/crawl:
   - `class AsyncManagedDriveSource` with the `mcp_sources`-compatible async
     surface the indexer consumes:
     - `async list_children(source_id, folder_id="") -> list[dict]`
     - `async fetch_document(source, doc_ref) -> {content_b64, filename}`
     - (`get_file_metadata`, `get_source_url`, `check_access`, `get_changes` as
       needed by crawl — `get_changes` returns a full-list initial-sync shape;
       the managed MCP has no delta cursor.)
   - Each async method wraps the sync `DatabricksMCPClient` call via
     `await asyncio.to_thread(self._call, tool, args)`. The sync `_call`
     (injected) invokes `DatabricksMCPClient.call_tool` and JSON-parses the
     response text. Constructed per-request from the OBO token.
   - Mapping reuses `map_search_item`; `list_children` filters/returns the same
     metadata shape `crawl_source` expects (`item_id, is_folder, name, mime_type,
     size, web_url, etag, modified_at, owner, path`).

3. **Wiring — `app/backend/source_routes.py`.**
   - Register provider **`gdrive_managed`** (distinct from OAuth `gdrive`).
   - The crawl route, when the source's provider is `gdrive_managed`:
     - `token = obo.user_ai_gateway_token(request)`
     - build `AsyncManagedDriveSource` from `token` + the source's root folder id
     - call the **existing** `run_index_job(..., deps=PipelineDeps(
       crawl_fn=<managed crawl>, fetch_fn=<managed fetch>))`, where the managed
       crawl is `indexer.crawl.crawl_source` with `mcp=<the async adapter>`.
   - `FastAPI Request` must be available to the route (add `request: Request`).
   - Non-text files (PDF/binary) are crawled as reference rows but skipped for
     content indexing (managed MCP is text-only) — mirror the runner's behavior;
     surface a per-file "skipped: not text-readable" note.

4. **Dependency — `app/backend/requirements.txt`.** `mcp>=1.13.0,<2.0.0` +
   `databricks-mcp` (already applied and live-validated). No other pin changes.

5. **UI — `app/frontend/src/app/sources/page.tsx`** (+ existing components).
   - Offer a "Google Drive (managed — no setup)" source: a folder-id field and a
     **Connect & Crawl** button → `POST /api/sources/{id}/crawl`.
   - Reuse the existing inventory + hybrid-search panels. Show the text-only note
     ("PDFs are listed but not yet indexed").
   - A soft error surface when the crawl returns 401 (user authorization needed).

### Data model

**No schema change.** Reuses `external_documents` (metadata + `web_url` reference,
`source_item_id`, `etag`) and `document_chunks` (`embedding vector(1024)`, `tsv`).
Scoped by `domain_id` + `project_id` like every other source.

## Ops / configuration

- The app must have `user_api_scopes` including `ai-gateway` (control-plane;
  `databricks apps update --json '{"user_api_scopes":["ai-gateway"]}'`). Document
  this as a one-time deploy step; `app.yaml` cannot express it.
- The app SP OAuth creds (`DATABRICKS_CLIENT_ID`/`SECRET`) are already present in
  the Apps runtime env; the exchange uses them.
- The calling user needs EXECUTE on `system.ai.google_drive` (holds for the
  workspace user in the spike).

## Security

- Forwarded and exchanged tokens are **never logged, persisted, or returned** in
  any response. The token seam is isolated in `obo.py`.
- `auth_type="pat"` on a fresh `Config` prevents the user token from mixing with
  the app SP env creds.
- OBO preserves the user's Drive permissions (they only see their own files).

## Testing

- **Offline (pytest, `.venv-test`):**
  - `obo.py`: fake exchanger — asserts the exchange payload includes
    `requested_token_type` + `scope=ai-gateway`, returns the exchanged token, and
    that a missing header raises 401; assert the token value never appears in log
    output.
  - `managed_gdrive` async adapter: fake sync `_call` — `list_children` issues the
    parent query and maps items; `fetch_document` returns `{content_b64,
    filename}`; unsupported/binary raises; async methods run without a live loop.
  - Route: monkeypatch `obo.user_ai_gateway_token` + `run_index_job` — assert the
    `gdrive_managed` crawl injects the managed deps and returns the job summary;
    401 propagates when the helper raises.
- **Live smoke (controller):** deploy; `POST /api/sources/{gdrive_managed}/crawl`
  for the DocIntel folder via the app (browser/OBO) → `external_documents` rows
  with Drive `web_url`, `document_chunks` vectors for the text files, hybrid
  search returns them. PDFs listed, `pending`.

## Non-goals / follow-ons

- **PDF/binary content** — managed MCP is text-only. A separate path (user-token
  `files.get?alt=media` + `pypdf`) is a follow-on, not in this build.
- **Incremental/delta crawl** — managed MCP has no change cursor; full re-list
  each crawl (fine for demo corpora).
- **Removing the throwaway `_obo_probe`** (route in `app.py`, `_obo_probe.py`,
  the `app.yaml` `user_api_scopes` block) is part of this build's cleanup.

## Rollback

Revert the `requirements.txt` pin and unregister the `gdrive_managed` provider;
the existing OAuth `gdrive` path and all other routes are untouched.
