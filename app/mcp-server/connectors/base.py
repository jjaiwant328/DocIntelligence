"""Pluggable document-source connector interface.

A connector reads documents from ONE external source (Google Drive today; Gmail
/ SharePoint later). It only talks to the external service — landing bytes in a
UC Volume and running the pipeline stays in the DocIntelligence backend. Every
connector returns the same two shapes so the MCP tools and the backend don't
care which source they're talking to:

  list_documents -> {"items": [DocMeta, ...]}
      DocMeta = {doc_ref, name, mime_type, size, modified, folder, doc_type_hint}
  fetch_document -> {doc_ref, name, filename, mime_type, content_b64}
"""
from __future__ import annotations

from typing import Optional


class Connector:
    id: str = "base"
    name: str = "Base"

    def describe(self) -> dict:
        """Source id/name + whether it's live (real API) or synthetic demo data,
        and whether a real connection is currently authorized."""
        raise NotImplementedError

    def list_documents(self, folder_id: str = "", query: str = "") -> dict:
        raise NotImplementedError

    def fetch_document(self, doc_ref: str) -> dict:
        raise NotImplementedError

    # ── metadata / crawl API ─────────────────────────────────────────────────

    def list_children(self, folder_id: str = "") -> dict:
        """Return {items:[<metadata dict>]} for items directly under folder_id
        (root if empty). Metadata shape: {item_id, name, path, mime_type, size,
        web_url, etag, modified_at, owner, is_folder}."""
        raise NotImplementedError

    def get_file_metadata(self, item_id: str) -> dict:
        """Return a single <metadata dict> for item_id."""
        raise NotImplementedError

    def get_changes(self, since_token: str = "") -> dict:
        """Return {items:[<metadata dict>], next_token} for items changed since
        since_token (empty string = initial full sync). Pass next_token back on
        the next call to advance the cursor."""
        raise NotImplementedError

    def check_access(self, item_id: str) -> dict:
        """Return {accessible:bool, reason:str} for item_id."""
        raise NotImplementedError

    def get_source_url(self, item_id: str) -> str:
        """Return the web view URL string for item_id."""
        raise NotImplementedError


_REGISTRY: dict[str, Connector] = {}


def register(conn: Connector) -> None:
    _REGISTRY[conn.id] = conn


def get(source: str) -> Optional[Connector]:
    return _REGISTRY.get(source)


def all_sources() -> list[dict]:
    return [c.describe() for c in _REGISTRY.values()]
