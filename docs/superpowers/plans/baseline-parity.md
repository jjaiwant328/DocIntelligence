# Baseline Parity Snapshot

Reference outputs of the **existing** DocIntelligence pipeline, captured before the thin-spine
refactor. Used as an **informational sanity check** for the new Lakeflow Declarative Pipeline
(owner direction: the old app "isn't very useful," so this does not hard-block schema deletion —
it confirms the new pipeline parses/extracts the synthetic corpus correctly).

- **Captured:** 2026-09-21
- **Catalog:** `jai_docintel`  ·  **Warehouse:** `85a4ed5bcff25c0d` (Serverless Starter)
- **Active domain (populated):** `supply_chain` → schema `raw`

## Reference numbers (supply_chain / `raw`)

| Metric | Value |
|---|---|
| `raw.parsed_documents_content` rows | **273** |
| `raw.parsed_documents` docs | **78** (13 doc_types × 6) |
| `raw.extracted_fields` rows | **52** |
| `raw.extracted_fields` distinct doc_type | **5** |

### doc_type distribution (`raw.parsed_documents`)
```
bill_of_lading 6, carrier_sla 6, certificate_of_analysis 6, delivery_exception 6,
email_chain 6, inspection_report 6, maintenance_report 6, quality_incident_report 6,
recall_notice 6, supplier_contract 6, supplier_scorecard 6, temperature_log 6,
weather_report 6
```

### `raw.extracted_fields` columns (current — NO evidence columns)
```
doc_id, doc_type, field_name, field_value
```
> The new silver `extracted_fields` MUST add `page_id`, `bbox`, `source_text` (spec §4.2).

### Registered domains (`platform.domain_configs`)
```
ap_three_way_match, compliance_due_diligence, supplier_performance, supply_chain
```

## Parity check (fill in after Task 3 builds the SDP)

| Metric | Baseline | New (`template_raw`) | Match? |
|---|---|---|---|
| parsed_documents_content rows | 273 | _TBD_ | _TBD_ |
| extracted_fields rows | 52 | _TBD_ | _TBD_ |
| doc_type distribution | see above | _TBD_ | _TBD_ |
| evidence columns present | no | _expect yes_ | _TBD_ |

## Task 3 progress — bronze verified (2026-09-21)

New pipeline `docintel_spine` (schema `jai_docintel.template`), reading `/Volumes/jai_docintel/raw/documents/` **in place (no copy)**:

| Table | Rows | Notes |
|---|---|---|
| `template.bronze_parsed_raw` | 61 | 23 jpg + 19 pdf + 19 txt |
| `template.bronze_parsed_content` | 61 | all content non-null, 0 parse errors |

Volume currently holds 61 files (baseline 273 accumulated across historical runs/domains). `ai_parse_document` + VARIANT + Auto Loader confirmed working in serverless SDP.

### Full pipeline verified (2026-09-21) — Tasks 2+3 complete

One SDP (`docintel_spine`) now consolidates old notebooks 01/02/03, config-driven from `domain_configs` (domain=`supply_chain`):

| Table | Rows | Notes |
|---|---|---|
| `template.silver_classified` | 61 | ai_classify → 13 doc_types |
| `template.silver_chunks` | 44 | ai_prep_search chunks (42 docs) for Vector Search |
| `template.gold_documents` | 61 | doc_id, doc_type, source_file |
| `template.gold_extracted_fields` | 99 | ai_extract long format, 26 docs / 5 types, nulls filtered, scalar values |

SDP runtime notes: read config inside MV function bodies (not module top-level); `variant_explode` unavailable → use `explode(try_cast(... AS ARRAY<VARIANT>))`; `ai_extract` nests each field under `.value`.

## Notes
- Existing demo full-run (job `docintel_process_docs`) NOT re-run for baseline — table snapshot
  above is the anchor; re-running the legacy job adds no signal given the revamp direction.
- Legacy branches preserved: `demoV1`, `remove-vector-search` (worktrees removed, branches intact).
- Salvaged references: `notebooks/05_vector_search.reference.py`, `notebooks/09_source_ingest.reference.py`.
