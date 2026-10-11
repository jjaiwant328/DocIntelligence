"""Tests for map_docs_to_inputs (offline)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_runtime.doc_inputs import map_docs_to_inputs  # noqa: E402
from skill_runtime.loader import load_registry  # noqa: E402
from skill_runtime.models import InputError  # noqa: E402

REG = load_registry()
DOCS = [
    {"doc_id": "D1", "doc_type": "ordinance", "text": "alcohol license fee $20"},
    {"doc_id": "D2", "doc_type": "email", "text": "feasibility for Store 1827"},
]


def test_text_skill_gets_concatenated_text():
    # summarize_document has a required `text` input
    inp = map_docs_to_inputs(REG.get("summarize_document"), DOCS)
    assert "alcohol license" in inp["text"] and "feasibility" in inp["text"]


def test_detect_change_fills_current_and_previous():
    inp = map_docs_to_inputs(REG.get("detect_change"), DOCS)
    assert inp["current"] and inp["previous"]  # both text keys filled


def test_query_input_defaults_to_doc_types():
    # find_supporting_evidence has `query` + `schema_vec`(caller) + k
    inp = map_docs_to_inputs(REG.get("find_supporting_evidence"), DOCS,
                             base_inputs={"schema_vec": "compliance_due_diligence"})
    assert "ordinance" in inp["query"] and "email" in inp["query"]
    assert inp["schema_vec"] == "compliance_due_diligence"


def test_empty_corpus_for_text_skill_raises():
    try:
        map_docs_to_inputs(REG.get("summarize_document"), [])
        assert False, "expected InputError"
    except InputError as e:
        assert "no parsed documents" in str(e)


def test_base_inputs_take_precedence():
    inp = map_docs_to_inputs(REG.get("summarize_document"), DOCS,
                             base_inputs={"text": "override"})
    assert inp["text"] == "override"


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
