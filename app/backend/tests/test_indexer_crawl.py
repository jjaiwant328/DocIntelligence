"""Tests for indexer.crawl — metadata walk, no content copy.

Fake MCP and fake repo so no live network or DB is needed.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Fake MCP ──────────────────────────────────────────────────────────────────
# Tree: root → [folder1, folder2, file1]
#       folder1 → [file2]
#       folder2 → [file3]
# Totals: 2 folders, 3 files.

def _file(item_id, name, path):
    return {
        "item_id": item_id, "name": name, "is_folder": False,
        "path": path, "mime_type": "application/pdf", "size": 100,
        "web_url": f"http://example.com/{item_id}", "etag": f"e-{item_id}",
        "modified_at": None, "owner": "",
    }


def _folder(item_id, name, path):
    return {
        "item_id": item_id, "name": name, "is_folder": True,
        "path": path, "mime_type": "folder", "size": 0,
        "web_url": "", "etag": "", "modified_at": None, "owner": "",
    }


_TREE = {
    "": [
        _folder("folder1", "FolderA", "/FolderA"),
        _folder("folder2", "FolderB", "/FolderB"),
        _file("file1", "doc1.pdf", "/doc1.pdf"),
    ],
    "folder1": [
        _file("file2", "doc2.pdf", "/FolderA/doc2.pdf"),
    ],
    "folder2": [
        _file("file3", "doc3.pdf", "/FolderB/doc3.pdf"),
    ],
}


class FakeMcp:
    async def list_children(self, source: str, folder_id: str = "") -> list:
        return list(_TREE.get(folder_id, []))


# ── Fake Repo ──────────────────────────────────────────────────────────────────

class FakeRepo:
    def __init__(self):
        self.upserted: list[dict] = []

    @staticmethod
    def stable_doc_id(provider, site, drive, item_id):
        return f"{provider}|{site}|{drive}|{item_id}"

    def upsert_metadata(self, conn, doc: dict) -> None:
        self.upserted.append(doc)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_crawl_discovers_3_files_and_2_folders():
    from indexer.crawl import crawl_source

    repo = FakeRepo()
    result = asyncio.run(
        crawl_source(
            source_id="gdrive",
            provider="gdrive",
            domain_id="d1",
            project_id="p1",
            root_folder="",
            mcp=FakeMcp(),
            repo=repo,
            conn=object(),
        )
    )

    assert result["discovered"] == 3, f"expected 3 files discovered, got {result['discovered']}"
    assert result["folders"] == 2, f"expected 2 folders traversed, got {result['folders']}"
    assert len(result["seen_ids"]) == 3, f"expected 3 seen_ids, got {len(result['seen_ids'])}"
    assert len(repo.upserted) == 3, f"expected 3 upserts, got {len(repo.upserted)}"


def test_crawl_seen_ids_match_upserted_doc_ids():
    from indexer.crawl import crawl_source

    repo = FakeRepo()
    result = asyncio.run(
        crawl_source(
            source_id="gdrive",
            provider="gdrive",
            domain_id="d1",
            project_id="p1",
            mcp=FakeMcp(),
            repo=repo,
            conn=object(),
        )
    )

    upserted_ids = {doc["external_document_id"] for doc in repo.upserted}
    assert upserted_ids == result["seen_ids"]


def test_crawl_sets_source_and_project_on_each_doc():
    from indexer.crawl import crawl_source

    repo = FakeRepo()
    asyncio.run(
        crawl_source(
            source_id="my_source",
            provider="gdrive",
            domain_id="dom42",
            project_id="proj99",
            mcp=FakeMcp(),
            repo=repo,
            conn=object(),
        )
    )

    for doc in repo.upserted:
        assert doc["source_id"] == "my_source"
        assert doc["domain_id"] == "dom42"
        assert doc["project_id"] == "proj99"


def test_crawl_depth_bounded():
    """A deeply nested tree is stopped at _MAX_DEPTH to prevent runaway walks."""
    from indexer.crawl import crawl_source, _MAX_DEPTH

    # Build a chain deeper than _MAX_DEPTH
    depth = _MAX_DEPTH + 5
    deep_tree: dict = {}
    for i in range(depth):
        deep_tree[f"f{i}"] = [_folder(f"f{i+1}", f"Folder{i+1}", f"/d{i+1}")]
    deep_tree[f"f{depth}"] = [_file("leaf", "leaf.pdf", "/leaf.pdf")]

    # Root returns folder f0
    deep_tree[""] = [_folder("f0", "Root", "/Root")]

    class DeepMcp:
        async def list_children(self, source: str, folder_id: str = "") -> list:
            return list(deep_tree.get(folder_id, []))

    repo = FakeRepo()
    result = asyncio.run(
        crawl_source(
            source_id="gdrive",
            provider="gdrive",
            domain_id="d1",
            project_id="p1",
            mcp=DeepMcp(),
            repo=repo,
            conn=object(),
        )
    )

    # The leaf file at depth > _MAX_DEPTH must NOT have been upserted.
    assert result["discovered"] == 0, (
        f"leaf file beyond max depth should not be discovered; got {result['discovered']}"
    )
