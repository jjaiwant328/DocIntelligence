# Agent Tool Definitions — Compliance Due Diligence

MVP: four capabilities implemented as tools inside the existing `agent_query` LangChain executor
(`app/backend/docintel_routes.py`, `notebooks/06_agent.py`). They are added to the generic
`else` branch that activates for `domain_id = compliance_due_diligence`.

---

## Tool 1 — Intake

**Name:** `classify_feasibility_request`

**Description:** Classify an incoming feasibility request document and extract its key fields.

**Inputs:**
- `document_text` (str): Raw text of the feasibility request.

**Logic:**
1. Call `ai_classify(document_text, labels=CLASSIFICATION_LABELS)` → `doc_type`.
2. Run the `feasibility_request` extraction schema via the LLM extractor → structured fields.
3. Return `{doc_type, project_id, store_number, municipality, request_type, priority}`.

**Reuses:** `ai_classify` UC function + existing extractor pipeline.

---

## Tool 2 — Research

**Name:** `research_municipal_requirements`

**Description:** Retrieve current municipal requirements and required licenses for a given store/municipality.

**Inputs:**
- `municipality` (str): Municipality name.
- `state` (str): State abbreviation.
- `store_number` (str, optional): Store or project number for context.

**Logic:**
1. Vector Search query over `{compliance_due_diligence}_docs_index` filtered to
   `doc_type IN (municipal_requirement, alcohol_license, tobacco_license, business_license, zoning_document, permit)`.
2. Augment with ontology graph: traverse `Municipality DEFINES RegulatoryRequirement` and
   `RegulatoryRequirement REQUIRES License` edges from `{schema}.relationships`.
3. Return ranked list of requirements with `{requirement_type, authority, lead_time, expiration_date, source_document}`.

---

## Tool 3 — Historical Knowledge

**Name:** `recall_prior_responses`

**Description:** Retrieve prior feasibility responses for a municipality to answer "have we been here before?"

**Inputs:**
- `municipality` (str): Municipality name.
- `state` (str, optional): State abbreviation.

**Logic:**
1. Vector Search over `{compliance_due_diligence}_docs_index` filtered to `doc_type = historical_response`.
2. Augment with ontology: traverse `Project HAS_HISTORY_OF Response` edges.
3. Return `[{store_number, response_date, responder, summary, source_document}]` sorted by date descending.

---

## Tool 4 — Action

**Name:** `create_or_track_action`

**Description:** Create a new tracked action or retrieve open actions for a project.

**Inputs:**
- `action_type` (str): e.g. `obtain_alcohol_license`, `resolve_zoning`, `submit_permit`.
- `project_id` (str): Project or store identifier.
- `municipality` (str): Municipality.
- `due_date` (str, optional): ISO date.
- `notes` (str, optional): Free-text context.

**Logic:**
1. `POST /action-master` via the existing `platform.action_master` lifecycle.
2. `evaluate_escalations(domain_id=compliance_due_diligence, context=...)` if priority is CRITICAL/HIGH.
3. Return `{action_id, status, due_date, escalated}`.

**Reuses:** `platform.action_master` + escalation engine (Phase 1 / Prompt 03).
