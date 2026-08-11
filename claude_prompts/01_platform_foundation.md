# Component 1 — Core Document Intelligence Platform (reuse-aware)

## Goal
Formalize and document the **existing** reusable foundation. Do **not** create a parallel Bronze/Silver/Gold.

## What already exists — DO NOT rebuild
The full ingest → parse → classify → extract → chunk → embed → index → retrieve pipeline is live on catalog `jai_docintel`:
- **Bronze:** `{schema}.parsed_documents_raw` (`path`, `parsed` VARIANT, `parsed_at`) — `app/unstructured_workflow/src/transformations/01_parse_documents.py` (Auto Loader; `ai_parse_document` for PDF/image, whole-file text for `.txt`).
- **Silver:** `{schema}.parsed_documents_content` — `.../02_extract_document_content.py`.
- **Processed/Gold:** `{schema}.parsed_documents`, `{schema}.extracted_fields` (long format), `gold_{doc_type}`, `suggested_extractions` — `notebooks/03_idp_pipeline.py` (`ai_classify`, `ai_extract`, `ai_prep_search`, `schema_mode` = configured|hybrid|ai_infer).
- **Vector:** `{schema}.document_chunks` → Delta Sync index `{catalog}.{schema_vec}.{domain_id}_docs_index`; endpoint `docintel-vs-endpoint`; embed `databricks-gte-large-en` — `notebooks/05_vector_search.py`.
- **Retrieval:** `VectorSearchClient.similarity_search` in `app/backend/docintel_routes.py` (agent + copilot paths).
- **Registry:** `platform.domain_configs` — `notebooks/00_platform_setup.py`.

There is **NO** need for `documents_raw`, `documents_processed`, or `document_knowledge_objects` — the above are the equivalents.

## Gap to fill (small)
1. Author `platform/MANIFEST.md` if missing (name map — see repo; keep it current).
2. Confirm the pipeline is genuinely domain-agnostic: grep `notebooks/03_idp_pipeline.py`, `05_vector_search.py`, transformations `01`/`02` for hardcoded `supply_chain`/`compliance` and report any that break a new domain (expected: none in these files; the pockets are `00_setup.py`, `04_ontology_mapping.py`, `06_agent.py`).
3. Produce a short `platform/PIPELINE.md` documenting the task DAG, the job parameters each stage consumes (`domain_id`, `volume_path`, `mode`, `batch_size`, `doc_types`, `schema_mode`), and the tables each stage reads/writes.

## Deliverables
- `platform/MANIFEST.md` (exists — verify/update)
- `platform/PIPELINE.md` (new, documentation only)
- A grep report of any non-agnostic code in the core stages.

## Acceptance criteria
- No new Delta tables created.
- `docintel_process_docs` runs green for `domain_id=supply_chain` and `domain_id=compliance` with zero code changes.
- Docs accurately name real tables/params (cross-check against `MANIFEST.md`).

## Constraints
Documentation + verification only. Do not modify pipeline logic in this component.
