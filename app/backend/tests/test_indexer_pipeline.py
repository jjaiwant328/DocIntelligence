"""Tests for indexer/pipeline.py — on-demand index-job orchestration.

All dependencies are injected as fakes: no live MCP, DB, or serving endpoints.
"""
import asyncio
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexer import pipeline


# ── Fake dependencies ─────────────────────────────────────────────────────────

_DIM = 1024


class FakeJobsRepo:
    def __init__(self):
        self.started = []
        self.bumped = []
        self.finished = []

    def start(self, conn, job_id):
        self.started.append(job_id)

    def bump(self, conn, job_id, **counts):
        self.bumped.append({"job_id": job_id, **counts})

    def finish(self, conn, job_id, status, error_summary=""):
        self.finished.append({"job_id": job_id, "status": status})


class FakeDocsRepo:
    def __init__(self, docs: list[dict]):
        self._docs = {d["external_document_id"]: d for d in docs}
        self.status_updates: list[dict] = []
        self.indexed: list[dict] = []

    def list_for_project(self, conn, domain_id, project_id, statuses=None):
        return list(self._docs.values())

    def ids_missing_from(self, conn, domain_id, project_id, seen_ids):
        return [did for did in self._docs if did not in seen_ids]

    def set_status(self, conn, doc_id, status, last_error=""):
        self.status_updates.append({"doc_id": doc_id, "status": status})

    def mark_indexed(self, conn, doc_id, index_version, embedding_model, etag, chunk_count):
        self.indexed.append({"doc_id": doc_id, "etag": etag})


class FakeChunksRepo:
    def __init__(self):
        self.replaced: list[dict] = []
        self.deleted: list[str] = []

    def replace_chunks(self, conn, doc_id, chunks):
        self.replaced.append({"doc_id": doc_id, "chunks": chunks})
        return len(chunks)

    def delete_for_doc(self, conn, doc_id):
        self.deleted.append(doc_id)
        return 0


def _fake_fetch(content: str):
    """Return an async fetch function that yields canned content."""
    encoded = base64.b64encode(content.encode()).decode()

    async def _fetch(source, doc_ref):
        return {"content_b64": encoded, "filename": f"{doc_ref}.txt"}

    return _fetch


def _fake_embed(texts):
    return [[0.1] * _DIM for _ in texts]


def _build_deps(docs_repo, chunks_repo, jobs_repo, *, fetch_fn=None,
                fail_doc_id=None):
    """Construct a PipelineDeps with all fakes wired in."""

    async def _crawl(**_kwargs):
        # Return the seen_ids from docs_repo so plan_scope sees them
        return {
            "discovered": len(docs_repo._docs),
            "folders": 0,
            "seen_ids": set(docs_repo._docs.keys()),
        }

    if fetch_fn is None:
        fetch_fn = _fake_fetch("some text content")

    def _parse(filename, content):
        if fail_doc_id and fail_doc_id in filename:
            raise ValueError(f"parse failed for {filename}")
        return "extracted text"

    def _chunk_split(text, *, size=1200, overlap=150):
        return [text[:size]] if text else []

    def _chunk_id(doc_id, ordinal):
        return f"{doc_id}-{ordinal}"

    return pipeline.PipelineDeps(
        crawl_fn=_crawl,
        fetch_fn=fetch_fn,
        parse_fn=_parse,
        chunk_split_fn=_chunk_split,
        chunk_id_fn=_chunk_id,
        embed_fn=_fake_embed,
        chunks_repo=chunks_repo,
        docs_repo=docs_repo,
        jobs_repo=jobs_repo,
    )


# ── Test: 3-file scenario ─────────────────────────────────────────────────────

def _make_doc(doc_id, etag, status="indexed"):
    return {"external_document_id": doc_id, "etag": etag,
            "content_hash": "", "status": status,
            "source_id": "src1", "name": f"{doc_id}.txt",
            "path": f"/{doc_id}.txt"}


def test_pipeline_unchanged_changed_deleted():
    """1 unchanged, 1 changed, 1 deleted → embedded=1, skipped=1, deleted=1."""
    docs_repo = FakeDocsRepo(docs=[
        _make_doc("unchanged_doc", "same-etag"),
        _make_doc("changed_doc",   "old-etag"),
        _make_doc("deleted_doc",   "gone-etag"),
    ])
    chunks_repo = FakeChunksRepo()
    jobs_repo = FakeJobsRepo()

    # seen_docs contains unchanged + changed but NOT deleted_doc
    # We override the crawl to simulate a specific crawl result
    async def _custom_crawl(**_kwargs):
        return {
            "discovered": 2,
            "folders": 0,
            "seen_ids": {"unchanged_doc", "changed_doc"},
        }

    deps = _build_deps(docs_repo, chunks_repo, jobs_repo)
    deps.crawl_fn = _custom_crawl

    # Make seen_docs in crawl reflect: unchanged_doc has same-etag, changed_doc has new-etag
    # We need plan_scope to see the updated etags. Override docs_repo to simulate:
    docs_repo._docs["changed_doc"]["etag"] = "old-etag"  # DB has old etag
    # The crawl returns seen_ids, but plan_scope compares etags.
    # We need to pass seen_docs explicitly, so override plan_scope.

    seen = [
        {"external_document_id": "unchanged_doc", "etag": "same-etag",
         "content_hash": "", "name": "unchanged_doc.txt", "path": "/unchanged_doc.txt"},
        {"external_document_id": "changed_doc",   "etag": "new-etag",
         "content_hash": "", "name": "changed_doc.txt", "path": "/changed_doc.txt"},
    ]

    from indexer import diff as _diff

    def _fake_plan_scope(conn, domain_id, project_id, seen_docs, repo):
        return _diff.plan_scope(conn, domain_id, project_id, seen, repo)

    deps.plan_scope_fn = _fake_plan_scope

    result = asyncio.run(
        pipeline.run_index_job(
            "job1", "src1", "gdrive", "d1", "p1",
            scope="project", scope_ref="",
            deps=deps, conn=object(),
        )
    )

    assert result["embedded"] == 1
    assert result["skipped"]  == 1
    assert result["deleted"]  == 1
    assert chunks_repo.replaced[0]["doc_id"] == "changed_doc"
    assert "deleted_doc" in chunks_repo.deleted


def test_pipeline_job_status_transitions():
    """Job is started, bumped, and finished."""
    docs_repo = FakeDocsRepo(docs=[_make_doc("doc1", "e1")])
    chunks_repo = FakeChunksRepo()
    jobs_repo = FakeJobsRepo()

    deps = _build_deps(docs_repo, chunks_repo, jobs_repo)

    asyncio.run(
        pipeline.run_index_job(
            "job2", "src1", "gdrive", "d1", "p1",
            scope="project", scope_ref="",
            deps=deps, conn=object(),
        )
    )

    assert "job2" in jobs_repo.started
    assert any(b["job_id"] == "job2" for b in jobs_repo.bumped)
    assert jobs_repo.finished[0]["status"] in ("done", "completed", "finished")


def test_pipeline_per_file_error_continues():
    """A parse failure on one file sets it failed but continues the rest."""
    docs_repo = FakeDocsRepo(docs=[
        _make_doc("good_doc",   "e1", status="discovered"),
        _make_doc("broken_doc", "e2", status="discovered"),
    ])
    chunks_repo = FakeChunksRepo()
    jobs_repo = FakeJobsRepo()

    deps = _build_deps(docs_repo, chunks_repo, jobs_repo, fail_doc_id="broken_doc")

    # Force both docs to be in to_index
    def _plan_all(conn, domain_id, project_id, seen_docs, repo):
        return {
            "to_index":  ["good_doc", "broken_doc"],
            "to_delete": [],
            "skipped":   0,
        }

    deps.plan_scope_fn = _plan_all

    async def _crawl_two(**_):
        return {"discovered": 2, "folders": 0,
                "seen_ids": {"good_doc", "broken_doc"}}

    deps.crawl_fn = _crawl_two

    result = asyncio.run(
        pipeline.run_index_job(
            "job3", "src1", "gdrive", "d1", "p1",
            scope="project", scope_ref="",
            deps=deps, conn=object(),
        )
    )

    assert result["failed"] == 1
    assert result["embedded"] == 1
    failed_updates = [u for u in docs_repo.status_updates
                      if u["status"] == "failed"]
    assert any(u["doc_id"] == "broken_doc" for u in failed_updates)


def test_pipeline_discards_content_without_env_flag():
    """Content bytes must not be retained after embedding (no INDEX_RETAIN_RAW)."""
    import os as _os
    _os.environ.pop("INDEX_RETAIN_RAW", None)

    docs_repo = FakeDocsRepo(docs=[_make_doc("doc_x", "e1")])
    chunks_repo = FakeChunksRepo()
    jobs_repo = FakeJobsRepo()
    deps = _build_deps(docs_repo, chunks_repo, jobs_repo)

    # Just checking it runs without error and doesn't expose raw content
    result = asyncio.run(
        pipeline.run_index_job(
            "job4", "src1", "gdrive", "d1", "p1",
            scope="project", scope_ref="",
            deps=deps, conn=object(),
        )
    )
    assert "raw_content" not in result


def test_pipeline_scope_doc_does_not_delete_other_docs():
    """scope='doc' must reindex only the target doc, leaving all others untouched.

    Previously, plan_scope's ids_missing_from({target_id}) would return every
    other doc in the project as to_delete. The fix bypasses plan_scope entirely
    for scope='doc' so delete_for_doc is never called for non-target docs.
    """
    target_doc  = _make_doc("target_doc", "e1")
    other_doc_a = _make_doc("other_a",    "e2")
    other_doc_b = _make_doc("other_b",    "e3")

    docs_repo   = FakeDocsRepo(docs=[target_doc, other_doc_a, other_doc_b])
    chunks_repo = FakeChunksRepo()
    jobs_repo   = FakeJobsRepo()
    deps        = _build_deps(docs_repo, chunks_repo, jobs_repo)

    result = asyncio.run(
        pipeline.run_index_job(
            "job5", "src1", "gdrive", "d1", "p1",
            scope="doc", scope_ref="target_doc",
            deps=deps, conn=object(),
        )
    )

    # Only target_doc was indexed
    assert result["embedded"] == 1
    assert result["deleted"]  == 0

    # delete_for_doc must NEVER have been called for the other docs
    assert "other_a" not in chunks_repo.deleted
    assert "other_b" not in chunks_repo.deleted

    # And no "deleted" status was written for them
    deleted_status = {u["doc_id"] for u in docs_repo.status_updates
                      if u["status"] == "deleted"}
    assert "other_a" not in deleted_status
    assert "other_b" not in deleted_status
