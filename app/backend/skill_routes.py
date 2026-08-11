"""Skills/Workflow overlay routes — additive; does not touch agent_query.

  POST /api/docintel/workflow-run       run a template for a domain + project
  GET  /api/docintel/skills             list registered skills
  GET  /api/docintel/skill-executions   recent execution log rows
"""
from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from skill_runtime.loader import load_registry
from skill_runtime.dispatcher import Dispatcher
from skill_runtime.executions import ExecutionLogger, ensure_table, executions_table
from skill_runtime.context import build_live_context, domain_loader
from skill_runtime.intent import classify
from workflow_engine.engine import WorkflowEngine

router = APIRouter(prefix="/api/docintel", tags=["Skills"])

_REGISTRY = load_registry()

# Overlay-to-platform domain id mapping for the deterministic agent path.
_OVERLAY_DOMAIN = {"compliance_due_diligence": "compliance", "compliance": "compliance",
                   "supply_chain": "supply_chain"}


def deterministic_agent_answer(question: str, platform_domain_id: str,
                               chat_history=None, approve: bool = False) -> dict:
    """ADR-003 deterministic agent: LLM interprets intent only; the engine/skills
    do all orchestration. Consequential intents require explicit confirmation.

    Returns a dict shaped like agent_query's response (answer/question/model/...)
    plus `intent` and, for workflow runs, the structured `run`.
    """
    import docintel_routes as routes

    overlay_domain = _OVERLAY_DOMAIN.get(platform_domain_id, "compliance")
    dom = domain_loader(overlay_domain)

    logger = ExecutionLogger(run_sql=lambda q: routes.run_sql(q, timeout_secs=50),
                             catalog=routes.CATALOG)
    try:
        ensure_table(logger.run_sql, catalog=routes.CATALOG)
    except Exception as e:
        print(f"[det-agent] ensure_table failed: {e}")

    ctx = build_live_context(dom.platform_domain_id)
    dispatcher = Dispatcher(_REGISTRY, ctx, logger=logger)
    engine = WorkflowEngine(dispatcher, domain_loader=domain_loader)

    templates = ["due_diligence"]
    intent = classify(question, ctx.chat_completion, templates, _REGISTRY.enabled_ids())

    # Consequential and not yet approved → summarize, ask for confirmation, do nothing.
    if intent.requires_confirmation and not approve:
        return {
            "answer": (f"This will run the consequential action "
                       f"'{intent.skill or intent.template}'. Re-send with approve=true to proceed."),
            "question": question, "model": routes.AGENT_MODEL,
            "intent": intent.to_dict(), "requires_confirmation": True,
        }

    if intent.kind == "workflow_run":
        inputs = {"domain": overlay_domain, "project": intent.project or question,
                  "schema_vec": dom.schema_vec, "context": "", "approve": approve}
        run = engine.run(intent.template or "due_diligence", overlay_domain, inputs)
        return {
            "answer": _summarize_run(run),
            "question": question, "model": routes.AGENT_MODEL,
            "intent": intent.to_dict(), "run": run.to_dict(),
        }

    if intent.kind == "skill_invoke" and intent.skill:
        result = dispatcher.invoke(intent.skill, intent.params or {})
        return {
            "answer": f"Skill '{intent.skill}' → {result.status}.",
            "question": question, "model": routes.AGENT_MODEL,
            "intent": intent.to_dict(), "result": result.to_dict(),
        }

    # conversational → deterministic retrieval + answer (no tool-order decisions)
    evidence = ctx.vs_search(question, dom.schema_vec, 6, None) or []
    context_text = "\n\n---\n\n".join(
        f"[Source: {r.get('doc_id','?')}]\n{r.get('chunk_to_retrieve','')}" for r in evidence)
    prompt = (f"Answer using only these excerpts; cite document ids.\n\n{context_text}"
              f"\n\nQuestion: {question}") if context_text else question
    answer = ctx.chat_completion(prompt)
    return {"answer": answer, "question": question, "model": routes.AGENT_MODEL,
            "intent": intent.to_dict(),
            "cited_docs": [r.get("doc_id") for r in evidence]}


def _summarize_run(run) -> str:
    lines = [f"Ran {run.template_id} for {run.domain} — status: {run.status}."]
    for s in run.steps:
        lines.append(f"• {s.skill}: {s.status}" + (f" ({s.error})" if s.error else ""))
    if run.status == "pending_approval":
        lines.append("Halted at approval gate — re-send with approve=true to create actions.")
    return "\n".join(lines)


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
