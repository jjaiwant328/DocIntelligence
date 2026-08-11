# Platform Manifest — what exists and where

This document is the source of truth mapping the **conceptual platform** (from `component_and_claude_instructions.md`) to the **actual assets** already implemented on catalog `jai_docintel` (workspace `adb-4101016551133680.0.azuredatabricks.net`, CLI profile `jai-az-ws`).

> The platform layer is **built**. New work contributes *domain modules* (schemas, ontology overlays, prompts, agents, sample data) + two small platform gaps (config-driven ontology, escalation engine). Do not rebuild the layer.

## Layer → asset map

| Conceptual (the doc) | Actual asset(s) | Location |
|---|---|---|
| `documents_raw` (Bronze) | `{schema}.parsed_documents_raw` (`path`, `parsed` VARIANT, `parsed_at`) | `app/unstructured_workflow/src/transformations/01_parse_documents.py` |
| Silver processed text | `{schema}.parsed_documents_content` (`path`, `content`, `error_status`) | `.../transformations/02_extract_document_content.py` |
| `documents_processed` | `{schema}.parsed_documents` + `{schema}.extracted_fields` (long: `doc_id, doc_type, field_name, field_value`) + `gold_{doc_type}` + `suggested_extractions` | `notebooks/03_idp_pipeline.py` |
| `document_knowledge_objects` / entities & relationships | `{schema}.entities` (`entity_id, entity_type, canonical_id, attributes, source, display_name`), `{schema}.relationships` (`subject_id, predicate, object_id, reference_id, confidence, source_doc`), `{schema}.entity_aliases` | `notebooks/04_ontology_mapping.py` |
| `platform.embeddings` / vector index | `document_chunks` + Delta Sync index `{catalog}.{schema_vec}.{domain_id}_docs_index`; endpoint `docintel-vs-endpoint`; embed model `databricks-gte-large-en` | `notebooks/05_vector_search.py` |
| `platform.actions` + `action_history` | `platform.action_master` + `platform.action_history` (lifecycle `_ACTION_STATUS_FLOW`); review queue `platform.attorney_review_queue` | `app/backend/docintel_routes.py` (~4332) |
| Agent framework | single LangChain `create_tool_calling_agent`+`AgentExecutor` (`agent_query`, ~478) + Copilot (`copilot-query`, ~3529) + UC-function tools | `docintel_routes.py`, `notebooks/06_agent.py` |
| Domain registry / "domain modules" | `platform.domain_configs` (JSON: `classification_labels`, `extraction_schemas`, `entity_types`, `agent_system_prompt`, `analytics_config`, `suggested_questions`) | `notebooks/00_platform_setup.py` |
| Governance | Unity Catalog `jai_docintel`; per-domain schemas; app service principal `00ec2ab7-2445-4bc8-b68d-25e463b5bbe3` | `notebooks/00_setup.py` |
| Ingestion / pipelines (Lakeflow) | Auto Loader (`cloudFiles`, `availableNow`) + shared jobs `docintel_full_pipeline`, `docintel_process_docs` (nightly cron, param `domain_id`), `docintel_setup_domain` | root `databricks.yml` |
| Demo UI | Next.js app: Document Intelligence, Document Library, Control Tower (Overview / Knowledge Graph / Action Center / Compliance Map / Copilot Studio), AI Agent — all inherit any domain via `?domain_id=` | `app/frontend/src/app/*`, `context/DomainContext.tsx` |

## Supporting platform tables

`platform.domain_configs`, `platform.pipeline_runs`, `platform.processing_configs`, `platform.file_processing_log` (dedup), `platform.doc_type_schemas` (cross-domain reusable schema library), `platform.copilot_prompts`.

## Existing domains

| domain_id | Schemas | Pipeline job id | Notes |
|---|---|---|---|
| `supply_chain` | split: `raw`/`ontology`/`vectors`/`agents` | `1095463829768201` | Original; hardcoded ontology + 4 bespoke agent tools |
| `compliance` | single: `compliance` | `1096897875306787` | RaceTrac operational compliance, 48 docs; generic ontology path |

## How to add a domain (established recipe)

1. Register a row in `platform.domain_configs` (model on `scripts/setup_compliance.py`).
2. Provision schema + volume via job **"DocIntelligence — Setup New Domain"** (`docintel_setup_domain`).
3. Upload corpus to the domain volume; convert to PDF (`notebooks/00c_generate_pdfs.py`).
4. Create the per-domain pipeline job with `scripts/create_domain_job.py <domain_id>` (writes `job_id` into `analytics_config.pipeline_job_id`).
5. Activate (`status='active'`) → domain appears in the UI and inherits all tabs.

## Known extension points (where new domains need real code)

- `notebooks/04_ontology_mapping.py` — generic `FIELD_ENTITY_MAP` (~264) is **hardcoded**; new entity types must be added (Phase 1 makes it config-driven).
- `notebooks/06_agent.py` — bespoke tools live in a `supply_chain` branch; generic tools in the `else` branch.
- `app/backend/docintel_routes.py` — `_KNOWN_JOB_IDS` fallback (~994), escalation is LLM-string-driven (Phase 1 adds a rules engine).
