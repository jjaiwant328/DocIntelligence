"""Tests for skill_runtime.models. Run: python -m pytest app/backend/tests/test_skill_models.py -v
or: python app/backend/tests/test_skill_models.py (self-contained)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_runtime.models import (  # noqa: E402
    Evidence, SkillResult, WorkObject, SkillContract, InputError, OutputError,
)


def test_evidence_roundtrips():
    e = Evidence(document_id="doc1", locator="p2", source_text="txt",
                 confidence=0.9, method="retrieval")
    d = e.to_dict()
    assert d["document_id"] == "doc1" and d["confidence"] == 0.9


def test_skill_result_defaults():
    r = SkillResult(status="ok")
    assert r.evidence == [] and r.error is None
    assert r.to_dict()["status"] == "ok"


def test_skill_result_serializes_evidence():
    r = SkillResult(status="ok", evidence=[Evidence(document_id="d")])
    assert r.to_dict()["evidence"][0]["document_id"] == "d"


def test_workobject_to_dict():
    w = WorkObject(id="w1", type="review", title="t", domain="compliance")
    d = w.to_dict()
    assert d["type"] == "review" and d["status"] == "open"


def test_contract_validate_inputs_missing_required():
    c = SkillContract(id="s", version="1.0", category="reasoning",
                      adapter="llm_schema", implementation="p.md",
                      inputs={"x": {"type": "string", "required": True}})
    try:
        c.validate_inputs({})
        assert False, "expected InputError"
    except InputError:
        pass
    c.validate_inputs({"x": "ok"})  # no raise


def test_contract_validate_enum_output():
    c = SkillContract(id="s", version="1.0", category="reasoning",
                      adapter="llm_schema", implementation="p.md",
                      outputs={"status": {"type": "enum", "values": ["a", "b"]}})
    c.validate_outputs({"status": "a"})
    try:
        c.validate_outputs({"status": "z"})
        assert False, "expected OutputError"
    except OutputError:
        pass


def test_contract_creates_actions():
    c = SkillContract(id="s", version="1.0", category="workflow",
                      adapter="internal_call", implementation="create_action",
                      side_effects={"creates_actions": True})
    assert c.creates_actions() is True


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
