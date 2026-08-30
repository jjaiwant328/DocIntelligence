"""Source registration, crawl trigger, inventory, index-jobs, and search routes.

  GET   /api/sources                              list registered sources
  POST  /api/sources                              register a source (validates credential_ref)
  GET   /api/sources/{id}/auth-url                OAuth start URL for a source
  POST  /api/sources/{id}/crawl                   trigger a metadata crawl (no content copy)
  GET   /api/inventory?domain_id=&project_id=     list external documents for a project
  PATCH /api/documents/{external_document_id}/included  persist inclusion flag
  POST  /api/index-jobs                           create + launch an index job (background)
  GET   /api/index-jobs/{job_id}                  get a single index job
  GET   /api/index-jobs?domain_id=&project_id=    list index jobs for a project
  POST  /api/search                               hybrid vector+FTS search
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
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


# ── Document inclusion toggle ──────────────────────────────────────────────────

class IncludedRequest(BaseModel):
    included: bool


@router.patch("/documents/{external_document_id}/included")
def set_included(external_document_id: str, req: IncludedRequest):
    """Persist the inclusion flag for a single document.

    The indexer reads *included* at run time; setting it to False before a
    Build/Refresh run prevents the document from being (re-)indexed.
    """
    opstore.set_doc_included(external_document_id, req.included)
    return {"external_document_id": external_document_id, "included": req.included}


# ── Index-job routes ───────────────────────────────────────────────────────────

class IndexJobRequest(BaseModel):
    source_id:  str
    domain_id:  str
    project_id: str
    scope:      str = "project"
    scope_ref:  str = ""
    requested_by: str = "app_user"


def _run_index_job_task(
    job_id: str,
    source_id: str,
    provider: str,
    domain_id: str,
    project_id: str,
    scope: str,
    scope_ref: str,
) -> None:
    """Background task: opens its own Lakebase connection and runs the pipeline.

    Called by FastAPI BackgroundTasks after the HTTP response is sent.
    Uses its own connection — never the request-scoped connection.
    """
    from indexer.pipeline import run_index_job
    with lakebase.connection() as conn:
        asyncio.run(
            run_index_job(
                job_id, source_id, provider, domain_id, project_id,
                scope=scope, scope_ref=scope_ref,
                conn=conn,
            )
        )


@router.post("/index-jobs")
def create_index_job(req: IndexJobRequest, background_tasks: BackgroundTasks):
    """Create an index-job row and launch the pipeline as a background task.

    The source must already be registered. Returns {job_id} immediately;
    the actual indexing runs asynchronously.
    """
    source = opstore.get_source(req.source_id)
    if source is None:
        raise HTTPException(
            status_code=404,
            detail=f"source '{req.source_id}' not found — register it first",
        )

    job_id = str(uuid.uuid4())
    opstore.create_index_job(
        job_id,
        req.domain_id,
        req.project_id,
        req.scope,
        req.scope_ref,
        req.requested_by,
    )

    background_tasks.add_task(
        _run_index_job_task,
        job_id,
        req.source_id,
        source.get("provider", req.source_id),
        req.domain_id,
        req.project_id,
        req.scope,
        req.scope_ref,
    )

    return {"job_id": job_id}


@router.get("/index-jobs/{job_id}")
def get_index_job(job_id: str):
    """Return a single index job by ID."""
    job = opstore.get_index_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")
    return {"job": job}


@router.get("/index-jobs")
def list_index_jobs(domain_id: str = "", project_id: str = ""):
    """List all index jobs for a domain + project."""
    jobs = opstore.list_index_jobs(domain_id, project_id)
    return {"jobs": jobs, "total": len(jobs)}


# ── Search route ───────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    domain_id:  str
    project_id: str
    query:      str
    k:          int = 10
    folder:     str = ""
    types:      Optional[list[str]] = None


def _search_backend():
    """Factory for the search backend. Monkeypatchable in tests."""
    from search.lakebase_search import LakebaseSearch
    return LakebaseSearch()


@router.post("/search")
def search_documents(req: SearchRequest):
    """Hybrid vector + FTS search over indexed documents.

    Returns up to *k* ranked chunks with their source document metadata.
    """
    backend = _search_backend()
    results = backend.search(
        req.domain_id,
        req.project_id,
        req.query,
        k=req.k,
        folder=req.folder,
        types=req.types,
    )
    return {
        "domain_id":  req.domain_id,
        "project_id": req.project_id,
        "query":      req.query,
        "results":    results,
        "total":      len(results),
    }
