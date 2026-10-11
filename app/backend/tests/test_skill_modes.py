"""Tests for skill_modes.classify_skill — which skills run on docs, which need
manual input, which are workflow-only."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_runtime.loader import load_registry
from skill_runtime.skill_modes import classify_skill

reg = load_registry()


def _m(sid):
    return classify_skill(reg.get(sid))


def test_doc_runnable_skills():
    for sid in ["classify_document", "extract_entities", "extract_dates",
                "summarize_document"]:
        m = _m(sid)
        assert m["runnable_on_docs"] is True, sid
        assert m["needs_docs"] is True, sid
        assert not [x for x in m["manual_inputs"] if x["required"]], sid


def test_search_needs_query():
    m = _m("search_documents")
    assert m["runnable_on_docs"] is False
    q = [x for x in m["manual_inputs"] if x["name"] == "query"]
    assert q and q[0]["required"] is True
    assert q[0]["kind"] == "text"


def test_generate_response_needs_question():
    m = _m("generate_response")
    assert m["runnable"] is True
    assert any(x["name"] == "question" for x in m["manual_inputs"])


def test_upstream_only_skills_blocked():
    for sid in ["assess_risk", "identify_gap", "create_finding",
                "assign_action", "generate_executive_summary"]:
        m = _m(sid)
        assert m["runnable"] is False, sid
        assert m["blocked_reason"], sid


if __name__ == "__main__":
    passed = 0
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); passed += 1
        print(f"  ok {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
