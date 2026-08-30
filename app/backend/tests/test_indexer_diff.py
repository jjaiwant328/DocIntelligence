"""Tests for indexer/diff.py — incremental change detection.

All tests are pure (no network, no DB). FakeRepo and FakeConn stand in for
the external_docs_repo and Lakebase connection.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexer import diff


# ── classify ──────────────────────────────────────────────────────────────────

def test_classify_new_when_existing_is_none():
    seen = {"external_document_id": "doc1", "etag": "abc", "content_hash": ""}
    assert diff.classify(None, seen) == "new"


def test_classify_unchanged_when_etag_matches():
    existing = {"etag": "abc", "content_hash": ""}
    seen = {"etag": "abc", "content_hash": ""}
    assert diff.classify(existing, seen) == "unchanged"


def test_classify_unchanged_when_content_hash_matches_etag_empty():
    existing = {"etag": "", "content_hash": "sha256:xyz"}
    seen = {"etag": "", "content_hash": "sha256:xyz"}
    assert diff.classify(existing, seen) == "unchanged"


def test_classify_changed_when_etag_differs():
    existing = {"etag": "old", "content_hash": ""}
    seen = {"etag": "new", "content_hash": ""}
    assert diff.classify(existing, seen) == "changed"


def test_classify_changed_when_both_etag_and_hash_differ():
    existing = {"etag": "e1", "content_hash": "h1"}
    seen = {"etag": "e2", "content_hash": "h2"}
    assert diff.classify(existing, seen) == "changed"


def test_classify_deleted_when_seen_is_none():
    existing = {"etag": "abc", "content_hash": ""}
    assert diff.classify(existing, None) == "deleted"


def test_classify_new_when_etag_empty_and_not_in_db():
    # No etag, existing=None → still new
    seen = {"external_document_id": "doc2", "etag": "", "content_hash": ""}
    assert diff.classify(None, seen) == "new"


def test_classify_unchanged_when_etag_matches_regardless_of_hash():
    """etag match takes precedence: same etag → unchanged, even if content_hash differs."""
    existing = {"etag": "same", "content_hash": "old-hash"}
    seen = {"etag": "same", "content_hash": "new-hash"}
    assert diff.classify(existing, seen) == "unchanged"


# ── plan_scope ────────────────────────────────────────────────────────────────

class FakeConn:
    pass


class FakeRepo:
    """Minimal repo stub for plan_scope tests."""

    def __init__(self, db_docs: list[dict]):
        self._db_docs = db_docs
        self.missing_called_with: dict = {}

    def list_for_project(self, conn, domain_id: str, project_id: str,
                         statuses=None) -> list[dict]:
        return self._db_docs

    def ids_missing_from(self, conn, domain_id: str, project_id: str,
                         seen_ids: set) -> list[str]:
        self.missing_called_with = {
            "domain_id": domain_id,
            "project_id": project_id,
            "seen_ids": seen_ids,
        }
        return [
            d["external_document_id"]
            for d in self._db_docs
            if d["external_document_id"] not in seen_ids
            and d.get("status", "") != "deleted"
        ]


def _doc(doc_id: str, etag: str, status: str = "indexed") -> dict:
    return {"external_document_id": doc_id, "etag": etag, "content_hash": "",
            "status": status}


def test_plan_scope_new_doc_goes_to_index():
    repo = FakeRepo(db_docs=[])  # nothing in DB
    seen_docs = [_doc("new1", "e1")]
    result = diff.plan_scope(FakeConn(), "d1", "p1", seen_docs, repo)
    assert "new1" in result["to_index"]
    assert result["skipped"] == 0


def test_plan_scope_unchanged_etag_is_skipped():
    db_doc = _doc("doc1", "etag-unchanged")
    repo = FakeRepo(db_docs=[db_doc])
    seen_docs = [_doc("doc1", "etag-unchanged")]
    result = diff.plan_scope(FakeConn(), "d1", "p1", seen_docs, repo)
    assert "doc1" not in result["to_index"]
    assert result["skipped"] == 1


def test_plan_scope_changed_etag_goes_to_index():
    db_doc = _doc("doc2", "old-etag")
    repo = FakeRepo(db_docs=[db_doc])
    seen_docs = [_doc("doc2", "new-etag")]
    result = diff.plan_scope(FakeConn(), "d1", "p1", seen_docs, repo)
    assert "doc2" in result["to_index"]


def test_plan_scope_deleted_doc_in_to_delete():
    db_doc = _doc("doc3", "etag")
    repo = FakeRepo(db_docs=[db_doc])
    # doc3 is in DB but NOT in the current seen_docs
    seen_docs = []
    result = diff.plan_scope(FakeConn(), "d1", "p1", seen_docs, repo)
    assert "doc3" in result["to_delete"]


def test_plan_scope_mixed_new_changed_unchanged_deleted():
    db_docs = [
        _doc("unchanged", "etag-same"),
        _doc("changed", "old-etag"),
        _doc("deleted", "etag-gone"),
    ]
    repo = FakeRepo(db_docs=db_docs)
    seen_docs = [
        _doc("unchanged", "etag-same"),
        _doc("changed",   "new-etag"),
        _doc("new_doc",   "etag-new"),
    ]
    result = diff.plan_scope(FakeConn(), "d1", "p1", seen_docs, repo)
    assert "changed"   in result["to_index"]
    assert "new_doc"   in result["to_index"]
    assert "unchanged" not in result["to_index"]
    assert "deleted"   in result["to_delete"]
    assert result["skipped"] == 1


def test_plan_scope_calls_ids_missing_from_with_correct_seen():
    repo = FakeRepo(db_docs=[_doc("doc1", "e1")])
    seen_docs = [_doc("doc1", "e1"), _doc("doc2", "e2")]
    diff.plan_scope(FakeConn(), "d1", "p1", seen_docs, repo)
    seen_ids = repo.missing_called_with["seen_ids"]
    assert "doc1" in seen_ids
    assert "doc2" in seen_ids
