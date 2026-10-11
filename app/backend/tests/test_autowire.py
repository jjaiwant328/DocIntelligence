"""infer_inputs_map tests (offline)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_runtime.autowire import infer_inputs_map  # noqa: E402
from skill_runtime.loader import load_registry  # noqa: E402

REG = load_registry()


def test_due_diligence_shaped_autowiring():
    steps = [
        {"id": "create_review", "skill": "create_work_object"},
        {"id": "identify_requirements", "skill": "extract_requirements"},
        {"id": "collect_evidence", "skill": "find_supporting_evidence"},
        {"id": "evaluate", "skill": "assess_requirement"},
        {"id": "identify_gaps", "skill": "identify_gap"},
    ]
    wired = infer_inputs_map(steps, REG)
    m = {s["id"]: s["inputs_map"] for s in wired}

    # domain + project come from workflow input
    assert m["create_review"]["domain"] == "$input.domain"
    assert m["create_review"]["project"] == "$input.project"
    # requirements candidate list comes from domain config
    assert m["identify_requirements"]["candidate_requirements"] == "$domain.requirements"
    # assess_requirement.requirements should wire from extract_requirements output
    assert m["evaluate"]["requirements"] == "$steps.identify_requirements.requirements"
    # evidence wires from collect_evidence output
    assert m["evaluate"]["evidence"] == "$steps.collect_evidence.evidence"
    # identify_gap.assessments wires from assess_requirement output
    assert m["identify_gaps"]["assessments"] == "$steps.evaluate.assessments"


def test_existing_map_preserved():
    steps = [{"id": "x", "skill": "assess_risk", "inputs_map": {"gaps": "$input.custom"}}]
    wired = infer_inputs_map(steps, REG)
    assert wired[0]["inputs_map"]["gaps"] == "$input.custom"


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
