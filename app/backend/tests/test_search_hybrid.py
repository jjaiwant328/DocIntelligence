"""Tests for search/lakebase_search.py — hybrid search backend.

LakebaseSearch must embed the query once via embed.embed_texts then forward
to chunks_repo.hybrid_search. All deps are injected as fakes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from search.lakebase_search import LakebaseSearch

_DIM = 1024


# ── Fakes ──────────────────────────────────────────────────────────────────────

class _FakeEmbedder:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, texts: list[str], **_kwargs) -> list[list[float]]:
        self.calls.append(texts)
        return [[float(i) / 100] * _DIM for i in range(len(texts))]


class _FakeChunksRepo:
    def __init__(self, results: list[dict] = None):
        self._results = results or []
        self.calls: list[dict] = []

    def hybrid_search(self, conn, domain_id, project_id, query_embedding,
                      query_text, k=10, folder="", types=None, doc_ids=None):
        self.calls.append({
            "domain_id": domain_id,
            "project_id": project_id,
            "query_embedding": query_embedding,
            "query_text": query_text,
            "k": k,
            "folder": folder,
            "types": types,
        })
        return self._results


class _FakeLakebase:
    class _FakeConn:
        def __enter__(self):
            return object()
        def __exit__(self, *_):
            pass

    @staticmethod
    def connection():
        return _FakeLakebase._FakeConn()


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_search_embeds_query_once():
    embedder = _FakeEmbedder()
    repo = _FakeChunksRepo()
    backend = LakebaseSearch(embed_fn=embedder, chunks_repo=repo,
                             lakebase=_FakeLakebase)
    backend.search("d1", "p1", "late delivery", k=5)
    assert len(embedder.calls) == 1
    assert embedder.calls[0] == ["late delivery"]


def test_search_forwards_embedding_to_hybrid_search():
    embedder = _FakeEmbedder()
    repo = _FakeChunksRepo()
    backend = LakebaseSearch(embed_fn=embedder, chunks_repo=repo,
                             lakebase=_FakeLakebase)
    backend.search("d1", "p1", "query text", k=7)
    assert len(repo.calls) == 1
    call = repo.calls[0]
    assert len(call["query_embedding"]) == _DIM
    assert call["query_text"] == "query text"
    assert call["k"] == 7
    assert call["domain_id"] == "d1"
    assert call["project_id"] == "p1"


def test_search_passes_folder_and_types_filters():
    embedder = _FakeEmbedder()
    repo = _FakeChunksRepo()
    backend = LakebaseSearch(embed_fn=embedder, chunks_repo=repo,
                             lakebase=_FakeLakebase)
    backend.search("d1", "p1", "query", k=5,
                   folder="/reports/", types=["application/pdf"])
    call = repo.calls[0]
    assert call["folder"] == "/reports/"
    assert call["types"] == ["application/pdf"]


def test_search_returns_results_list():
    embedder = _FakeEmbedder()
    results = [{"chunk_id": "c1", "snippet": "hello", "score": 0.9}]
    repo = _FakeChunksRepo(results=results)
    backend = LakebaseSearch(embed_fn=embedder, chunks_repo=repo,
                             lakebase=_FakeLakebase)
    out = backend.search("d1", "p1", "q", k=10)
    assert out == results


def test_search_empty_returns_empty_list():
    embedder = _FakeEmbedder()
    repo = _FakeChunksRepo(results=[])
    backend = LakebaseSearch(embed_fn=embedder, chunks_repo=repo,
                             lakebase=_FakeLakebase)
    out = backend.search("d1", "p1", "q", k=10)
    assert out == []
