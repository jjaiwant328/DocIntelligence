"""Create a use case's ingestion pipeline job — the callable fold of the old
`scripts/create_domain_job.py`.

The provisioner calls this to give a blueprint-provisioned use case its own
serverless pipeline job (parse → extract → IDP → ontology → agent), register the
job id in `domain_configs.analytics_config`, and grant the app service principal
CAN_MANAGE so the app can trigger + monitor runs. Job name, notebook base path,
and the app SP all come from config (env / params) — nothing hardcoded — so any
new use case gets a correctly-parameterised job with no redeploy and no script.
"""
from __future__ import annotations

import io
import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional

# Notebook base path from the bundle deployment. Overridable via env so the
# provisioner is not tied to one workspace/user (folds out create_domain_job.py's
# hardcoded NB_BASE).
DEFAULT_NB_BASE = "/Workspace/Users/jaiwant.jonathan@databricks.com/.bundle/docintel/dev/files"


def _nb_base() -> str:
    return os.getenv("DOCINTEL_NB_BASE", DEFAULT_NB_BASE)


def _app_sp() -> str:
    # The app's service principal — same id used for the Lakebase login.
    return os.getenv("DOCINTEL_APP_SP") or os.getenv("LAKEBASE_USER", "")


def build_tasks(domain_id: str, schema_raw: str, volume_docs: str,
                catalog: str, nb_base: Optional[str] = None) -> list:
    """The 6-task pipeline spec (parse → extract → IDP → ontology → agent),
    parameterised by the use case's schema/volume. Returns SDK Task objects."""
    from databricks.sdk.service.jobs import (
        NotebookTask, Source, Task, TaskDependency,
    )
    nb_base = nb_base or _nb_base()
    wf_base = f"{nb_base}/app/unstructured_workflow/src/transformations"
    src_vol = f"/Volumes/{catalog}/{schema_raw}/{volume_docs}/"
    out_vol = f"/Volumes/{catalog}/{schema_raw}/{volume_docs}/outputs/"
    chk_base = f"docintel_{domain_id}_workflow"
    chk_root = f"/Volumes/{catalog}/{schema_raw}/checkpoints/{chk_base}"
    dom_param = "{{job.parameters.domain_id}}"

    def _nb(path, params):
        return NotebookTask(notebook_path=path, base_parameters=params,
                            source=Source.WORKSPACE)

    return [
        Task(task_key="workflow_prepare", notebook_task=_nb(
            f"{wf_base}/00-clean-pipeline-tables", {
                "catalog": catalog, "schema": schema_raw,
                "source_volume_path": src_vol, "output_volume_path": out_vol,
                "raw_table_name": "parsed_documents_raw",
                "content_table_name": "parsed_documents_content",
                "structured_table_name": "parsed_documents_structured",
                "checkpoint_base_path": chk_base, "clean_pipeline_tables": "No",
            })),
        Task(task_key="workflow_parse",
             depends_on=[TaskDependency(task_key="workflow_prepare")],
             notebook_task=_nb(f"{wf_base}/01_parse_documents", {
                 "catalog": catalog, "schema": schema_raw,
                 "source_volume_path": src_vol, "output_volume_path": out_vol,
                 "table_name": "parsed_documents_raw",
                 "checkpoint_location": f"{chk_root}/01_parse_documents",
             })),
        Task(task_key="workflow_extract",
             depends_on=[TaskDependency(task_key="workflow_parse")],
             notebook_task=_nb(f"{wf_base}/02_extract_document_content", {
                 "catalog": catalog, "schema": schema_raw,
                 "source_table_name": "parsed_documents_raw",
                 "table_name": "parsed_documents_content",
                 "checkpoint_location": f"{chk_root}/02_extract_document_content",
             })),
        Task(task_key="idp_pipeline",
             depends_on=[TaskDependency(task_key="workflow_extract")],
             notebook_task=_nb(f"{nb_base}/notebooks/03_idp_pipeline",
                               {"domain_id": dom_param})),
        Task(task_key="ontology_mapping",
             depends_on=[TaskDependency(task_key="idp_pipeline")],
             notebook_task=_nb(f"{nb_base}/notebooks/04_ontology_mapping",
                               {"domain_id": dom_param})),
        Task(task_key="agent",
             depends_on=[TaskDependency(task_key="ontology_mapping")],
             notebook_task=_nb(f"{nb_base}/notebooks/06_agent",
                               {"domain_id": dom_param})),
    ]


def create_pipeline_job(w, domain_id: str, cfg: dict, *, catalog: str,
                        nb_base: Optional[str] = None) -> int:
    """Create the serverless STANDARD pipeline job. Returns the new job_id."""
    from databricks.sdk.service.jobs import JobParameterDefinition, PerformanceTarget
    schema_raw = cfg["schema_raw"]
    volume_docs = cfg.get("volume_docs") or "documents"
    # Best-effort: ensure the outputs sub-dir exists (parse step writes there).
    try:
        out_vol = f"/Volumes/{catalog}/{schema_raw}/{volume_docs}/outputs/"
        w.files.upload(f"{out_vol}.keep",
                       io.BytesIO(b"# outputs directory placeholder\n"), overwrite=True)
    except Exception as e:
        print(f"[provision] outputs dir not created (best-effort): {e}")
    job = w.jobs.create(
        name=f"DocIntelligence — {domain_id.replace('_', ' ').title()} Pipeline",
        parameters=[JobParameterDefinition(name="domain_id", default=domain_id)],
        performance_target=PerformanceTarget.STANDARD,
        tasks=build_tasks(domain_id, schema_raw, volume_docs, catalog, nb_base),
    )
    return int(job.job_id)


def register_job_id(run_sql: Callable[..., Any], domain_id: str, job_id: int,
                    cfg: dict, catalog: str) -> None:
    """Merge pipeline_job_id into the use case's analytics_config JSON."""
    ac: dict = {}
    raw = cfg.get("analytics_config") or "{}"
    try:
        ac = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception:
        ac = {}
    ac["pipeline_job_id"] = job_id
    esc = json.dumps(ac).replace("'", "''")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    run_sql(
        f"UPDATE {catalog}.platform.domain_configs "
        f"SET analytics_config = '{esc}', updated_at = TIMESTAMP '{now}' "
        f"WHERE domain_id = '{domain_id}'"
    )


def grant_app_sp(w, job_id: int, app_sp: Optional[str] = None) -> None:
    """Grant the app SP CAN_MANAGE on the job (best-effort — a grant hiccup must
    not fail provisioning; it can be granted manually)."""
    app_sp = app_sp or _app_sp()
    if not app_sp:
        print("[provision] no app SP configured (DOCINTEL_APP_SP/LAKEBASE_USER); skip grant")
        return
    try:
        from databricks.sdk.service.iam import PermissionLevel
        from databricks.sdk.service.jobs import JobAccessControlRequest
        w.jobs.update_permissions(job_id=job_id, access_control_list=[
            JobAccessControlRequest(service_principal_name=app_sp,
                                    permission_level=PermissionLevel.CAN_MANAGE)])
    except Exception as e:
        print(f"[provision] could not grant app SP on job {job_id}: {e}")


def provision_pipeline_job(*, w, run_sql: Callable[..., Any], domain_id: str,
                           cfg: dict, catalog: str,
                           nb_base: Optional[str] = None) -> int:
    """Full fold of create_domain_job.py: create the job, register its id in
    domain_configs, grant the app SP. Returns the job_id."""
    job_id = create_pipeline_job(w, domain_id, cfg, catalog=catalog, nb_base=nb_base)
    register_job_id(run_sql, domain_id, job_id, cfg, catalog)
    grant_app_sp(w, job_id)
    return job_id
