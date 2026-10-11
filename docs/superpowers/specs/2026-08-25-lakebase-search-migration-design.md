# Design Spike: Lakebase Search for DocIntelligence retrieval

**Date:** 2026-08-25
**Status:** Spike — for review, no code changes proposed yet
**Author:** (drafted with Claude Code)
**Feature under evaluation:** [Lakebase Search](https://learn.microsoft.com/en-us/azure/databricks/oltp/projects/lakebase-search) (Beta)

---

## TL;DR

Lakebase Search adds hybrid vector + keyword search *inside* Lakebase Postgres via two
extensions (`lakebase_vector` → `lakebase_ann` ANN index; `lakebase_text` → `lakebase_bm25`
BM25 index), queried with plain SQL and fused with Reciprocal Rank Fusion (RRF).

**At our scale (<50k chunks/domain), the ANN index is not the reason to adopt this.** The
honest driver is **architectural consolidation** — retrieval and project-scoping would live
in the *same* Postgres we already run — plus a real **BM25 upgrade** over our current
`ILIKE` substring keyword search. Speed/scale is a secondary, longer-horizon benefit.

**Recommendation:** worth doing as a *deliberate consolidation*, but gated. The blocker isn't
technical fit — it's (a) we have **no materialized embeddings today** and would need a new
embedding step, and (b) enabling the feature is **irreversible, Beta, restarts all project
computes, and needs an account-rep request**. Don't flip that switch until the embedding
pipeline exists and the consolidation payoff is judged worth the gate.

---

## Current state (what the code actually does)

Retrieval and operational data live in **two different systems**:

| Concern | System | Where |
|---|---|---|
| Semantic retrieval | Unity Catalog Delta (SQL warehouse) | `document_chunks` table, queried by `_vs_search` |
| Keyword search | Unity Catalog Delta (SQL warehouse) | `parsed_documents.raw_text`, `ILIKE` substring |
| Project scoping | **Lakebase Postgres** | `document_project_tags` |
| Operational data | **Lakebase Postgres** | `projects`, `workflow_runs`, `skill_executions` |

### Semantic retrieval — `_vs_search` (`app/backend/docintel_routes.py:325`)

```sql
SELECT chunk_id, doc_id, doc_type, chunk_to_retrieve
FROM (
    SELECT chunk_id, doc_id, doc_type, chunk_to_retrieve,
           ai_similarity(chunk_to_retrieve, '<query>') AS _score
    FROM {catalog}.{schema}.document_chunks
    {optional WHERE doc_type = ...}
) t
ORDER BY _score DESC
LIMIT k
```

Characteristics:
- **No index.** Every query is an O(N) scan that calls `ai_similarity` (a model call) per row.
- 30s timeout; returns `[]` on any failure (best-effort by design).
- No precomputed embeddings — `document_chunks.chunk_to_embed` exists but nothing populates a
  vector column; similarity is computed on the fly.

### Keyword search — `search-docs` mode="keyword" (`docintel_routes.py:~1533`)

```sql
SELECT doc_id, filename, doc_type, LEFT(raw_text, 300) AS snippet
FROM {catalog}.{schema}.parsed_documents
WHERE LOWER(raw_text) LIKE '%q%' OR LOWER(filename) LIKE '%q%'
ORDER BY processed_ts DESC LIMIT k
```

Plain substring match, no relevance ranking (ordered by recency).

### Project-scoped retrieval today

`document_project_tags` (Lakebase) maps `doc_id → project_id`. A project-scoped query means:
retrieve from Delta via `_vs_search`, then reconcile against the Lakebase tag table in app
code. **Cross-system coordination on every scoped query.**

---

## What Lakebase Search offers (mapped to our code)

| Capability | Fixes / replaces | Value at our scale |
|---|---|---|
| `lakebase_bm25` full-text | `ILIKE` substring in `search-docs` | **High** — real relevance for names, codes, parcel IDs |
| Co-located retrieval + scoping | cross-system reconcile in `_vs_search` call-sites | **High** — scoped hybrid search becomes one SQL join to `document_project_tags` |
| `lakebase_ann` vector index | `ai_similarity` full scan at query time | **Medium/low now** — removes per-query model cost & 30s timeouts, but <50k chunks doesn't *need* ANN. Payoff grows with corpus |
| Hybrid (RRF) in one query | binary "semantic OR keyword fallback" | **Medium** — proper fused ranking instead of all-or-nothing |
| Survives scale-to-zero, no warmup | n/a | Nice-to-have |

### Notable alignment

`document_chunks` **already has Change Data Feed enabled** — the prerequisite for
[synced tables](https://learn.microsoft.com/en-us/azure/databricks/oltp/projects/sync-tables).
The documented pattern is exactly: sync a UC table into Lakebase, map columns to
`vector(n)` / `tsvector` during sync, then build `lakebase_ann` / `lakebase_bm25`. So the
ingestion side is closer than expected.

---

## The two real costs

### 1. We have no embeddings (main new work)

`lakebase_vector` does **not** embed — you bring your own vectors. Today nothing materializes
an embedding; `ai_similarity` does it implicitly at query time. To use `lakebase_ann` we must:

- Pick an embedding model (Databricks Model Serving, e.g. `ai_query` over an embedding
  endpoint) and a fixed dimension `n` (commonly 384–1536).
- Materialize a `VECTOR(n)` column on the synced chunks — both for the corpus and at
  **query time** (the user query must be embedded with the *same* model before the
  `<=>` lookup).

> **Note:** BM25 keyword search needs **no embeddings** — only a `tsvector` column. So the
> keyword-relevance upgrade + consolidation can ship *without* the embedding pipeline. This
> matters for phasing (see below).

### 2. Enabling is a one-way, gated door

- **Irreversible** — cannot be turned off once enabled.
- **Restarts all project computes**, dropping active connections (our Lakebase app pool).
- **Beta** — requires an account-rep request for access.
- Requires an **Autoscaling** Lakebase project on **Postgres 16+**. *(Unverified — see open
  questions; we connect via `projects/docintel/branches/production/endpoints/primary`.)*

---

## Proposed target design

Replace `_vs_search`'s cross-system retrieval with a single Lakebase hybrid query joined to
the scoping table. Sketch (post-embedding-pipeline):

```sql
-- chunks synced into Lakebase: app.chunks(chunk_id, doc_id, doc_type,
--   chunk_to_retrieve, embedding VECTOR(n), body_tsv TSVECTOR)
WITH scoped AS (
  SELECT c.chunk_id, c.doc_id, c.doc_type, c.chunk_to_retrieve, c.embedding, c.body_tsv
  FROM app.chunks c
  JOIN app.document_project_tags t
    ON t.domain_id = :domain AND t.doc_id = c.doc_id AND t.project_id = :project
),
vec AS (
  SELECT chunk_id, RANK() OVER (ORDER BY embedding <=> :qvec) AS rank
  FROM scoped ORDER BY embedding <=> :qvec LIMIT 40
),
kw AS (
  SELECT chunk_id,
         RANK() OVER (ORDER BY body_tsv <@> to_bm25query(to_tsvector('english', :q), 'chunks_body_bm25')) AS rank
  FROM scoped LIMIT 40
)
SELECT s.chunk_id, s.doc_id, s.doc_type, s.chunk_to_retrieve,
       COALESCE(1.0/(60+vec.rank),0) + COALESCE(1.0/(60+kw.rank),0) AS rrf
FROM scoped s
LEFT JOIN vec ON vec.chunk_id = s.chunk_id
LEFT JOIN kw  ON kw.chunk_id  = s.chunk_id
WHERE vec.chunk_id IS NOT NULL OR kw.chunk_id IS NOT NULL
ORDER BY rrf DESC LIMIT :k;
```

`_vs_search` keeps its `[chunk_id, doc_id, doc_type, chunk_to_retrieve]` return shape, so
every call-site (`agent-query`, `copilot-query`, `search-docs`) stays drop-in.

`:qvec` = the user query embedded via the same Model Serving endpoint used to populate the
corpus. Project scoping moves *inside* the query — no app-side reconcile.

---

## Phased plan (each phase independently shippable)

**Phase 0 — Prerequisites & gate (no irreversible action)**
Verify Autoscaling + Postgres 16; confirm/request Beta access; decide the embedding model +
dimension. → *verify: prereqs documented; go/no-go decision recorded.*

**Phase 1 — Sync `document_chunks` → Lakebase (keyword-only, no embeddings)**
Synced table with a generated `tsvector` column; build `lakebase_bm25`. Replace `search-docs`
`ILIKE` with BM25. → *verify: BM25 results beat substring on a fixed query set; keyword
search no longer touches the SQL warehouse.*

**Phase 2 — Consolidate scoping**
Move project-scoped retrieval into the Lakebase query (join to `document_project_tags`);
remove app-side cross-system reconcile. → *verify: scoped results match the old two-step path
on a sample of projects.*

**Phase 3 — Embeddings + vector + hybrid**
Add Model Serving embedding step (corpus + query-time), materialize `VECTOR(n)`, build
`lakebase_ann`, add the RRF hybrid query behind `_vs_search`. → *verify: hybrid recall ≥
current `ai_similarity` on a labeled query set; p95 latency improved; `ai_similarity`
query-time path removed.*

Phases 1–2 deliver the "consolidation + BM25" value **without** enabling the vector side or
building the embedding pipeline. Phase 3 is the bigger lift and the one that needs the
irreversible enable.

> Caveat: Phases 1–2 still require *enabling Lakebase Search* to install `lakebase_text`
> (the irreversible step gates BM25 too). So the true gate is Phase 0→1. If we want to defer
> the irreversible enable entirely, Phase 1 is blocked and only a `pg_trgm`/native
> `tsvector` GIN approach (no Lakebase Search) would improve keyword search reversibly — a
> possible fallback if the Beta gate is a problem.

---

## Open questions (need answers before Phase 0 exits)

1. **Is `docintel` an Autoscaling Lakebase project on Postgres 16+?** (enable prereq)
2. Do we have — or can we get — Beta access from our account rep?
3. Embedding model + dimension: which Model Serving endpoint, what `n`, what per-query
   embedding latency/cost does that add to `agent-query`/`copilot-query`?
4. Is the irreversible-enable acceptable on the *production* branch, or do we prototype on a
   dev branch first?
5. Sync freshness: how quickly must new documents become searchable (synced-table lag vs the
   current query-time freshness)?

---

## Bottom line

Good fit, real simplification, but **not** a quick win and **not** primarily a speed play at
our current scale. Sequence it: prove the consolidation + BM25 value in Phases 1–2, then
decide whether the embedding pipeline (Phase 3) earns the ANN index as the corpus grows.
