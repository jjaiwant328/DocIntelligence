"""Turn a Blueprint into a live use case.

Orchestrates, in one call, what used to be a wizard + the manual
scripts/create_domain_job.py:
  1. register the use-case config (platform.domain_configs)
  2. create its Lakehouse schema + document/checkpoint volumes
  3. seed its starter workflow (workflow_templates)
  4. create its project row (Lakebase)
  5. (optional) create the ingestion pipeline job + grant the app SP
  6. mark the use case active

Every step returns a status entry so the caller can report progress. `dry_run`
resolves + validates without writing anything.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from . import loader

CATALOG_DEFAULT = "jai_docintel"


def _esc(v) -> str:
    return str(v if v is not None else "").replace("'", "''")


def _json_col(v) -> str:
    return json.dumps(v or {}, ensure_ascii=False)


def derive_config(blueprint: dict, use_case_id: str) -> dict:
    """Blueprint → the domain_configs row values. New use cases use ONE schema
    named after the id (the single-schema layout 00_setup uses for new domains)."""
    schema = use_case_id
    return {
        "domain_id": use_case_id,
        "name": blueprint.get("name", use_case_id),
        "description": (blueprint.get("description") or "").strip(),
        "schema_raw": schema, "schema_ont": schema,
        "schema_vec": schema, "schema_agt": schema,
        "volume_docs": "documents",
        "classification_labels": _json_col(blueprint.get("classification_labels")),
        "extraction_schemas": _json_col(blueprint.get("extraction_schemas")),
        "entity_types": json.dumps(blueprint.get("entity_types") or []),
        "agent_system_prompt": (blueprint.get("agent_system_prompt") or "").strip(),
        "analytics_config": _json_col({"blueprint_id": blueprint.get("id")}),
        "suggested_questions": json.dumps(blueprint.get("suggested_questions") or []),
    }


def _domain_exists(run_sql, catalog: str, use_case_id: str) -> bool:
    try:
        rows = run_sql(
            f"SELECT 1 FROM {catalog}.platform.domain_configs "
            f"WHERE domain_id = '{_esc(use_case_id)}' LIMIT 1"
        ) or []
        return len(rows) > 0
    except Exception:
        return False


def register_use_case(run_sql, cfg: dict, catalog: str = CATALOG_DEFAULT) -> None:
    """UPSERT the domain_configs row (INSERT new, else UPDATE the JSON columns)."""
    if _domain_exists(run_sql, catalog, cfg["domain_id"]):
        run_sql(f"""
            UPDATE {catalog}.platform.domain_configs SET
              name='{_esc(cfg['name'])}', description='{_esc(cfg['description'])}',
              classification_labels='{_esc(cfg['classification_labels'])}',
              extraction_schemas='{_esc(cfg['extraction_schemas'])}',
              entity_types='{_esc(cfg['entity_types'])}',
              agent_system_prompt='{_esc(cfg['agent_system_prompt'])}',
              analytics_config='{_esc(cfg['analytics_config'])}',
              suggested_questions='{_esc(cfg['suggested_questions'])}',
              updated_at=current_timestamp()
            WHERE domain_id='{_esc(cfg['domain_id'])}'
        """)
        return
    run_sql(f"""
        INSERT INTO {catalog}.platform.domain_configs VALUES (
            '{_esc(cfg['domain_id'])}', '{_esc(cfg['name'])}', '{_esc(cfg['description'])}',
            'configuring', '{_esc(cfg['schema_raw'])}', '{_esc(cfg['schema_ont'])}',
            '{_esc(cfg['schema_vec'])}', '{_esc(cfg['schema_agt'])}', '{_esc(cfg['volume_docs'])}',
            '{_esc(cfg['classification_labels'])}', '{_esc(cfg['extraction_schemas'])}',
            '{_esc(cfg['entity_types'])}', '{_esc(cfg['agent_system_prompt'])}',
            '{_esc(cfg['analytics_config'])}', '{_esc(cfg['suggested_questions'])}',
            current_timestamp(), current_timestamp()
        )
    """)


def create_schema_and_volumes(run_sql, cfg: dict, catalog: str = CATALOG_DEFAULT) -> None:
    """Create the use case's schema (required) and its document/checkpoint volumes.
    Volumes are only needed for real PDF ingestion (ai_parse), so their creation is
    best-effort — a permission hiccup there must not fail the whole provision."""
    schema = cfg["schema_raw"]
    run_sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
    for vol in ("documents", "checkpoints"):
        try:
            run_sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.{vol}")
        except Exception as e:
            print(f"[provision] volume {schema}.{vol} not created (ingestion-only): {e}")


def mark_active(run_sql, use_case_id: str, catalog: str = CATALOG_DEFAULT) -> None:
    run_sql(
        f"UPDATE {catalog}.platform.domain_configs SET status='active', "
        f"updated_at=current_timestamp() WHERE domain_id='{_esc(use_case_id)}'"
    )


def provision(*, blueprint_id: str, use_case_id: str, name: str = "",
              owner: str = "app_user", run_sql: Callable[..., Any],
              catalog: str = CATALOG_DEFAULT, dry_run: bool = False,
              create_project_row: bool = True,
              create_pipeline_job: bool = False, ws_client=None) -> dict:
    """Provision a use case from a blueprint. Returns a status dict.

    When ``create_pipeline_job`` is set and a ``ws_client`` (WorkspaceClient) is
    supplied, also stands up the ingestion pipeline job (the fold of the old
    scripts/create_domain_job.py) and registers its id in domain_configs."""
    bp = loader.load_blueprint(blueprint_id)
    if not bp:
        return {"ok": False, "error": f"unknown blueprint '{blueprint_id}'"}
    use_case_id = (use_case_id or bp["id"]).strip()
    cfg = derive_config(bp, use_case_id)
    if name:
        cfg["name"] = name

    steps: list[dict] = []

    def _step(label, fn):
        if dry_run:
            steps.append({"step": label, "status": "planned"})
            return
        try:
            fn()
            steps.append({"step": label, "status": "ok"})
        except Exception as e:
            steps.append({"step": label, "status": "error", "error": str(e)})

    _step("register_config", lambda: register_use_case(run_sql, cfg, catalog))
    _step("create_schema_volumes", lambda: create_schema_and_volumes(run_sql, cfg, catalog))
    job = {"id": None}
    if create_pipeline_job and ws_client is not None and not dry_run:
        def _job():
            from . import pipeline_job as pj
            job["id"] = pj.provision_pipeline_job(
                w=ws_client, run_sql=run_sql, domain_id=use_case_id,
                cfg=cfg, catalog=catalog)
        _step("create_pipeline_job", _job)
    if create_project_row and not dry_run:
        def _proj():
            from db import operational as opstore
            from db.lakebase import LakebaseUnavailable
            try:
                if not opstore.name_exists(use_case_id, cfg["name"]):
                    opstore.create_project(domain_id=use_case_id, project_id=use_case_id,
                                           name=cfg["name"], owner=owner)
            except LakebaseUnavailable:
                pass
        _step("create_project", _proj)
    _step("mark_active", lambda: mark_active(run_sql, use_case_id, catalog))

    return {
        "ok": all(s["status"] in ("ok", "planned") for s in steps),
        "use_case_id": use_case_id,
        "name": cfg["name"],
        "blueprint_id": blueprint_id,
        "pipeline_job_id": job["id"],
        "steps": steps,
    }
