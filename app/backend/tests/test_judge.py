"""Unit tests for the System One judge client (no network)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import judge as j


class FakeConfig:
    host = "adb-example.azuredatabricks.net"

    def authenticate(self):
        return {"Authorization": "Bearer tok"}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_ask_posts_systemone_body(monkeypatch):
    captured = {}
    import requests

    monkeypatch.setattr(
        requests, "post", lambda url, json=None, headers=None, timeout=None: captured.update(
            url=url, json=json, headers=headers) or FakeResponse({"answers": {}})
    )
    jc = j.JudgeClient(config=FakeConfig())
    jc.ask({"chunk": "x"}, j.RELEVANCE_QUESTION)
    assert captured["url"] == "https://adb-example.azuredatabricks.net/ai-gateway/typesafe/v1/systemone"
    assert captured["json"]["model"] == j.JUDGE_MODEL
    assert captured["json"]["questions"]["relevance"]["type"] == "score"
    assert captured["headers"]["Authorization"] == "Bearer tok"


def test_relevance_reads_top_level_probability(monkeypatch):
    payload = {"answers": {"relevance": {"probabilities": {"0": 0.05, "1": 0.15, "2": 0.8}}}}
    jc = j.JudgeClient(config=FakeConfig())
    monkeypatch.setattr(jc, "ask", lambda state, questions: payload)
    assert jc.relevance("q", "chunk") == 0.8


def test_relevance_missing_probs_defaults_zero(monkeypatch):
    jc = j.JudgeClient(config=FakeConfig())
    monkeypatch.setattr(jc, "ask", lambda state, questions: {"answers": {}})
    assert jc.relevance("q", "chunk") == 0.0


def test_ask_requires_config():
    jc = j.JudgeClient(config=None)
    with pytest.raises(RuntimeError):
        jc.ask({}, {})


def test_validate_extraction_batches_fields_and_type(monkeypatch):
    payload = {
        "answers": {
            "field::total": {"type": "noul", "noul": 0.91},
            "field::vendor": {"type": "noul", "noul": 0.2},
            "doc_type_check": {"type": "choice", "choice": "invoice", "confidence": 0.88},
        }
    }
    jc = j.JudgeClient(config=FakeConfig())
    captured = {}
    def fake_ask(state, questions):
        captured["questions"] = questions
        return payload
    monkeypatch.setattr(jc, "ask", fake_ask)
    out = jc.validate_extraction(
        "doc text", "invoice",
        [{"field_name": "total", "field_value": "$1,100"}, {"field_name": "vendor", "field_value": "Acme"}],
        ["invoice", "purchase_order"],
    )
    assert out["field_confidence"] == {"total": 0.91, "vendor": 0.2}
    assert out["type_check"]["match"] is True
    assert out["type_check"]["judge_choice"] == "invoice"
    assert captured["questions"]["doc_type_check"]["criteria"] == {"invoice": None, "purchase_order": None}


def test_validate_extraction_type_mismatch(monkeypatch):
    payload = {"answers": {"doc_type_check": {"type": "choice", "choice": "contract", "confidence": 0.7}}}
    jc = j.JudgeClient(config=FakeConfig())
    monkeypatch.setattr(jc, "ask", lambda state, questions: payload)
    out = jc.validate_extraction("text", "invoice", [], ["invoice", "contract"])
    assert out["type_check"]["match"] is False
    assert out["field_confidence"] == {}
