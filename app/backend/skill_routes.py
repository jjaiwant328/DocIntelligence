"""Skills/Workflow overlay routes — additive; does not touch agent_query.

  POST /api/docintel/workflow-run       run a template for a domain + project
  GET  /api/docintel/skills             list registered skills
  GET  /api/docintel/skill-executions   recent execution log rows
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from skill_runtime.loader import load_registry
from skill_runtime.dispatcher import Dispatcher
from skill_runtime.executions import ExecutionLogger, ensure_table, executions_table
from skill_runtime.context import build_live_context, domain_loader
from workflow_engine.engine import WorkflowEngine

router = APIRouter(prefix="/api/docintel", tags=["Skills"])

_REGISTRY = load_registry()


class WorkflowRunRequest(BaseModel):
    template: str = "due_diligence"
    domain_id: str = "compliance"      # overlay domain id: compliance | supply_chain
    project: str
    context: Optional[str] = None
    approve: bool = False


@router.get("/skills")
async def list_skills():
    return {"skills": _REGISTRY.list(enabled_only=False),
            "enabled": _REGISTRY.enabled_ids()}


@router.post("/workflow-run")
async def workflow_run(req: WorkflowRunRequest):
    import docintel_routes as routes

    dom = domain_loader(req.domain_id)
    logger = ExecutionLogger(run_sql=lambda q: routes.run_sql(q, timeout_secs=50),
                             catalog=routes.CATALOG)
    try:
        ensure_table(logger.run_sql, catalog=routes.CATALOG)
    except Exception as e:
        print(f"[workflow-run] ensure_table failed: {e}")

    ctx = build_live_context(dom.platform_domain_id)
    dispatcher = Dispatcher(_REGISTRY, ctx, logger=logger)
    engine = WorkflowEngine(dispatcher, domain_loader=domain_loader)

    inputs = {
        "domain": req.domain_id,
        "project": req.project,
        "schema_vec": dom.schema_vec,
        "context": req.context or "",
        "approve": req.approve,
    }
    run = engine.run(req.template, req.domain_id, inputs)
    return run.to_dict()


@router.get("/skill-executions")
async def skill_executions(workflow_id: Optional[str] = None, limit: int = 50):
    import docintel_routes as routes
    where = f"WHERE workflow_id = '{workflow_id}'" if workflow_id else ""
    try:
        rows = routes.run_sql(f"""
            SELECT execution_id, skill_id, skill_version, workflow_id,
                   work_object_id, start_time, end_time, status, error,
                   model, evidence_count
            FROM {executions_table(routes.CATALOG)}
            {where}
            ORDER BY start_time DESC
            LIMIT {limit}
        """, timeout_secs=30)
    except Exception as e:
        return {"executions": [], "error": str(e)}
    return {"executions": rows or [], "total": len(rows or [])}
