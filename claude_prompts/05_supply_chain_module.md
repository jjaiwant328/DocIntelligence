# Component 5 — Supply Chain Module (reuse-aware) — LOW PRIORITY / PHASE 3

## Goal
Capture the existing, working supply_chain domain as a **logical** module under `domains/supply_chain/` for consistency with the platform/domain split. Do **not** break or relocate running code.

## What already exists — DO NOT rebuild
- `supply_chain` is fully live: split schemas `raw`/`ontology`/`vectors`/`agents`, job id `1095463829768201`, corpus in `notebooks/01_synthetic_corpus.py` + `02_structured_tables.py`, hand-authored ontology (`notebooks/04_ontology_mapping.py` supply_chain branch), 4 bespoke agent tools (`notebooks/06_agent.py`), and Control Tower UI.
- Entities already modeled: Supplier, Lot, Shipment, RecallEvent, Carrier, Product, DistributionCenter, Restaurant.

## Gap to fill (documentation/organization only for MVP)
1. Create `domains/supply_chain/` with subfolders (`schemas/`, `ontology/`, `prompts/`, `agents/`, `sample_data/`) containing **manifest docs** that point to where each artifact currently lives (do not copy/move code yet).
2. Document the supply_chain entities/agents/questions as domain content, matching the format used by `domains/compliance_due_diligence/`.
3. (Phase 3 optional) Migrate the hardcoded supply_chain branches in nb 04/06 to config-driven equivalents once Prompt 02/06 land — only if it does not risk the working demo.

## Deliverables
- `domains/supply_chain/**/README.md` manifests referencing existing assets.

## Acceptance criteria
- No behavior change; supply_chain demo works exactly as before.

## Constraints
Additive documentation. No code moves in Phases 0–2.
