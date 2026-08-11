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
import uuid
from datetime import datetime, timezone

from .adapters.base import Context
from .domains import load_domain


def _now_sql() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _work_objects_table(routes, agt_schema: str) -> str:
    return f"{routes.CATALOG}.{agt_schema}.work_objects"


def build_live_context(domain_id: str) -> Context:
    import docintel_routes as routes  # live module

    schemas = routes._get_domain_schemas(domain_id)
    agt_schema = schemas["schema_agt"]

    def chat_completion(prompt: str) -> str:
        llm, _model = routes._get_llm()
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
        tbl = f"{routes.CATALOG}.{agt_schema}.action_log"
        routes._ensure_action_log_table(tbl)
        ids = []
        for a in inputs.get("proposed_actions", []) or []:
            aid = str(uuid.uuid4())[:8].upper()
            atype = str(a.get("action_type", "REVIEW")).replace("'", "''")
            desc = str(a.get("description", "")).replace("'", "''")
            prio = str(a.get("priority", "MEDIUM")).upper().replace("'", "''")
            incident = str(inputs.get("project", "")).replace("'", "''")
            routes.run_sql(f"""
                INSERT INTO {tbl}
                (action_id, logged_at, action_type, description, priority,
                 incident_ref, logged_by, status)
                VALUES ('{aid}', TIMESTAMP '{_now_sql()}', '{atype}', '{desc}',
                        '{prio}', '{incident}', 'workflow_engine', 'DRAFT')
            """, timeout_secs=30)
            ids.append(aid)
        return {"action_ids": ids}, []

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
    """Engine domain loader. Overlay domain id ('compliance'/'supply_chain')."""
    return load_domain(domain_id)
