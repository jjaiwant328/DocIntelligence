"""Managed-MCP Google Drive source adapter (on-behalf-of the calling user).

Where `mcp_sources` makes the backend an MCP *client of our own sources app*
(service-principal auth, blocked for a user's personal Drive), this adapter
talks to the Databricks-managed `system.ai.google_drive` AI-Gateway MCP as the
*calling user*, so it sees that user's own Drive with no OAuth client.

It exposes the same two shapes the connector-first indexer consumes:
  list_children(folder_id) -> [ {item_id, is_folder, name, mime_type, size,
                                 web_url, etag, modified_at, owner, path}, ... ]
  fetch_document(item_id)  -> {content_b64, filename}

The MCP transport is INJECTED (`call_tool`) so this module is offline-testable
and free of any `mcp`-version coupling — the runner wires the real client.
"""
from __future__ import annotations

import base64
from typing import Any, Callable

# Google Workspace mime types the managed MCP CAN return as text. Binary files
# (application/pdf, images, …) are unsupported by google_file_download and are
# skipped by the crawler rather than fetched.
_FOLDER_MIME = "application/vnd.google-apps.folder"
TEXT_READABLE_MIMES = {
    "text/plain",
    "text/csv",
    "text/markdown",
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
}


def is_text_readable(mime_type: str) -> bool:
    """True if the managed MCP can return this file's content as text."""
    return mime_type in TEXT_READABLE_MIMES


def map_search_item(raw: dict) -> dict:
    """Map one google_drive_search result to the indexer's metadata shape."""
    mime = raw.get("mimeType", "")
    owners = raw.get("owners") or []
    owner = ""
    if owners and isinstance(owners, list):
        owner = owners[0].get("emailAddress", "") if isinstance(owners[0], dict) else ""
    return {
        "item_id": raw.get("id", ""),
        "is_folder": mime == _FOLDER_MIME,
        "name": raw.get("name", ""),
        "mime_type": mime,
        "size": int(raw.get("size", 0) or 0),
        "web_url": raw.get("webViewLink", ""),
        # No cheap content etag from search; modifiedTime is a stable change token.
        "etag": raw.get("modifiedTime", ""),
        "modified_at": raw.get("modifiedTime", ""),
        "owner": owner,
        "path": "",
    }


class ManagedDriveSource:
    """Adapter over the managed system.ai.google_drive MCP.

    `call_tool(tool_name, args) -> dict` is injected: it must invoke the MCP tool
    and return the parsed JSON object (the runner supplies a real client; tests
    supply a fake).
    """

    def __init__(self, call_tool: Callable[[str, dict], dict], root_folder_id: str):
        self._call = call_tool
        self._root = root_folder_id

    def list_children(self, folder_id: str = "") -> list[dict]:
        parent = folder_id or self._root
        resp = self._call(
            "google_drive_search",
            {"query": f"'{parent}' in parents and trashed = false", "max_results": 200},
        )
        items = resp.get("items", []) if isinstance(resp, dict) else []
        return [map_search_item(it) for it in items]

    def fetch_document(self, item_id: str) -> dict:
        """Return {content_b64, filename}. Raises if the file is not text-readable."""
        resp = self._call("google_file_download", {"file_id": item_id})
        if not isinstance(resp, dict) or resp.get("error_code"):
            raise ValueError(
                f"cannot download {item_id}: {resp.get('error_code') if isinstance(resp, dict) else resp}"
            )
        content = resp.get("content", "")
        raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        return {
            "content_b64": base64.b64encode(raw).decode("ascii"),
            "filename": resp.get("name", item_id),
        }
