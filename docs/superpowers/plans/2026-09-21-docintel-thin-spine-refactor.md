# DocIntelligence Thin-Spine Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor DocIntelligence in place into a thin, config-driven spine (ingest → parse → extract → search → evidence), consolidating four notebooks into one Lakeflow Declarative Pipeline and moving domain-specific logic into `domain_configs`.

**Architecture:** Reuse the proven `ai_parse_document` + Auto Loader + IDP core. Collapse notebooks 01/02/03/(05) into one serverless Lakeflow Declarative Pipeline writing a medallion (bronze parsed → silver extracted+evidence → gold). Replace bespoke Drive OAuth/fetch/clean with Lakeflow Connect (synthetic fallback retained). Strip skills/workflow/action layers and extra UI tabs.

**Tech Stack:** Databricks (Lakeflow Declarative Pipelines, Lakeflow Connect, Unity Catalog, `ai_parse_document`/`ai_classify`/`ai_extract`/`ai_prep_search`, Vector Search Delta Sync), Python/FastAPI backend, Next.js frontend, pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-docintel-thin-spine-design.md`

## Global Constraints

- **Refactor in place** on branch `docintel-thin-spine-refactor`. Do not create a competing framework.
- **Parity gate before deletion:** never delete an old notebook/route until its replacement reproduces the prior output (verified by SQL/table diff on the synthetic corpus).
- **New outputs land in a fresh schema** `template` under the existing catalog `jai_docintel` (assumption: keeps the current demo tables runnable during parity testing). Do not overwrite existing `raw`/`ontology`/`vectors` schemas until parity is signed off.
- **Domain = configuration.** No new vertical-specific branches in generic code; move existing hardcoding to `platform.domain_configs`.
- **Evidence required:** every extracted value and search hit must resolve to `document_id + page + bbox + source_text`.
- **Synthetic data only.** No production credentials or customer data.
- **Thin optional agent retained** but isolated and droppable (assumption, pending owner).
- Commit messages end with: `Co-authored-by: Isaac <no-reply@databricks.com>`
- Databricks profile: `jai-az-ws`; workspace `adb-4101016551133680.0.azuredatabricks.net`.

## Status (2026-10-11)

- ✅ **T1** cleanup (worktrees removed, refs salvaged, baseline captured)
- ✅ **T2** `template` + `template_cdd` schemas provisioned
- ✅ **T3** one SDP `docintel_spine` (bronze parse → silver classify/chunk → gold extract), verified
- ✅ **T4** same pipeline runs `compliance_due_diligence` via config only (both domains verified)
- ✅ **T5** endpoint-free retrieval (batch embed + `vector_cosine_similarity`) — Vector Search dropped (spec §T5 stale: planned Delta Sync index, shipped endpoint-free)
- 🔶 **T6** Lakeflow Connect — design/doc done (`pipelines/docintel_spine/ingest/lakeflow_connect_source.md`); **going live needs the source owner's OAuth** (external gate). Pipeline reads any `source_volume_path` in place.
- ✅ **T7** backend stripped: skills/workflow/action/attorney/escalation removed; agent kept (legacy paths); suite 216 green
- ✅ **T8** frontend collapsed to Sources · Search & Evidence · Agent (domain-driven); static build clean
- ✅ **T9** corpus generators consolidated → `notebooks/01_synthetic_corpus.py` + `domains/<domain>/sample_data.py`; offline E2E byte-identical
- ✅ **T10** cutover: old notebooks 02/03/04/05.ref/07/09.ref + `app/unstructured_workflow/` deleted; bundle trimmed to `docintel_setup_domain`; `app/CLAUDE.md` rewritten

Additions beyond plan (2026-10-11): OpenJev judge (`judge.py`) — search rerank
on `/api/spine/search` + field-confidence/doc-type validation on
`/api/spine/evidence?validate=true`. `ai_decide` (SQL-side judge) is Beta-gated
off in this workspace; gateway route used instead.

Verified counts — supply_chain: 61 docs/13 types, 72 chunks, 96 fields · compliance: 24 docs/7 types, 41 chunks, 227 fields. Endpoint-free search returns relevant hits for both.

---

### Task 1: Baseline snapshot + remove dead worktrees

**Files:**
- Create: `docs/superpowers/plans/baseline-parity.md` (records the reference outputs)
- Delete: `.worktrees/remove-vs/`, `.worktrees/b1-provision-cdd/`

**Interfaces:**
- Produces: `baseline-parity.md` documenting, for the supply_chain synthetic corpus, the row counts and a canonical query result for `parsed_documents_content`, `extracted_fields`, and one gold table — the numbers later parity gates compare against.

- [ ] **Step 1: Salvage the missing vector-search logic before deleting worktrees**

Confirm whether `05_vector_search.py` exists only in a worktree and copy it into `notebooks/` for reference (it will be superseded by the pipeline in Task 3, but we must not lose the logic):
```bash
cd /Users/Jaiwant.jonathan/DBXApps/DocIntelligence
find .worktrees -name '05_vector_search.py'
cp .worktrees/b1-provision-cdd/notebooks/05_vector_search.py notebooks/05_vector_search.reference.py 2>/dev/null || echo "not found — check other worktree"
```

- [ ] **Step 2: Record baseline outputs**

Run these against the existing demo (via `databricks sql` or a notebook) and paste results into `baseline-parity.md`:
```sql
SELECT count(*) FROM jai_docintel.raw.parsed_documents_content;
SELECT count(*), count(DISTINCT doc_type) FROM jai_docintel.raw.extracted_fields;
SELECT doc_type, count(*) FROM jai_docintel.raw.parsed_documents GROUP BY doc_type ORDER BY 1;
```

- [ ] **Step 3: Verify current demo still runs**

Trigger the existing `docintel_process_docs` job (or run `07_demo_scenario.py`) and confirm it completes green. Note the run URL in `baseline-parity.md`.

- [ ] **Step 4: Delete worktrees**

```bash
git worktree list
git worktree remove .worktrees/remove-vs --force
git worktree remove .worktrees/b1-provision-cdd --force
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/baseline-parity.md notebooks/05_vector_search.reference.py
git commit -m "chore: baseline parity snapshot; salvage vector-search ref; remove dead worktrees

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 2: Provision the `template` schema + seed a second domain config

**Files:**
- Modify: `notebooks/00_platform_setup.py` (add `template` schema provisioning; register `compliance_due_diligence` alongside `supply_chain`)
- Modify: `scripts/setup_compliance_due_diligence.py` (target `template` schema)

**Interfaces:**
- Produces: schemas `jai_docintel.template_raw`, `template_ont`, `template_vec` (or a single `template` schema — match the existing per-domain schema convention in `00_setup.py`); two rows in `platform.domain_configs` (`supply_chain`, `compliance_due_diligence`) pointing at the template schema. Later tasks read `domain_configs` for all domain semantics.

- [ ] **Step 1: Read the existing schema convention**

Read `notebooks/00_platform_setup.py` and `notebooks/00_setup.py` to copy the exact schema/volume naming and `domain_configs` column set. Do not invent columns.

- [ ] **Step 2: Add template-schema provisioning**

Following the existing pattern verbatim, add creation of the template schemas + a UC Volume for landing. Keep it parameterized by `domain_id`.

- [ ] **Step 3: Deploy + run setup**

```bash
databricks bundle deploy --profile jai-az-ws
databricks bundle run docintel_setup_domain --profile jai-az-ws
```
Expected: template schemas + volume exist; `SELECT domain_id FROM jai_docintel.platform.domain_configs` returns both domains.

- [ ] **Step 4: Commit**

```bash
git add notebooks/00_platform_setup.py scripts/setup_compliance_due_diligence.py
git commit -m "feat(platform): provision template schema and register second domain

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 3: One Lakeflow Declarative Pipeline (parse + extract + chunk + evidence)

**Files:**
- Create: `pipelines/docintel_spine/` — a Lakeflow Declarative Pipeline (SDP) bundle resource
- Create: `pipelines/docintel_spine/transformations/bronze_parse.py` (ports `01_parse_documents.py` + `02_extract_document_content.py`)
- Create: `pipelines/docintel_spine/transformations/silver_extract.py` (ports `03_idp_pipeline.py`: classify/extract/prep_search, + promote bbox/page evidence to typed columns)
- Create: `pipelines/docintel_spine/transformations/gold_entities.py` (ports `04_ontology_mapping.py` logic, config-driven — see Task 4)
- Modify: `databricks.yml` (add the SDP resource; keep old jobs until parity)

> Use the `spark-declarative-pipelines` skill for SDP syntax (streaming tables, MVs, Auto Loader). Port transformation logic **verbatim** from the named notebooks; the deliverable is output parity, not new logic.

**Interfaces:**
- Consumes: landing Volume path + `domain_configs` row (from Task 2).
- Produces: `jai_docintel.template_raw.parsed_documents_content`, `template_raw.extracted_fields` (with added `page_id`, `bbox`, `source_text` evidence columns), gold per-type tables — schema-compatible with the Task 1 baseline.

- [ ] **Step 1: Scaffold the SDP bundle resource**

Invoke `spark-declarative-pipelines` skill; scaffold `pipelines/docintel_spine/` targeting serverless, catalog `jai_docintel`, schema `template_raw`.

- [ ] **Step 2: Bronze — port parse + content extraction**

Move the Auto Loader read + `ai_parse_document` call from `app/unstructured_workflow/src/transformations/01_parse_documents.py` and the variant→text flattening from `02_extract_document_content.py` into `bronze_parse.py` as streaming tables. Keep `bbox`/`page_id`/`confidence` in the output (do not drop them during flattening).

- [ ] **Step 3: Silver — port classify/extract/prep_search + evidence**

Move `ai_classify`/`ai_extract`/`ai_prep_search` from `notebooks/03_idp_pipeline.py` into `silver_extract.py`. Add `page_id`, `bbox`, `source_text` columns on `extracted_fields` sourced from the parsed elements.

- [ ] **Step 4: Deploy + run the pipeline on the synthetic corpus**

```bash
databricks bundle deploy --profile jai-az-ws
databricks bundle run docintel_spine --profile jai-az-ws
```

- [ ] **Step 5: Parity gate — verify against baseline**

Run the Task 1 baseline queries against `template_raw.*` and diff row counts / doc_type distribution against `baseline-parity.md`. They must match (modulo the new evidence columns). Record the diff in `baseline-parity.md`.
Expected: PASS (equal counts). If not, fix before proceeding — do not delete old notebooks.

- [ ] **Step 6: Commit**

```bash
git add pipelines/docintel_spine databricks.yml docs/superpowers/plans/baseline-parity.md
git commit -m "feat(pipeline): consolidate parse+extract+chunk into one SDP with evidence columns

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 4: Move domain hardcoding into `domain_configs`

**Files:**
- Modify: `notebooks/04_ontology_mapping.py` / `pipelines/docintel_spine/transformations/gold_entities.py` (read `field_entity_map` + `entity_types` from config, not the hardcoded `FIELD_ENTITY_MAP`)
- Modify: `app/backend/docintel_routes.py` (remove `SUPPLY_CHAIN_DEFAULT` fallback; require domain config)
- Modify: `notebooks/06_agent.py` (agent tools from config, not `if domain_id == "supply_chain"`)
- Modify: setup scripts to populate the new config keys for both domains
- Test: `app/backend/tests/test_domain_config_resolution.py`

**Interfaces:**
- Consumes: `domain_configs` rows.
- Produces: config keys `field_entity_map`, `entity_types`, `agent_tools` resolved per domain with **no code branch on `domain_id`**.

- [ ] **Step 1: Write the failing test**

```python
# app/backend/tests/test_domain_config_resolution.py
from domains import resolve_domain_config  # adjust import to actual module

def test_resolution_has_no_supply_chain_default():
    cfg = resolve_domain_config("compliance_due_diligence")
    assert cfg["field_entity_map"]           # comes from config, not code
    assert cfg["entity_types"]
    # a fabricated domain must raise, not silently fall back to supply_chain
    import pytest
    with pytest.raises(KeyError):
        resolve_domain_config("does_not_exist")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/backend && python -m pytest tests/test_domain_config_resolution.py -v`
Expected: FAIL (current code returns a supply_chain default).

- [ ] **Step 3: Extract the hardcoded maps into config**

Read the current `FIELD_ENTITY_MAP` in `notebooks/04_ontology_mapping.py` and the supply_chain tool list in `06_agent.py`; write them into the `supply_chain` `domain_configs` row and author the equivalent for `compliance_due_diligence`. Change code to read from config and raise on unknown domain.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app/backend && python -m pytest tests/test_domain_config_resolution.py -v`
Expected: PASS

- [ ] **Step 5: Domain-reuse gate**

Run the pipeline (Task 3) for both `supply_chain` and `compliance_due_diligence` selecting only the config; both complete with identical code. Record in `baseline-parity.md`.

- [ ] **Step 6: Commit**

```bash
git add notebooks/04_ontology_mapping.py notebooks/06_agent.py app/backend/docintel_routes.py app/backend/tests/test_domain_config_resolution.py pipelines/docintel_spine
git commit -m "refactor(domains): move field_entity_map/entity_types/agent_tools to domain_configs

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 5: Vector Search Delta Sync over silver chunks

**Files:**
- Create: `pipelines/docintel_spine/transformations/vector_index.py` or a setup step (use `notebooks/05_vector_search.reference.py` as the source of truth)
- Modify: `app/backend/search/` (point search at the template index)

**Interfaces:**
- Consumes: silver `prep_search` chunk table + evidence columns.
- Produces: a Delta Sync Vector Search index `jai_docintel.template_vec.{domain}_docs_index` on endpoint `docintel-vs-endpoint`; search returns hits carrying `document_id + page + bbox`.

- [ ] **Step 1: Create the Delta Sync index**

Port the endpoint/index creation from `notebooks/05_vector_search.reference.py`; source table = silver chunks; embed model `databricks-gte-large-en`; sync mode continuous/triggered per existing choice.

- [ ] **Step 2: Verify sync + evidence-carrying hits**

Query the index for a known synthetic phrase; assert the top hit resolves to the correct `document_id` and has non-null `page`/`bbox`.

- [ ] **Step 3: Point backend search at template index; run existing search tests**

Run: `cd app/backend && python -m pytest tests/test_vs_search.py tests/test_search_hybrid.py -v`
Expected: PASS against the template index.

- [ ] **Step 4: Commit**

```bash
git add pipelines/docintel_spine app/backend/search
git commit -m "feat(search): Delta Sync vector index over silver chunks with evidence refs

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 6: Swap ingestion to Lakeflow Connect (synthetic fallback retained)

**Files:**
- Create: `pipelines/docintel_spine/ingest/lakeflow_connect_source.md` (setup + the UC connection/connector config; managed connector is workspace config, not app code)
- Modify: `app/backend/source_routes.py`, `app/backend/mcp_sources.py` (route "real source" to the Lakeflow Connect landing table/Volume; keep `synthetic` connector path)
- Delete (after cutover): `app/mcp-server/connectors/gdrive.py`, `app/mcp-server/oauth.py`, and the clean/re-upload logic — only once the connector lands data end to end.

> Confirm the managed Google Drive / SharePoint connector is **enabled in the Azure workspace** before this task. If it is Preview/blocked, stop and land via the object-storage External Location path instead (spec §2).

**Interfaces:**
- Consumes: a UC connection to the SaaS source.
- Produces: incremental, permission-aware landing into the template landing location that the Task 3 pipeline reads — replacing fetch→upload→clean.

- [ ] **Step 1: Create the UC connection + Lakeflow Connect ingestion**

Follow current Databricks docs for the managed Drive/SharePoint connector; land into the template landing Volume/table. Document exact steps in the `.md` file.

- [ ] **Step 2: End-to-end run from real source**

Ingest a small real folder; confirm files appear in landing and flow through the Task 3 pipeline to search. Verify **no clean/re-upload** step runs and re-running only picks up new files (incremental).

- [ ] **Step 3: Keep synthetic fallback green**

Run: `cd app/backend && python -m pytest tests/test_source_routes.py -v`
Expected: PASS with synthetic connector still available for offline demo.

- [ ] **Step 4: Retire bespoke copy code + commit**

```bash
git rm app/mcp-server/connectors/gdrive.py app/mcp-server/oauth.py
git add app/backend/source_routes.py app/backend/mcp_sources.py pipelines/docintel_spine/ingest
git commit -m "feat(ingest): Lakeflow Connect single-hop landing; retire bespoke OAuth/fetch/clean

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 7: Strip backend to the thin spine

**Files:**
- Delete: `app/backend/skill_routes.py`, `app/backend/workflow_engine/`, `app/backend/skill_runtime/`
- Modify: `app/backend/app.py` (stop mounting removed routers; remove action/escalation/attorney-queue endpoints in `docintel_routes.py`)
- Delete: obsolete tests under `app/backend/tests/skills/` for removed routes
- Keep: `/api/sources`, `/api/search`, `/api/evidence` (add if missing), optional `/api/agent`

**Interfaces:**
- Produces: a backend exposing only Sources, Search, Evidence (+ optional Agent).

- [ ] **Step 1: Add/confirm the evidence endpoint + test**

```python
# app/backend/tests/test_evidence_routes.py
def test_evidence_resolves_field_to_page_and_bbox(client):
    r = client.get("/api/evidence", params={"field_id": "<known>"})
    body = r.json()
    assert body["document_id"] and body["page"] is not None and body["bbox"]
    assert body["source_text"]
```

- [ ] **Step 2: Run it, verify fail, implement `/api/evidence`, verify pass**

Run: `cd app/backend && python -m pytest tests/test_evidence_routes.py -v`

- [ ] **Step 3: Remove skills/workflow/action routers**

Delete the modules and their mounts in `app.py`; remove action/escalation code paths from `docintel_routes.py`. Delete their tests.

- [ ] **Step 4: Run the full backend suite**

Run: `cd app/backend && python -m pytest -q`
Expected: PASS (only spine tests remain).

- [ ] **Step 5: Commit**

```bash
git add -A app/backend
git commit -m "refactor(backend): strip skills/workflow/action; expose thin spine + evidence

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 8: Strip frontend to Sources · Corpus/Search · Evidence (+ optional Agent)

**Files:**
- Delete: `app/frontend/src/app/{copilot,skills,workflows,executions,supply-chain}/`
- Modify: nav/routing to three tabs (+ optional Agent); make the corpus/search page domain-driven via `DomainContext` (no per-domain page)
- Keep/trim: `app/frontend/src/app/{sources,project}/`, evidence drill-down component

**Interfaces:**
- Produces: a 3-tab (+optional) UI reading only the spine APIs; switching domain is a context change, not a new page.

- [ ] **Step 1: Remove the extra tab directories and their nav entries**

- [ ] **Step 2: Generalize the corpus/search page to read `domain_id` from `DomainContext`**

- [ ] **Step 3: Wire the Evidence drill-down to `/api/evidence`**

- [ ] **Step 4: Build the frontend**

Run: `cd app/frontend && npm run build`
Expected: static export succeeds with no references to deleted routes.

- [ ] **Step 5: Commit**

```bash
git add -A app/frontend
git commit -m "refactor(ui): collapse to Sources/Search/Evidence, domain-driven

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 9: Consolidate synthetic-corpus generators + E2E test

**Files:**
- Create: `notebooks/01_synthetic_corpus.py` (parameterized by domain; single generator)
- Delete: `notebooks/01_synthetic_corpus_compliance.py`, `notebooks/01_synthetic_corpus_store_dev.py`
- Create: `app/backend/tests/test_ingestion_e2e.py` (or a notebook-driven check)

**Interfaces:**
- Consumes: a domain's data templates (moved into `domains/<domain>/sample_data` / config).
- Produces: one generator that emits either domain's corpus; an E2E check land→parse→extract→search→evidence.

- [ ] **Step 1: Diff the three generators; extract the shared engine**

Identify the common generation code vs. the per-domain document templates. Move templates into each `domains/<domain>/` folder.

- [ ] **Step 2: Write the parameterized generator; verify both domains produce their corpus**

- [ ] **Step 3: Write the E2E test**

```python
# app/backend/tests/test_ingestion_e2e.py
def test_synthetic_source_to_evidenced_hit():
    # land a synthetic doc → run pipeline (or use a fixture table) →
    # query search → assert a known phrase returns a hit with page+bbox+source_text
    ...
```

- [ ] **Step 4: Run E2E + full suite**

Run: `cd app/backend && python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Delete old generators; final parity check; commit**

```bash
git rm notebooks/01_synthetic_corpus_compliance.py notebooks/01_synthetic_corpus_store_dev.py
git add notebooks/01_synthetic_corpus.py app/backend/tests/test_ingestion_e2e.py domains
git commit -m "refactor(data): single parameterized corpus generator; add ingestion E2E test

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 10: Cutover — retire old notebooks/jobs, update docs

**Files:**
- Delete: `app/unstructured_workflow/` (superseded by the SDP), old `notebooks/02/03/04` after parity, `notebooks/05_vector_search.reference.py`
- Modify: `databricks.yml` (remove old jobs; keep the SDP + a thin process job)
- Modify: `app/CLAUDE.md`, root docs to describe the thin spine

**Interfaces:**
- Produces: a repo whose only ingestion path is the SDP; docs match reality.

- [ ] **Step 1: Confirm all parity + reuse gates passed** (review `baseline-parity.md`).

- [ ] **Step 2: Remove superseded bundle + notebooks; update `databricks.yml`.**

- [ ] **Step 3: Deploy; run the SDP end to end for both domains; confirm green.**

Run: `databricks bundle deploy --profile jai-az-ws && databricks bundle run docintel_spine --profile jai-az-ws`

- [ ] **Step 4: Update CLAUDE.md/docs to the thin-spine architecture.**

- [ ] **Step 5: Commit.**

```bash
git add -A
git commit -m "chore(cutover): retire old ingestion notebooks/bundle; docs to thin spine

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

## Self-Review

**Spec coverage:**
- §2 at-source/no-copy → Task 6 (Lakeflow Connect single hop) + Global Constraints (External Location alt).
- §3 keep/cut/consolidate → Tasks 3 (keep spine), 7/8 (cut layers/UI), 9 (consolidate corpus), 1 (delete worktrees).
- §4.1 one pipeline → Task 3; §4.2 evidence → Tasks 3, 5, 7; §4.3 config model → Tasks 2, 4.
- §5 components → Tasks 3–8. §6 sequencing → Tasks 1–10 (same order). §7 testing gates → Tasks 1, 3, 4, 5, 9.
- §8 risks (connector availability) → Task 6 guard. §10 open questions → surfaced in Global Constraints as documented assumptions.

**Placeholder scan:** Databricks pipeline tasks are written as parity contracts against named source files (not fabricated SQL) — deliberate given a parity-driven refactor; each has a concrete verification query/command. Python/backend tasks carry real test code. No "TBD"/"handle edge cases".

**Type/name consistency:** `domain_configs` keys (`field_entity_map`, `entity_types`, `agent_tools`) used consistently across Tasks 2/4; evidence columns (`page_id`, `bbox`, `source_text`) consistent across Tasks 3/5/7; index name `template_vec.{domain}_docs_index` consistent Tasks 5/globals.

**Known gap to confirm at execution:** exact `domain_configs` column names and the search module layout must be read from the live code in Tasks 2/4/5 before editing (called out in those tasks' Step 1).
