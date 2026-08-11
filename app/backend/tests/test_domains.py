"""Domain config tests + the headless Compliance->Supply-Chain swap proof."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_runtime.domains import load_domain  # noqa: E402
from workflow_engine.engine import WorkflowEngine  # noqa: E402
from tests.test_engine import FakeDispatcher  # noqa: E402


def test_compliance_requirements():
    d = load_domain("compliance")
    assert d.requirements == ["zoning", "alcohol_license",
                              "environmental_permit", "business_license"]
    assert "Municipality" in d.ontology_entities
    assert d.schema_vec == "compliance_due_diligence"


def test_supply_chain_requirements():
    d = load_domain("supply_chain")
    assert d.requirements == ["insurance", "quality_certification",
                              "food_safety", "audit"]
    assert "Supplier" in d.ontology_entities


def test_same_template_different_domain_no_engine_change():
    """The core 'aha': one engine + one template, two domains, requirements differ,
    zero engine/skill/template change between runs."""
    fake = FakeDispatcher()
    eng = WorkflowEngine(fake, domain_loader=load_domain)

    eng.run("due_diligence", "compliance",
            {"domain": "compliance", "project": "Store 1827",
             "schema_vec": "compliance_due_diligence", "approve": True})
    comp_reqs = [c[1] for c in fake.calls
                 if c[0] == "extract_requirements"][0]["candidate_requirements"]

    fake.calls.clear()
    eng.run("due_diligence", "supply_chain",
            {"domain": "supply_chain", "project": "Supplier ABC",
             "schema_vec": "supply_chain", "approve": True})
    sc_reqs = [c[1] for c in fake.calls
               if c[0] == "extract_requirements"][0]["candidate_requirements"]

    assert comp_reqs == ["zoning", "alcohol_license",
                         "environmental_permit", "business_license"]
    assert sc_reqs == ["insurance", "quality_certification",
                       "food_safety", "audit"]
    assert comp_reqs != sc_reqs   # domain drove the difference, not code


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
