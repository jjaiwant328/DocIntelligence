# claude_prompts — reuse-aware build prompts

These are the component build prompts from `component_and_claude_instructions.md`, **reshaped for the reality of this codebase**. Feed one file at a time to Claude Code / Cursor to build that component.

## The one rule: reuse, don't rebuild

`component_and_claude_instructions.md` describes the target architecture as if it were greenfield ("Create `documents_raw`… Create `platform.actions`…"). **~90% of that platform already exists and runs** on catalog `jai_docintel` — just under different table names and not split into `platform/`+`domains/` folders.

If you hand Claude the original prompts verbatim, it will build a **second, parallel, conflicting platform**. That is exactly the duplication the doc warns against.

So every prompt here leads with a **"What already exists — DO NOT rebuild"** inventory (real catalog/table/file/symbol names), then states only the **gap to fill**, additively and backward-compatibly.

Authoritative name map: [`../platform/MANIFEST.md`](../platform/MANIFEST.md).

## Build order

| Phase | Prompts | Why |
|---|---|---|
| **0 — Framing** | (this folder + `platform/MANIFEST.md` + `domains/compliance_due_diligence/` skeleton) | Logical platform/domain split. No code moves. |
| **1 — Platform hardening** | `02_ontology_framework`, `03_action_framework` | The only two real *platform* gaps: config-driven ontology map + deterministic escalation engine. |
| **2 — Flagship domain** | `04_compliance_due_diligence_domain`, `07_databricks_implementation`, `08_demo_experience` | Store-development due diligence — the demoable MVP. |
| **3 — Enterprise polish** | `06_agent_framework`, `05_supply_chain_module` | Served multi-agent supervisor, live email/web, supply-chain module refactor. |

## Global constraints for every prompt

- **Additive & backward-compatible.** `supply_chain` and `compliance` domains must keep working unchanged.
- **Config-driven.** New domain behavior comes from a `platform.domain_configs` row + config tables, not new hardcoded branches.
- **No duplicate tables.** Reuse `parsed_documents_raw` / `parsed_documents_content` / `extracted_fields` / `entities` / `relationships` / `action_master`. Never create `documents_raw` / `documents_processed` / `platform.actions`.
- **No relocation of live code** in Phases 0–2. New artifacts go under `domains/` and new scripts/notebooks; the deployed backend/frontend/notebooks stay put.
- **Verify before done.** Each prompt lists acceptance criteria; run them against profile `jai-az-ws`.

## Files

- `01_platform_foundation.md`
- `02_ontology_framework.md`
- `03_action_framework.md`
- `04_compliance_due_diligence_domain.md`
- `05_supply_chain_module.md`
- `06_agent_framework.md`
- `07_databricks_implementation.md`
- `08_demo_experience.md`
