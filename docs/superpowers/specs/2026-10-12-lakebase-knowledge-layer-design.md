# Lakebase Knowledge Layer — Design

**Date:** 2026-10-12 · **Status:** approved design (4/4 sections) · **Builds on:** thin-spine refactor (complete, `docintel-thin-spine` memory)

## Intent

Docs stay at their source. Knowledge and metadata accrue in Lakebase. Users assemble doc-sets per project/research and search + agent reason over any set with evidence and citations.

**Locked decisions (user, 2026-10-12):**
- Sources: SaaS drives + cloud storage + UC Volumes + web/wiki.
- Knowledge store: converge on Lakebase (single repo; spine medallion becomes legacy).
- Sync: scheduled (Databricks job per source) + on-demand.
- Doc-sets: pinned + query-defined.

**Success criteria:** connect N sources → incremental sync → every doc searchable with evidence → doc-set scoping for search and agent → open-at-source for every hit.

## Architecture

Lakebase `app` schema is the single knowledge repo. Thin per-source crawler adapters (one `SourceAdapter` protocol: `list_docs(checkpoint)`, `fetch_text(doc)`) feed the shared `indexer/pipeline.py` (crawl→parse→chunk→embed→diff). Consumers (search, evidence, doc-sets, agent, UI) read Lakebase only.

Adapters: `gdrive_managed` (exists), `sharepoint_managed`, `s3_gcs` (external location), `uc_volume` (one-shot backfill), `web_wiki`.

## Data model (Lakebase `app` schema, additive)

- `external_documents` — gains `source_url` (Drive web_url / volume path / wiki URL). Existing etag/checkpoint incremental crawl preserved.
- `document_chunks` — exists (vector 1024 + tsv, HNSW + GIN).
- `extracted_fields` — NEW: `(doc_id, field_name, field_value, page, bbox, source_text, confidence)`. Judge validation writes `confidence` back.
- `doc_sets` — NEW: `(id, domain_id, name, kind ∈ {pinned, query}, filter_json)`.
- `doc_set_members` — NEW: pinned (doc_set_id, doc_id). Legacy `tags` rows migrate in as pinned sets per project.
- `entities` — NEW in P4 only: `(doc_id, type, name)`.
- `sources`, `index_jobs`, `tags` — exist, reused.

Domain is a column (`external_documents.domain_id`), never a schema.

## Sync execution

- `docintel_sync` Databricks job: one task per source, hourly, serverless; runs `indexer.sync --source-id X` (list vs etag checkpoint → index new/changed → mark deleted).
- On-demand crawl = `jobs.run_now` with source param (replaces request-held inline indexing).
- OBO limitation (accepted): scheduled sync covers app-SP-readable sources (S3/GCS, volumes, drives shared with SP); user-private Drive re-syncs on user visit. UI shows `auth: needs user re-crawl` when stale.

## Doc-sets + consumers

- `/api/doc-sets` CRUD; `query` sets hold `filter_json {source_ids, doc_types, text, labels}` evaluated live as SQL; never materialized.
- `/api/spine/search` v2: Lakebase hybrid RRF only, optional `doc_set_id`, OpenJev rerank unchanged, per-hit `source` + `source_url`.
- `/api/spine/evidence`: Lakebase `extracted_fields` + chunks + `source_url`; judge validation unchanged.
- Agent: `search_documents` tool swaps to Lakebase hybrid search (+ `doc_set_id`); UC toolkit untouched.
- UI: new Doc-Sets tab; Search tab gains doc-set selector + open-at-source; Sources tab gains sync status.

## Phasing

- **P1** Converged store + search: additive DDL; `scripts/backfill_spine_to_lakebase.py` (idempotent, vectors carried over, no re-embed); search/evidence internals swapped (response shape kept); parity gate = 5 probe questions, ≥80% top-3 overlap; spine tables kept for rollback.
- **P2** Doc-set assembly + agent grounding.
- **P3** `docintel_sync` scheduler + on-demand via run_now + SharePoint + S3/GCS adapters.
- **P4** Extraction on crawled docs (ai_extract → Lakebase), web/wiki adapter, PDF-at-source via ai_parse_document on fetched bytes, entities if signal proves.

Rollback: P1 = revert swap commit; P2–P4 additive deletes.

## Non-goals

Entity-graph UI; event-driven sync; multi-workspace; source ACL/retention mirroring (v1 = workspace-level access).

## Testing

Adapter contract tests (fake MCP transport); backfill diff test; doc-set resolve SQL tests; search parity test; live smoke checklist per phase.
