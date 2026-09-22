# DocIntelligence Thin-Spine Refactor — Design

**Date:** 2026-09-21
**Status:** Draft (awaiting review)
**Scope:** Refactor the existing DocIntelligence repo in place into a thin, config-driven
Document Intelligence template, and replace the bespoke source-copy machinery with a single
Lakeflow Connect + Declarative Pipeline ingestion path.

---

## 1. Problem & Motivation

DocIntelligence grew across several iterations organized by subject area. The result is a
capable but over-built platform: reusable primitives are entangled with domain-specific copies,
dead experiments, and product-grade layers (skills registry, workflow engine, action management,
multi-tab UI) that exceed what a reusable *template* demo needs.

Two goals drive this refactor:

1. **Optimize unstructured-document ingestion**, ideally consuming sources without copying data.
2. **Scale the platform down to a thin, reusable template** that a new domain can be built on
   without touching platform code.

### Key decisions (confirmed with owner)

- **Data sources are SaaS** (Google Drive, SharePoint, Outlook) — not object storage.
- **Refactor in place** (not a new bundle, not a full rebuild).
- **Thin spine only**: `ingest → parse → extract → search → evidence`. Cut skills registry,
  workflow engine, action management, and the multi-tab UI.

### Assumption (owner did not override)

- A **thin, optional conversational agent** over the same search index is retained because it
  provides the "ask a question → get an evidenced answer" demo moment cheaply. It is clearly
  isolated and **droppable** without affecting the spine. If the owner wants it gone, remove the
  single agent route + one UI panel; nothing else depends on it.

---

## 2. Reality Check: "At Source Without Copying"

For **SaaS sources**, true zero-copy is physically impossible — the bytes live behind an API and
must be pulled before Databricks can parse them. The realistic optimization is to go from the
current **two copies + full re-upload each run** to a **single, incremental, permission-aware hop**.

| Source type | Zero-copy possible? | Approach |
|---|---|---|
| SaaS (Drive/SharePoint/Outlook) | No | Lakeflow Connect managed connector: one incremental, permission-aware landing into UC |
| Object storage (S3/ADLS/GCS) | Yes | UC External Location / external Volume; Auto Loader + `ai_parse_document` read in place |

The template supports **both** via a source-type abstraction, but the demo path is SaaS.

> Managed Lakeflow Connect connector availability (GA vs Preview) varies by cloud. **Confirm the
> Google Drive / SharePoint managed connector is enabled in the target Azure workspace** before
> wiring it; retain the existing synthetic connector as an offline-demo fallback.

---

## 3. Current State (what we keep vs. cut)

### Keep (proven spine)
- `ai_parse_document` v2.0 parsing (`app/unstructured_workflow/src/transformations/01_parse_documents.py`)
- Auto Loader + Structured Streaming incremental pattern (checkpointed)
- Config-driven IDP: `ai_classify` / `ai_extract` / `ai_prep_search` (`notebooks/03_idp_pipeline.py`)
- Multi-domain registry: `platform.domain_configs` and `app/backend/platform_routes.py`
- Pluggable source-connector abstraction (`app/mcp-server/connectors/base.py`, `synthetic.py`)

### Cut (platform overhead beyond a template)
- Skills registry + workflow engine (`app/backend/skill_routes.py`, `workflow_engine/`, `skill_runtime/`)
- Action management + escalation + attorney-review queue (`platform.action_master`,
  `action_history`, `attorney_review_queue`, escalation parsing in `docintel_routes.py`)
- Multi-tab frontend: `agent` (unless thin agent kept), `copilot`, `skills`, `workflows`,
  `executions`, `supply-chain` pages → collapse to: **Sources**, **Corpus/Search**, **Evidence**.

### Consolidate / delete (mess)
- 3 synthetic-corpus notebooks (`01_synthetic_corpus*.py`) → **1 parameterized generator**.
- `supply_chain` hardcoding in `04_ontology_mapping.py`, `06_agent.py`, `docintel_routes.py`
  → move into `domain_configs`.
- `.worktrees/remove-vs/` and `.worktrees/b1-provision-cdd/` → **delete** (after lifting the
  missing `05_vector_search` logic into the pipeline).
- Diverging interactive-vs-batch ingestion paths → unify on one pipeline.

---

## 4. Target Architecture

```
SaaS (Drive / SharePoint / Outlook)
   └─ Lakeflow Connect managed connector (incremental, permission-aware)
Object storage (optional)                                   ▼
   └─ UC External Location (zero-copy) ───────────►  UC landing (managed table / Volume)
                                                            ▼
        ONE Lakeflow Declarative Pipeline (serverless, streaming, medallion):
           bronze:  Auto Loader ▶ ai_parse_document            → parsed (variant + bbox/page)
           silver:  ai_classify / ai_extract / ai_prep_search  → extracted fields + evidence
           gold:    per-doc-type wide tables + entities/relationships (config-driven)
                                                            ▼
        Vector Search Delta Sync index  ◄── silver chunks (self-updating)
                                                            ▼
        FastAPI (thin): /sources, /search, /evidence [, /agent (optional)]
                                                            ▼
        Frontend (thin): Sources · Corpus/Search · Evidence drill-down
```

### 4.1 Ingestion (headline change)
- Replace bespoke OAuth/fetch/upload/clean (`mcp-server/connectors/gdrive.py`, `oauth.py`,
  clean-batch logic) with a **Lakeflow Connect managed connector** landing into UC.
- Collapse `01_parse` + `02_extract` + `03_idp` + (missing) `05_vector_search` into **one
  Lakeflow Declarative Pipeline** using streaming tables + materialized views. Interactive
  single-file mode triggers the *same* pipeline (no divergent code path).
- Object-storage sources (if ever present) mount as a **UC External Location** and are read in
  place — genuinely no copy.

### 4.2 Evidence / provenance (first-class)
`ai_parse_document` already emits `bbox`, `page_id`, `confidence` in the variant. Promote these
to typed columns and carry them: parsed element → extracted field → search chunk. Every
extracted value and every search hit resolves to `document_id + page + bbox + source_text`.
One `evidence` view backs the Evidence UI drill-down.

### 4.3 Config model (domain = configuration, not code)
All domain semantics live in `platform.domain_configs` (already the registry):
- `classification_labels`, `extraction_schemas` (already config)
- `entity_types` + `field_entity_map` (currently hardcoded in `04_ontology_mapping.py` → move here)
- `agent_system_prompt`, `suggested_questions` (already config)
- `source_connectors` (which Lakeflow Connect connector + landing location)

**Success test:** Compliance and Supply Chain run the *same* pipeline and backend code; only
their `domain_configs` rows differ.

---

## 5. Components & Boundaries

| Unit | Responsibility | Depends on |
|---|---|---|
| **Ingestion pipeline** (Lakeflow Declarative) | Land → parse → extract → chunk → evidence, incrementally | Lakeflow Connect / External Location, `domain_configs`, `ai_*` functions |
| **Source connector config** | Register a domain's SaaS/object source + landing target | Lakeflow Connect, `domain_configs` |
| **Vector index** | Self-syncing search index over silver chunks | Delta Sync, silver table |
| **Search API** | Query index, return hits + evidence refs | Vector Search endpoint |
| **Evidence API/view** | Resolve any field/hit → page + bbox + source text | silver + parsed tables |
| **Thin agent (optional)** | NL question → search → evidenced answer | Search API only |
| **Thin UI** | Sources config · Corpus/Search · Evidence drill-down | the APIs above |

Each unit is independently testable and communicates through Delta tables or a typed HTTP contract.

---

## 6. Refactor Sequencing (each step keeps the demo runnable)

1. **Branch + clean.** New branch; delete `.worktrees/*`; snapshot that the current demo runs
   (baseline tables + a known query).
2. **One pipeline.** Build the Lakeflow Declarative Pipeline replacing notebooks 01/02/03/(05).
   Verify parity on the existing synthetic corpus: same output tables **+** evidence columns.
3. **De-hardcode.** Move `supply_chain` maps/tools/fallbacks into `domain_configs`. Prove
   Compliance + Supply Chain run identical code.
4. **Swap ingestion.** Wire Lakeflow Connect (Drive/SharePoint), keep synthetic connector as
   offline fallback. Retire bespoke OAuth/fetch/clean code.
5. **Strip UI + backend.** Remove skills/workflow/action routes and extra tabs; reduce to the
   thin spine (+ optional agent).
6. **Consolidate + test.** 3 corpus notebooks → 1 parameterized; add the missing end-to-end
   ingestion test (land → parse → extract → search → evidence).

---

## 7. Testing / Verification

- **Parity gate (step 2):** new pipeline reproduces current `parsed_documents_content`,
  `extracted_fields`, and gold tables on the synthetic corpus (plus evidence columns).
- **Domain-reuse gate (step 3):** a single automated run configures Compliance and Supply Chain
  from `domain_configs` only and both complete with no code branch.
- **E2E ingestion test (step 6):** synthetic source → pipeline → a known query returns the
  expected hit with resolvable page+bbox evidence.
- Preserve the existing 40+ backend route tests for the surfaces that remain; delete tests for
  removed routes.

---

## 8. Risks & Assumptions

- **Managed-connector availability.** Google Drive / SharePoint managed connectors may be
  Preview or unavailable in the target Azure workspace. Mitigation: confirm enablement first;
  synthetic connector remains the offline fallback; object-storage/External-Location path is
  the no-copy alternative if a connector is blocked.
- **Lakeflow Declarative Pipeline vs. notebooks.** Consolidating four notebooks into one pipeline
  is the largest change. Mitigation: strict parity gate before deleting the old notebooks.
- **Dropping layers may remove demo value.** Cutting skills/workflow/action reduces the "closed
  loop" story from `docIntel-framework.md`. Owner accepted thin-spine scope; these can be
  reintroduced later as optional add-ons on top of the template.
- **Agent scope ambiguity.** Retained as optional per stated assumption; trivially removable.

---

## 9. Non-Goals

- No new competing framework; no rebuild from scratch.
- No action-management / escalation / approval workflow in the template.
- No visual drag-and-drop workflow editor.
- No production credentials or customer data; synthetic corpus only.

---

## 10. Open Questions

1. Confirm Google Drive **and** SharePoint are both in scope for the demo, or just one.
2. Keep the thin agent, or truly spine-only (no chat)?
3. Target catalog/schema for the refactored template — reuse `jai_docintel` or a fresh
   `jai_docintel_template` to keep the old platform intact alongside?
