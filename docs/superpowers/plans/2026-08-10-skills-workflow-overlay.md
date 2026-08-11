# Skills/Workflow Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a thin, deterministic Skills → Workflow overlay that wraps existing DocIntelligence capabilities, runs one Due-Diligence template over Compliance and Supply Chain with zero engine/skill change, logs every step, and exposes a run API + thin UI in the live app.

**Architecture:** New self-contained `skill_runtime/` + `workflow_engine/` packages **inside `app/backend/`** (so they deploy with the app). Skills wrap existing seams (`run_sql`, `_vs_search`, `_get_domain_schemas`, `_resolve_model`, `action_master`) behind versioned YAML contracts resolved by one of three adapters. Adapters are injectable so tests run offline with fakes. A single new FastAPI route runs a template; a thin Next.js page drives it.

**Tech Stack:** Python 3.10 (app runtime), FastAPI, PyYAML (already a dep), databricks-sdk, Next.js 15 frontend. Tests are plain `python -m` runnable (mirrors `app/backend/tests/test_vs_search.py`).

## Global Constraints

- All overlay code lives under `app/backend/` (deploy.sh packages only that dir). Verbatim: `find . -mindepth 1 -maxdepth 1 ... -exec cp -r {} build/`.
- Reuse, never duplicate: ingestion, search, ontology tables, action model. Wrap existing seams.
- No dynamic code-exec from YAML. Exactly three adapters: `uc_function`, `internal_call`, `llm_schema`.
- Every AI answer carries `Evidence[]`. LLM skills must be able to return `insufficient_evidence`.
- AI-created actions are DRAFT by default; consequential steps gated by one human-approval gate.
- Catalog `jai_docintel`, warehouse id `85a4ed5bcff25c0d`, profile `jai-az-ws`.
- Tests must pass offline (no live Databricks) via injected fake adapters. Live smoke test is separate.
- File-based versioning via `version:` field. One new table only: `platform.skill_executions`.

---

### Task 1: Core dataclasses (`models.py`)

**Files:**
- Create: `app/backend/skill_runtime/__init__.py`
- Create: `app/backend/skill_runtime/models.py`
- Test: `app/backend/tests/test_skill_models.py`

**Interfaces:**
- Produces: `Evidence(document_id, locator, source_text, confidence, method)`;
  `WorkObject(id, type, title, domain, status, owner, created_at, updated_at, documents, findings, actions, evidence, decisions, metadata)`;
  `SkillResult(status, outputs: dict, evidence: list[Evidence], error: str|None)`;
  `SkillContract` (parsed contract) with `.validate_inputs(dict)` / `.validate_outputs(dict)` raising `InputError`/`OutputError`.
- All dataclasses have `.to_dict()`.

- [ ] Write failing test asserting `Evidence(...).to_dict()` round-trips and `SkillResult` defaults `evidence=[]`, `error=None`.
- [ ] Implement dataclasses + `InputError`/`OutputError` exceptions.
- [ ] Run `python -m pytest app/backend/tests/test_skill_models.py -v`; commit.

### Task 2: Registry + contract loader (`loader.py`)

**Files:**
- Create: `app/backend/skill_runtime/loader.py`
- Create: `app/backend/skill_runtime/registry.yaml` (8 enabled + stubs)
- Create: `app/backend/skill_runtime/contracts/*.yaml` (8 enabled)
- Create: `app/backend/skill_runtime/prompts/*.md` (5 llm_schema skills)
- Test: `app/backend/tests/test_loader.py`

**Interfaces:**
- Produces: `load_registry(path) -> Registry`; `Registry.list(enabled_only=False)`, `.get(skill_id) -> SkillContract`, `.validate() -> list[str]` (errors).
- Contract fields: `id, version, category, adapter, implementation, inputs, outputs, required_capabilities, ontology_dependencies, evidence_requirements, side_effects, test_method`.

- [ ] Write failing test: registry loads, `list(enabled_only=True)` returns the 8 slice skills, `validate()` returns `[]`, every enabled skill has a contract file whose `adapter` is one of the three.
- [ ] Author `registry.yaml` (8 enabled: create_work_object, extract_requirements, find_supporting_evidence, assess_requirement, identify_gap, assess_risk, generate_recommendation, create_action; remaining docs skills `enabled: false`).
- [ ] Author the 8 contract YAMLs + 5 prompt files.
- [ ] Implement loader with validation (unknown adapter, missing contract, missing prompt → errors).
- [ ] Run tests; commit.

### Task 3: Adapters (`adapters/`)

**Files:**
- Create: `app/backend/skill_runtime/adapters/{__init__,base,uc_function,internal_call,llm_schema}.py`
- Test: `app/backend/tests/test_adapters.py`

**Interfaces:**
- Produces: `Adapter.execute(contract, inputs, ctx) -> (outputs: dict, evidence: list[Evidence])`.
- `ctx` carries callables: `run_sql`, `vs_search`, `resolve_model`, `chat_completion`, `internal` (name→callable map). Injectable for offline tests.
- `uc_function`: builds `SELECT ... FROM {impl}(...)` via `ctx.run_sql`. `internal_call`: looks up `ctx.internal[impl]`. `llm_schema`: renders prompt, calls `ctx.chat_completion`, parses JSON constrained to contract outputs.

- [ ] Write failing tests with a fake ctx (fake run_sql returns canned rows; fake chat_completion returns canned JSON) — one per adapter — asserting shape + evidence.
- [ ] Implement three adapters + base.
- [ ] Run tests; commit.

### Task 4: Dispatcher + execution envelope (`dispatcher.py`, `executions.py`)

**Files:**
- Create: `app/backend/skill_runtime/dispatcher.py`
- Create: `app/backend/skill_runtime/executions.py`
- Test: `app/backend/tests/test_dispatcher.py`

**Interfaces:**
- Produces: `Dispatcher(registry, ctx, adapters, logger).invoke(skill_id, inputs, wf_ctx=None) -> SkillResult`.
- Envelope: validate inputs → execute adapter → validate outputs → attach evidence → log → return. On any failure return `SkillResult(status="error", error=...)` and still log.
- `executions.py`: `ensure_table(run_sql)` (idempotent DDL for `platform.skill_executions`); `ExecutionLogger.log(record)` (writes a row via run_sql, swallows logging errors).

- [ ] Write failing tests: happy invoke logs one row + returns typed outputs; bad input → `status="error"`, still logs; fake logger captures records.
- [ ] Implement dispatcher + executions (DDL matches spec §5 columns).
- [ ] Run tests; commit.

### Task 5: Workflow engine (`engine.py`) + template

**Files:**
- Create: `app/backend/workflow_engine/__init__.py`
- Create: `app/backend/workflow_engine/engine.py`
- Create: `app/backend/workflow_engine/templates/due_diligence.yaml`
- Test: `app/backend/tests/test_engine.py`

**Interfaces:**
- Produces: `WorkflowEngine(dispatcher, templates_dir).run(template_id, domain, inputs) -> WorkflowRun`.
- `WorkflowRun(status, steps: list[StepRecord], work_object, halted_at)`. Supports sequential steps, I/O mapping (later step reads earlier outputs by key), bounded retries (default 1), failure state (halt with history), one approval gate before `create_action` (returns status `pending_approval` unless `inputs["approve"]` truthy).
- Template YAML: `id, version, steps:[{id, skill, inputs_map}]`, `approval_before: create_action`.

- [ ] Write failing test with a fake dispatcher: engine runs 8 steps in order, maps outputs→inputs, halts at approval gate when `approve` absent, resumes when present; a step error halts with partial history.
- [ ] Implement engine + author `due_diligence.yaml`.
- [ ] Run tests; commit.

### Task 6: Domain configs

**Files:**
- Create: `app/backend/domains/compliance/{domain,ontology,requirements}.yaml`
- Create: `app/backend/domains/supply_chain/{domain,ontology,requirements}.yaml`
- Test: `app/backend/tests/test_domains.py`

**Interfaces:**
- Produces: `load_domain(domains_dir, domain_id) -> DomainConfig` with `.ontology_entities`, `.requirements`, `.prompts` (added to `skill_runtime/loader.py` or a small `domains.py`).
- compliance requirements: zoning, alcohol_license, environmental_permit, business_license. supply_chain: insurance, quality_certification, food_safety, audit.

- [ ] Write failing test: both domains load; requirements lists match spec; engine `run(..., domain="compliance")` vs `"supply_chain"` uses same template, different requirements (with fake dispatcher).
- [ ] Author 6 YAMLs + `load_domain`.
- [ ] Run tests; commit — **this proves the swap headless.**

### Task 7: Skill test harness (`test.py`) + fixtures

**Files:**
- Create: `app/backend/skill_runtime/test.py`
- Create: `app/backend/tests/skills/<skill>/{happy,missing_input,invalid,insufficient_evidence,ambiguous}.yaml` + `expected_outputs.yaml` for the 8 skills
- Test: `app/backend/tests/test_harness.py`

**Interfaces:**
- Produces: `python -m skill_runtime.test --skill <id>` and `--all` (run from `app/backend/`). Uses fake ctx so it runs offline. For `llm_schema` skills asserts structure/invariants (schema-valid, `insufficient_evidence` on thin evidence, confidence present), not exact prose; for others exact values.

- [ ] Write failing test: `--all` returns exit 0 with fake ctx; a deliberately broken fixture returns non-zero.
- [ ] Author fixtures + harness runner.
- [ ] Run tests; commit.

### Task 8: Backend wiring — real ctx + run route

**Files:**
- Create: `app/backend/skill_runtime/context.py` (builds the live `ctx` from `docintel_routes` seams)
- Modify: `app/backend/docintel_routes.py` (add `POST /api/docintel/workflow-run` + `GET /api/docintel/skill-executions`)
- Test: `app/backend/tests/test_workflow_route.py` (route wiring with monkeypatched engine)

**Interfaces:**
- Consumes: `run_sql`, `_vs_search`, `_resolve_model`, `_get_domain_schemas`, action helpers from `docintel_routes.py`.
- `build_live_context() -> Context` maps: uc_function→`run_sql`; internal→{`create_work_object`, `create_action`(DRAFT via existing action_master path)}; llm_schema→chat via `_resolve_model` + serving endpoint call already used by `agent_query`/`copilot_query`.
- Route: `POST /api/docintel/workflow-run {template, domain_id, project, inputs, approve?}` → `WorkflowRun.to_dict()`. `GET /skill-executions?workflow_id=` → rows.

- [ ] Write failing test: route returns 200 and a run dict when engine is monkeypatched; validates request model.
- [ ] Implement `context.py` + routes (reuse existing LLM call helper; do NOT touch `agent_query` logic).
- [ ] Run tests; commit.

### Task 9: Live table + smoke test on jai-az-ws

**Files:**
- Create: `app/backend/scripts/create_skill_executions.py` (idempotent DDL runner via databricks-sdk)
- Create: `app/backend/scripts/smoke_workflow.py` (runs due_diligence for compliance + supply_chain against live ctx, prints step statuses + evidence counts)

- [ ] Run `python app/backend/scripts/create_skill_executions.py` against `jai-az-ws`; verify table exists.
- [ ] Run `python app/backend/scripts/smoke_workflow.py`; confirm both domains complete through the approval gate, evidence present, rows logged. Capture output.
- [ ] Commit scripts + smoke output notes.

### Task 10: Thin frontend surface

**Files:**
- Create: `app/frontend/src/app/workflow/page.tsx` (Run panel + Step inspector)
- Modify: nav/link source if a shared nav exists (else route reachable by URL)
- Test: `cd app/frontend && npm run build` (static export must succeed)

**Interfaces:**
- Consumes: `getApiBaseUrl()` + `POST /api/docintel/workflow-run`, `GET /api/docintel/skill-executions`. Reads `?domain_id=` via `useSearchParams()`.
- Renders: template/domain/project inputs → Run → per-step output + evidence; Approve button re-runs with `approve:true`; DRAFT actions listed.

- [ ] Build page following `supply-chain/page.tsx` patterns.
- [ ] Add `cp out/workflow/index.html out/workflow.html` to `deploy.sh` static-fix block.
- [ ] `npm run build` succeeds; commit.

### Task 11: Deploy + verify

- [ ] `bash app/deploy.sh` (defaults: docintel-supply-chain, jai-az-ws).
- [ ] Poll `databricks apps list -p jai-az-ws` until `docintel-supply-chain` DeploymentStatus SUCCEEDED.
- [ ] Hit the live `/workflow?domain_id=compliance_due_diligence` page; run once; confirm steps + evidence render and a skill_executions row appears.
- [ ] Report: files changed, capabilities added, tests run, known limitations, next phase.

---

## Self-review notes
- Spec coverage: §2 arch→T1–8; §3 flow/swap→T5,T6; §4 contract/adapters→T2,T3; §5 harness/observability→T4,T7,T9; §6 errors→T4,T5; §7 surfaces→T10; §8 DoD→T6(headless)+T11(live). All covered.
- No placeholders: each task names exact files + interfaces. LLM-skill tests assert structure not prose (consistent T3/T7).
- Type consistency: `SkillResult`, `Evidence`, `Context`, `WorkflowRun` names used identically across tasks.
- Agent demotion (ADR-003 / spec Approach A "flip last") intentionally deferred beyond this slice — route is additive; `agent_query` untouched. Flagged as next phase.
