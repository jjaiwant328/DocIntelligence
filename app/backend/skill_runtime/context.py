"""Build the live execution Context from docintel_routes seams.

Wraps existing capabilities — never reimplements them:
  - uc_function / vs_search  -> docintel_routes._vs_search (ai_similarity retrieval)
  - run_sql                  -> docintel_routes.run_sql
  - chat_completion          -> docintel_routes._get_llm().invoke(...)
  - internal create_work_object / create_action -> thin writes reusing run_sql +
    the existing per-domain action_log table + skill work_objects table.

Imported lazily inside functions so the module stays importable offline (tests).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from .adapters.base import Context
from .domains import load_domain


def _now_sql() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# Map a reconcile finding's check name to an actionable action_type. First
# substring match wins; unmatched checks become the upper-cased check itself.
_CHECK_ACTION_TYPES = [
    ("price", "PRICE_DISPUTE"),
    ("quantity", "QUANTITY_DISPUTE"),
    ("duplicate", "BLOCK_DUPLICATE"),
    ("receipt", "REQUEST_GRN"),
    ("on_time", "SUPPLIER_ESCALATION"),
    ("sla", "SUPPLIER_ESCALATION"),
    ("delivery", "SUPPLIER_ESCALATION"),
]
_SEVERITY_PRIORITY = {"high": "HIGH", "critical": "HIGH",
                      "medium": "MEDIUM", "low": "LOW"}


def _finding_to_action(f: dict) -> dict:
    """Translate a reconcile finding into an actionable action.

    Findings are {check, severity, subject_doc, reference_doc, detail,
    amount_impact}; actions need {action_type, description, priority}. Templates
    wire `proposed_actions: $steps.reconcile.findings` directly, so without this
    every action would fall back to create_action's defaults (REVIEW / '' /
    MEDIUM). An item already carrying `action_type` is returned unchanged."""
    if f.get("action_type"):
        return f
    check = str(f.get("check", "")).lower()
    atype = None
    for key, val in _CHECK_ACTION_TYPES:
        if key in check:
            atype = val
            break
    if not atype:
        atype = re.sub(r"[^A-Z0-9]+", "_", check.upper()).strip("_") or "REVIEW"
    detail = str(f.get("detail") or f.get("description") or "").strip()
    refs = " vs ".join(x for x in [str(f.get("subject_doc") or "").strip(),
                                   str(f.get("reference_doc") or "").strip()] if x)
    try:
        impact = float(f.get("amount_impact") or 0)
    except (TypeError, ValueError):
        impact = 0.0
    parts = ([f"[{refs}]"] if refs else []) + [detail or check or "Review discrepancy"]
    if impact:
        parts.append(f"— ${impact:,.2f} impact")
    prio = _SEVERITY_PRIORITY.get(str(f.get("severity", "")).lower(), "MEDIUM")
    return {"action_type": atype, "description": " ".join(parts), "priority": prio,
            "amount_impact": impact}


def _work_objects_table(routes, agt_schema: str) -> str:
    return f"{routes.CATALOG}.{agt_schema}.work_objects"


def build_live_context(domain_id: str) -> Context:
    import docintel_routes as routes  # live module

    schemas = routes._get_domain_schemas(domain_id)
    agt_schema = schemas["schema_agt"]

    def chat_completion(prompt: str) -> str:
        # Skills like reconcile_documents emit findings + scorecard + verbatim
        # evidence quotes; a real multi-document corpus needs ~2.7k output tokens.
        # The default 2048 truncates that mid-string (finish_reason=length) and the
        # partial JSON fails to parse ("model did not return JSON"), so give the
        # skill LLM calls comfortable headroom.
        llm, _model = routes._get_llm(max_tokens=8192)
        resp = llm.invoke(prompt)
        return getattr(resp, "content", str(resp))

    def vs_search(query, schema_vec, k=6, doc_type=None):
        return routes._vs_search(query, schema_vec, k=k, doc_type_filter=doc_type)

    def create_work_object(inputs, ctx):
        tbl = _work_objects_table(routes, agt_schema)
        routes.run_sql(f"""
            CREATE TABLE IF NOT EXISTS {tbl} (
                work_object_id STRING, domain STRING, type STRING,
                title STRING, project STRING, status STRING, created_at TIMESTAMP
            ) USING DELTA
        """, timeout_secs=30)
        wid = "WO-" + str(uuid.uuid4())[:8].upper()
        title = (inputs.get("title") or inputs.get("project") or "").replace("'", "''")
        routes.run_sql(f"""
            INSERT INTO {tbl} VALUES (
                '{wid}', '{inputs.get("domain","")}', '{inputs.get("type","review")}',
                '{title}', '{str(inputs.get("project","")).replace("'","''")}',
                'open', TIMESTAMP '{_now_sql()}')
        """, timeout_secs=30)
        return {"work_object_id": wid,
                "work_object": {"id": wid, "domain": inputs.get("domain"),
                                "type": inputs.get("type", "review"),
                                "project": inputs.get("project")}}, []

    def create_action(inputs, ctx):
        # Reuse the existing per-domain action_log table; AI actions are DRAFT.
        # Reconcile findings are translated to actionable actions first — the raw
        # defaults would otherwise drop the type/description/priority of each one.
        tbl = f"{routes.CATALOG}.{agt_schema}.action_log"
        routes._ensure_action_log_table(tbl)
        incident = str(inputs.get("project", "")).replace("'", "''")
        created = []
        for raw in inputs.get("proposed_actions", []) or []:
            a = (_finding_to_action(raw) if isinstance(raw, dict)
                 else {"action_type": "REVIEW", "description": str(raw),
                       "priority": "MEDIUM"})
            aid = str(uuid.uuid4())[:8].upper()
            atype = str(a.get("action_type", "REVIEW")).replace("'", "''")
            desc = str(a.get("description", "")).replace("'", "''")
            prio = str(a.get("priority", "MEDIUM")).upper().replace("'", "''")
            routes.run_sql(f"""
                INSERT INTO {tbl}
                (action_id, logged_at, action_type, description, priority,
                 incident_ref, logged_by, status)
                VALUES ('{aid}', TIMESTAMP '{_now_sql()}', '{atype}', '{desc}',
                        '{prio}', '{incident}', 'workflow_engine', 'DRAFT')
            """, timeout_secs=30)
            created.append({"action_id": aid,
                            "action_type": a.get("action_type", "REVIEW"),
                            "description": a.get("description", ""),
                            "priority": a.get("priority", "MEDIUM"),
                            "status": "DRAFT"})
        return {"action_ids": [c["action_id"] for c in created],
                "actions": created}, []

    def create_finding(inputs, ctx):
        tbl = f"{routes.CATALOG}.{agt_schema}.findings"
        routes.run_sql(f"""
            CREATE TABLE IF NOT EXISTS {tbl} (
                finding_id STRING, work_object_id STRING, finding_type STRING,
                description STRING, created_at TIMESTAMP
            ) USING DELTA
        """, timeout_secs=30)
        fid = "FND-" + str(uuid.uuid4())[:8].upper()
        desc = str(inputs.get("description", "")).replace("'", "''")
        routes.run_sql(f"""
            INSERT INTO {tbl} VALUES (
                '{fid}', '{str(inputs.get("work_object_id","")).replace("'","''")}',
                '{str(inputs.get("finding_type","")).replace("'","''")}',
                '{desc}', TIMESTAMP '{_now_sql()}')
        """, timeout_secs=30)
        return {"finding_id": fid}, []

    def _update_action(action_id, sets: str):
        tbl = f"{routes.CATALOG}.{agt_schema}.action_log"
        routes._ensure_action_log_table(tbl)
        aid = str(action_id).replace("'", "''")
        routes.run_sql(f"UPDATE {tbl} SET {sets} WHERE action_id = '{aid}'",
                       timeout_secs=30)

    def assign_action(inputs, ctx):
        who = str(inputs.get("assigned_to", "")).replace("'", "''")
        _update_action(inputs["action_id"], f"status = 'ASSIGNED', logged_by = '{who}'")
        return {"action_id": inputs["action_id"], "status": "ASSIGNED"}, []

    def escalate_action(inputs, ctx):
        _update_action(inputs["action_id"], "priority = 'CRITICAL', status = 'ESCALATED'")
        return {"action_id": inputs["action_id"], "status": "ESCALATED"}, []

    def close_action(inputs, ctx):
        _update_action(inputs["action_id"], "status = 'CLOSED'")
        return {"action_id": inputs["action_id"], "status": "CLOSED"}, []

    return Context(
        run_sql=lambda q: routes.run_sql(q, timeout_secs=50),
        vs_search=vs_search,
        chat_completion=chat_completion,
        resolve_model=routes._resolve_model,
        internal={"create_work_object": create_work_object,
                  "create_action": create_action,
                  "create_finding": create_finding,
                  "assign_action": assign_action,
                  "escalate_action": escalate_action,
                  "close_action": close_action},
    )


def domain_loader(domain_id: str):
    """Engine use-case config loader — `domain_id` is the canonical use_case_id
    (no more overlay→platform translation). Loads ontology + requirements."""
    return load_domain(domain_id)
