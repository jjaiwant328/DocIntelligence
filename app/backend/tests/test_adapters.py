"""Adapter tests with fake ctx seams (offline)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_runtime.adapters import (  # noqa: E402
    UCFunctionAdapter, InternalCallAdapter, LLMSchemaAdapter,
)
from skill_runtime.adapters.base import Context  # noqa: E402
from skill_runtime.loader import load_registry  # noqa: E402

REG = load_registry()


def test_uc_function_vs_search_normalizes_evidence():
    ctx = Context(vs_search=lambda q, s, k, dt: [
        {"doc_id": "D1", "chunk_id": "c1", "chunk_to_retrieve": "text one"},
        {"doc_id": "D2", "chunk_id": "c2", "chunk_to_retrieve": "text two"},
    ])
    out, ev = UCFunctionAdapter().execute(
        REG.get("find_supporting_evidence"),
        {"query": "zoning", "schema_vec": "vectors", "k": 2}, ctx)
    assert len(ev) == 2 and ev[0].document_id == "D1"
    assert ev[0].method == "ai_similarity"
    assert out["evidence"][1]["source_text"] == "text two"


def test_internal_call_resolves_callable():
    def _create(inputs, ctx):
        return {"work_object_id": "W-1"}, []
    ctx = Context(internal={"create_work_object": _create})
    out, ev = InternalCallAdapter().execute(
        REG.get("create_work_object"),
        {"domain": "compliance", "project": "Store 1827"}, ctx)
    assert out["work_object_id"] == "W-1" and ev == []


def test_llm_schema_parses_json_and_evidence():
    canned = ('```json\n{"status":"satisfied","rationale":"ok","confidence":0.8,'
              '"evidence":[{"document_id":"D1","source_text":"t","method":"reasoning"}]}\n```')
    ctx = Context(chat_completion=lambda prompt: canned)
    out, ev = LLMSchemaAdapter().execute(
        REG.get("assess_requirement"),
        {"requirement": "zoning", "evidence": [{"document_id": "D1"}]}, ctx)
    assert out["status"] == "satisfied" and out["confidence"] == 0.8
    assert len(ev) == 1 and ev[0].document_id == "D1"


def test_llm_schema_insufficient_evidence_is_firstclass():
    canned = '{"status":"insufficient_evidence","rationale":"none","confidence":0.1,"evidence":[]}'
    ctx = Context(chat_completion=lambda prompt: canned)
    out, ev = LLMSchemaAdapter().execute(
        REG.get("assess_requirement"),
        {"requirement": "alcohol_license", "evidence": []}, ctx)
    assert out["status"] == "insufficient_evidence" and ev == []


def test_llm_schema_renders_placeholders():
    seen = {}
    def _cap(prompt):
        seen["p"] = prompt
        return '{"risk":"low","rationale":"x","confidence":0.9,"evidence":[]}'
    ctx = Context(chat_completion=_cap)
    LLMSchemaAdapter().execute(REG.get("assess_risk"),
                               {"gaps": [], "evidence": []}, ctx)
    assert "{gaps}" not in seen["p"]  # placeholder was filled/blanked


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except Exception as e:
            failed += 1; print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
