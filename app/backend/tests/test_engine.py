"""Workflow engine tests with a fake dispatcher (offline, deterministic)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflow_engine.engine import WorkflowEngine  # noqa: E402
from skill_runtime.models import SkillResult, Evidence  # noqa: E402


class FakeDomain:
    requirements = ["zoning", "alcohol_license"]


class FakeDispatcher:
    """Returns canned SkillResults keyed by skill; records call order + inputs."""
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def invoke(self, skill, inputs, wf_ctx=None):
        self.calls.append((skill, inputs))
        if skill == self.fail_on:
            return SkillResult(status="error", error="boom")
        canned = {
            "create_work_object": {"work_object_id": "W-1", "work_object": {}},
            "extract_requirements": {"requirements": ["zoning"], "evidence": []},
            "find_supporting_evidence": {"evidence": [{"document_id": "D1"}]},
            "assess_requirement": {"assessments": [{"requirement": "zoning",
                                                     "status": "gap"}],
                                    "evidence": []},
            "identify_gap": {"gaps": [{"requirement": "zoning"}], "evidence": []},
            "assess_risk": {"risk": "medium", "rationale": "x",
                            "confidence": 0.7, "evidence": []},
            "generate_recommendation": {"recommendation": "hold",
                                        "proposed_actions": [{"action_type": "review"}],
                                        "evidence": []},
            "create_action": {"action_ids": ["A-1"]},
        }
        out = canned.get(skill, {})
        ev = [Evidence(document_id="D1")] if skill == "find_supporting_evidence" else []
        return SkillResult(status=out.get("status", "ok"), outputs=out, evidence=ev)


def _engine(fake):
    return WorkflowEngine(fake, domain_loader=lambda d: FakeDomain())


def test_runs_all_steps_in_order_with_approval():
    fake = FakeDispatcher()
    run = _engine(fake).run("due_diligence", "compliance",
                            {"domain": "compliance", "project": "Store 1827",
                             "schema_vec": "vectors", "approve": True})
    order = [c[0] for c in fake.calls]
    assert order == ["create_work_object", "extract_requirements",
                     "find_supporting_evidence", "assess_requirement",
                     "identify_gap", "assess_risk", "generate_recommendation",
                     "create_action"]
    assert run.status == "completed" and run.work_object_id == "W-1"


def test_halts_at_approval_gate_when_not_approved():
    fake = FakeDispatcher()
    run = _engine(fake).run("due_diligence", "compliance",
                            {"domain": "compliance", "project": "S1",
                             "schema_vec": "vectors"})
    assert run.status == "pending_approval" and run.halted_at == "actions"
    assert "create_action" not in [c[0] for c in fake.calls]


def test_step_error_halts_with_partial_history():
    fake = FakeDispatcher(fail_on="assess_risk")
    run = _engine(fake).run("due_diligence", "compliance",
                            {"domain": "compliance", "project": "S1",
                             "schema_vec": "vectors", "approve": True})
    assert run.status == "failed" and run.halted_at == "risk"
    assert run.steps[-1].error == "boom"


def test_io_mapping_passes_domain_requirements():
    fake = FakeDispatcher()
    _engine(fake).run("due_diligence", "compliance",
                      {"domain": "compliance", "project": "S1",
                       "schema_vec": "vectors", "approve": True})
    # extract_requirements should receive the domain's candidate_requirements
    er_inputs = [c[1] for c in fake.calls if c[0] == "extract_requirements"][0]
    assert er_inputs["candidate_requirements"] == ["zoning", "alcohol_license"]


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
