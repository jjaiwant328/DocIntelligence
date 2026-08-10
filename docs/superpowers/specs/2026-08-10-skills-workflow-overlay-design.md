# Design — Skills / Workflow Overlay (reuse-first slice)

**Date:** 2026-08-10
**Branch:** `store_mvp`
**Workspace:** `jai-az-ws` (`adb-4101016551133680.0.azuredatabricks.net`), catalog `jai_docintel`
**Source docs:** `Document_Intelligence_Cursor_Claude_Code_Build_Plan.md` (20-phase plan) +
`Document_Intelligence_Skills_Workflow_Architecture_Reference.pdf` (reference architecture).
**Prior analysis (Phase 1, already done):** `docs/current-state.md`,
`docs/architecture-decisions.md` (ADR-001…008), `docs/skills-workflow-implementation-plan.md`.

---

## 1. Goal & scope

Build a **thin Skills → Workflow Templates → Domain Configs → Projects** overlay on top of
the existing, live DocIntelligence platform, satisfying the two source docs' architecture and
their 10-step Definition of Done — **without rebuilding** ingestion, parsing, search,
ontology, or the action model.

**Scope decisions (locked with user, 2026-08-10):**
- **Reuse-first slice** (ADR-002): one Due-Diligence template composing ~8 skills that *wrap*
  existing capabilities; prove the Compliance→Supply-Chain swap; defer the full 25-skill
  library and Playground/Builder UI to a follow-on (Scope A).
- **Build locally against `jai-az-ws`; deploy the app only at reviewed milestones.** The one
  workspace write in the slice is the `platform.skill_executions` DDL, run at milestone 1.

**Chosen approach — "Overlay beside the agent, flip last" (Approach A).** Build the overlay as
self-contained `skill_runtime/` + `workflow_engine/` and prove the domain swap headless (test
harness + CLI) *before* touching the live LangChain `agent_query` path. Agent demotion (the
highest-risk step, R1) happens last, behind a feature flag, once the engine passes the demo
scenarios. Rejected: agent-first re-wire (edits live orchestration while engine is immature);
pure config/no-engine (leaves orchestration non-deterministic — violates the docs' central
guardrail).

## 2. Component architecture

```
skills/
  registry.yaml               declares every skill (id, version, category, impl ref, enabled)
  contracts/<skill>.yaml       full contract per enabled skill
skill_runtime/
  loader.py                    parse + validate registry/contracts on load
  dispatcher.py                routes skill id -> one of 3 adapters (ADR-005)
  adapters/{uc_function,internal_call,llm_schema}.py
  models.py                    Skill, Evidence, WorkObject dataclasses (thin projections, ADR-006)
  test.py                      `python -m skill_runtime.test --skill <id>` harness
workflow_engine/
  engine.py                    sequential steps + I/O mapping + conditions + retries
                               + failure states + ONE approval gate + execution history
templates/
  due_diligence.yaml           the 8-step skill graph (config, not code)
domains/
  compliance/{domain,ontology,requirements}.yaml
  supply_chain/{domain,ontology,requirements}.yaml
tests/skills/<skill>/{happy,missing_input,invalid,insufficient_evidence,ambiguous}.yaml
                               + expected_outputs.yaml
platform.skill_executions      new Delta table on jai_docintel (observability, ADR-007)
```

Nothing here duplicates ingestion, search, ontology tables, or the action model — all are
*wrapped*. The ~8 slice skills: `create_work_object`, `extract_requirements`,
`find_supporting_evidence`, `assess_requirement`, `identify_gap`, `assess_risk`,
`generate_recommendation`, `create_action`. The remaining ~17 skills from the docs register as
`enabled: false` stubs so the registry shape is complete and Scope A is purely additive.

## 3. Data flow & the Compliance→Supply-Chain swap

```
run(template=due_diligence, domain=compliance, project=Store 1827)
  engine loads templates/due_diligence.yaml   -> ordered skill list
  engine loads domains/compliance/*.yaml       -> ontology + requirements + prompts

  create_work_object     -> work_objects row (type=review, domain=compliance)
  extract_requirements   -> domains/compliance/requirements.yaml + extracted_fields
  find_supporting_evidence -> ai_similarity retrieval (PR #6) -> Evidence[]
  assess_requirement     -> LLM-with-schema over (requirement, evidence) -> status+confidence+evidence
  identify_gap           -> LLM-with-schema -> gaps[]
  assess_risk            -> LLM-with-schema -> risk+rationale+evidence
  generate_recommendation-> LLM-with-schema -> recommendation+evidence
  create_action          -> action_master (DRAFT, ADR-008) -- approval gate --> human

  every step writes one platform.skill_executions row
```

**The swap:** re-run with `domain=supply_chain, project=Supplier ABC`. The engine reads the
*same* `due_diligence.yaml` and the *same* skill code; only the loaded domain config differs
(insurance, quality_certification, food_safety, audit + that domain's ontology/prompts). **No
file in `workflow_engine/` or `skill_runtime/` changes.** This is the demonstrable proof for
Definition-of-Done steps 8–10.

Invariants in this flow:
- **Evidence threaded through every reasoning skill** — `assess_requirement`, `assess_risk`,
  `generate_recommendation` each return supporting `Evidence[]` (document_id, chunk, source
  text, confidence, method), never a bare conclusion (guardrail 14).
- **Single approval gate** before `create_action` commits beyond DRAFT — consequential
  side-effects gated, everything upstream read-only.

## 4. Skill Contract & dispatcher adapters

Every enabled skill has one `skills/contracts/<skill>.yaml` matching the docs' Skill Contract:

```yaml
id: assess_requirement
version: "1.0"
category: reasoning
description: Judge whether a single requirement is satisfied by the available evidence.
adapter: llm_schema            # uc_function | internal_call | llm_schema
implementation: prompts/assess_requirement.md
inputs:
  requirement: {type: string, required: true}
  evidence:    {type: array,  required: true}
outputs:
  status:     {type: enum, values: [satisfied, gap, insufficient_evidence]}
  confidence: {type: number}
  evidence:   {type: array}
required_capabilities: [llm]
ontology_dependencies: [Requirement]
evidence_requirements: required
side_effects: {creates_actions: false}
test_method: tests/skills/assess_requirement/
```

The **dispatcher** takes a skill id + validated inputs and routes to exactly one of three
adapters (ADR-005 — never dynamic code-exec from YAML):

| Adapter | Wraps (existing asset) | `implementation:` resolves to | Slice skills |
|---|---|---|---|
| `uc_function` | UC SQL functions on `jai_docintel` (`cdd_*`, `get_entity_documents`, `ai_similarity`) | catalog.schema.function | `find_supporting_evidence` |
| `internal_call` | FastAPI logic in `docintel_routes.py` + `action_master` writes | registered Python callable | `create_work_object`, `create_action` |
| `llm_schema` | `databricks-claude-sonnet-4-5` via existing `_resolve_model` chain, output constrained to contract schema | prompt file | `extract_requirements`, `assess_requirement`, `identify_gap`, `assess_risk`, `generate_recommendation` |

Every adapter enforces the same envelope, so the engine never knows which kind a skill is:

```
validate input (contract schema) -> resolve data sources -> execute via adapter
  -> validate output (contract schema) -> attach evidence -> return structured result
  -> write skill_executions row
```

Commitments: **wrap, don't rewrite** (evidence skill calls existing `ai_similarity`; action
skill calls existing `action_master` DRAFT flow); **LLM skills are schema-bound** (must return
`insufficient_evidence` rather than fabricate, expose confidence); **the dispatcher is the only
place** that knows adapter types.

## 5. Test harness & observability

**Test harness** (docs Phase 6). Five deterministic fixture classes per enabled skill under
`tests/skills/<skill>/` (`happy`, `missing_input`, `invalid`, `insufficient_evidence`,
`ambiguous`) + `expected_outputs.yaml`. Runner: `python -m skill_runtime.test --skill <id>`
and `--all`. For `llm_schema` skills the harness **asserts on structure and invariants, not
exact prose**: output validates against the contract schema, `insufficient_evidence` fires on
thin evidence, confidence present, evidence non-empty when required, conflict fixtures stay
low-confidence. `uc_function` / `internal_call` skills get exact-value assertions. Reuse an
existing repo test runner if one fits; otherwise this is a thin standalone module (no second
framework).

**Observability** (docs Phase 16). One new Delta table extending the `pipeline_runs` pattern:

```
platform.skill_executions
  execution_id, skill_id, skill_version, workflow_id, workflow_version,
  work_object_id, start_time, end_time, status, error,
  model (if llm_schema), evidence_count, inputs_digest
```

Dispatcher writes one row per invocation (success or failure); engine correlates by
`workflow_id`/`work_object_id` for per-run history. **This is the one `jai-az-ws` write in the
slice** — an idempotent `CREATE TABLE IF NOT EXISTS` script run at milestone 1.

## 6. Error handling

Docs: *"return a useful error rather than silently failing."* Three levels, all deterministic
and logged:
- **Skill level** — input fails contract validation -> structured `InputError` (no crash);
  adapter raises -> caught; output-schema failure -> `OutputError`; thin LLM evidence -> a
  first-class `insufficient_evidence` result, not an error. Every case writes a
  `skill_executions` row with `status=error` + `error` text.
- **Engine level** — bounded per-step `retries` (default 1), then a **failure state** that
  halts the run with partial execution history intact. No half-committed side-effects — the
  only write (`create_action`) sits behind the end approval gate.
- **Approval gate** — if declined, workflow ends cleanly with actions left in DRAFT.

## 7. Demo surfaces (thin slice only)

Read-mostly views on the **existing** Next.js app shell, inheriting `?domain_id=` — no new app:

| Surface | Shows | Backed by |
|---|---|---|
| **Run panel** | pick template + domain + project -> Run | engine `run()` via one new FastAPI route |
| **Step inspector** | each step's typed output + evidence | `skill_executions` + returned Evidence[] |
| **Action tracker (reuse)** | resulting DRAFT actions, owner, status | existing `action_master` UI |

Deferred to Scope A (not built now): full Skill Playground, Workflow Builder editor, Case
Workspace, standalone Evidence Explorer.

## 8. Definition of Done (from the source docs)

Register a skill -> test it independently -> add to a template -> configure the template for
Compliance -> run against Store 1827 -> inspect evidence/outputs -> create + track actions ->
reconfigure the SAME template for Supply Chain -> run against Supplier Qualification -> show
the platform and skills did not change.

## 9. Risks & assumptions

- **R1 — Agent re-wiring** (highest). Mitigated by Approach A: agent demotion is last, behind a
  feature flag, only after engine parity on the demo scenarios.
- **R2 — Heterogeneous skill impls behind one contract.** Mitigated by exactly three adapters;
  no code-exec from YAML.
- **R3 — Engine scope creep into BPM.** Mitigated: sequential + conditions + retries + one
  approval gate + history only; nothing else.
- **R4 — Plan reconciliation** with `claude_prompts/`. Assumption: these two docs supersede on
  registry/engine formalism; `claude_prompts` stays valid for domain/data work.
- **A1** synthetic data only; **A2** single app / vector stack / action model retained;
  **A3** file-based versioning sufficient for the demo.

## 10. Traceability to source docs

| Source doc phase | Covered by |
|---|---|
| 1 Reconnaissance | Already done (`docs/current-state.md`, `architecture-decisions.md`) |
| 2 Platform contracts | §4 Skill Contract; §2 Evidence/WorkObject (ADR-006) |
| 3 Skill registry | §2 `skills/registry.yaml` + loader |
| 4 Skill library | §2 ~8 enabled skills; remaining stubs |
| 5 Skill impl rules | §4 envelope; §6 error handling |
| 6 Test harness | §5 |
| 7 Workflow engine | §2, §3 `workflow_engine/` |
| 8 Workflow config | §2 `templates/due_diligence.yaml` |
| 9-10 Domain config & rules | §2, §3 `domains/*/*.yaml` |
| 11-12 Compliance & Supply-Chain use cases | §3 the swap |
| 13 Interactive surfaces | §7 (thin slice; rest deferred) |
| 14 Agent interaction | Approach A, flip last (ADR-003) |
| 15 Action management | §3 `create_action` reuse (ADR-008) |
| 16 Observability | §5 `skill_executions` |
| 17 Versioning | file-based `version:` (ADR-007) |
| 18-19 Demo data & scenarios | reuse existing CDD corpus + Dallas pair |
| 20 Validation | §8 Definition of Done |
