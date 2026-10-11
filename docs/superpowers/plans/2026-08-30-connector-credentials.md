# App-Managed Connector Credentials — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Configure a document-source connector's OAuth credentials from inside the app (client id/secret/scopes + Authorize), stored in a Databricks secret scope, read by the sources server at runtime — generalizing across connectors.

**Architecture:** Lakebase `connectors` table holds non-secret config; secret lives in scope `docintel_connectors` (main app SP writes via SDK, sources app SP reads at runtime). New `/api/connectors` routes on the main app; `oauth.py` on the sources server becomes provider-parameterized and reads creds from the scope (env fallback). A Connectors panel UI on the Sources page.

**Tech Stack:** FastAPI, psycopg/pgvector Lakebase, Databricks SDK `secrets`, FastMCP sources server, Next.js/TS.

**Spec:** `docs/superpowers/specs/2026-08-30-connector-credentials-design.md`

## Global Constraints
- Backend under `app/backend/`; sources server under `app/mcp-server/` (no `from __future__ import annotations` there). Tests offline in `.venv-test`: `cd app/backend && ../../.venv-test/bin/python -m pytest tests/<f> -v`.
- **The client secret must never** be stored in the Lakebase row, returned in any HTTP response, logged, or committed. Lakebase stores only a `secret_ref` pointer.
- Two SPs: main `00ec2ab7-2445-4bc8-b68d-25e463b5bbe3` (writes), sources `4858ec89-257e-4a19-9269-6a5ec8e01d14` (reads). Scope `docintel_connectors`.
- All secret access behind a `secret_store` seam (injectable client) so the "SP can't put/get at runtime" fallback is localized.
- Commit per task, scoped `git add`, trailer `Co-authored-by: Isaac <no-reply@databricks.com>`.

---

## File Structure
- Modify `app/backend/db/schema.py` — add `connectors` table DDL.
- Create `app/backend/db/repositories/connectors_repo.py` — CRUD.
- Modify `app/backend/db/operational.py` — facade wrappers.
- Create `app/backend/secret_store.py` — put/exists/delete connector secret via SDK (injectable).
- Create `app/backend/connector_routes.py` — `/api/connectors`; register in `app/backend/app.py`.
- Modify `app/mcp-server/oauth.py` — provider-parameterized runtime resolve + env fallback.
- Modify `app/mcp-server/server.py` — generalize `/oauth/{provider}/start|callback` (+ google aliases).
- Create `app/frontend/src/components/ConnectorsPanel.tsx`; wire into `app/frontend/src/app/sources/page.tsx`.
- Tests: `tests/test_connectors_repo.py`, `tests/test_secret_store.py`, `tests/test_connector_routes.py`.

---

## Task 1: `connectors` table + repo + facade
**Files:** Modify `db/schema.py`; Create `db/repositories/connectors_repo.py`; Modify `db/operational.py`; Test `tests/test_connectors_repo.py`.

**Interfaces produced:**
- `connectors_repo.list_connectors(conn) -> list[dict]`, `get_connector(conn, provider) -> dict|None`, `upsert_connector(conn, provider, display_name, client_id, redirect_uri, scopes:list, secret_ref, status, updated_by) -> dict`, `set_status(conn, provider, status) -> None`, `delete_connector(conn, provider) -> None`.
- `operational` facade: `list_connectors()`, `get_connector(provider)`, `upsert_connector(**)`, `set_connector_status(provider, status)`, `delete_connector(provider)` (each `with lakebase.connection()` + `_ensure()`).

- [ ] **Step 1: Failing test** — `connectors` DDL present; repo upsert stores `secret_ref` and NO secret column; scopes JSON round-trips.
```python
# tests/test_connectors_repo.py
import db.schema as schema
from db.repositories import connectors_repo
def test_ddl_has_connectors_no_secret_column():
    j = "\n".join(schema.DDL).lower()
    assert "create table if not exists connectors" in j
    assert "secret_ref" in j
    assert "client_secret" not in j   # secret never in the table
```
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — add DDL (PK `provider`, cols per spec §3, `scopes JSONB`), repo (psycopg, `_dicts`, `ON CONFLICT (provider) DO UPDATE`; `scopes` via `json.dumps(...)::jsonb`), facade wrappers.
- [ ] **Step 4: Run → pass** (full suite too).
- [ ] **Step 5: Commit** `feat(db): connectors table + repo + facade`.

## Task 2: `secret_store.py` (write-only secret handling)
**Files:** Create `app/backend/secret_store.py`; Test `tests/test_secret_store.py`.

**Interfaces produced:**
- `SCOPE = os.getenv("DOCINTEL_CONNECTOR_SCOPE", "docintel_connectors")`
- `secret_key(provider) -> str` (`f"{provider}_client_secret"`).
- `put_connector_credentials(provider, client_id, client_secret, redirect_uri, scopes, *, client=None) -> str` — writes `{provider}_client_secret` (+ `_client_id`, `_redirect_uri`, `_scopes`) via `WorkspaceClient().secrets.put_secret`; returns the `secret_ref` `f"{SCOPE}/{secret_key(provider)}"`. **Never returns the secret.**
- `secret_configured(provider, *, client=None) -> bool` (list keys, no value read).
- `delete_connector_credentials(provider, *, client=None) -> None`.

- [ ] **Step 1: Failing test** — inject a fake client; assert `put_connector_credentials` calls `put_secret(scope, "gdrive_client_secret", string_value=<secret>)` and the return value is the ref string, not the secret.
```python
def test_put_writes_secret_and_returns_ref_not_secret():
    calls=[]
    class FakeSecrets:
        def put_secret(self, scope, key, string_value=None): calls.append((scope,key,string_value))
    class FakeWS: secrets=FakeSecrets()
    ref = secret_store.put_connector_credentials("gdrive","cid","SHH","uri",["s"],client=FakeWS())
    assert ("docintel_connectors","gdrive_client_secret","SHH") in calls
    assert "SHH" not in ref and ref=="docintel_connectors/gdrive_client_secret"
```
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** (default `client` lazily builds `WorkspaceClient()`).
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** `feat(secrets): connector secret_store (write-only)`.

## Task 3: `/api/connectors` routes
**Files:** Create `app/backend/connector_routes.py`; Modify `app/backend/app.py`; Test `tests/test_connector_routes.py`.

**Interfaces produced (router prefix `/api`):**
- `GET /api/connectors` → `{connectors:[{provider,display_name,client_id_last4,status,redirect_uri,scopes}]}` — **no secret, no full client_secret**.
- `POST /api/connectors` — body `{provider, display_name?, client_id, client_secret?, redirect_uri?, scopes?}`; upsert config + (if `client_secret` present) `secret_store.put_connector_credentials`; `redirect_uri` defaults to `https://docintel-sources-4101016551133680.0.azure.databricksapps.com/oauth/{provider}/callback`; status→`configured`. Returns the stripped connector (no secret).
- `DELETE /api/connectors/{provider}` — facade delete + `secret_store.delete_connector_credentials` (best effort).
- `GET /api/connectors/{provider}/authorize-url` → `{auth_url: "<sources>/oauth/{provider}/start"}` (base from `DOCINTEL_MCP_SOURCES_URL`).

- [ ] **Step 1: Failing test** (TestClient; monkeypatch `operational` + `secret_store` seams): `POST` with `client_secret` calls `put_connector_credentials` and the **response body contains no `client_secret`/secret**; `GET` returns no secret; editing without `client_secret` does NOT call put.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement**; register `connector_routes.router` in `app.py` with the existing error-guard pattern.
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** `feat(api): /api/connectors credential config routes`.

## Task 4: Sources server — provider-parameterized runtime creds
**Files:** Modify `app/mcp-server/oauth.py`, `app/mcp-server/server.py`. (No offline harness — verify `python -c "import server"` + a throwaway resolve check.)

**Interfaces produced:**
- `oauth.ProviderOAuth(provider)` — `client_id/secret/redirect_uri/scopes` resolved by `_resolve(provider)`: try scope `docintel_connectors` keys `{provider}_client_id/_client_secret/_redirect_uri/_scopes` via `WorkspaceClient().secrets.get_secret` (short TTL cache); fall back to legacy `GOOGLE_OAUTH_*` env when the provider is `google`/`gdrive` and the scope has nothing. `configured` / `connected` unchanged in meaning.
- `server.py`: `/oauth/{provider}/start` + `/oauth/{provider}/callback`; keep `/oauth/google/start|callback` as aliases delegating with `provider="gdrive"`.

- [ ] **Step 1: Failing check** — a throwaway script: inject a fake secret client returning creds for `gdrive`; assert `ProviderOAuth("gdrive").client_id` comes from the scope; with an empty scope, env `GOOGLE_OAUTH_CLIENT_ID` is used. (Delete the script after.)
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** the resolver + route generalization; keep `GoogleOAuth` as a thin `ProviderOAuth("gdrive")` alias so existing imports work.
- [ ] **Step 4: Verify** `python -c "import server"` clean; throwaway resolve check passes; delete it.
- [ ] **Step 5: Commit** `feat(sources): provider-parameterized OAuth creds from secret scope`.

## Task 5: Connectors panel UI
**Files:** Create `app/frontend/src/components/ConnectorsPanel.tsx`; Modify `app/frontend/src/app/sources/page.tsx`. Verify `cd app/frontend && npm run build` clean (ignoreBuildErrors is on → match API shapes carefully).

**Consumes:** `GET/POST/DELETE /api/connectors`, `GET /api/connectors/{provider}/authorize-url` via `lib/api-config.ts`.

- [ ] **Step 1** — Panel: list connectors with status chips; **Add/Configure** form (provider select, display name, client ID, client secret [`type=password`, write-only, cleared on submit, never populated from server], redirect URI [auto-filled, read-only], scopes); Save → POST; **Authorize** button opens `authorize-url` in a new tab; a "credentials are shared/sensitive" note.
- [ ] **Step 2** — mount ConnectorsPanel on `sources/page.tsx`.
- [ ] **Step 3** — `npm run build` clean.
- [ ] **Step 4: Commit** `feat(ui): connectors credential config panel`.

## Task 6: P0 setup + deploy + live verify
**Files:** none (ops). *(Controller runs; auto-approved.)*
- [ ] **Step 1** — create scope + grants: `databricks secrets create-scope docintel_connectors -p jai-az-ws`; `put-acl docintel_connectors <main-SP> WRITE`; `put-acl docintel_connectors <sources-SP> READ`.
- [ ] **Step 2** — deploy sources app then main app.
- [ ] **Step 3** — **runtime spike:** via app OAuth, `POST /api/connectors` with a dummy provider+secret → confirm 200 and secret lands in the scope (`databricks secrets list-secrets docintel_connectors`), `GET /api/connectors` shows it with **no secret**; then DELETE it. If `put_secret` is denied at runtime → invoke the fallback (env secret-resource) and note it.
- [ ] **Step 4** — (when user provides real Google client id/secret + folder IDs) configure Google Drive via `POST /api/connectors`, authorize, crawl+index a real folder, verify search.

---

## Self-Review
- **Spec coverage:** §3 model→T1; §4 secret store→T2; §5 routes→T3; §6 sources resolver→T4; §7 UI→T5; §2 D3 runtime read + P0 spike→T4/T6; §8 security (strip on read, write-only, seam)→T2/T3/T5.
- **Placeholders:** none; code/seams named.
- **Type consistency:** `secret_store.put_connector_credentials(provider, client_id, client_secret, redirect_uri, scopes, *, client=None) -> secret_ref` identical in T2/T3; `connectors_repo`/facade names identical T1/T3; scope name `docintel_connectors` consistent T2/T4/T6.
