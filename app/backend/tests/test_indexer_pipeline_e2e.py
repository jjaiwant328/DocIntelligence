"""End-to-end pipeline test proving C1 (incremental skip), C2 (fetch by native
id) and I1 (inclusion toggle) together.

Unlike test_indexer_pipeline.py — which injects a pre-canned plan — this test
drives the REAL crawl → list_for_project → diff.plan_scope → fetch path. Only
the MCP client (list_children/fetch_document) and the embedding client are
faked; the crawl, diff, parse, chunk and repo-facade logic are the production
modules running against an in-memory document store.
"""
import asyncio
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexer import pipeline
from indexer.crawl import crawl_source
from db.repositories.external_docs_repo import stable_doc_id

_DIM = 1024

# Source tree: 3 files at the root, each with a stable etag. Native item_ids
# are short strings; the crawler hashes them into 40-char external_document_ids.
_TREE = {
    "": [
        {"item_id": "file-a", "name": "a.txt", "is_folder": False,
         "path": "/a.txt", "mime_type": "text/plain", "size": 10,
         "web_url": "http://x/a", "etag": "etag-a", "modified_at": None,
         "owner": ""},
        {"item_id": "file-b", "name": "b.txt", "is_folder": False,
         "path": "/b.txt", "mime_type": "text/plain", "size": 10,
         "web_url": "http://x/b", "etag": "etag-b", "modified_at": None,
         "owner": ""},
        {"item_id": "file-c", "name": "c.txt", "is_folder": False,
         "path": "/c.txt", "mime_type": "text/plain", "size": 10,
         "web_url": "http://x/c", "etag": "etag-c", "modified_at": None,
         "owner": ""},
    ],
}
_NATIVE_IDS = {"file-a", "file-b", "file-c"}


class FakeMcp:
    """Fake MCP source — only list_children is used by the crawl."""
    def __init__(self, tree):
        self.tree = tree

    async def list_children(self, source, folder_id=""):
        return list(self.tree.get(folder_id, []))


class InMemoryDocsRepo:
    """In-memory stand-in for external_docs_repo mirroring its real semantics:
    upsert preserves status / last_indexed_etag / included on conflict, and
    mark_indexed records the fingerprint that change-detection reads back."""
    def __init__(self):
        self.rows: dict[str, dict] = {}

    stable_doc_id = staticmethod(stable_doc_id)

    def upsert_metadata(self, conn, doc):
        did = doc["external_document_id"]
        existing = self.rows.get(did)
        if existing is None:
            row = dict(doc)
            row.setdefault("status", "discovered")
            row.setdefault("included", True)
            row.setdefault("last_indexed_etag", "")
            self.rows[did] = row
        else:
            # Metadata re-crawl: refresh mutable metadata but never clobber
            # status / last_indexed_etag / included (the I1b fix).
            for k in ("source_id", "source_item_id", "parent_folder_id", "path",
                      "name", "mime_type", "size_bytes", "web_url", "etag",
                      "content_hash", "owner", "source_modified_at"):
                if k in doc:
                    existing[k] = doc[k]

    def list_for_project(self, conn, domain_id, project_id, statuses=None):
        out = [r for r in self.rows.values()
               if r.get("domain_id") == domain_id and r.get("project_id") == project_id]
        if statuses:
            out = [r for r in out if r.get("status") in statuses]
        return out

    def ids_missing_from(self, conn, domain_id, project_id, seen_ids):
        return [did for did, r in self.rows.items()
                if r.get("domain_id") == domain_id
                and r.get("project_id") == project_id
                and r.get("status") != "deleted"
                and did not in seen_ids]

    def set_status(self, conn, doc_id, status, last_error=""):
        if doc_id in self.rows:
            self.rows[doc_id]["status"] = status

    def set_included(self, conn, doc_id, included):
        if doc_id in self.rows:
            self.rows[doc_id]["included"] = included

    def mark_indexed(self, conn, doc_id, index_version, embedding_model, etag, chunk_count):
        r = self.rows[doc_id]
        r["status"] = "indexed"
        r["last_indexed_etag"] = etag
        r["chunk_count"] = chunk_count
        r["index_version"] = index_version


class FakeJobsRepo:
    def start(self, conn, job_id): pass
    def bump(self, conn, job_id, **counts): pass
    def finish(self, conn, job_id, status, error_summary=""): pass


class FakeChunksRepo:
    def __init__(self):
        self.replaced = []
        self.deleted = []

    def replace_chunks(self, conn, doc_id, chunks):
        self.replaced.append(doc_id)
        return len(chunks)

    def delete_for_doc(self, conn, doc_id):
        self.deleted.append(doc_id)
        return 0


def _build(store, chunks_repo, jobs_repo, fetched_refs):
    fake_mcp = FakeMcp(_TREE)

    async def _crawl_fn(**kwargs):
        # Real crawl logic against the fake MCP + in-memory store.
        return await crawl_source(**kwargs, mcp=fake_mcp, repo=store)

    async def _fetch(source, doc_ref):
        fetched_refs.append(doc_ref)
        body = base64.b64encode(f"content for {doc_ref}".encode()).decode()
        return {"content_b64": body, "filename": f"{doc_ref}.txt"}

    def _embed(texts):
        return [[0.1] * _DIM for _ in texts]

    # parse_fn / chunk_split_fn / chunk_id_fn / plan_scope_fn left as defaults
    # → the real modules run.
    return pipeline.PipelineDeps(
        crawl_fn=_crawl_fn,
        fetch_fn=_fetch,
        embed_fn=_embed,
        chunks_repo=chunks_repo,
        docs_repo=store,
        jobs_repo=jobs_repo,
    )


def _run(store, deps):
    return asyncio.run(
        pipeline.run_index_job(
            "job", "gdrive", "gdrive", "d1", "p1",
            scope="project", scope_ref="",
            deps=deps, conn=object(),
        )
    )


def test_first_build_indexes_all_then_rerun_skips_all():
    """C1: first Build indexes N; a re-run with unchanged etags skips all N.
    C2: fetch is called with the native item_id, never the sha-1 doc id."""
    store = InMemoryDocsRepo()
    jobs_repo = FakeJobsRepo()

    # ── First build ──────────────────────────────────────────────────────────
    fetched1 = []
    chunks1 = FakeChunksRepo()
    result1 = _run(store, _build(store, chunks1, jobs_repo, fetched1))

    assert result1["embedded"] == 3, f"first build must index all 3, got {result1}"
    assert result1["skipped"] == 0
    assert len(store.rows) == 3

    # C2: fetch received the native ids, NOT the 40-char sha-1 external ids.
    assert set(fetched1) == _NATIVE_IDS, f"fetch got {fetched1!r}"
    for ref in fetched1:
        assert len(ref) != 40 or ref in _NATIVE_IDS
        assert ref not in store.rows, "fetch must NOT be called with the sha-1 doc id"

    # ── Re-run, nothing changed ──────────────────────────────────────────────
    fetched2 = []
    chunks2 = FakeChunksRepo()
    result2 = _run(store, _build(store, chunks2, jobs_repo, fetched2))

    assert result2["embedded"] == 0, f"unchanged re-run must embed nothing, got {result2}"
    assert result2["skipped"] == 3
    assert fetched2 == [], "unchanged docs must not be fetched"
    assert chunks2.replaced == []


def test_excluded_doc_is_not_indexed_and_recrawl_keeps_it_excluded():
    """I1a: a doc with included=False is never put in to_index.
    I1b: the metadata re-crawl inside the job does not flip it back to True."""
    store = InMemoryDocsRepo()
    jobs_repo = FakeJobsRepo()

    # Populate the store with a standalone crawl (all discovered, included=True).
    fake_mcp = FakeMcp(_TREE)
    asyncio.run(crawl_source(
        source_id="gdrive", provider="gdrive", domain_id="d1", project_id="p1",
        root_folder="", mcp=fake_mcp, repo=store, conn=object(),
    ))

    excluded_id = next(r["external_document_id"] for r in store.rows.values()
                       if r["source_item_id"] == "file-b")
    store.set_included(object(), excluded_id, False)

    fetched = []
    chunks = FakeChunksRepo()
    result = _run(store, _build(store, chunks, jobs_repo, fetched))

    # Only the two included docs were indexed.
    assert result["embedded"] == 2, f"excluded doc must not index, got {result}"
    assert "file-b" not in fetched, "excluded doc must not be fetched"
    assert set(fetched) == {"file-a", "file-c"}

    # I1b: the re-crawl inside the job must not have reset the flag.
    assert store.rows[excluded_id]["included"] is False
    assert store.rows[excluded_id]["status"] != "indexed"
