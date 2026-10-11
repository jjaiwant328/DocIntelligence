# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DocIntelligence is a thin, config-driven document-intelligence spine on Databricks:
**ingest → parse → classify/chunk → extract → search → evidence**. One Lakeflow
Declarative Pipeline does all document processing; domain semantics live in
`jai_docintel.platform.domain_configs` (no per-domain code branches). The app is
a FastAPI backend + Next.js static-export frontend deployed as a Databricks App.

## Architecture

### Pipeline (`pipelines/docintel_spine/`, separate bundle `docintel_spine`)
- One serverless SDP per domain (`docintel_spine` → schema `template`,
  `docintel_spine_cdd` → schema `template_cdd`, catalog `jai_docintel`).
- `transformations/bronze_parse.py`: Auto Loader + `ai_parse_document` in place
  (no volume copy) from `source_volume_path` (pipeline configuration).
- `transformations/silver_classify_chunk.py`: `ai_classify` (labels from
  `domain_configs`) + `ai_prep_search` chunks with a content-split fallback.
- `transformations/gold_extract.py`: `ai_extract` schemas from `domain_configs`
  → `gold_documents`, `gold_extracted_fields` (evidence: page/bbox/source_text).
- `transformations/gold_search.py`: batch-embedded `gold_chunks`
  (`databricks-gte-large-en`); retrieval is endpoint-free
  (`vector_cosine_similarity`) — there is NO Vector Search endpoint.
- Deploy/run: `cd pipelines/docintel_spine && databricks bundle deploy -p jai-az-ws
  && databricks bundle run docintel_spine -p jai-az-ws` (and `_cdd`).
- Ingestion swap to Lakeflow Connect: see `pipelines/docintel_spine/ingest/lakeflow_connect_source.md`.

### Backend (`app/backend/`, FastAPI)
- `spine_routes.py` — the thin-spine API: `GET /api/spine/domains`,
  `POST /api/spine/search` (cosine over `gold_chunks` + OpenJev judge rerank),
  `GET /api/spine/evidence` (`?validate=true` adds judge field-confidence +
  doc-type verification).
- `judge.py` — System One client for the OpenJev model service
  (`system.ai.openjev-qwen35-4b` via `/ai-gateway/typesafe/v1/systemone`):
  noul/choice/score questions, never prose. Fail-open everywhere.
- Kept legacy routers: `docintel_routes.py` (`/api/docintel/*` — agent_query,
  document library, domain schema setup), `platform_routes.py` (domain CRUD +
  blueprint provisioning), `source_routes.py` + `connector_routes.py`
  (Lakebase connector-first sources), `mcp_server.py` (`/mcp/`).
- Removed (thin-spine T7): skills/workflow engine/runtime, action-log,
  action-master, attorney queue, escalation rules, CDD four-agent path.
- Tests: `cd app/backend && <repo>/.venv-test/bin/python -m pytest -q`.

### Frontend (`app/frontend/`, Next.js static export)
- Three tabs only: **Sources** (`app/sources/page.tsx`), **Search & Evidence**
  (`components/SpineSearchPanel.tsx` — judge rerank badges, evidence drill-down,
  "Validate with judge"), **Agent** (`app/agent/page.tsx`).
- `app/page.tsx`: domain-card landing (from `/api/spine/domains`) + tab shell
  with `DomainContext`. Build: `cd app/frontend && npm run build`.

### Synthetic corpus (`domains/<domain>/sample_data.py` + `notebooks/01_synthetic_corpus.py`)
- One parameterized generator; content modules are verbatim per domain.
- Run: notebook widget `domain_id`, or `DOMAIN_ID=x DOCINTEL_CORPUS_OUT=/tmp/out python3 notebooks/01_synthetic_corpus.py`.

## Deploy

```bash
cd app && ./deploy.sh   # profile jai-az-ws, app docintel-supply-chain
```

App URL: https://docintel-supply-chain-4101016551133680.0.azure.databricksapps.com

## Gotchas

- New UC schemas need `USE SCHEMA` + `SELECT` granted to the app SP
  `00ec2ab7-2445-4bc8-b68d-25e463b5bbe3` or `/api/spine/*` 500s.
- `ai_decide` (SQL-side judge) is Beta; not enabled in this workspace — the
  judge runs through the gateway route instead.
- `app/.git` is a leftover nested clone of the original ai-parse template repo.
  Run git from the repo root, not from `app/`.
- The old notebook pipeline (01–07) and `app/unstructured_workflow/` were
  retired in the T10 cutover; `notebooks/06_agent.py` (UC function registration)
  and `00*_setup.py` remain in use.
