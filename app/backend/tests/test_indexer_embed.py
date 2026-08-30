"""Tests for indexer/embed.py.

Injects a fake client so no live Databricks serving endpoint is needed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexer import embed

_DIM = 1024


# ── FakeClient ────────────────────────────────────────────────────────────────

class _FakePredictions:
    def __init__(self, n: int):
        self.predictions = [[float(i) / 100] * _DIM for i in range(n)]


class _FakeEndpoints:
    def __init__(self):
        self.calls: list[dict] = []

    def query(self, name: str, dataframe_records: list) -> _FakePredictions:
        self.calls.append({"name": name, "records": dataframe_records})
        return _FakePredictions(len(dataframe_records))


class FakeClient:
    def __init__(self):
        self.serving_endpoints = _FakeEndpoints()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_embed_texts_returns_one_vector_per_input():
    client = FakeClient()
    texts = ["hello", "world", "foo"]
    result = embed.embed_texts(texts, client=client)
    assert len(result) == 3


def test_embed_texts_each_vector_has_1024_dims():
    client = FakeClient()
    result = embed.embed_texts(["a", "b"], client=client)
    for vec in result:
        assert len(vec) == _DIM


def test_embed_texts_single_input():
    client = FakeClient()
    result = embed.embed_texts(["only one"], client=client)
    assert len(result) == 1
    assert len(result[0]) == _DIM


def test_embed_texts_calls_serving_endpoint_with_correct_model():
    client = FakeClient()
    embed.embed_texts(["text"], model="my-model", client=client)
    assert len(client.serving_endpoints.calls) >= 1
    assert client.serving_endpoints.calls[0]["name"] == "my-model"


def test_embed_texts_passes_texts_as_dataframe_records():
    client = FakeClient()
    embed.embed_texts(["alpha", "beta"], client=client)
    records = client.serving_endpoints.calls[0]["records"]
    assert isinstance(records, list)
    assert len(records) == 2
    # Each record must be a dict with "input" key
    for r in records:
        assert isinstance(r, dict)
        assert "input" in r


def test_embed_texts_empty_list_returns_empty():
    client = FakeClient()
    result = embed.embed_texts([], client=client)
    assert result == []


def test_embed_texts_default_model_is_gte():
    """Default model env var default is databricks-gte-large-en."""
    import os as _os
    _os.environ.pop("EMBED_MODEL", None)
    client = FakeClient()
    embed.embed_texts(["test"], client=client)
    assert client.serving_endpoints.calls[0]["name"] == "databricks-gte-large-en"


def test_embed_texts_vectors_are_floats():
    client = FakeClient()
    result = embed.embed_texts(["hello"], client=client)
    assert all(isinstance(x, float) for x in result[0])
