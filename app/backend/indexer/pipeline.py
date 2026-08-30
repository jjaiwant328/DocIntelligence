"""On-demand index-job pipeline.

Orchestrates: crawl (optional) → diff → per-file fetch/parse/chunk/embed/
store → job-status accounting. All dependencies are injectable via
PipelineDeps so the pipeline can be tested fully offline.

Usage (production)::

    from indexer.pipeline import run_index_job, PipelineDeps
    result = await run_index_job(
        job_id, source_id, provider, domain_id, project_id,
        scope="project", scope_ref="",
        deps=PipelineDeps(),      # uses real modules
        conn=<lakebase connection>,
    )
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from indexer import chunk as _chunk_mod
from indexer import diff as _diff_mod
from indexer import embed as _embed_mod
from indexer import parse as _parse_mod
from db.repositories import chunks_repo as _chunks_repo
from db.repositories import external_docs_repo as _docs_repo
from db.repositories import index_jobs_repo as _jobs_repo
import mcp_sources as _mcp


# ── Injectable deps bundle ─────────────────────────────────────────────────────

@dataclass
class PipelineDeps:
    """All external dependencies for run_index_job, bundled for injection.

    Production code uses the module-level defaults (real modules); tests
    supply fakes via the constructor.
    """
    # Async crawl function — signature matches indexer.crawl.crawl_source
    crawl_fn: Callable = field(default=None)  # type: ignore[assignment]

    # Optional override for diff.plan_scope (tests can pre-set the plan)
    plan_scope_fn: Callable = field(default=None)  # type: ignore[assignment]

    # Async document fetch: (source, doc_ref) -> {content_b64, filename}
    fetch_fn: Callable = field(default=None)  # type: ignore[assignment]

    # Text extraction: (filename, content_bytes) -> str
    parse_fn: Callable = field(default=None)  # type: ignore[assignment]

    # Chunker: (text, *, size, overlap) -> list[str]
    chunk_split_fn: Callable = field(default=None)  # type: ignore[assignment]

    # Chunk ID: (doc_id, ordinal) -> str
    chunk_id_fn: Callable = field(default=None)  # type: ignore[assignment]

    # Embedding: (list[str]) -> list[list[float]]
    embed_fn: Callable = field(default=None)  # type: ignore[assignment]

    # Repo objects (duck-typed)
    chunks_repo: Any = field(default=None)
    docs_repo:   Any = field(default=None)
    jobs_repo:   Any = field(default=None)

    def __post_init__(self):
        """Fill in real-module defaults for any field left as None."""
        if self.crawl_fn is None:
            from indexer.crawl import crawl_source
            self.crawl_fn = crawl_source
        if self.plan_scope_fn is None:
            self.plan_scope_fn = _diff_mod.plan_scope
        if self.fetch_fn is None:
            self.fetch_fn = _mcp.fetch_document
        if self.parse_fn is None:
            self.parse_fn = _parse_mod.extract_text
        if self.chunk_split_fn is None:
            self.chunk_split_fn = _chunk_mod.split
        if self.chunk_id_fn is None:
            self.chunk_id_fn = _chunk_mod.chunk_id
        if self.embed_fn is None:
            self.embed_fn = _embed_mod.embed_texts
        if self.chunks_repo is None:
            self.chunks_repo = _chunks_repo
        if self.docs_repo is None:
            self.docs_repo = _docs_repo
        if self.jobs_repo is None:
            self.jobs_repo = _jobs_repo


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_index_job(
    job_id: str,
    source_id: str,
    provider: str,
    domain_id: str,
    project_id: str,
    scope: str,
    scope_ref: str,
    *,
    deps: Optional[PipelineDeps] = None,
    conn: Any,
) -> dict:
    """Run an index job end-to-end.

    Args:
        job_id:     The pre-created job row ID.
        source_id:  Source to crawl/fetch from.
        provider:   Provider string (e.g. "gdrive").
        domain_id:  Domain scope.
        project_id: Project scope.
        scope:      "project" or "folder" → triggers crawl;
                    "doc" → single-document index (scope_ref = doc_id).
        scope_ref:  Folder path or doc ID depending on scope.
        deps:       Injectable dependency bundle (uses real modules if None).
        conn:       Open Lakebase connection for all DB operations in this job.

    Returns:
        Summary dict with keys: embedded, skipped, deleted, failed.
    """
    if deps is None:
        deps = PipelineDeps()

    embed_model = os.getenv("EMBED_MODEL", "databricks-gte-large-en")
    retain_raw  = bool(os.getenv("INDEX_RETAIN_RAW"))

    counters = {"embedded": 0, "skipped": 0, "deleted": 0, "failed": 0}

    # ── 1. Start job ──────────────────────────────────────────────────────────
    deps.jobs_repo.start(conn, job_id)

    # ── 2. Crawl (if scope requires it) ───────────────────────────────────────
    seen_docs: list[dict] = []

    if scope in ("project", "folder"):
        crawl_result = await deps.crawl_fn(
            source_id=source_id,
            provider=provider,
            domain_id=domain_id,
            project_id=project_id,
            root_folder=scope_ref if scope == "folder" else "",
            conn=conn,
        )
        deps.jobs_repo.bump(conn, job_id, discovered=crawl_result.get("discovered", 0))

        # Build seen_docs from the crawl result (seen_ids)
        seen_ids_from_crawl = crawl_result.get("seen_ids", set())
        # Get the actual metadata rows from DB (they were upserted by crawl)
        all_docs = deps.docs_repo.list_for_project(conn, domain_id, project_id)
        seen_docs = [d for d in all_docs if d["external_document_id"] in seen_ids_from_crawl]
    elif scope == "doc":
        doc = deps.docs_repo.list_for_project(conn, domain_id, project_id)
        seen_docs = [d for d in doc if d["external_document_id"] == scope_ref]

    # ── 3. Diff: determine what to index and what to delete ──────────────────
    plan = deps.plan_scope_fn(conn, domain_id, project_id, seen_docs, deps.docs_repo)
    to_index  = plan["to_index"]
    to_delete = plan["to_delete"]
    counters["skipped"] = plan.get("skipped", 0)

    # ── 4. Index changed/new docs ─────────────────────────────────────────────
    for doc_id in to_index:
        try:
            # Find doc metadata (need name/path for parse)
            doc_meta = next(
                (d for d in seen_docs if d["external_document_id"] == doc_id),
                {"name": doc_id, "etag": "", "path": ""},
            )

            # Fetch content
            fetch_result = await deps.fetch_fn(source_id, doc_id)
            raw_bytes = base64.b64decode(fetch_result.get("content_b64", ""))
            filename  = fetch_result.get("filename", doc_meta.get("name", doc_id))

            # Parse
            text = deps.parse_fn(filename, raw_bytes)
            if not text:
                deps.docs_repo.set_status(conn, doc_id, "failed",
                                          "empty text after extraction")
                counters["failed"] += 1
                continue

            # Chunk
            snippets = deps.chunk_split_fn(text)
            chunks   = [
                {
                    "chunk_id":             deps.chunk_id_fn(doc_id, i),
                    "external_document_id": doc_id,
                    "domain_id":            domain_id,
                    "project_id":           project_id,
                    "ordinal":              i,
                    "location":             f"chunk:{i}",
                    "snippet":              s,
                    "source_version":       doc_meta.get("etag", ""),
                    "index_version":        1,
                }
                for i, s in enumerate(snippets)
            ]

            # Embed
            embeddings = deps.embed_fn([c["snippet"] for c in chunks])
            for c, vec in zip(chunks, embeddings):
                c["embedding"] = vec

            # Discard raw content unless retention is requested
            if not retain_raw:
                raw_bytes = b""

            # Store
            deps.chunks_repo.replace_chunks(conn, doc_id, chunks)
            deps.docs_repo.mark_indexed(
                conn, doc_id,
                index_version=1,
                embedding_model=embed_model,
                etag=doc_meta.get("etag", ""),
                chunk_count=len(chunks),
            )
            counters["embedded"] += 1
            deps.jobs_repo.bump(conn, job_id, embedded=1)

        except Exception as exc:
            deps.docs_repo.set_status(conn, doc_id, "failed", str(exc))
            counters["failed"] += 1
            deps.jobs_repo.bump(conn, job_id, failed=1)

    # ── 5. Delete removed docs ────────────────────────────────────────────────
    for doc_id in to_delete:
        try:
            deps.chunks_repo.delete_for_doc(conn, doc_id)
            deps.docs_repo.set_status(conn, doc_id, "deleted")
            counters["deleted"] += 1
            deps.jobs_repo.bump(conn, job_id, deleted=1)
        except Exception as exc:
            deps.docs_repo.set_status(conn, doc_id, "failed", str(exc))
            counters["failed"] += 1
            deps.jobs_repo.bump(conn, job_id, failed=1)

    # ── 6. Finish job ─────────────────────────────────────────────────────────
    final_status = "done"
    deps.jobs_repo.finish(conn, job_id, final_status)

    return counters
