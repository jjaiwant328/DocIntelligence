# Domain Module — Compliance Due Diligence (Store Development)

AI-powered **store-development / feasibility due diligence** for a fuel/convenience retailer (RaceTrac). Answers "what do I need to do to open this store?" — classify feasibility requests, research municipal requirements, recall prior responses, detect regulatory changes, and track actions to completion.

- **domain_id:** `compliance_due_diligence` (distinct from the operational `compliance` domain)
- **Source vision:** `../../store_development.md`
- **Build prompt:** `../../claude_prompts/04_compliance_due_diligence_domain.md`
- **Runs on:** the shared platform — see `../../platform/MANIFEST.md`. This module contributes **content only** (schemas, ontology overlay, prompts, agents, sample data).

## Ontology (overlay)
Entities: `Project`, `FeasibilityRequest`, `Municipality`, `RegulatoryRequirement`, `License`, `Response`, `Action`, `Document`.
Relationships: `Project LOCATED_IN Municipality`, `Municipality DEFINES RegulatoryRequirement`, `RegulatoryRequirement REQUIRES License`, `FeasibilityRequest GENERATES Action`, `Response ANSWERS FeasibilityRequest`, `Response SUPPORTED_BY Document`, `Project HAS_HISTORY_OF Response`.

## The four agents (MVP = tools inside the existing agent)
1. Intake — classify feasibility requests.
2. Research — municipal requirements & licenses (Vector Search + ontology).
3. Historical Knowledge — "have we handled this municipality before?"
4. Action — create/track tasks (reuse `action_master` + escalation engine).

## Folder layout
- `schemas/` — extraction schemas per doc type.
- `ontology/` — `ontology_config` (field→entity map + relationship rules).
- `prompts/` — agent system prompt + Copilot prompt(s).
- `agents/` — the 4 agent/tool definitions.
- `sample_data/` — synthetic corpus spec (feasibility emails, municipal requirements, licenses, zoning, historical responses, before/after regulatory pairs).
- `DEMO.md` — Tampa feasibility walkthrough (added in Component 8).

> All folders currently hold placeholder manifests; they are populated when `claude_prompts/04_*` is executed.
