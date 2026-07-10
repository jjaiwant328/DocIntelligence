# Component 4 — Compliance Due Diligence Domain Module (reuse-aware) — THE FLAGSHIP BUILD

## Goal
Add a new domain `compliance_due_diligence` (AI-powered **Store Development / feasibility due diligence** — see `store_development.md`) that runs entirely on the existing platform. This is content + a thin ontology overlay + agent tools — **not** new pipeline infrastructure.

> Note: `domain_id = compliance_due_diligence` is DISTINCT from the existing operational `compliance` (RaceTrac) domain. Do not modify `compliance`.

## What already exists — DO NOT rebuild
- The whole pipeline (parse/classify/extract/chunk/vector) is domain-driven off `platform.domain_configs` — see `platform/MANIFEST.md`.
- `scripts/setup_compliance.py` is the end-to-end domain bootstrap template.
- `scripts/create_domain_job.py <domain_id>` mints the per-domain pipeline job.
- Ontology generic builder + (after Prompt 02) config-driven `FIELD_ENTITY_MAP`.
- Agent + Copilot wiring (`docintel_routes.py`), UC-function tools (`notebooks/06_agent.py`).
- Escalation engine (after Prompt 03).
- The Next.js UI auto-inherits any active domain via `?domain_id=`.

## Build

### 1. Domain config (`scripts/setup_compliance_due_diligence.py`, modeled on `setup_compliance.py`)
Insert one `platform.domain_configs` row (single schema `compliance_due_diligence`):
- **classification_labels:** `feasibility_request`, `municipal_requirement`, `alcohol_license`, `tobacco_license`, `business_license`, `zoning_document`, `permit`, `historical_response`, `regulatory_change`, `consultant_correspondence`.
- **extraction_schemas** (per label; shape `{doc_type:{schema:{field:{type,description}},instructions}}`). Key fields to extract across types: `project_id`, `store_number`, `address`, `market`, `state`, `municipality`, `county`, `request_type`, `requester`, `priority`, `requirement_type`, `authority`, `license_type`, `issuing_authority`, `lead_time`, `renewal_period`, `effective_date`, `expiration_date`, `responder`, `response_date`, `source_document`.
- **entity_types:** `Project`, `FeasibilityRequest`, `Municipality`, `RegulatoryRequirement`, `License`, `Response`, `Action`, `Document`.
- **ontology_config** (feeds Prompt 02; stored **nested under `analytics_config`** — see `platform/ontology/CORE_ENTITIES.md`): `field_entity_map`, e.g. `store_number→["Project","PROJ"]`, `municipality→["Municipality","MUNI"]`, `requirement_type→["RegulatoryRequirement","REQ"]`, `license_type→["License","LIC"]`, `responder→["Response","RESP"]`; `relationship_rules` (field-based) e.g. `{store_number LOCATED_IN municipality}`, `{municipality DEFINES requirement_type}`, `{requirement_type REQUIRES license_type}`. (Express the `Response ANSWERS FeasibilityRequest` / `HAS_HISTORY_OF` edges as field-based rules where the fields co-occur on a document.)
- **agent_system_prompt:** compliance-teammate persona (classify → research → recall prior → detect change → create/track actions; cite sources; flag low confidence).
- **suggested_questions:** "What are the requirements to open this store?", "Have we answered this municipality before?", "What changed since the last feasibility request for <municipality>?", "What actions remain open for <project>?".

### 2. Synthetic corpus (`notebooks/01_synthetic_corpus_store_dev.py`, `write_doc(...)` pattern)
Generate a coherent RaceTrac store-development set across 2–3 markets (e.g. Tampa FL, Dallas TX, Atlanta GA), including:
- feasibility request **emails** (as `.txt`/`.eml`), municipal requirement docs, alcohol/zoning/business-license docs, consultant correspondence, and **historical responses** with dates.
- **Before/after regulatory pairs** for ≥1 municipality (e.g. Dallas alcohol: v2024 "standard permit" → v2025 "distance waiver required") to drive change detection.
Bootstrap uploads corpus → volume → `00c_generate_pdfs.py` → activate.

### 3. Ontology overlay
Rely on Prompt 02's config-driven map (from `ontology_config`). Verify Project/Municipality/RegulatoryRequirement/License/Response entities + the relationships above materialize in `{compliance_due_diligence}.entities`/`.relationships`.

> **Known pre-existing bug to fix here** (surfaced in Phase 1 live testing): in `notebooks/04_ontology_mapping.py`, the generic `Document`-entity loop currently yields 0 rows even when `parsed_documents` has data (compliance had 43 docs but 0 Document entities). The Knowledge Graph for the new domain needs Document nodes — debug the `doc["doc_id"]`/`parsed_documents` read (likely a column-name/Row-access issue) as part of this domain build.

### 4. The four "agents" as tools (MVP — orchestrated inside existing agent)
Add UC-function/LangChain tools consumed by `agent_query` for `domain_id=compliance_due_diligence`:
1. **Intake** — classify a feasibility request → `{request_type, project/store, municipality, priority}` (reuse `ai_classify` + extracted fields).
2. **Research** — retrieve municipality requirements/licenses via Vector Search over `{domain}_docs_index` (+ ontology `Municipality DEFINES` edges).
3. **Historical Knowledge** — "have we handled this municipality before?": VS + `HAS_HISTORY_OF` / prior `Response` docs, return cited prior answers with dates.
4. **Action** — create/track via `POST /action-master` (reuse lifecycle + escalation engine).

### 5. Change detection
`detect_regulatory_change(municipality, requirement_type)`: compare the latest ingested requirement vs the prior `effective_date` version (from extracted fields / `entities` attributes). On material change: emit a structured `REGULATORY CHANGE DETECTED` result (`affected_project(s)`, `previous`, `new`, `impact`) and fire `evaluate_escalations(... requirement_change ...)` → escalated action. Persist to a Gold view `regulatory_change_history` (or a `change_detected` flag on requirement entities).

## Deliverables
- `scripts/setup_compliance_due_diligence.py`
- `notebooks/01_synthetic_corpus_store_dev.py`
- `domains/compliance_due_diligence/` populated (schemas, ontology, prompts, agents, sample_data manifests referencing the above)
- Change-detection + 4 tool functions wired for the domain.

## Acceptance criteria
- `setup_compliance_due_diligence.py` (profile `jai-az-ws`) → `domain_configs` row `status=active`; domain appears in UI.
- Pipeline job populates `parsed_documents`, `extracted_fields`, `{domain}_docs_index`; Knowledge Graph shows Project/Municipality/Requirement/License.
- Tampa demo (AI Agent tab): classify → research → recall prior → create tracked action, with citations.
- Before/after Dallas pair → `REGULATORY CHANGE DETECTED` + an escalated action.
- `supply_chain` and `compliance` unchanged.

## Constraints
Do not modify platform components or the `compliance` domain. Content + config + thin overlay only.
