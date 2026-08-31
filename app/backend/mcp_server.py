"""In-app MCP server — exposes DocIntelligence as MCP tools, mounted at /mcp/.

Where mcp_sources.py makes this backend an MCP *client* of the external sources
server, this module makes the DocIntelligence backend itself an MCP *server*:
any MCP client (Claude Code/Desktop, Cursor, another agent) can connect to
`<app-url>/mcp/` and call the tools below. Each tool reuses an existing route
handler, so behavior stays identical to the REST API — no duplicated logic.

It is hosted inside the same FastAPI app (see `attach` + app.py), so it lives
behind the Databricks App's workspace-OAuth exactly like every other route; a
connecting client presents its bearer token the same way the sources client
does. Nothing to deploy separately.

NB: do NOT add `from __future__ import annotations` — FastMCP (<1.9) inspects
real param annotations at tool registration; stringized annotations make it call
issubclass() on a str and crash. (Same constraint as app/mcp-server/server.py.)
"""
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

# stateless_http + json_response mirrors app/mcp-server/server.py: safe for a
# multi-worker Databricks App and simplest for request/response tool clients.
mcp = FastMCP("docintel", stateless_http=True, json_response=True)
# Serve the endpoint at the mount root so mounting this app at "/mcp" yields the
# "/mcp/" endpoint the house convention expects (default would be "/mcp/mcp").
# Side effect: this root mount catches every path under /mcp/, so custom_route
# health/etc. can't coexist here — verify a deploy with an MCP `initialize` call
# (or the app's top-level /_health, which reports mcp_server: mounted).
mcp.settings.streamable_http_path = "/"


@mcp.tool()
async def list_domains() -> dict:
    """List the DocIntelligence domains (use cases) on this app, each with a
    document count. Returns {domains:[{domain_id,name,status,doc_count,...}], total}."""
    from platform_routes import list_domains as _list_domains
    try:
        return _list_domains()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def search_documents(query: str, domain_id: str = "supply_chain",
                           mode: str = "keyword", limit: int = 20) -> dict:
    """Search a domain's parsed documents. mode='keyword' (ILIKE substring, always
    available) or 'semantic' (ai_similarity ranking). Returns {results:[{doc_id,
    filename,doc_type,snippet,score?}], mode, total}."""
    from docintel_routes import search_docs
    try:
        return await search_docs(domain_id=domain_id, q=query, mode=mode, limit=limit)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def list_documents(domain_id: str = "supply_chain", doc_types: str = "") -> dict:
    """List a domain's documents grouped by type. `doc_types` is an optional
    comma-separated filter (e.g. 'invoice,contract'). Returns {by_type:{<type>:[
    {doc_id,filename,doc_type,processed_ts}]}}."""
    from docintel_routes import docs_by_type
    try:
        return await docs_by_type(domain_id=domain_id, doc_types=doc_types)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def query_agent(question: str, domain_id: str = "supply_chain",
                      incident_ref: str = "") -> dict:
    """Ask the DocIntelligence AI agent a natural-language question. It retrieves
    relevant document context and answers with citations. `incident_ref` optionally
    focuses the answer on a specific incident. Returns the agent's answer payload."""
    from docintel_routes import agent_query, AgentQueryRequest
    try:
        req = AgentQueryRequest(question=question, incident_ref=(incident_ref or None))
        return await agent_query(req, domain_id=domain_id)
    except Exception as e:
        return {"error": str(e)}


def attach(parent_app) -> None:
    """Mount this MCP server at /mcp/ on `parent_app` and wire the Streamable-HTTP
    session-manager lifespan (required even in stateless mode, or requests fail
    with 'Task group is not initialized'). Call BEFORE the app's catch-all route
    is registered so /mcp/* isn't swallowed by static routing."""
    mcp_asgi = mcp.streamable_http_app()  # builds mcp.session_manager

    @asynccontextmanager
    async def _lifespan(_app):
        async with mcp.session_manager.run():
            yield

    parent_app.router.lifespan_context = _lifespan
    parent_app.mount("/mcp", mcp_asgi)
