"""Document-source MCP server (hosted as a Databricks App).

A standalone Model Context Protocol server that reads documents from external
sources — Google Drive today, behind a pluggable connector interface. Exposes
Streamable HTTP at /mcp (consumed by the DocIntelligence backend as an MCP
client) plus Google OAuth + health routes. Runs on seeded synthetic data until
Google OAuth secrets are configured, then serves live Drive.

Tools:
  list_sources()                              -> [{id,name,mode,connected}]
  list_documents(source, folder_id, query)    -> {items:[DocMeta]}
  fetch_document(source, doc_ref)              -> {doc_ref,name,filename,mime_type,content_b64}
  fetch_documents(source, doc_refs)            -> {items:[...]}
"""
# NB: do NOT add `from __future__ import annotations` — FastMCP (<1.9) inspects
# real param annotations to find its Context arg; stringized annotations make it
# call issubclass() on a str and crash at tool registration.
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from mcp.server.fastmcp import FastMCP

from connectors import base as registry
from connectors.gdrive import GoogleDriveConnector
from oauth import GoogleOAuth

_oauth = GoogleOAuth()
registry.register(GoogleDriveConnector(_oauth))

# stateless_http + json_response: safe for a multi-worker Databricks App and
# simplest for a request/response tool client (no long-lived SSE session).
mcp = FastMCP("docintel-sources", stateless_http=True, json_response=True)


def _connector(source: str):
    conn = registry.get(source)
    if conn is None:
        raise ValueError(f"unknown source '{source}'")
    return conn


@mcp.tool()
def list_sources() -> list[dict]:
    """List the document sources this server can read, and whether each is on
    live (real API) or synthetic demo data and currently connected."""
    return registry.all_sources()


@mcp.tool()
def list_documents(source: str, folder_id: str = "", query: str = "") -> dict:
    """List documents available in a source, optionally filtered by folder and a
    name/keyword query. Returns {items:[{doc_ref,name,mime_type,size,modified,
    folder,doc_type_hint}]}."""
    return _connector(source).list_documents(folder_id=folder_id, query=query)


@mcp.tool()
def fetch_document(source: str, doc_ref: str) -> dict:
    """Fetch one document's bytes (base64). Google-native docs are exported to a
    portable format. Returns {doc_ref,name,filename,mime_type,content_b64}."""
    return _connector(source).fetch_document(doc_ref)


@mcp.tool()
def fetch_documents(source: str, doc_refs: list[str]) -> dict:
    """Fetch several documents at once. Returns {items:[fetch_document result]}."""
    conn = _connector(source)
    return {"items": [conn.fetch_document(r) for r in doc_refs]}


# ── plain HTTP routes (health + Google OAuth consent) ─────────────────────────
@mcp.custom_route("/health", methods=["GET"])
async def health(_req: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "sources": registry.all_sources()})


@mcp.custom_route("/oauth/google/start", methods=["GET"])
async def oauth_start(request: Request):
    if not _oauth.configured:
        return JSONResponse({"error": "Google OAuth is not configured (synthetic mode)."}, status_code=400)
    return RedirectResponse(_oauth.start_url(state=request.query_params.get("state", "")))


@mcp.custom_route("/oauth/google/callback", methods=["GET"])
async def oauth_callback(request: Request):
    err = request.query_params.get("error")
    if err:
        return JSONResponse({"error": err}, status_code=400)
    code = request.query_params.get("code")
    if not code:
        return JSONResponse({"error": "missing code"}, status_code=400)
    try:
        _oauth.exchange_code(code)
    except Exception as e:
        return JSONResponse({"error": f"token exchange failed: {e}"}, status_code=400)
    return JSONResponse({"connected": True, "message": "Google Drive connected — you can close this tab."})


# ASGI entrypoint for `uvicorn server:app`.
app = mcp.streamable_http_app()
