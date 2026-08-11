# Component 7 — Databricks Implementation Layer (reuse-aware)

## Goal
Provision the `compliance_due_diligence` domain on the **existing** Databricks assets. Do **not** rename live tables or restructure the catalog.

## What already exists — DO NOT rebuild
- Catalog `jai_docintel`; platform schema `jai_docintel.platform`; per-domain schemas.
- Jobs (root `databricks.yml`): `docintel_setup_domain` ("Setup New Domain"), `docintel_process_docs` (nightly, param `domain_id`), `docintel_full_pipeline`.
- `scripts/create_domain_job.py <domain_id>` builds the 7-task per-domain job (serverless) and writes its id into `domain_configs.analytics_config.pipeline_job_id`; grants app SP `00ec2ab7-2445-4bc8-b68d-25e463b5bbe3` `CAN_MANAGE_RUN`.
- VS endpoint `docintel-vs-endpoint`; embed `databricks-gte-large-en`.
- Job-id fallback dict `_KNOWN_JOB_IDS` in `docintel_routes.py` (~994).

The doc's proposed tables (`platform.documents_raw/processed/embeddings/entities/relationships/actions`, `compliance.projects/requests/requirements`) already have equivalents — **map, don't create** (see `platform/MANIFEST.md`). Reuse `extracted_fields` + `entities`/`relationships`; the "projects/requests/requirements" appear as ontology entities, not new tables.

## Gap to fill
1. Run `docintel_setup_domain` for `domain_id=compliance_due_diligence` (creates schema + `documents` volume).
2. Run `scripts/create_domain_job.py compliance_due_diligence`; confirm `analytics_config.pipeline_job_id` is written.
3. Add the new job id to `_KNOWN_JOB_IDS` as a fallback.
4. Confirm the VS index `jai_docintel.compliance_due_diligence.compliance_due_diligence_docs_index` is created/synced by nb 05.
5. (Optional) Add the domain as a first-class var/target in `databricks.yml` if you want it deployed via bundle rather than the imperative script.

## Deliverables
- Provisioned schema/volume/job for the new domain.
- `_KNOWN_JOB_IDS` updated.

## Acceptance criteria
- `GET /api/docintel/pipeline-status?domain_id=compliance_due_diligence` resolves the job and shows task progress.
- End-to-end run populates `parsed_documents`, `extracted_fields`, `entities`, `document_chunks`, and the VS index.

## Constraints
Reuse existing jobs/scripts. No catalog restructure, no live-table renames. Grants go to the existing app SP.
