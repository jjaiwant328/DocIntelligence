"""Route wiring test — calls the workflow-run handler with the engine monkeypatched
so no live Databricks is needed. Verifies request model + response shape."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skill_routes  # noqa: E402
from workflow_engine.engine import WorkflowRun, StepRecord  # noqa: E402


def test_workflow_run_returns_run_dict(monkeypatch=None):
    # Fake the pieces that need live Databricks.
    fake_run = WorkflowRun(
        template_id="due_diligence", template_version="1.0",
        domain="compliance", status="pending_approval",
        work_object_id="WO-1", halted_at="actions",
        steps=[StepRecord(id="create_review", skill="create_work_object",
                          status="ok", outputs={"work_object_id": "WO-1"})],
    )

    class FakeEngine:
        def __init__(self, *a, **k): pass
        def run(self, template, domain, inputs, docs=None, params=None):
            assert template == "due_diligence"
            assert inputs["project"] == "Store 1827"
            return fake_run

    skill_routes.build_live_context = lambda pid: object()
    skill_routes.Dispatcher = lambda *a, **k: object()
    skill_routes.WorkflowEngine = FakeEngine

    class FakeLogger:
        def __init__(self, *a, **k): self.run_sql = lambda q: None
    skill_routes.ExecutionLogger = FakeLogger
    skill_routes.ensure_table = lambda *a, **k: None

    # stub the lazily-imported docintel_routes
    import types
    fake_routes = types.ModuleType("docintel_routes")
    fake_routes.run_sql = lambda q, timeout_secs=50: []
    fake_routes.CATALOG = "jai_docintel"
    fake_routes._get_domain_schemas = lambda pid: {"schema_raw": "raw"}
    sys.modules["docintel_routes"] = fake_routes

    req = skill_routes.WorkflowRunRequest(
        template="due_diligence", domain_id="compliance_due_diligence", project="Store 1827")
    result = asyncio.run(skill_routes.workflow_run(req))
    assert result["status"] == "pending_approval"
    assert result["work_object_id"] == "WO-1"
    assert result["steps"][0]["skill"] == "create_work_object"


def test_request_model_defaults():
    req = skill_routes.WorkflowRunRequest(project="X")
    assert req.template == "due_diligence" and req.domain_id == "compliance_due_diligence"
    assert req.approve is False


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
