"""Skills/Workflow overlay routes — additive; does not touch agent_query.

  POST /api/docintel/workflow-run       run a template for a domain + project
  GET  /api/docintel/skills             list registered skills
  GET  /api/docintel/skill-executions   recent execution log rows
"""
from __future__ import annotations

import json
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

# Lakebase operational store (fast path). On any unavailability the routes fall
# back to the Lakehouse warehouse SQL below — this is the P1 cutover seam.
from db import operational as opstore
from db.lakebase import LakebaseUnavailable

router = APIRouter(prefix="/api/docintel", tags=["Skills"])

_REGISTRY = load_registry()


def deterministic_agent_answer(question: str, use_case_id: str,
                               chat_history=None, approve: bool = False) -> dict:
    """ADR-003 deterministic agent: LLM interprets intent only; the engine/skills
    do all orchestration. Consequential intents require explicit confirmation.

    `use_case_id` is the canonical id (= project = Lakehouse schema; no overlay).
    Returns a dict shaped like agent_query's response (answer/question/model/...)
    plus `intent` and, for workflow runs, the structured `run`.
    """
    import docintel_routes as routes

    logger = ExecutionLogger(run_sql=lambda q: routes.run_sql(q, timeout_secs=50),
                             catalog=routes.CATALOG)
    try:
        ensure_table(logger.run_sql, catalog=routes.CATALOG)
    except Exception as e:
        print(f"[det-agent] ensure_table failed: {e}")

    ctx = build_live_context(use_case_id)
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
        inputs = {"domain": use_case_id, "project": intent.project or question,
                  "schema_vec": use_case_id, "context": "", "approve": approve}
        run = engine.run(intent.template or "due_diligence", use_case_id, inputs)
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
    evidence = ctx.vs_search(question, use_case_id, 6, None) or []
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
    domain_id: str = "compliance_due_diligence"      # use_case_id (= project = schema)
    project: str
    context: Optional[str] = None
    approve: bool = False
    doc_ids: Optional[list] = None     # explicit document set; else the project's tagged docs
    params: Optional[dict] = None      # declared run-time inputs ($param.*), from the run-time form
    save: bool = False                 # persist the full execution for later review
    label: str = ""                    # optional human label for a saved execution


@router.get("/skills")
async def list_skills():
    from skill_runtime.skill_modes import classify_skill
    rows = _REGISTRY.list(enabled_only=False)
    detailed = []
    for r in rows:
        item = dict(r)
        try:
            c = _REGISTRY.get(r["id"])
            item.update({"description": c.description, "adapter": c.adapter,
                         "inputs": c.inputs, "outputs": c.outputs,
                         "evidence_requirements": c.evidence_requirements,
                         "side_effects": c.side_effects,
                         "mode": classify_skill(c)})
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
async def list_templates(domain_id: str = "compliance_due_diligence"):
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
    domain_id: str = "compliance_due_diligence"
    name: str
    steps: list                       # [{id, skill[, inputs_map]}]
    approval_before: Optional[str] = None
    description: str = ""
    autowire: bool = True             # infer inputs_map from step order + contracts
    inputs: Optional[list] = None     # declared run-time params ($param.*): [{name,type,label,default,required,options?}]


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
            catalog=routes.CATALOG, inputs=req.inputs)
        return {**res, "steps": steps, "inputs": req.inputs or []}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, domain_id: str = "compliance_due_diligence"):
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
    domain_id: str = "compliance_due_diligence"
    inputs: dict = {}
    doc_ids: Optional[list] = None       # apply the skill to these parsed documents


def _parse_collaborators(v) -> list:
    """collaborators is stored as a JSON array string; tolerate comma-strings too."""
    if not v:
        return []
    if isinstance(v, list):
        return v
    s = str(v).strip()
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except Exception:
        pass
    return [x.strip() for x in s.split(",") if x.strip()]


@router.get("/projects")
async def list_projects(domain_id: str = "compliance_due_diligence",
                        as_user: Optional[str] = None, enforce: bool = False):
    """Real projects/cases for a subject area, from platform.projects.

    Lightweight access model (demo): every project has an `owner` and a list of
    `collaborators`. When `enforce` is true, only projects where `as_user` is the
    owner or a collaborator are returned; otherwise all are returned (labels-only).
    Enforcement is app-level metadata — not Databricks-enforced — so it can be
    rewired to real access control later.
    """
    import docintel_routes as routes
    pdid = domain_id
    try:
        # Fast path: Lakebase (sub-second). Falls back to the warehouse on any error.
        rows = opstore.list_projects(pdid)
    except LakebaseUnavailable:
        try:
            rows = routes.run_sql(f"""
                SELECT project_id, name, municipality, state, status, owner, collaborators
                FROM {routes.CATALOG}.platform.projects
                WHERE domain_id = '{pdid}' AND status <> '__marker__'
                ORDER BY updated_at DESC NULLS LAST
            """, timeout_secs=30)
        except Exception as e:
            return {"projects": [], "error": str(e)}
    except Exception as e:
        return {"projects": [], "error": str(e)}
    out = []
    for r in (rows or []):
        r["collaborators"] = _parse_collaborators(r.get("collaborators"))
        r["owner"] = r.get("owner") or ""
        if enforce and as_user:
            members = {r["owner"], *r["collaborators"]}
            r["_visible"] = as_user in members
        else:
            r["_visible"] = True
        if r["_visible"]:
            out.append(r)
    return {"projects": out, "total": len(out)}


class ProjectCreateRequest(BaseModel):
    domain_id: str = "compliance_due_diligence"
    name: str
    project_id: Optional[str] = None   # auto-generated from name when omitted
    municipality: str = ""
    state: str = ""
    owner: str = ""                    # the creating user (demo identity)


class ProjectMembersRequest(BaseModel):
    domain_id: str = "compliance_due_diligence"
    owner: Optional[str] = None            # set/transfer owner
    collaborators: Optional[list] = None   # full replacement list


def _gen_project_id(name: str) -> str:
    """Derive a stable-ish project id from a name (slug + short random suffix)."""
    import re
    import uuid as _uuid
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:32] or "project"
    return f"{slug}-{_uuid.uuid4().hex[:6]}"


@router.post("/projects")
async def create_project(req: ProjectCreateRequest):
    """Create a project/case for a subject area. Only the name is required; the
    project_id is auto-generated from it when not supplied."""
    import docintel_routes as routes
    pdid = req.domain_id
    if not (req.name or "").strip():
        return {"status": "error", "error": "project name is required"}
    name = req.name.strip()
    project_id = (req.project_id or "").strip() or _gen_project_id(name)
    owner = (req.owner or "app_user").strip()

    # Fast path: Lakebase. Falls back to the warehouse on unavailability.
    try:
        if opstore.name_exists(pdid, name):
            return {"status": "error", "error": f'A project named "{name}" already exists.'}
        opstore.create_project(domain_id=pdid, project_id=project_id, name=name,
                               municipality=req.municipality, state=req.state, owner=owner)
        return {"status": "created", "project_id": project_id, "name": name, "owner": owner}
    except LakebaseUnavailable:
        pass

    def esc(v: str) -> str:
        return str(v or "").replace("'", "''")

    # Reject duplicate names within the same subject area (case-insensitive).
    try:
        dup = routes.run_sql(f"""
            SELECT count(*) AS c FROM {routes.CATALOG}.platform.projects
            WHERE domain_id = '{pdid}' AND status <> '__marker__'
              AND lower(trim(name)) = lower('{esc(name)}')
        """, timeout_secs=30) or []
        if dup and int(dup[0].get("c", 0)) > 0:
            return {"status": "error", "error": f'A project named "{name}" already exists.'}
    except Exception as e:
        print(f"[create_project] dup check failed: {e}")

    try:
        routes.run_sql(f"""
            INSERT INTO {routes.CATALOG}.platform.projects
              (project_id, domain_id, name, municipality, state, address,
               parcel_id, status, created_by, created_at, updated_at,
               owner, collaborators)
            VALUES ('{esc(project_id)}', '{pdid}', '{esc(name)}',
                    '{esc(req.municipality)}', '{esc(req.state)}', '', '',
                    'Active', '{esc(owner)}', current_timestamp(), current_timestamp(),
                    '{esc(owner)}', '[]')
        """, timeout_secs=40)
    except Exception as e:
        return {"status": "error", "error": str(e)}
    return {"status": "created", "project_id": project_id, "name": name, "owner": owner}


@router.patch("/projects/{project_id}/members")
async def update_project_members(project_id: str, req: ProjectMembersRequest):
    """Set a project's owner and/or its collaborator list (demo identity metadata)."""
    import docintel_routes as routes
    pdid = req.domain_id
    pid = str(project_id).replace("'", "''")

    try:
        opstore.update_members(domain_id=pdid, project_id=str(project_id),
                               owner=req.owner, collaborators=req.collaborators)
        return {"status": "ok", "project_id": project_id}
    except LakebaseUnavailable:
        pass

    def esc(v: str) -> str:
        return str(v or "").replace("'", "''")
    sets = ["updated_at = current_timestamp()"]
    if req.owner is not None:
        sets.append(f"owner = '{esc(req.owner)}'")
    if req.collaborators is not None:
        collabs = json.dumps([str(c).strip() for c in req.collaborators if str(c).strip()])
        sets.append(f"collaborators = '{esc(collabs)}'")
    try:
        routes.run_sql(f"""
            UPDATE {routes.CATALOG}.platform.projects
            SET {', '.join(sets)}
            WHERE domain_id = '{pdid}' AND project_id = '{pid}'
        """, timeout_secs=40)
    except Exception as e:
        return {"status": "error", "error": str(e)}
    return {"status": "ok", "project_id": project_id}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, domain_id: str = "compliance_due_diligence"):
    """Delete a project and its document tags. Hard delete (demo data)."""
    import docintel_routes as routes
    pdid = domain_id
    pid = str(project_id).replace("'", "''")
    try:
        opstore.delete_project(domain_id=pdid, project_id=str(project_id))
        return {"status": "deleted", "project_id": project_id}
    except LakebaseUnavailable:
        pass
    try:
        routes.run_sql(f"""
            DELETE FROM {routes.CATALOG}.platform.projects
            WHERE domain_id = '{pdid}' AND project_id = '{pid}'
        """, timeout_secs=40)
        # also drop this project's document tags so nothing dangles
        routes.run_sql(f"""
            DELETE FROM {routes.CATALOG}.platform.document_project_tags
            WHERE domain_id = '{pdid}' AND project_id = '{pid}'
        """, timeout_secs=40)
    except Exception as e:
        return {"status": "error", "error": str(e)}
    return {"status": "deleted", "project_id": project_id}


class ProjectDocsRequest(BaseModel):
    domain_id: str = "compliance_due_diligence"
    project_id: str
    doc_ids: list                      # documents to add or remove


@router.post("/project-documents")
async def add_project_documents(req: ProjectDocsRequest):
    """Tag one or more documents to a project (idempotent per doc)."""
    import docintel_routes as routes
    pdid = req.domain_id
    pid = str(req.project_id).replace("'", "''")
    try:
        added = opstore.add_tags(domain_id=pdid, project_id=str(req.project_id),
                                 doc_ids=req.doc_ids or [])
        return {"status": "ok", "added": added, "project_id": req.project_id}
    except LakebaseUnavailable:
        pass
    added = 0
    for did in req.doc_ids or []:
        d = str(did).replace("'", "''")
        try:
            # delete-then-insert keeps it idempotent (no duplicate tag rows)
            routes.run_sql(f"""
                DELETE FROM {routes.CATALOG}.platform.document_project_tags
                WHERE domain_id='{pdid}' AND project_id='{pid}' AND doc_id='{d}'
            """, timeout_secs=30)
            routes.run_sql(f"""
                INSERT INTO {routes.CATALOG}.platform.document_project_tags
                  (domain_id, doc_id, project_id, scope, source, tagged_by, tagged_at)
                VALUES ('{pdid}','{d}','{pid}','project','manual','app_user',current_timestamp())
            """, timeout_secs=30)
            added += 1
        except Exception as e:
            print(f"[project-documents] add failed for {did}: {e}")
    return {"status": "ok", "added": added, "project_id": req.project_id}


@router.delete("/project-documents")
async def remove_project_documents(req: ProjectDocsRequest):
    """Untag documents from a project."""
    import docintel_routes as routes
    pdid = req.domain_id
    pid = str(req.project_id).replace("'", "''")
    try:
        removed = opstore.remove_tags(domain_id=pdid, project_id=str(req.project_id),
                                      doc_ids=req.doc_ids or [])
        return {"status": "ok", "removed": removed, "project_id": req.project_id}
    except LakebaseUnavailable:
        pass
    removed = 0
    for did in req.doc_ids or []:
        d = str(did).replace("'", "''")
        try:
            routes.run_sql(f"""
                DELETE FROM {routes.CATALOG}.platform.document_project_tags
                WHERE domain_id='{pdid}' AND project_id='{pid}' AND doc_id='{d}'
            """, timeout_secs=30)
            removed += 1
        except Exception as e:
            print(f"[project-documents] remove failed for {did}: {e}")
    return {"status": "ok", "removed": removed, "project_id": req.project_id}


@router.get("/all-documents")
async def all_documents(domain_id: str = "compliance_due_diligence", project_id: Optional[str] = None):
    """Every parsed doc in the subject area, each flagged with whether it is in
    `project_id` — powers the 'assemble documents for a project' picker."""
    import docintel_routes as routes
    pdid = domain_id
    schemas = routes._get_domain_schemas(pdid)
    raw = schemas["schema_raw"]
    tagged = set(_project_doc_ids(routes, pdid, project_id)) if project_id else set()
    try:
        rows = routes.run_sql(f"""
            SELECT doc_id,
                   array_join(array_sort(collect_set(doc_type)), ', ') AS doc_type
            FROM {routes.CATALOG}.{raw}.parsed_documents
            GROUP BY doc_id
            ORDER BY doc_id
            LIMIT 500
        """, timeout_secs=30) or []
    except Exception as e:
        return {"documents": [], "error": str(e)}
    for r in rows:
        r["in_project"] = r.get("doc_id") in tagged
    return {"documents": rows, "total": len(rows), "in_project_count": len(tagged)}


@router.get("/parsed-documents")
async def parsed_documents(domain_id: str = "compliance_due_diligence",
                           project_id: Optional[str] = None):
    """List a subject area's parsed documents (for the Skills 'apply to' picker).

    When project_id is given, restrict to documents tagged to that project via
    platform.document_project_tags.
    """
    import docintel_routes as routes
    pdid = domain_id
    schemas = routes._get_domain_schemas(pdid)
    raw = schemas["schema_raw"]
    # A document can carry more than one classification (multiple doc_type rows)
    # and/or more than one project tag. Aggregate so each doc_id appears ONCE
    # with all its categories collected into doc_types.
    try:
        if project_id:
            # Tags live in Lakebase now, so resolve the project's doc_ids there and
            # filter parsed_documents by them (no cross-store JOIN).
            doc_ids = _project_doc_ids(routes, pdid, project_id)
            if not doc_ids:
                return {"documents": [], "total": 0}
            in_list = ", ".join("'" + str(d).replace("'", "''") + "'" for d in doc_ids)
            rows = routes.run_sql(f"""
                SELECT pd.doc_id,
                       array_join(array_sort(collect_set(pd.doc_type)), ', ') AS doc_type,
                       collect_set(pd.doc_type) AS doc_types,
                       max(pd.processed_ts) AS processed_ts
                FROM {routes.CATALOG}.{raw}.parsed_documents pd
                WHERE pd.doc_id IN ({in_list})
                GROUP BY pd.doc_id
                ORDER BY processed_ts DESC NULLS LAST
                LIMIT 200
            """, timeout_secs=30)
        else:
            rows = routes.run_sql(f"""
                SELECT doc_id,
                       array_join(array_sort(collect_set(doc_type)), ', ') AS doc_type,
                       collect_set(doc_type) AS doc_types,
                       max(processed_ts) AS processed_ts
                FROM {routes.CATALOG}.{raw}.parsed_documents
                GROUP BY doc_id
                ORDER BY processed_ts DESC NULLS LAST
                LIMIT 200
            """, timeout_secs=30)
    except Exception as e:
        return {"documents": [], "error": str(e)}
    # run_sql serializes SQL arrays (collect_set) as JSON strings; decode doc_types
    # back into a real list so the client always receives an array.
    for r in (rows or []):
        dt = r.get("doc_types")
        if isinstance(dt, str):
            try:
                r["doc_types"] = json.loads(dt)
            except Exception:
                r["doc_types"] = [x.strip() for x in dt.split(",") if x.strip()]
    return {"documents": rows or [], "total": len(rows or [])}


def _project_doc_ids(routes, use_case_id: str, project_id: str) -> list:
    """The doc_ids tagged to a project. Single choke point for tag lookups, so
    it also isolates the tags store: Lakebase first, warehouse fallback. This is
    what lets `document_project_tags` live in Lakebase while parsed_documents
    (the thing we join against) stays in the Lakehouse."""
    if not project_id:
        return []
    try:
        return opstore.doc_ids_for_project(domain_id=use_case_id,
                                           project_id=str(project_id))
    except LakebaseUnavailable:
        pass
    except Exception as e:
        print(f"[tags] Lakebase doc lookup failed: {e}")
    pid = str(project_id).replace("'", "''")
    try:
        rows = routes.run_sql(f"""
            SELECT DISTINCT doc_id
            FROM {routes.CATALOG}.platform.document_project_tags
            WHERE domain_id = '{use_case_id}' AND project_id = '{pid}'
        """, timeout_secs=30) or []
    except Exception as e:
        print(f"[workflow-run] project doc lookup failed: {e}")
        return []
    return [r.get("doc_id") for r in rows if r.get("doc_id")]


def _fetch_doc_rows(routes, raw_schema: str, doc_ids: list) -> list:
    """Fetch doc_id/doc_type/text for the given docs from parsed_documents.

    A doc with multiple classifications has multiple rows; collapse to ONE row
    per doc_id (text taken once) so skill inputs don't get duplicated text."""
    if not doc_ids:
        return []
    ids = ", ".join("'" + str(d).replace("'", "''") + "'" for d in doc_ids)
    try:
        return routes.run_sql(f"""
            SELECT doc_id,
                   array_join(array_sort(collect_set(doc_type)), ', ') AS doc_type,
                   max(SUBSTRING(CAST(parsed_content AS STRING), 1, 4000)) AS text
            FROM {routes.CATALOG}.{raw_schema}.parsed_documents
            WHERE doc_id IN ({ids})
            GROUP BY doc_id
        """, timeout_secs=40) or []
    except Exception as e:
        print(f"[skill-invoke] fetch doc rows failed: {e}")
        return []


def _resolve_doc_set(domain_id: str, project_id: str, routes=None) -> list[dict]:
    """Return [{doc_id, doc_type, text}] for the workflow engine.

    Primary path: Lakebase external_documents (status=indexed) + concatenated
    chunk snippets as text.  Fallback: legacy Volume/parsed_documents when no
    indexed external docs exist (cutover safety — keeps legacy projects working).

    `routes` is the lazily-imported docintel_routes module; required only for
    the legacy fallback path.  The Lakebase path never needs it.
    """
    try:
        ext_docs = opstore.list_docs_for_project(domain_id, project_id,
                                                  statuses=["indexed"])
        if ext_docs:
            result = []
            for doc in ext_docs:
                eid = doc["external_document_id"]
                chunks = opstore.list_chunks_for_doc(eid)
                text = "\n\n".join(
                    c.get("snippet", "") for c in chunks if c.get("snippet")
                )
                result.append({
                    "doc_id": eid,
                    "doc_type": doc.get("mime_type") or doc.get("name") or "",
                    "text": text,
                })
            return result
    except LakebaseUnavailable:
        pass
    except Exception as e:
        print(f"[resolve-doc-set] Lakebase lookup failed: {e}")

    # Legacy fallback — requires the docintel_routes object for SQL access.
    if routes is None:
        return []
    doc_ids = _project_doc_ids(routes, domain_id, project_id)
    schemas = routes._get_domain_schemas(domain_id)
    return _fetch_doc_rows(routes, schemas["schema_raw"], doc_ids) if doc_ids else []


@router.post("/skill-invoke")
async def skill_invoke(req: SkillInvokeRequest):
    """Playground: invoke ONE skill. If doc_ids given, auto-build inputs from those
    parsed documents; otherwise use the supplied inputs dict."""
    import docintel_routes as routes
    from skill_runtime.doc_inputs import map_docs_to_inputs
    from skill_runtime.models import InputError

    logger = ExecutionLogger(run_sql=lambda q: routes.run_sql(q, timeout_secs=50),
                             catalog=routes.CATALOG)
    try:
        ensure_table(logger.run_sql, catalog=routes.CATALOG)
    except Exception as e:
        print(f"[skill-invoke] ensure_table failed: {e}")
    ctx = build_live_context(req.domain_id)
    dispatcher = Dispatcher(_REGISTRY, ctx, logger=logger)

    from skill_runtime.skill_modes import classify_skill
    contract = _REGISTRY.get(req.skill)
    base = dict(req.inputs or {})
    base.setdefault("schema_vec", req.domain_id)

    if not req.doc_ids:
        return dispatcher.invoke(req.skill, base).to_dict()

    schemas = routes._get_domain_schemas(req.domain_id)
    rows = _fetch_doc_rows(routes, schemas["schema_raw"], req.doc_ids)

    # Document-reading skills (classify/summarize/extract…) apply to ONE document
    # at a time — running them once over concatenated text would collapse many
    # documents into a single answer. Run per-document and return per_doc results.
    mode = classify_skill(contract)
    if mode.get("needs_docs") and len(rows) > 1:
        per_doc = []
        for r in rows:
            try:
                inputs = map_docs_to_inputs(contract, [r], base_inputs=base)
                res = dispatcher.invoke(req.skill, inputs).to_dict()
            except InputError as e:
                res = {"status": "error", "outputs": {}, "evidence": [], "error": str(e)}
            res["doc_id"] = r.get("doc_id")
            per_doc.append(res)
        ok = [p for p in per_doc if p.get("status") not in ("error",)]
        return {
            "status": "ok" if ok else "error",
            "per_doc": per_doc,
            "outputs": {"documents_processed": len(per_doc),
                        "succeeded": len(ok)},
            "evidence": [],
            "error": None if ok else "all documents failed",
        }

    # single document, or a skill that consumes the corpus at once
    try:
        inputs = map_docs_to_inputs(contract, rows, base_inputs=base)
    except InputError as e:
        return {"status": "error", "outputs": {}, "evidence": [], "error": str(e)}
    result = dispatcher.invoke(req.skill, inputs).to_dict()
    if len(rows) == 1:
        result["doc_id"] = rows[0].get("doc_id")
    return result


@router.post("/workflow-run")
async def workflow_run(req: WorkflowRunRequest):
    import docintel_routes as routes

    logger = ExecutionLogger(run_sql=lambda q: routes.run_sql(q, timeout_secs=50),
                             catalog=routes.CATALOG)
    try:
        ensure_table(logger.run_sql, catalog=routes.CATALOG)
    except Exception as e:
        print(f"[workflow-run] ensure_table failed: {e}")

    ctx = build_live_context(req.domain_id)
    dispatcher = Dispatcher(_REGISTRY, ctx, logger=logger)
    engine = WorkflowEngine(dispatcher, domain_loader=domain_loader,
                            template_loader=_db_template_loader(routes))

    # Assemble the workflow's document set.
    # Explicit doc_ids in the request take precedence (legacy Volume path).
    # Otherwise _resolve_doc_set checks Lakebase-indexed external docs first
    # and falls back to the legacy parsed_documents path for projects that have
    # no external docs yet (cutover safety).
    if req.doc_ids:
        schemas = routes._get_domain_schemas(req.domain_id)
        docs = _fetch_doc_rows(routes, schemas["schema_raw"], req.doc_ids)
    else:
        docs = _resolve_doc_set(req.domain_id, req.project, routes=routes)

    inputs = {
        "domain": req.domain_id,
        "project": req.project,
        "schema_vec": req.domain_id,
        "context": req.context or "",
        "approve": req.approve,
    }
    from workflow_engine.engine import NoDocumentsError, ParamError
    try:
        run = engine.run(req.template, req.domain_id, inputs, docs=docs, params=req.params)
    except ParamError as e:
        return {"status": "error", "error": str(e), "kind": "param_error"}
    except NoDocumentsError as e:
        return {"status": "error", "error": str(e), "kind": "no_documents"}
    result = run.to_dict()
    # Every run is auto-saved, losslessly (Lakebase). No opt-in.
    try:
        from skill_runtime.run_store import record_run
        label = req.label or f"{req.template} · {req.project}".strip(" ·")
        rid = record_run(lambda q: routes.run_sql(q, timeout_secs=40),
                         req.domain_id, req.project, result,
                         label=label, catalog=routes.CATALOG)
        result["run_id"] = rid
        result["saved"] = True
    except Exception as e:
        print(f"[workflow-run] record_run failed: {e}")
    return result


@router.get("/workflow-runs")
async def workflow_runs(domain_id: str = "compliance_due_diligence",
                        project_id: Optional[str] = None,
                        saved_only: bool = False):
    """Run summaries for the Executions tab, grouped by project when given."""
    import docintel_routes as routes
    from skill_runtime.run_store import list_runs
    rows = list_runs(lambda q: routes.run_sql(q, timeout_secs=40),
                     domain_id, project_id, saved_only=saved_only,
                     catalog=routes.CATALOG)
    return {"runs": rows or [], "total": len(rows or [])}


@router.get("/run-coverage")
async def run_coverage(domain_id: str = "compliance_due_diligence",
                       project_id: Optional[str] = None):
    """Coverage summary for the Executions → Coverage tab: documents ingested by
    type, reconcile findings grouped by check (severity + $ impact), and evidence
    reach. Findings come from the latest run of each template (no re-run double
    counting). Populated for AP/Supplier domains where the ontology graph is empty."""
    import docintel_routes as routes
    from skill_runtime.run_store import list_runs, get_run
    _sql = lambda q: routes.run_sql(q, timeout_secs=40)  # noqa: E731
    schemas = routes._get_domain_schemas(domain_id)
    raw = schemas["schema_raw"]

    # 1. Documents covered — distinct docs per type, scoped to the project's
    #    tagged docs when it has any, else the whole domain corpus.
    doc_ids = _project_doc_ids(routes, domain_id, project_id) if project_id else []
    where = ""
    if doc_ids:
        ids = ", ".join("'" + str(d).replace("'", "''") + "'" for d in doc_ids)
        where = f"WHERE doc_id IN ({ids})"
    by_type, total_docs = [], 0
    try:
        by_type = _sql(f"""
            SELECT doc_type, COUNT(DISTINCT doc_id) AS count
            FROM {routes.CATALOG}.{raw}.parsed_documents {where}
            GROUP BY doc_type ORDER BY count DESC
        """) or []
        tot = _sql(f"SELECT COUNT(DISTINCT doc_id) AS n "
                   f"FROM {routes.CATALOG}.{raw}.parsed_documents {where}") or []
        total_docs = int((tot[0] or {}).get("n", 0)) if tot else 0
    except Exception as e:
        print(f"[run-coverage] document rollup failed: {e}")

    # 2. Findings by check + evidence reach — latest run per template.
    runs = list_runs(_sql, domain_id, project_id, catalog=routes.CATALOG) or []
    checks: dict = {}
    ev_quotes, ev_docs, seen_templates = 0, set(), set()
    for r in runs:
        tid = r.get("template_id")
        if tid in seen_templates:
            continue
        seen_templates.add(tid)
        full = get_run(_sql, r.get("run_id"), catalog=routes.CATALOG)
        for step in (full or {}).get("steps", []) or []:
            outs = step.get("outputs") or {}
            for f in outs.get("findings") or []:
                if not isinstance(f, dict):
                    continue
                c = str(f.get("check") or "other")
                e = checks.setdefault(c, {"check": c, "count": 0, "high": 0,
                                          "medium": 0, "low": 0, "impact": 0.0})
                e["count"] += 1
                sev = str(f.get("severity", "")).lower()
                if sev in ("high", "medium", "low"):
                    e[sev] += 1
                try:
                    e["impact"] += float(f.get("amount_impact") or 0)
                except (TypeError, ValueError):
                    pass
            for ev in step.get("evidence") or []:
                if isinstance(ev, dict):
                    ev_quotes += 1
                    if ev.get("document_id"):
                        ev_docs.add(ev.get("document_id"))

    by_check = sorted(checks.values(), key=lambda x: x["count"], reverse=True)
    findings_total = sum(c["count"] for c in by_check)
    return {
        "documents": {"total": total_docs, "by_type": by_type},
        "findings": {"total": findings_total, "by_check": by_check},
        "evidence": {"quotes": ev_quotes, "docs": len(ev_docs)},
        "runs_considered": len(seen_templates),
    }


@router.get("/workflow-run/{run_id}")
async def get_workflow_run(run_id: str):
    """Reopen a saved execution's full detail (steps/outputs/evidence)."""
    import docintel_routes as routes
    from skill_runtime.run_store import get_run
    run = get_run(lambda q: routes.run_sql(q, timeout_secs=40),
                  run_id, catalog=routes.CATALOG)
    if run is None:
        return {"error": "not found", "run": None}
    return {"run": run}


class RunRenameRequest(BaseModel):
    label: str


@router.delete("/workflow-run/{run_id}")
async def delete_workflow_run(run_id: str):
    """Hard-delete a saved execution (any status — clears stuck/halted runs too)."""
    import docintel_routes as routes
    from skill_runtime.run_store import delete_run
    ok = delete_run(lambda q: routes.run_sql(q, timeout_secs=40),
                    run_id, catalog=routes.CATALOG)
    return {"deleted": bool(ok), "run_id": run_id}


@router.patch("/workflow-run/{run_id}")
async def rename_workflow_run(run_id: str, req: RunRenameRequest):
    """Rename a saved execution (its human-readable label)."""
    import docintel_routes as routes
    from skill_runtime.run_store import rename_run
    ok = rename_run(lambda q: routes.run_sql(q, timeout_secs=40),
                    run_id, req.label, catalog=routes.CATALOG)
    return {"renamed": bool(ok), "run_id": run_id, "label": req.label}


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
