"""Tests for indexer/embed.py.

Injects a fake client so no live Databricks serving endpoint is needed.

The fake mirrors the REAL Foundation Models API (FMAPI) response shape:
    response.data  — list of objects, each with .embedding (list[float])
NOT the old custom-pyfunc shape (response.predictions).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexer import embed

_DIM = 1024


# ── FakeClient — mirrors FMAPI response shape ─────────────────────────────────

class _FakeEmbeddingItem:
    """Mirrors a single item in response.data for FMAPI embedding endpoints."""
    def __init__(self, vec: list[float]):
        self.embedding = vec


class _FakeResponse:
    """Mirrors the FMAPI QueryEndpointResponse for embedding models."""
    def __init__(self, n: int, dim: int = _DIM):
        self.data = [_FakeEmbeddingItem([float(i) / 100] * dim) for i in range(n)]


class _FakeEndpoints:
    def __init__(self):
        self.calls: list[dict] = []

    def query(self, name: str, input: list) -> _FakeResponse:
        self.calls.append({"name": name, "input": input})
        return _FakeResponse(len(input))


class _FakeEndpointsWrongDim:
    """Returns vectors of the wrong dimension to test validation."""
    def __init__(self, wrong_dim: int):
        self._dim = wrong_dim

    def query(self, name: str, input: list) -> _FakeResponse:
        return _FakeResponse(len(input), dim=self._dim)


class FakeClient:
    def __init__(self):
        self.serving_endpoints = _FakeEndpoints()


class FakeClientWrongDim:
    def __init__(self, dim: int):
        self.serving_endpoints = _FakeEndpointsWrongDim(dim)


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


def test_embed_texts_passes_texts_as_input_list():
    """FMAPI shape: input= keyword, raw list (not dataframe_records dicts)."""
    client = FakeClient()
    embed.embed_texts(["alpha", "beta"], client=client)
    call_input = client.serving_endpoints.calls[0]["input"]
    assert isinstance(call_input, list)
    assert len(call_input) == 2
    # items are raw strings, NOT {"input": str} dicts
    assert call_input[0] == "alpha"
    assert call_input[1] == "beta"


def test_embed_texts_empty_list_returns_empty():
    client = FakeClient()
    result = embed.embed_texts([], client=client)
    assert result == []


def test_embed_texts_default_model_is_gte(monkeypatch):
    """Default model env var default is databricks-gte-large-en."""
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    client = FakeClient()
    embed.embed_texts(["test"], client=client)
    assert client.serving_endpoints.calls[0]["name"] == "databricks-gte-large-en"


def test_embed_texts_vectors_are_floats():
    client = FakeClient()
    result = embed.embed_texts(["hello"], client=client)
    assert all(isinstance(x, float) for x in result[0])


def test_embed_texts_wrong_dim_raises_value_error():
    """A model returning wrong-dimension vectors must raise ValueError loudly."""
    import pytest
    bad_client = FakeClientWrongDim(dim=512)  # 512 ≠ EMBED_DIM (1024)
    with pytest.raises(ValueError, match="dimension mismatch"):
        embed.embed_texts(["hello"], client=bad_client)


def test_embed_texts_batches_large_input(monkeypatch):
    """Texts exceeding EMBED_BATCH are split into multiple endpoint calls."""
    # embed_texts reads the module-level EMBED_BATCH at call time, so patching
    # it here actually changes the batch size (monkeypatch auto-restores).
    monkeypatch.setattr(embed, "EMBED_BATCH", 3)
    client = FakeClient()
    # 7 texts with batch size 3 → ceil(7/3) = 3 endpoint calls.
    texts = [f"text{i}" for i in range(7)]
    result = embed.embed_texts(texts, client=client)
    assert len(result) == 7
    assert len(client.serving_endpoints.calls) == 3


def test_embed_texts_response_data_shape():
    """Validates the fake uses the FMAPI shape: .data[i].embedding not .predictions."""
    client = FakeClient()
    result = embed.embed_texts(["test"], client=client)
    # If we accidentally used response.predictions, we'd either get an error
    # or wrong results. Verify result is a 1x1024 list of floats.
    assert len(result) == 1
    assert len(result[0]) == _DIM
    assert all(isinstance(x, float) for x in result[0])
