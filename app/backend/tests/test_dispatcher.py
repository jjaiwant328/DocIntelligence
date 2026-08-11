"""Dispatcher envelope + execution logging tests (offline)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_runtime.dispatcher import Dispatcher  # noqa: E402
from skill_runtime.adapters.base import Context  # noqa: E402
from skill_runtime.executions import ExecutionLogger  # noqa: E402
from skill_runtime.loader import load_registry  # noqa: E402

REG = load_registry()


def _ctx():
    return Context(
        internal={"create_work_object": lambda i, c: ({"work_object_id": "W-1",
                                                       "work_object": {}}, [])},
        chat_completion=lambda p: '{"assessments":[{"requirement":"zoning",'
                                  '"status":"satisfied","confidence":0.9}],"evidence":[]}',
        resolve_model=lambda: "databricks-claude-sonnet-4-5",
    )


def test_happy_invoke_logs_one_row():
    logger = ExecutionLogger()  # no run_sql -> in-memory only
    d = Dispatcher(REG, _ctx(), logger=logger)
    r = d.invoke("create_work_object", {"domain": "compliance", "project": "S1"})
    assert r.status != "error" and r.outputs["work_object_id"] == "W-1"
    assert len(logger.records) == 1
    assert logger.records[0].skill_id == "create_work_object"
    assert logger.records[0].skill_version == "1.0"


def test_bad_input_returns_error_and_logs():
    logger = ExecutionLogger()
    d = Dispatcher(REG, _ctx(), logger=logger)
    r = d.invoke("create_work_object", {"project": "S1"})  # missing 'domain'
    assert r.status == "error" and "domain" in r.error
    assert logger.records[0].status == "error"


def test_llm_skill_records_model():
    logger = ExecutionLogger()
    d = Dispatcher(REG, _ctx(), logger=logger)
    r = d.invoke("assess_requirement",
                 {"requirements": ["zoning"], "evidence": [{"document_id": "D"}]})
    assert r.status != "error" and r.outputs["assessments"][0]["status"] == "satisfied"
    assert logger.records[0].model == "databricks-claude-sonnet-4-5"


def test_wf_ctx_threads_into_record():
    logger = ExecutionLogger()
    d = Dispatcher(REG, _ctx(), logger=logger)
    d.invoke("create_work_object", {"domain": "c", "project": "p"},
             wf_ctx={"workflow_id": "wf1", "work_object_id": "W-9"})
    assert logger.records[0].workflow_id == "wf1"
    assert logger.records[0].work_object_id == "W-9"


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
