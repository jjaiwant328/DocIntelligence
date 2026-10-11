"""MCP client for the document-source server (a separate Databricks App).

The DocIntelligence backend is the MCP *client*: it connects to the sources MCP
server over Streamable HTTP (mcp<1.9, same dialect both sides) and calls its
tools to browse and fetch documents from external sources (Google Drive today).
Landing bytes in the UC Volume and running the pipeline stays in the backend
(see the /sources routes) — the MCP server only reads the external source.

Cross-app auth: the sources server is another Databricks App behind workspace
OAuth, so we present this app's service-principal token. The backend SP needs
"Can Use" on the sources app.
"""
from __future__ import annotations

import json
import os
from typing import Any


def sources_base() -> str:
    return os.environ.get("DOCINTEL_MCP_SOURCES_URL", "").rstrip("/")


def configured() -> bool:
    return bool(sources_base())


def _endpoint() -> str:
    # Trailing slash is REQUIRED: FastMCP mounts at /mcp/ and Starlette 307-redirects
    # /mcp -> an internal localhost URL the client can't follow (breaks the call).
    return f"{sources_base()}/mcp/"


def auth_url(source: str = "gdrive") -> str:
    """Where the frontend sends the user to authorize a real source connection."""
    return f"{sources_base()}/oauth/google/start"


def _bearer() -> dict:
    try:
        from databricks.sdk import WorkspaceClient
        return WorkspaceClient().config.authenticate() or {}
    except Exception as e:
        print(f"[mcp_sources] could not mint auth header: {e}")
        return {}


def _payload(result) -> Any:
    """Tolerate either structured content or JSON-in-text (mcp<1.9 uses text).
    A tool returning a bare list serializes as one text block per item, so we
    gather all blocks: 1 block -> that value, many -> a list."""
    sc = getattr(result, "structuredContent", None)
    if sc:
        return sc
    parsed = []
    for c in getattr(result, "content", []) or []:
        t = getattr(c, "text", None)
        if t is None:
            continue
        try:
            parsed.append(json.loads(t))
        except Exception:
            parsed.append({"text": t})
    if not parsed:
        return {}
    return parsed[0] if len(parsed) == 1 else parsed


def _as_list(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("sources", []) or []
    return []


async def _call(tool: str, args: dict) -> Any:
    if not configured():
        raise RuntimeError("DOCINTEL_MCP_SOURCES_URL is not set — the sources MCP server is not wired.")
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(_endpoint(), headers=_bearer()) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return _payload(await session.call_tool(tool, args))


async def list_sources() -> list:
    return _as_list(await _call("list_sources", {}))


async def list_documents(source: str, folder: str = "", query: str = "") -> Any:
    return await _call("list_documents", {"source": source, "folder_id": folder, "query": query})


async def fetch_document(source: str, doc_ref: str) -> Any:
    return await _call("fetch_document", {"source": source, "doc_ref": doc_ref})


# ── Metadata tools (Phase 2) ──────────────────────────────────────────────────

async def list_children(source: str, folder_id: str = "") -> list:
    """List immediate children (files + sub-folders) of a folder.

    The sources server returns ``{"items": [...]}`` for this tool (unlike
    ``list_sources`` which returns ``{"sources": [...]}``), so unwrap ``items``
    here rather than via ``_as_list``.
    """
    result = await _call("list_children", {"source": source, "folder_id": folder_id})
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("items", []) or []
    return []


async def get_file_metadata(source: str, item_id: str) -> dict:
    """Return metadata for a single file/folder by its item_id."""
    return await _call("get_file_metadata", {"source": source, "item_id": item_id})


async def get_changes(source: str, since_token: str = "") -> dict:
    """Return items changed since *since_token*. Result: {items, next_token}."""
    return await _call("get_changes", {"source": source, "since_token": since_token})


async def check_access(source: str, item_id: str) -> dict:
    """Check whether the service account can read/download an item."""
    return await _call("check_access", {"source": source, "item_id": item_id})


async def get_source_url(source: str, item_id: str) -> str:
    """Return the external web URL for an item.

    Checks the most common key names across sources (url, web_url,
    webViewLink — Google Drive's actual field — and web_view_link).
    Returns "" (not the string "None") when no URL-like key is present.
    """
    result = await _call("get_source_url", {"source": source, "item_id": item_id})
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("url", "web_url", "webViewLink", "web_view_link"):
            val = result.get(key)
            if val:
                return val
        return ""
    return ""
