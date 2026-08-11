"""Live smoke test: run due_diligence for compliance + supply_chain against
jai-az-ws (real LLM + ai_similarity + Delta writes). Prints per-step status +
evidence counts. Requires env for docintel_routes (warehouse id, catalog).

Usage: python app/backend/scripts/smoke_workflow.py [--profile jai-az-ws] [--approve]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABRICKS_WAREHOUSE_ID", "85a4ed5bcff25c0d")
os.environ.setdefault("DOCINTEL_CATALOG", "jai_docintel")


def run_one(domain_id, project, approve, profile):
    # Point the SDK at the chosen profile for this process.
    os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", profile)

    from skill_runtime.loader import load_registry
    from skill_runtime.dispatcher import Dispatcher
    from skill_runtime.executions import ExecutionLogger, ensure_table
    from skill_runtime.context import build_live_context, domain_loader
    from workflow_engine.engine import WorkflowEngine
    import docintel_routes as routes

    dom = domain_loader(domain_id)
    logger = ExecutionLogger(run_sql=lambda q: routes.run_sql(q, timeout_secs=50),
                             catalog=routes.CATALOG)
    ensure_table(logger.run_sql, catalog=routes.CATALOG)
    ctx = build_live_context(dom.platform_domain_id)
    d = Dispatcher(load_registry(), ctx, logger=logger)
    engine = WorkflowEngine(d, domain_loader=domain_loader)

    inputs = {"domain": domain_id, "project": project,
              "schema_vec": dom.schema_vec, "context": "", "approve": approve}
    print(f"\n=== {domain_id} / {project} (approve={approve}) ===")
    run = engine.run("due_diligence", domain_id, inputs)
    print("run status:", run.status, "| halted_at:", run.halted_at,
          "| work_object:", run.work_object_id)
    for s in run.steps:
        print(f"  - {s.id:22s} {s.skill:24s} {s.status:20s} "
              f"evidence={len(s.evidence)}"
              + (f" ERROR={s.error}" if s.error else ""))
    return run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="jai-az-ws")
    ap.add_argument("--approve", action="store_true")
    args = ap.parse_args()

    run_one("compliance", "Store 1827", args.approve, args.profile)
    run_one("supply_chain", "Supplier ABC", args.approve, args.profile)
    print("\nSmoke complete.")


if __name__ == "__main__":
    main()
