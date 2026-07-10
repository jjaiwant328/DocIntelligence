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

## Primary target: the Compliance store-MVP demo

The concrete goal these prompts serve is the **Compliance Due Diligence store-development demo** (RaceTrac feasibility — see `../store_development.md`). When a prompt offers options, choose what advances that demo: the Tampa feasibility walkthrough (classify → research municipal requirements → recall prior response → detect a regulatory change → create a tracked, escalated action). `compliance_due_diligence` is the flagship `domain_id`; `supply_chain` and the operational `compliance` domain are only regression baselines.

## Deployment surface — apps & Genie (read before Phases 2–3)

- **One Databricks App, not one-per-phase.** The existing multi-domain app (`app/frontend` + `app/backend`) serves every subject area via `?domain_id=`. Do **not** create a separate app for the compliance domain or for any phase — a new domain is a `domain_configs` row that the single app inherits. A second app would fork the platform (the anti-pattern this repo avoids).
- **Genie space (optional, Phase 2/3).** The in-app AI Agent/Copilot already answers NL questions over Vector Search + gold tables. A **Genie space** is a worthwhile *addition* for structured/aggregate questions over the compliance tracker tables (e.g. "how many Tampa feasibility requests are open?", "which municipalities changed requirements this quarter?") — Genie generates SQL over `extracted_fields` / gold / `action_master`. Treat it as an optional enhancement wired into the Historical-Knowledge/Ask surface, not a replacement for the agent. If built: one Genie space scoped to the `compliance_due_diligence` schema + `platform.action_master`, surfaced in the app's Ask/Copilot tab. See `08_demo_experience.md`.

## Files

- `01_platform_foundation.md`
- `02_ontology_framework.md`
- `03_action_framework.md`
- `04_compliance_due_diligence_domain.md`
- `05_supply_chain_module.md`
- `06_agent_framework.md`
- `07_databricks_implementation.md`
- `08_demo_experience.md`
