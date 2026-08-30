"""Source registration, crawl trigger, and inventory routes.

  GET  /api/sources                          list registered sources
  POST /api/sources                          register a source (validates credential_ref)
  GET  /api/sources/{id}/auth-url            OAuth start URL for a source
  POST /api/sources/{id}/crawl               trigger a metadata crawl (no content copy)
  GET  /api/inventory?domain_id=&project_id= list external documents for a project
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import mcp_sources
from db import lakebase
from db import operational as opstore

router = APIRouter(prefix="/api", tags=["Sources"])


# ── Request models ─────────────────────────────────────────────────────────────

class SourceRegisterRequest(BaseModel):
    source_id: str
    provider: str
    display_name: str
    auth_mode: str = ""
    credential_ref: str = ""
    site: str = ""
    mode: str = "live"


class CrawlRequest(BaseModel):
    domain_id: str
    project_id: str
    root_folder: str = ""


# ── Seam for testability: the crawl import is deferred so tests can patch it ──

async def _crawl_source(**kwargs):
    """Thin wrapper so tests can monkeypatch `source_routes._crawl_source`."""
    from indexer.crawl import crawl_source
    return await crawl_source(**kwargs)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/sources")
def list_sources():
    """List all registered sources from the operational store."""
    return {"sources": opstore.list_sources()}


@router.post("/sources")
def register_source(req: SourceRegisterRequest):
    """Register (or update) a source connection.

    *credential_ref* must be empty or a reference string such as
    ``keeper://path/to/secret``. A non-empty value that does not look like a
    reference is rejected with HTTP 400 so that raw secrets are never stored
    or logged.
    """
    cred = (req.credential_ref or "").strip()
    if cred and not cred.startswith("keeper://"):
        raise HTTPException(
            status_code=400,
            detail=(
                "credential_ref must be a reference (e.g. keeper://...) or empty — "
                "never store a raw secret here"
            ),
        )
    row = opstore.upsert_source(
        req.source_id, req.provider, req.display_name,
        req.auth_mode, cred, req.site, req.mode,
    )
    return {"source": row}


@router.get("/sources/{source_id}/auth-url")
def get_auth_url(source_id: str):
    """Return the OAuth authorization URL for a source."""
    return {"url": mcp_sources.auth_url(source_id)}


@router.post("/sources/{source_id}/crawl")
async def crawl_source_route(source_id: str, req: CrawlRequest):
    """Trigger a metadata crawl for *source_id*.

    Looks up the registered source to get its canonical provider (e.g.
    "gdrive"), opens a Lakebase connection, then runs the metadata walk.
    Recursively lists folders and upserts one metadata row per file — no
    content is copied. Returns the counts from the walk.
    """
    row = opstore.get_source(source_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"source '{source_id}' not found")
    with lakebase.connection() as conn:
        result = await _crawl_source(
            source_id=source_id,
            provider=row["provider"],
            domain_id=req.domain_id,
            project_id=req.project_id,
            root_folder=req.root_folder,
            conn=conn,
        )
    return {
        "source_id": source_id,
        "discovered": result["discovered"],
        "folders": result["folders"],
        "seen_ids": sorted(result["seen_ids"]),
    }


@router.get("/inventory")
def inventory(domain_id: str = "", project_id: str = ""):
    """List external documents for a domain + project with status chips."""
    rows = opstore.list_docs_for_project(domain_id, project_id)
    status_counts: dict[str, int] = {}
    for r in rows:
        s = r.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1
    return {
        "domain_id": domain_id,
        "project_id": project_id,
        "documents": rows,
        "total": len(rows),
        "status_counts": status_counts,
    }
