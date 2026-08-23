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


_REGISTRY: dict[str, Connector] = {}


def register(conn: Connector) -> None:
    _REGISTRY[conn.id] = conn


def get(source: str) -> Optional[Connector]:
    return _REGISTRY.get(source)


def all_sources() -> list[dict]:
    return [c.describe() for c in _REGISTRY.values()]
