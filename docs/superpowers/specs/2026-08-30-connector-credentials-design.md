# App-Managed Connector Credentials — Design

**Date:** 2026-08-30
**Status:** Design approved (brainstorming), pending spec review
**Author:** Jaiwant Jonathan (with Isaac)
**Relates to:** `2026-08-29-lakebase-connector-first-redesign-design.md` (the connector-first slice this extends). Builds on [[connector-first-lakebase-redesign]].

## 1. Goal

Let a user configure a document-source connector's OAuth credentials **from inside the app** — pick a provider, paste its client ID / secret / scopes, authorize — instead of an operator setting `GOOGLE_OAUTH_*` env vars and redeploying. The mechanism must **generalize across connectors** (Google Drive now; SharePoint and others later reuse the same plumbing).

This same mechanism is used to set up Google Drive for the current demo (the client ID/secret land in the shared secret scope, not throwaway env vars).

### Success criteria
- A user opens a **Connectors** panel, adds a Google Drive connector by pasting client ID + secret + scopes, and clicks **Authorize** — no redeploy, no env-var editing.
- The secret is stored in a Databricks secret scope, **never** in the app DB, logs, git, or any HTTP response body.
- The sources app reads the connector's credentials **at runtime** and serves live Drive.
- Adding a second connector (e.g. SharePoint) is a new `connectors` row + provider-specific connector class — the credential/secret/authorize plumbing is unchanged.

### Non-goals
- Building the SharePoint *connector class* itself (fast follow; this delivers the credential plumbing + Google Drive via the UI).
- Fixing the per-user refresh-token persistence (still cached on the sources app `/tmp`; resets on redeploy — existing behavior).
- Admin/role gating — per decision, **any app user** can configure connectors (a visible note flags that config is shared/sensitive).

## 2. Decisions (locked in brainstorming)
| # | Decision |
|---|---|
| D1 | **Secret stored in a Databricks secret scope** (`docintel_connectors`). Non-secret config (client_id, redirect_uri, scopes, status) in a Lakebase `connectors` table. |
| D2 | **Any app user** can add/edit connectors (no admin gate). UI shows a "shared/sensitive" note. |
| D3 | The sources app reads credentials from the scope **at runtime** (per-use, small TTL cache), with env-var fallback for backward compat — so a newly-added connector needs no sources-app redeploy. |
| D4 | Scope now = credential plumbing + Google Drive via UI. SharePoint connector class is a fast follow. |
| D5 | The current-demo Google setup uses this same scope mechanism (not throwaway env vars). |

### Two service principals (key constraint)
Main app SP `00ec2ab7-2445-4bc8-b68d-25e463b5bbe3` (UI, **writes** secrets). Sources app SP `4858ec89-257e-4a19-9269-6a5ec8e01d14` (**reads** secrets). The scope must grant main WRITE/MANAGE and sources READ.

### Phase-0 linchpin spike (feasibility gate)
Confirm the app SPs can `secrets.put_secret` / `secrets.get_secret` at runtime under a scope ACL. **Fallback if not:** keep client_id + config in Lakebase and inject the secret via an app secret-resource env (works; adding a connector then needs one sources-app redeploy). All secret access sits behind a `secret_store` seam so this stays a localized change.

## 3. Data model — Lakebase `connectors` (schema `app`)
```
provider      TEXT PRIMARY KEY          -- 'gdrive', 'sharepoint', ...
display_name  TEXT NOT NULL DEFAULT ''
client_id     TEXT NOT NULL DEFAULT ''
redirect_uri  TEXT NOT NULL DEFAULT ''
scopes        JSONB NOT NULL DEFAULT '[]'::jsonb
secret_ref    TEXT NOT NULL DEFAULT ''   -- e.g. 'docintel_connectors/gdrive_client_secret' — a POINTER, never the secret
status        TEXT NOT NULL DEFAULT 'unconfigured'  -- unconfigured | configured | authorized
updated_by    TEXT NOT NULL DEFAULT ''
updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
```
Added to `db/schema.py` DDL (+ idempotent). New `db/repositories/connectors_repo.py` + `operational.py` facade wrappers.

## 4. Secret storage — scope `docintel_connectors`
- **Phase 0 (one-time, operator/CLI):** create scope; `databricks secrets put-acl docintel_connectors <main-SP> WRITE`; `... <sources-SP> READ`.
- Keys per provider: `{provider}_client_secret` (and, so the sources app is self-sufficient without Lakebase, also `{provider}_client_id`, `{provider}_redirect_uri`, `{provider}_scopes`).
- New `secret_store.py` (main app): `put_connector_secret(provider, client_id, client_secret, redirect_uri, scopes)` and `secret_exists(provider)` via `WorkspaceClient().secrets`. Never reads the secret back to the caller.

## 5. Backend (main app) — `/api/connectors`
- `GET /api/connectors` — list from Lakebase; **secrets stripped** (return only `status`, and `client_id` last-4 or a `configured: bool`).
- `POST /api/connectors` — body `{provider, display_name, client_id, client_secret, redirect_uri?, scopes?}`; upsert config → Lakebase (`secret_ref`, `status='configured'`), write secret → scope. `redirect_uri` defaults to the sources app callback. `client_secret` is required only when (re)setting it; omitting it on edit keeps the existing secret. **The secret is never returned.**
- `DELETE /api/connectors/{provider}` — remove config row + best-effort delete the scope key.
- `GET /api/connectors/{provider}/authorize-url` — returns the sources app `/oauth/{provider}/start` URL.
- Correlation IDs; structured logs that **exclude** the secret.

## 6. Sources server — provider-parameterized credentials
Generalize `oauth.py`: replace hard-coded `GOOGLE_OAUTH_*` reads with a `_resolve(provider)` that reads `{provider}_client_id/secret/redirect_uri/scopes` from the scope via SDK at runtime (short TTL cache), falling back to the legacy `GOOGLE_OAUTH_*` env when the scope has nothing (backward compat / the current env path). `GoogleOAuth` becomes `ProviderOAuth(provider)`; `/oauth/google/start|callback` generalize to `/oauth/{provider}/start|callback` (keep `/oauth/google/*` as aliases). No new connector classes here (SharePoint is the fast follow).

## 7. Frontend — Connectors panel (on the Sources page)
- List of connectors with status chips (`unconfigured`/`configured`/`authorized`).
- **Add / Configure connector** form: provider (select), display name, client ID, **client secret** (masked `password` input, write-only — never populated from the server), redirect URI (auto-filled to the sources callback, read-only), scopes (chips/textarea). Save → `POST /api/connectors`.
- **Authorize** button → opens `authorize-url` in a new tab (the OAuth consent flow), then reflects `authorized` status.
- A persistent note: "Connector credentials are shared across this app's users and are sensitive."
- Secret input cleared on submit; never echoed.

## 8. Security
Secret travels once over HTTPS behind workspace OAuth → straight to the scope. Never logged, never in git, never in a response body, never in the Lakebase row (only a `secret_ref` pointer). `GET` endpoints strip secrets. Any-user access is a deliberate demo choice (flagged in-UI); the `secret_store` seam makes adding role-gating later a small change.

## 9. Testing (offline, `.venv-test`, mocked)
- `connectors_repo` CRUD (fake conn); config round-trips, `secret_ref` stored, no secret column.
- `secret_store` writes via an injected fake `WorkspaceClient`; asserts the secret is passed to `put_secret` and **never** returned.
- `/api/connectors` routes (TestClient): `POST` writes config + calls secret_store; `GET` response contains **no** secret/`client_secret` field; omitting `client_secret` on edit preserves it; `DELETE` removes.
- Sources `oauth._resolve`: reads from an injected fake secret client; env fallback when scope empty; provider-parameterized.
- No live secrets in tests.

## 10. Phasing
- **P0** — spike + one-time setup: create scope `docintel_connectors`, grant both SPs, verify runtime put/get. *(operator/CLI; fallback documented)*
- **P1** — Lakebase `connectors` table + repo + facade + `secret_store.py`.
- **P2** — `/api/connectors` routes (main app).
- **P3** — sources server `oauth.py` provider-parameterized runtime resolve (+ env fallback).
- **P4** — Connectors panel UI.
- **P5** — deploy both apps; **demo setup**: enter the real Google client ID/secret via the UI (or seed the scope), user authorizes, crawl+index real Drive folders, verify search.

The demo's real Google client ID/secret + Drive folder IDs are user-supplied (only the user can create the Google OAuth client and folders); everything else is built + set up by this work.
