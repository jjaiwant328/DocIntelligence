"""Metadata crawler: walks an external source tree, upserts one row per file
(no content copy), and returns a seen-IDs set for stale-deletion.

Usage::

    result = await crawl_source(
        source_id="gdrive",
        provider="gdrive",
        domain_id="compliance_due_diligence",
        project_id="proj-abc",
        root_folder="",          # empty = drive root
    )
    # {discovered: int, folders: int, seen_ids: set[str]}

Inject *mcp* and *repo* in tests to avoid hitting the live MCP server or DB.
"""
from __future__ import annotations

from typing import Any

import mcp_sources as _default_mcp
from db.repositories import external_docs_repo as _default_repo

# Refuse to recurse deeper than this to guard against cycles / huge drives.
_MAX_DEPTH = 10


async def crawl_source(
    source_id: str,
    provider: str,
    domain_id: str,
    project_id: str,
    root_folder: str = "",
    *,
    mcp: Any = _default_mcp,
    repo: Any = _default_repo,
    conn: Any,
) -> dict:
    """Recursively walk *source_id* starting from *root_folder*.

    For every file found, compute a stable doc-id, then upsert a metadata row
    via *repo*. Folders are traversed but never upserted.

    Returns:
        ``{"discovered": int, "folders": int, "seen_ids": set[str]}``
    """
    discovered: int = 0
    folders: int = 0
    seen_ids: set[str] = set()

    async def _walk(folder_id: str, depth: int) -> None:
        nonlocal discovered, folders
        if depth > _MAX_DEPTH:
            return
        items = await mcp.list_children(source_id, folder_id)
        for item in items or []:
            if item.get("is_folder"):
                folders += 1
                await _walk(item["item_id"], depth + 1)
            else:
                doc_id = repo.stable_doc_id(
                    provider, "", source_id, item["item_id"]
                )
                seen_ids.add(doc_id)
                repo.upsert_metadata(conn, {
                    "external_document_id": doc_id,
                    "source_id": source_id,
                    "domain_id": domain_id,
                    "project_id": project_id,
                    "parent_folder_id": folder_id,
                    "path": item.get("path", ""),
                    "name": item.get("name", ""),
                    "mime_type": item.get("mime_type", ""),
                    "size_bytes": item.get("size", 0),
                    "web_url": item.get("web_url", ""),
                    "etag": item.get("etag", ""),
                    "owner": item.get("owner", ""),
                    "source_modified_at": item.get("modified_at"),
                })
                discovered += 1

    await _walk(root_folder, 0)
    return {"discovered": discovered, "folders": folders, "seen_ids": seen_ids}
