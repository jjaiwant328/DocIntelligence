# DocIntelligence — Document-source MCP server

A standalone **Model Context Protocol** server, hosted as its own Databricks App,
that reads documents from external sources (Google Drive today; Gmail/SharePoint
next) behind a pluggable connector. The DocIntelligence backend consumes it as an
MCP client and lands fetched documents into the UC Volume, where the normal
parse/skill pipeline takes over.

## Endpoints
- `/mcp` — Streamable HTTP MCP endpoint (tools: `list_sources`, `list_documents`,
  `fetch_document`, `fetch_documents`).
- `/health` — liveness + source status.
- `/oauth/google/start`, `/oauth/google/callback` — Google OAuth consent flow.

## Modes
- **Synthetic (default):** seeded, realistic supply-chain / AP documents. Works
  immediately, no OAuth. This is what the demo uses out of the box.
- **Live Google Drive:** activates when OAuth secrets are set (below).

## Deploy
```bash
./deploy.sh            # creates the app 'docintel-sources' (once) + deploys
databricks apps get docintel-sources --profile jai-az-ws   # get the URL
```
Then point the backend at it: set `DOCINTEL_MCP_SOURCES_URL` in
`app/backend/app.yaml` to the app URL and redeploy the backend. Also grant the
**backend app's service principal "Can Use"** on this app (cross-app auth).

## Enabling live Google Drive
1. In Google Cloud Console: create an OAuth 2.0 Client (type: Web application).
2. Add the redirect URI: `https://<this-app-url>/oauth/google/callback`.
3. Enable the Google Drive API; add scope `drive.readonly` on the consent screen.
4. Set as Databricks App secrets/env on THIS app:
   `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
   `GOOGLE_OAUTH_REDIRECT_URI` (= the callback URL above).
5. In DocIntelligence → Process Documents → Import from a source → **Connect
   Google Drive**, complete consent. `list_sources` then reports `mode: real`.

Note: the refresh token is cached to a file (`GDRIVE_TOKEN_PATH`) and is lost on
redeploy (re-consent needed). A UC/Lakebase-backed token store is a future
hardening.
