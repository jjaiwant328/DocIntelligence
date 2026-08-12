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
    engine = WorkflowEngine(dispatcher, domain_loader=domain_loader,
                            template_loader=_db_template_loader(routes))

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
    rows = _REGISTRY.list(enabled_only=False)
    detailed = []
    for r in rows:
        item = dict(r)
        try:
            c = _REGISTRY.get(r["id"])
            item.update({"description": c.description, "adapter": c.adapter,
                         "inputs": c.inputs, "outputs": c.outputs,
                         "evidence_requirements": c.evidence_requirements,
                         "side_effects": c.side_effects})
        except Exception:
            pass
        detailed.append(item)
    return {"skills": detailed, "enabled": _REGISTRY.enabled_ids()}


def _starter_templates() -> list:
    """The file-based starter templates (global seeds, clonable per domain)."""
    import os as _os
    import yaml as _yaml
    from workflow_engine.engine import DEFAULT_TEMPLATES_DIR
    out = []
    for fn in sorted(_os.listdir(DEFAULT_TEMPLATES_DIR)):
        if not fn.endswith(".yaml"):
            continue
        with open(_os.path.join(DEFAULT_TEMPLATES_DIR, fn)) as f:
            t = _yaml.safe_load(f)
        out.append({"id": t["id"], "version": t.get("version"),
                    "approval_before": t.get("approval_before"),
                    "steps": [{"id": s["id"], "skill": s["skill"],
                               "inputs_map": s.get("inputs_map", {})} for s in t["steps"]],
                    "source": "starter"})
    return out


def _db_template_loader(routes):
    """Return a callable(domain_id, template_id) -> template dict | None (DB)."""
    from skill_runtime import template_store as tstore

    def _load(domain_id, template_id):
        try:
            return tstore.get_template(
                lambda q: routes.run_sql(q, timeout_secs=40),
                domain_id, template_id, catalog=routes.CATALOG)
        except Exception:
            return None
    return _load


@router.get("/templates")
async def list_templates(domain_id: str = "compliance"):
    """Merge this domain's saved templates (DB) with the starter templates."""
    import docintel_routes as routes
    from skill_runtime import template_store as tstore
    user = []
    try:
        tstore.ensure_templates_table(lambda q: routes.run_sql(q, timeout_secs=40),
                                      catalog=routes.CATALOG)
        user = tstore.list_templates(lambda q: routes.run_sql(q, timeout_secs=40),
                                     domain_id, catalog=routes.CATALOG)
    except Exception as e:
        print(f"[templates] db list failed: {e}")
    user_ids = {t["id"] for t in user}
    starters = [t for t in _starter_templates() if t["id"] not in user_ids]
    return {"templates": user + starters}


class TemplateSaveRequest(BaseModel):
    template_id: str
    domain_id: str = "compliance"
    name: str
    steps: list                       # [{id, skill[, inputs_map]}]
    approval_before: Optional[str] = None
    description: str = ""
    autowire: bool = True             # infer inputs_map from step order + contracts


@router.post("/templates")
async def save_template(req: TemplateSaveRequest):
    import docintel_routes as routes
    from skill_runtime import template_store as tstore
    from skill_runtime.autowire import infer_inputs_map
    steps = infer_inputs_map(req.steps, _REGISTRY) if req.autowire else req.steps
    try:
        res = tstore.save_template(
            lambda q: routes.run_sql(q, timeout_secs=40),
            req.domain_id, req.template_id, req.name, steps,
            approval_before=req.approval_before, description=req.description,
            catalog=routes.CATALOG)
        return {**res, "steps": steps}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, domain_id: str = "compliance"):
    import docintel_routes as routes
    from skill_runtime import template_store as tstore
    try:
        tstore.delete_template(lambda q: routes.run_sql(q, timeout_secs=40),
                               domain_id, template_id, catalog=routes.CATALOG)
        return {"status": "archived", "template_id": template_id}
    except Exception as e:
        return {"status": "error", "error": str(e)}


class AutowireRequest(BaseModel):
    steps: list


@router.post("/autowire")
async def autowire(req: AutowireRequest):
    """Preview: given an ordered step list, return steps with inferred inputs_map."""
    from skill_runtime.autowire import infer_inputs_map
    return {"steps": infer_inputs_map(req.steps, _REGISTRY)}


class SkillInvokeRequest(BaseModel):
    skill: str
    domain_id: str = "compliance"
    inputs: dict = {}
    doc_ids: Optional[list] = None       # apply the skill to these parsed documents


@router.get("/parsed-documents")
async def parsed_documents(domain_id: str = "compliance"):
    """List a subject area's parsed documents (for the Skills 'apply to' picker)."""
    import docintel_routes as routes
    dom = domain_loader(domain_id)
    schemas = routes._get_domain_schemas(dom.platform_domain_id)
    raw = schemas["schema_raw"]
    try:
        rows = routes.run_sql(f"""
            SELECT doc_id, doc_type
            FROM {routes.CATALOG}.{raw}.parsed_documents
            ORDER BY processed_ts DESC NULLS LAST
            LIMIT 200
        """, timeout_secs=30)
    except Exception as e:
        return {"documents": [], "error": str(e)}
    return {"documents": rows or [], "total": len(rows or [])}


def _fetch_doc_rows(routes, raw_schema: str, doc_ids: list) -> list:
    """Fetch doc_id/doc_type/text for the given docs from parsed_documents."""
    if not doc_ids:
        return []
    ids = ", ".join("'" + str(d).replace("'", "''") + "'" for d in doc_ids)
    try:
        return routes.run_sql(f"""
            SELECT doc_id, doc_type,
                   SUBSTRING(CAST(parsed_content AS STRING), 1, 4000) AS text
            FROM {routes.CATALOG}.{raw_schema}.parsed_documents
            WHERE doc_id IN ({ids})
        """, timeout_secs=40) or []
    except Exception as e:
        print(f"[skill-invoke] fetch doc rows failed: {e}")
        return []


@router.post("/skill-invoke")
async def skill_invoke(req: SkillInvokeRequest):
    """Playground: invoke ONE skill. If doc_ids given, auto-build inputs from those
    parsed documents; otherwise use the supplied inputs dict."""
    import docintel_routes as routes
    from skill_runtime.doc_inputs import map_docs_to_inputs
    from skill_runtime.models import InputError

    dom = domain_loader(req.domain_id)
    logger = ExecutionLogger(run_sql=lambda q: routes.run_sql(q, timeout_secs=50),
                             catalog=routes.CATALOG)
    try:
        ensure_table(logger.run_sql, catalog=routes.CATALOG)
    except Exception as e:
        print(f"[skill-invoke] ensure_table failed: {e}")
    ctx = build_live_context(dom.platform_domain_id)
    dispatcher = Dispatcher(_REGISTRY, ctx, logger=logger)

    base = dict(req.inputs or {})
    base.setdefault("schema_vec", dom.schema_vec)
    if req.doc_ids:
        schemas = routes._get_domain_schemas(dom.platform_domain_id)
        rows = _fetch_doc_rows(routes, schemas["schema_raw"], req.doc_ids)
        try:
            inputs = map_docs_to_inputs(_REGISTRY.get(req.skill), rows, base_inputs=base)
        except InputError as e:
            return {"status": "error", "outputs": {}, "evidence": [], "error": str(e)}
    else:
        inputs = base

    result = dispatcher.invoke(req.skill, inputs)
    return result.to_dict()


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
    engine = WorkflowEngine(dispatcher, domain_loader=domain_loader,
                            template_loader=_db_template_loader(routes))

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
