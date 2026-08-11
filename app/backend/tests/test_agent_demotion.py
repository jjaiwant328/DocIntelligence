"""Parity tests for the deterministic agent path (D3). Fakes the live seams so
no Databricks is needed. Verifies intent → engine/skill routing + confirmation."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skill_routes  # noqa: E402
from workflow_engine.engine import WorkflowRun, StepRecord  # noqa: E402
from skill_runtime.models import SkillResult  # noqa: E402


def _install_fakes(intent_json, run=None, skill_result=None, vs_rows=None,
                   chat_answer="conversational answer"):
    # fake docintel_routes
    fr = types.ModuleType("docintel_routes")
    fr.run_sql = lambda q, timeout_secs=50: []
    fr.CATALOG = "jai_docintel"
    fr.AGENT_MODEL = "databricks-claude-sonnet-4-5"
    sys.modules["docintel_routes"] = fr

    class FakeDomain:
        platform_domain_id = "compliance_due_diligence"
        schema_vec = "compliance_due_diligence"
    skill_routes.domain_loader = lambda d: FakeDomain()

    class FakeCtx:
        def __init__(self):
            self.chat_completion = lambda p: (intent_json if '"kind"' in p or "intent" in p.lower()
                                              else chat_answer)
            self.vs_search = lambda *a, **k: (vs_rows or [])
    # classify() gets ctx.chat_completion; make it always return the intent json
    fake_ctx = FakeCtx()
    fake_ctx.chat_completion = lambda p: intent_json if "route" in p.lower() or "intent" in p.lower() or "classify" in p.lower() else chat_answer
    skill_routes.build_live_context = lambda pid: fake_ctx

    skill_routes.ExecutionLogger = lambda **k: types.SimpleNamespace(run_sql=lambda q: None)
    skill_routes.ensure_table = lambda *a, **k: None

    class FakeDispatcher:
        def __init__(self, *a, **k): pass
        def invoke(self, skill, inputs, wf_ctx=None):
            return skill_result or SkillResult(status="ok", outputs={"action_ids": ["A-1"]})
    skill_routes.Dispatcher = FakeDispatcher

    class FakeEngine:
        def __init__(self, *a, **k): pass
        def run(self, template, domain, inputs):
            return run
    skill_routes.WorkflowEngine = FakeEngine
    return fake_ctx


def test_workflow_intent_runs_engine():
    run = WorkflowRun(template_id="due_diligence", template_version="1.0",
                      domain="compliance", status="pending_approval",
                      work_object_id="WO-1", halted_at="actions",
                      steps=[StepRecord(id="risk", skill="assess_risk", status="ok")])
    _install_fakes('{"kind":"workflow_run","template":"due_diligence","project":"Store 1827","confirm_action":false}',
                   run=run)
    out = skill_routes.deterministic_agent_answer("What changed for Store 1827?",
                                                  "compliance_due_diligence")
    assert out["intent"]["kind"] == "workflow_run"
    assert "due_diligence" in out["answer"]
    assert out["run"]["status"] == "pending_approval"


def test_create_action_gated_until_approved():
    _install_fakes('{"kind":"skill_invoke","skill":"create_action","confirm_action":true}')
    out = skill_routes.deterministic_agent_answer("Create the required actions",
                                                  "compliance_due_diligence", approve=False)
    assert out.get("requires_confirmation") is True
    assert "approve=true" in out["answer"]


def test_create_action_runs_when_approved():
    _install_fakes('{"kind":"skill_invoke","skill":"create_action","confirm_action":true}',
                   skill_result=SkillResult(status="ok", outputs={"action_ids": ["A-9"]}))
    out = skill_routes.deterministic_agent_answer("Create the required actions",
                                                  "compliance_due_diligence", approve=True)
    assert "create_action" in out["answer"] and out["result"]["status"] == "ok"


def test_conversational_uses_retrieval():
    _install_fakes('{"kind":"conversational","template":null,"skill":null,"confirm_action":false}',
                   vs_rows=[{"doc_id": "D1", "chunk_to_retrieve": "zoning info"}],
                   chat_answer="Zoning is ...")
    out = skill_routes.deterministic_agent_answer("What is zoning?",
                                                  "compliance_due_diligence")
    assert out["intent"]["kind"] == "conversational"
    assert out["cited_docs"] == ["D1"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except Exception as e:
            import traceback; traceback.print_exc()
            failed += 1; print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
