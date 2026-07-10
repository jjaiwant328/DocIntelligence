#!/usr/bin/env python3
"""
create_domain_job.py

Creates a Databricks pipeline job for a given domain (e.g. compliance) with
domain-specific schema and volume path parameters, then registers the job_id
in platform.domain_configs so the app can trigger it directly.

Usage:
    python3 scripts/create_domain_job.py compliance
    python3 scripts/create_domain_job.py compliance --force          # recreate if exists
    python3 scripts/create_domain_job.py compliance --update-compute # patch existing job's compute

Architecture note:
    - One shared job exists for supply_chain (hardcoded in _KNOWN_JOB_IDS).
    - Each additional subject area (compliance, procurement, …) gets its own job
      with the correct schema/volume parameters baked in.
    - Job IDs are stored in domain_configs.analytics_config.pipeline_job_id so
      the app never needs to search by name.
    - Catalog and schema creation happen OUTSIDE the app (via setup scripts and
      Databricks Asset Bundles). The app only reads domain_configs.
"""

import sys
import json
import time
import argparse
from datetime import datetime, timezone
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import (
    Task, NotebookTask, JobParameterDefinition, Source, TaskDependency,
    JobAccessControlRequest, PerformanceTarget,
)
from databricks.sdk.service.iam import PermissionLevel

# ── Serverless standard compute ───────────────────────────────────────────────
# Tasks run on serverless compute (no classic cluster to manage).
# STANDARD = standard serverless tier; PERFORMANCE_OPTIMIZED = premium tier.
PERF_TARGET = PerformanceTarget.STANDARD

# Service principal that runs the Databricks App — must have CAN_MANAGE_RUN on every job
APP_SERVICE_PRINCIPAL = "00ec2ab7-2445-4bc8-b68d-25e463b5bbe3"

PROFILE = "jai-az-ws"
CATALOG = "jai_docintel"
PLATFORM_SCHEMA = "platform"

# Notebook paths (from the bundle deployment)
NB_BASE = "/Workspace/Users/jaiwant.jonathan@databricks.com/.bundle/docintel/dev/files"
WF_BASE = f"{NB_BASE}/app/unstructured_workflow/src/transformations"


def run_sql(w: WorkspaceClient, stmt: str, wh_id: str):
    r = w.statement_execution.execute_statement(
        statement=stmt, warehouse_id=wh_id,
        wait_timeout="50s", catalog=CATALOG, schema=PLATFORM_SCHEMA,
    )
    if r.status.state.value != "SUCCEEDED":
        raise RuntimeError(f"SQL failed: {r.status.error}")
    if not r.result or not r.result.data_array:
        return []
    cols = [c.name for c in r.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in r.result.data_array]


def get_domain_config(w: WorkspaceClient, wh_id: str, domain_id: str) -> dict:
    rows = run_sql(w, f"""
        SELECT schema_raw, schema_ont, schema_vec, schema_agt,
               volume_docs, analytics_config
        FROM {CATALOG}.{PLATFORM_SCHEMA}.domain_configs
        WHERE domain_id = '{domain_id}'
        LIMIT 1
    """, wh_id)
    if not rows:
        raise ValueError(f"Domain '{domain_id}' not found in platform.domain_configs")
    return rows[0]


def job_exists_for_domain(w: WorkspaceClient, domain_id: str):
    """Return existing job_id if already registered in analytics_config."""
    try:
        wh_id = next(iter(w.warehouses.list())).id
        cfg = get_domain_config(w, wh_id, domain_id)
        ac = cfg.get("analytics_config") or {}
        if isinstance(ac, str):
            ac = json.loads(ac)
        return int(ac["pipeline_job_id"]) if ac.get("pipeline_job_id") else None
    except Exception:
        return None


def create_domain_pipeline_job(w: WorkspaceClient, domain_id: str, cfg: dict) -> int:
    """Create the full pipeline job for a domain. Returns the new job_id."""
    schema_raw  = cfg["schema_raw"]
    volume_docs = cfg.get("volume_docs") or "documents"

    src_vol  = f"/Volumes/{CATALOG}/{schema_raw}/{volume_docs}/"
    out_vol  = f"/Volumes/{CATALOG}/{schema_raw}/{volume_docs}/outputs/"
    chk_base = f"docintel_{domain_id}_workflow"

    job = w.jobs.create(
        name=f"DocIntelligence — {domain_id.replace('_', ' ').title()} Pipeline",
        parameters=[
            JobParameterDefinition(name="domain_id", default=domain_id),
        ],
        # STANDARD serverless — no classic cluster, not performance-optimized tier
        performance_target=PERF_TARGET,
        tasks=[
            # ── Step 0: Prepare workflow tables ───────────────────────────────
            Task(
                task_key="workflow_prepare",
                notebook_task=NotebookTask(
                    notebook_path=f"{WF_BASE}/00-clean-pipeline-tables",
                    base_parameters={
                        "catalog":               CATALOG,
                        "schema":                schema_raw,
                        "source_volume_path":    src_vol,
                        "output_volume_path":    out_vol,
                        "raw_table_name":        "parsed_documents_raw",
                        "content_table_name":    "parsed_documents_content",
                        "structured_table_name": "parsed_documents_structured",
                        "checkpoint_base_path":  chk_base,
                        "clean_pipeline_tables": "No",
                    },
                    source=Source.WORKSPACE,
                ),
            ),
            # ── Step 1: Parse PDFs via ai_parse_document ──────────────────────
            Task(
                task_key="workflow_parse",
                depends_on=[TaskDependency(task_key="workflow_prepare")],
                notebook_task=NotebookTask(
                    notebook_path=f"{WF_BASE}/01_parse_documents",
                    base_parameters={
                        "catalog":             CATALOG,
                        "schema":              schema_raw,
                        "source_volume_path":  src_vol,
                        "output_volume_path":  out_vol,
                        "table_name":          "parsed_documents_raw",
                        "checkpoint_location": f"/Volumes/{CATALOG}/{schema_raw}/checkpoints/{chk_base}/01_parse_documents",
                    },
                    source=Source.WORKSPACE,
                ),
            ),
            # ── Step 2: Extract document content ─────────────────────────────
            Task(
                task_key="workflow_extract",
                depends_on=[TaskDependency(task_key="workflow_parse")],
                notebook_task=NotebookTask(
                    notebook_path=f"{WF_BASE}/02_extract_document_content",
                    base_parameters={
                        "catalog":             CATALOG,
                        "schema":              schema_raw,
                        "source_table_name":   "parsed_documents_raw",
                        "table_name":          "parsed_documents_content",
                        "checkpoint_location": f"/Volumes/{CATALOG}/{schema_raw}/checkpoints/{chk_base}/02_extract_document_content",
                    },
                    source=Source.WORKSPACE,
                ),
            ),
            # ── Step 3: Classify & Extract (IDP) ─────────────────────────────
            Task(
                task_key="idp_pipeline",
                depends_on=[TaskDependency(task_key="workflow_extract")],
                notebook_task=NotebookTask(
                    notebook_path=f"{NB_BASE}/notebooks/03_idp_pipeline",
                    base_parameters={"domain_id": "{{job.parameters.domain_id}}"},
                    source=Source.WORKSPACE,
                ),
            ),
            # ── Step 4: Ontology / Knowledge Graph ───────────────────────────
            Task(
                task_key="ontology_mapping",
                depends_on=[TaskDependency(task_key="idp_pipeline")],
                notebook_task=NotebookTask(
                    notebook_path=f"{NB_BASE}/notebooks/04_ontology_mapping",
                    base_parameters={"domain_id": "{{job.parameters.domain_id}}"},
                    source=Source.WORKSPACE,
                ),
            ),
            # ── Step 5: Vector Search ─────────────────────────────────────────
            Task(
                task_key="vector_search",
                depends_on=[TaskDependency(task_key="idp_pipeline")],
                notebook_task=NotebookTask(
                    notebook_path=f"{NB_BASE}/notebooks/05_vector_search",
                    base_parameters={"domain_id": "{{job.parameters.domain_id}}"},
                    source=Source.WORKSPACE,
                ),
            ),
            # ── Step 6: AI Agent ──────────────────────────────────────────────
            Task(
                task_key="agent",
                depends_on=[
                    TaskDependency(task_key="ontology_mapping"),
                    TaskDependency(task_key="vector_search"),
                ],
                notebook_task=NotebookTask(
                    notebook_path=f"{NB_BASE}/notebooks/06_agent",
                    base_parameters={"domain_id": "{{job.parameters.domain_id}}"},
                    source=Source.WORKSPACE,
                ),
            ),
        ],
    )
    return job.job_id


def register_job_in_domain_configs(w: WorkspaceClient, wh_id: str, domain_id: str,
                                    job_id: int, cfg: dict):
    """Store pipeline_job_id inside analytics_config JSON column."""
    ac = {}
    try:
        raw = cfg.get("analytics_config") or "{}"
        if isinstance(raw, str):
            ac = json.loads(raw)
        else:
            ac = raw
    except Exception:
        pass

    ac["pipeline_job_id"] = job_id

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    ac_escaped = json.dumps(ac).replace("'", "''")

    run_sql(w, f"""
        UPDATE {CATALOG}.{PLATFORM_SCHEMA}.domain_configs
        SET analytics_config = '{ac_escaped}',
            updated_at = TIMESTAMP '{now}'
        WHERE domain_id = '{domain_id}'
    """, wh_id)
    print(f"  Registered pipeline_job_id={job_id} in domain_configs for '{domain_id}'")


def update_job_to_standard_compute(w: WorkspaceClient, job_id: int):
    """
    Patches an existing job to use serverless compute with STANDARD performance
    target (not PERFORMANCE_OPTIMIZED). Clears any classic cluster references.
    """
    from databricks.sdk.service.jobs import JobSettings

    job = w.jobs.get(job_id=job_id)
    tasks = job.settings.tasks or []

    updated_tasks = []
    for t in tasks:
        updated_tasks.append(Task(
            task_key=t.task_key,
            depends_on=t.depends_on,
            notebook_task=t.notebook_task,
            libraries=t.libraries,
            # Clear classic-cluster fields so the task uses serverless
            job_cluster_key=None,
            existing_cluster_id=None,
        ))

    w.jobs.reset(
        job_id=job_id,
        new_settings=JobSettings(
            name=job.settings.name,
            parameters=job.settings.parameters,
            schedule=job.settings.schedule,
            performance_target=PERF_TARGET,   # serverless STANDARD tier
            job_clusters=[],                  # remove any classic clusters
            tasks=updated_tasks,
        ),
    )
    print(f"  Updated job {job_id} → serverless / STANDARD performance target")


def grant_app_permissions(w: WorkspaceClient, job_id: int):
    """Grant the Databricks App service principal CAN_MANAGE_RUN on the job."""
    try:
        acl = [JobAccessControlRequest(
            service_principal_name=APP_SERVICE_PRINCIPAL,
            permission_level=PermissionLevel.CAN_MANAGE_RUN,
        )]
        w.jobs.update_permissions(job_id=job_id, access_control_list=acl)
        print(f"  Granted CAN_MANAGE_RUN to app SP ({APP_SERVICE_PRINCIPAL})")
    except Exception as e:
        print(f"  Warning: could not grant app permissions — grant manually: {e}")


def main():
    parser = argparse.ArgumentParser(description="Create a domain pipeline job")
    parser.add_argument("domain_id", help="Domain ID (e.g. compliance, procurement)")
    parser.add_argument("--force", action="store_true",
                        help="Recreate even if job_id already registered")
    parser.add_argument("--update-compute", action="store_true",
                        help="Patch an existing job to serverless STANDARD compute without recreating it")
    args = parser.parse_args()
    domain_id = args.domain_id

    w = WorkspaceClient(profile=PROFILE)
    wh_id = next(iter(w.warehouses.list())).id

    print(f"=== Pipeline job for domain: {domain_id} ===")

    # --update-compute: patch existing job, no recreation
    if args.update_compute:
        existing = job_exists_for_domain(w, domain_id)
        if not existing:
            print(f"No registered job found for domain '{domain_id}'. "
                  f"Run without --update-compute to create one first.")
            sys.exit(1)
        print(f"  Patching job_id={existing} to serverless STANDARD compute…")
        update_job_to_standard_compute(w, existing)
        print(f"\nDone. Job {existing} now uses serverless / STANDARD performance target.")
        return

    # Check if already exists
    if not args.force:
        existing = job_exists_for_domain(w, domain_id)
        if existing:
            print(f"Job already registered: job_id={existing}. Use --force to recreate.")
            try:
                j = w.jobs.get(job_id=existing)
                print(f"  Job name: {j.settings.name}")
                print("  No action needed.")
                return
            except Exception:
                print("  Registered job_id no longer exists in workspace — will recreate.")

    # Load domain config
    cfg = get_domain_config(w, wh_id, domain_id)
    schema_raw  = cfg["schema_raw"]
    volume_docs = cfg.get("volume_docs") or "documents"
    src_vol     = f"/Volumes/{CATALOG}/{schema_raw}/{volume_docs}/"

    print(f"  schema_raw  : {schema_raw}")
    print(f"  volume_docs : {volume_docs}")
    print(f"  source_vol  : {src_vol}")

    # Ensure outputs sub-directory exists
    out_vol = f"/Volumes/{CATALOG}/{schema_raw}/{volume_docs}/outputs/"
    try:
        import io
        w.files.upload(f"{out_vol}.keep", io.BytesIO(b"# outputs directory placeholder\n"), overwrite=True)
        print(f"  Ensured outputs directory: {out_vol}")
    except Exception as e:
        print(f"  Warning: could not create outputs dir: {e}")

    # Create the job
    print("  Creating Databricks job…")
    job_id = create_domain_pipeline_job(w, domain_id, cfg)
    print(f"  Created job_id={job_id}")

    # Register in domain_configs
    register_job_in_domain_configs(w, wh_id, domain_id, job_id, cfg)

    # Grant the app service principal permission to trigger and monitor runs
    print("  Granting app permissions…")
    grant_app_permissions(w, job_id)

    print(f"\nDone. Pipeline job for '{domain_id}' is ready.")
    print(f"  job_id={job_id}")
    print(f"  Compute: serverless / STANDARD performance target")
    print(f"  The app will now use this job when 'Run Pipeline Now' is clicked.")
    print(f"\nTo run the job manually:")
    print(f"  databricks jobs run-now {job_id} --job-parameters '{{\"domain_id\":\"{domain_id}\"}}' --profile {PROFILE}")


if __name__ == "__main__":
    main()
