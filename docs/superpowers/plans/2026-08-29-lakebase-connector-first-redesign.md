# Connector-First Lakebase Redesign — Implementation Plan (P1–P5 vertical slice)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild DocIntelligence as a connector-first app whose hot data + search live entirely in Lakebase (pgvector + tsvector hybrid), demoed against Google Drive with no persistent Volume copy, and keep the existing skills/workflow engine runnable over the new Lakebase-backed documents.

**Architecture:** New Lakebase tables (`sources`, `external_documents`, `document_chunks`, `index_jobs`, `use_cases`) via the existing `db/` DDL + repository pattern. A new `indexer/` service crawls source metadata (no copy), then on demand fetches→parses→chunks→embeds changed files into Lakebase. A `search/` module runs one hybrid SQL query behind a `SearchBackend` interface. FastAPI routes + a lean two-panel Next.js workspace (Inventory + Search) drive it; KG/Compliance-Map/Action-Center tabs are unwired.

**Tech Stack:** Python 3 / FastAPI, psycopg 3 + psycopg_pool, pgvector 0.8.0 on PostgreSQL 17 (Lakebase), Databricks SDK (OAuth token + embedding endpoint `databricks-gte-large-en`), MCP over Streamable HTTP (`mcp<1.9`), Next.js 15 / TypeScript / Tailwind.

**Spec:** `docs/superpowers/specs/2026-08-29-lakebase-connector-first-redesign-design.md`

## Global Constraints

- **P0 resolved:** pgvector 0.8.0 + HNSW + tsvector confirmed on the live Lakebase (PG 17.11). Use pgvector; no VS fallback.
- **All backend code lives under `app/backend/`** — `deploy.sh` only packages that dir.
- **Tests run in `.venv-test`:** `cd app/backend && ../../.venv-test/bin/python -m pytest tests/<f>.py -v` (repo Python is 3.14 / PEP668; do not `pip install` into system Python). Existing suite is pytest-style files under `app/backend/tests/`.
- **No `from __future__ import annotations` in any FastMCP tool module** — FastMCP <1.9 inspects real annotations (see `mcp_server.py` header).
- **Lakebase writes are single-statement, autocommit=True** (pool rolls back on return). `ensure_schema` is per-statement try/except ignoring `already exists`/`must be owner`/`duplicate`.
- **Never put secrets in code/logs/prompts.** Sources store a `credential_ref`, never the secret.
- **Embedding dim = 1024** (`databricks-gte-large-en`). Make it configurable via `EMBED_MODEL` / `EMBED_DIM` env, default to these.
- **Metadata-first / no persistent copy is the default path.** The legacy `/sources/import` (copy-to-Volume) stays but is not default; existing Volume projects must keep working during cutover.
- **Commit after each task.** End commit messages with `Co-authored-by: Isaac <no-reply@databricks.com>`.

---

## File Structure

**Create (backend):**
- `app/backend/db/repositories/sources_repo.py` — CRUD for `sources`.
- `app/backend/db/repositories/external_docs_repo.py` — CRUD/upsert + status transitions for `external_documents`.
- `app/backend/db/repositories/chunks_repo.py` — upsert/delete chunks, hybrid search query.
- `app/backend/db/repositories/index_jobs_repo.py` — job lifecycle + counts.
- `app/backend/db/repositories/use_cases_repo.py` — use-case config CRUD (migrated domain_configs).
- `app/backend/indexer/__init__.py`, `crawl.py`, `diff.py`, `parse.py`, `chunk.py`, `embed.py`, `pipeline.py` — the indexing service.
- `app/backend/search/__init__.py`, `backend.py` (`SearchBackend` protocol), `lakebase_search.py`.
- `app/backend/source_routes.py` — the new `/api/sources`, `/api/inventory`, `/api/index-jobs`, `/api/search` routes.
- `app/backend/scripts/migrate_domain_configs_to_lakebase.py` — one-time config migration.

**Modify (backend):**
- `app/backend/db/schema.py` — add DDL for the 5 tables + pgvector extension + indexes.
- `app/backend/mcp_sources.py` — add metadata tools (`list_children`, `get_file_metadata`, `get_changes`, `check_access`, `get_source_url`).
- `app/backend/db/operational.py` — expose new repos behind the Lakebase-or-raise facade.
- `app/backend/app.py` — register `source_routes.router`.
- `app/backend/skill_routes.py` / `workflow_engine/engine.py` — resolve the workflow document set from Lakebase `external_documents`/`document_chunks`.

**Create/Modify (frontend):**
- `app/frontend/src/app/sources/page.tsx` — Sources connect page (evolve `SourcePicker.tsx` + landing).
- `app/frontend/src/app/project/page.tsx` — two-panel workspace (Inventory + Search).
- `app/frontend/src/components/InventoryPanel.tsx`, `SearchPanel.tsx`, `WhyThisResult.tsx`.
- Shell nav: unwire Knowledge Graph / Compliance Map / Action Center.

**Test:** `app/backend/tests/test_sources_repo.py`, `test_external_docs_repo.py`, `test_chunks_search.py`, `test_index_jobs_repo.py`, `test_indexer_diff.py`, `test_indexer_pipeline.py`, `test_search_hybrid.py`, `test_source_routes.py`, `test_use_cases_repo.py`, plus a live `test_pgvector_integration.py` (opt-in, needs LB env).

---

## PHASE 1 — Lakebase schema, repositories, config migration

### Task 1: pgvector-enabled schema DDL

**Files:**
- Modify: `app/backend/db/schema.py`
- Test: `app/backend/tests/test_schema_ddl.py`

**Interfaces:**
- Produces: `DDL: list[str]` extended with `CREATE EXTENSION IF NOT EXISTS vector`, tables `sources`, `external_documents`, `document_chunks` (with `embedding vector(1024)`, `tsv tsvector`), `index_jobs`, `use_cases`, and their indexes (HNSW on embedding, GIN on tsv). `ensure_schema(conn)` unchanged in contract.

- [ ] **Step 1: Write the failing test** — assert the DDL list contains the new tables and pgvector, and that `ensure_schema` runs each statement.

```python
# app/backend/tests/test_schema_ddl.py
import db.schema as schema

def test_ddl_includes_pgvector_and_new_tables():
    joined = "\n".join(schema.DDL).lower()
    assert "create extension if not exists vector" in joined
    for t in ("sources", "external_documents", "document_chunks", "index_jobs", "use_cases"):
        assert f"create table if not exists {t}" in joined
    assert "vector(1024)" in joined
    assert "tsvector" in joined
    assert "using hnsw" in joined
    assert "using gin" in joined

class _FakeConn:
    def __init__(self): self.ran = []
    def execute(self, sql): self.ran.append(sql)

def test_ensure_schema_runs_all_statements():
    c = _FakeConn(); schema.ensure_schema(c)
    assert len(c.ran) == len(schema.DDL)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/backend && ../../.venv-test/bin/python -m pytest tests/test_schema_ddl.py -v`
Expected: FAIL (`vector(1024)` not found).

- [ ] **Step 3: Implement** — append to `DDL` in `db/schema.py`, before the index statements add the extension first:

```python
# db/schema.py — prepend the extension, then append tables (order: referenced first)
DDL = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    # ... existing projects / document_project_tags / workflow_runs / skill_executions ...
    """
    CREATE TABLE IF NOT EXISTS sources (
        source_id      TEXT PRIMARY KEY,
        provider       TEXT NOT NULL,
        display_name   TEXT NOT NULL DEFAULT '',
        auth_mode      TEXT NOT NULL DEFAULT 'service_principal',
        credential_ref TEXT NOT NULL DEFAULT '',
        site           TEXT NOT NULL DEFAULT '',
        status         TEXT NOT NULL DEFAULT 'disconnected',
        mode           TEXT NOT NULL DEFAULT 'live',
        last_crawl_at  TIMESTAMPTZ,
        last_error     TEXT NOT NULL DEFAULT '',
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS external_documents (
        external_document_id TEXT PRIMARY KEY,
        source_id      TEXT NOT NULL,
        domain_id      TEXT NOT NULL,
        project_id     TEXT NOT NULL DEFAULT '',
        parent_folder_id TEXT NOT NULL DEFAULT '',
        path           TEXT NOT NULL DEFAULT '',
        name           TEXT NOT NULL DEFAULT '',
        mime_type      TEXT NOT NULL DEFAULT '',
        size_bytes     BIGINT NOT NULL DEFAULT 0,
        web_url        TEXT NOT NULL DEFAULT '',
        etag           TEXT NOT NULL DEFAULT '',
        content_hash   TEXT NOT NULL DEFAULT '',
        owner          TEXT NOT NULL DEFAULT '',
        source_created_at  TIMESTAMPTZ,
        source_modified_at TIMESTAMPTZ,
        status         TEXT NOT NULL DEFAULT 'discovered',
        included       BOOLEAN NOT NULL DEFAULT true,
        index_version  INT NOT NULL DEFAULT 0,
        embedding_model TEXT NOT NULL DEFAULT '',
        last_indexed_etag TEXT NOT NULL DEFAULT '',
        chunk_count    INT NOT NULL DEFAULT 0,
        last_error     TEXT NOT NULL DEFAULT '',
        updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_chunks (
        chunk_id       TEXT PRIMARY KEY,
        external_document_id TEXT NOT NULL,
        domain_id      TEXT NOT NULL,
        project_id     TEXT NOT NULL DEFAULT '',
        ordinal        INT NOT NULL DEFAULT 0,
        location       TEXT NOT NULL DEFAULT '',
        snippet        TEXT NOT NULL DEFAULT '',
        embedding      vector(1024),
        tsv            tsvector,
        source_version TEXT NOT NULL DEFAULT '',
        index_version  INT NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS index_jobs (
        job_id        TEXT PRIMARY KEY,
        domain_id     TEXT NOT NULL,
        project_id    TEXT NOT NULL DEFAULT '',
        scope         TEXT NOT NULL DEFAULT 'project',
        scope_ref     TEXT NOT NULL DEFAULT '',
        requested_by  TEXT NOT NULL DEFAULT '',
        status        TEXT NOT NULL DEFAULT 'queued',
        discovered    INT NOT NULL DEFAULT 0,
        embedded      INT NOT NULL DEFAULT 0,
        skipped       INT NOT NULL DEFAULT 0,
        deleted       INT NOT NULL DEFAULT 0,
        failed        INT NOT NULL DEFAULT 0,
        started_at    TIMESTAMPTZ,
        finished_at   TIMESTAMPTZ,
        error_summary TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS use_cases (
        use_case_id   TEXT PRIMARY KEY,
        name          TEXT NOT NULL DEFAULT '',
        status        TEXT NOT NULL DEFAULT 'active',
        classification_labels JSONB NOT NULL DEFAULT '{}'::jsonb,
        extraction_schemas    JSONB NOT NULL DEFAULT '{}'::jsonb,
        entity_types          JSONB NOT NULL DEFAULT '[]'::jsonb,
        agent_system_prompt   TEXT NOT NULL DEFAULT '',
        suggested_questions   JSONB NOT NULL DEFAULT '[]'::jsonb,
        enabled_skills        JSONB NOT NULL DEFAULT '[]'::jsonb,
        reconciliation        JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_extdocs_scope ON external_documents (domain_id, project_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_scope ON document_chunks (domain_id, project_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks (external_document_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_hnsw ON document_chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON document_chunks USING gin (tsv)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_scope ON index_jobs (domain_id, project_id, status)",
]
```

- [ ] **Step 4: Run test to verify it passes** — `pytest tests/test_schema_ddl.py -v` → PASS.

- [ ] **Step 5: Commit** — `git add app/backend/db/schema.py app/backend/tests/test_schema_ddl.py && git commit -m "feat(db): pgvector schema for connector-first catalog"`

---

### Task 2: `sources_repo` + `use_cases_repo` (CRUD)

**Files:**
- Create: `app/backend/db/repositories/sources_repo.py`, `app/backend/db/repositories/use_cases_repo.py`
- Test: `app/backend/tests/test_sources_repo.py`, `app/backend/tests/test_use_cases_repo.py`

**Interfaces:**
- Consumes: `db.lakebase.connection()` context manager (yields autocommit psycopg conn with search_path=app).
- Produces:
  - `sources_repo.list_sources(conn) -> list[dict]`, `upsert_source(conn, source_id, provider, display_name, auth_mode, credential_ref, site, mode) -> dict`, `set_status(conn, source_id, status, last_error="") -> None`, `get_source(conn, source_id) -> dict|None`.
  - `use_cases_repo.list_use_cases(conn) -> list[dict]`, `get_use_case(conn, use_case_id) -> dict|None`, `upsert_use_case(conn, use_case_id, **fields) -> dict`.

- [ ] **Step 1: Write failing tests** using an in-memory fake conn that records SQL + returns canned rows (mirror `tests/test_lakebase.py` style — no live DB).

```python
# tests/test_sources_repo.py
from db.repositories import sources_repo

class FakeCur:
    def __init__(self, rows): self._rows = rows; self.sql=[]; self.params=[]
    def execute(self, sql, params=None): self.sql.append(sql); self.params.append(params)
    def fetchall(self): return self._rows
    def fetchone(self): return self._rows[0] if self._rows else None
    @property
    def description(self): return [("source_id",),("provider",),("display_name",),("auth_mode",),("credential_ref",),("site",),("status",),("mode",),("last_crawl_at",),("last_error",),("created_at",)]

class FakeConn:
    def __init__(self, rows): self.cur = FakeCur(rows)
    def cursor(self): return self.cur
    def execute(self, sql, params=None): return self.cur.execute(sql, params)

def test_upsert_source_writes_no_secret_value():
    c = FakeConn([("gdrive","gdrive","Google Drive","service_principal","keeper://ref","","connected","live",None,"",None)])
    row = sources_repo.upsert_source(c, "gdrive", "gdrive", "Google Drive",
                                     "service_principal", "keeper://ref", "", "live")
    assert row["source_id"] == "gdrive"
    # the credential_ref is a reference, never a secret literal
    assert "keeper://" in (c.cur.params[0] or ())[4] if c.cur.params[0] else True
```

- [ ] **Step 2: Run to verify fail** — `pytest tests/test_sources_repo.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement** — small psycopg repos. Use a `_rows_to_dicts(cur)` helper (copy the idiom already used in `runs_repo.py`). Example:

```python
# db/repositories/sources_repo.py
def _dicts(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

def list_sources(conn):
    cur = conn.cursor()
    cur.execute("SELECT * FROM sources ORDER BY created_at")
    return _dicts(cur)

def get_source(conn, source_id):
    cur = conn.cursor()
    cur.execute("SELECT * FROM sources WHERE source_id=%s", (source_id,))
    rows = _dicts(cur)
    return rows[0] if rows else None

def upsert_source(conn, source_id, provider, display_name, auth_mode,
                  credential_ref, site, mode):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sources (source_id, provider, display_name, auth_mode,
                             credential_ref, site, mode)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (source_id) DO UPDATE SET
            provider=EXCLUDED.provider, display_name=EXCLUDED.display_name,
            auth_mode=EXCLUDED.auth_mode, credential_ref=EXCLUDED.credential_ref,
            site=EXCLUDED.site, mode=EXCLUDED.mode
    """, (source_id, provider, display_name, auth_mode, credential_ref, site, mode))
    return get_source(conn, source_id)

def set_status(conn, source_id, status, last_error=""):
    conn.execute("UPDATE sources SET status=%s, last_error=%s WHERE source_id=%s",
                 (status, last_error, source_id))
```

`use_cases_repo.py` follows the same shape; `upsert_use_case` JSON-encodes dict/list fields with `json.dumps` and `%s::jsonb`.

- [ ] **Step 4: Run to verify pass** — both test files PASS.
- [ ] **Step 5: Commit** — `feat(db): sources + use_cases repositories`

---

### Task 3: `external_docs_repo` (upsert + status transitions)

**Files:**
- Create: `app/backend/db/repositories/external_docs_repo.py`
- Test: `app/backend/tests/test_external_docs_repo.py`

**Interfaces:**
- Produces:
  - `stable_doc_id(provider, site, drive, item_id) -> str` (sha1 hex of the joined tuple).
  - `upsert_metadata(conn, doc: dict) -> None` (insert-or-update by `external_document_id`; sets `status='discovered'` on new, preserves `status` on existing unless caller overrides).
  - `list_for_project(conn, domain_id, project_id, statuses=None) -> list[dict]`.
  - `set_status(conn, external_document_id, status, last_error="") -> None`.
  - `mark_indexed(conn, external_document_id, index_version, embedding_model, etag, chunk_count) -> None`.
  - `ids_missing_from(conn, domain_id, project_id, seen_ids: set[str]) -> list[str]` (docs in DB not seen this crawl → candidates for `deleted`).

- [ ] **Step 1: Write failing test** — `stable_doc_id` is deterministic + order-sensitive; `ids_missing_from` returns the set difference.

```python
# tests/test_external_docs_repo.py
from db.repositories import external_docs_repo as r

def test_stable_doc_id_is_deterministic_and_distinct():
    a = r.stable_doc_id("gdrive","","d1","item1")
    b = r.stable_doc_id("gdrive","","d1","item1")
    c = r.stable_doc_id("gdrive","","d1","item2")
    assert a == b and a != c and len(a) == 40
```

- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** — `stable_doc_id` = `hashlib.sha1("|".join(parts).encode()).hexdigest()`; the rest are psycopg upserts using `ON CONFLICT (external_document_id)`.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat(db): external_documents repository + stable ids`

---

### Task 4: `chunks_repo` (upsert/delete + hybrid search SQL)

**Files:**
- Create: `app/backend/db/repositories/chunks_repo.py`
- Test: `app/backend/tests/test_chunks_search.py`

**Interfaces:**
- Produces:
  - `replace_chunks(conn, external_document_id, chunks: list[dict]) -> int` (delete existing for the doc, insert new; each chunk dict = `{chunk_id, ordinal, location, snippet, embedding: list[float], domain_id, project_id, source_version, index_version}`; sets `tsv = to_tsvector('english', snippet)`).
  - `delete_for_doc(conn, external_document_id) -> int`.
  - `hybrid_search(conn, domain_id, project_id, query_embedding: list[float], query_text: str, k: int = 10, folder: str = "", types: list[str] | None = None) -> list[dict]` — RRF-fused vector + FTS, joined to `external_documents` for metadata; returns `[{chunk_id, external_document_id, name, path, web_url, mime_type, status, ordinal, location, snippet, score}]`.

- [ ] **Step 1: Write failing test** — assert `hybrid_search` builds SQL that references both `embedding <=>` and `ts_rank`/`plainto_tsquery`, applies the project filter, and passes the vector param formatted as pgvector literal. (Use the FakeConn/FakeCur; assert on captured SQL + params.)

```python
def test_hybrid_search_uses_vector_and_fts_and_project_filter():
    c = FakeConn(rows=[])
    chunks_repo.hybrid_search(c, "supplier_performance", "p1",
                              [0.1]*1024, "late delivery", k=5)
    sql = " ".join(c.cur.sql).lower()
    assert "<=>" in sql and "plainto_tsquery" in sql
    assert "project_id" in sql
```

- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** the RRF hybrid query:

```python
def _vec_literal(v): return "[" + ",".join(f"{x:.6f}" for x in v) + "]"

def hybrid_search(conn, domain_id, project_id, query_embedding, query_text,
                  k=10, folder="", types=None):
    cur = conn.cursor()
    sql = """
    WITH vec AS (
        SELECT chunk_id, external_document_id,
               ROW_NUMBER() OVER (ORDER BY embedding <=> %s::vector) AS rnk
        FROM document_chunks
        WHERE domain_id=%s AND project_id=%s AND embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector LIMIT 50
    ),
    kw AS (
        SELECT chunk_id, external_document_id,
               ROW_NUMBER() OVER (ORDER BY ts_rank(tsv, plainto_tsquery('english', %s)) DESC) AS rnk
        FROM document_chunks
        WHERE domain_id=%s AND project_id=%s
          AND tsv @@ plainto_tsquery('english', %s)
        LIMIT 50
    ),
    fused AS (
        SELECT chunk_id, external_document_id,
               SUM(1.0/(60+rnk)) AS score
        FROM (SELECT * FROM vec UNION ALL SELECT * FROM kw) u
        GROUP BY chunk_id, external_document_id
    )
    SELECT c.chunk_id, c.external_document_id, d.name, d.path, d.web_url,
           d.mime_type, d.status, c.ordinal, c.location, c.snippet, f.score
    FROM fused f
    JOIN document_chunks c ON c.chunk_id=f.chunk_id
    JOIN external_documents d ON d.external_document_id=f.external_document_id
    ORDER BY f.score DESC LIMIT %s
    """
    ql = _vec_literal(query_embedding)
    cur.execute(sql, (ql, domain_id, project_id, ql,
                      query_text, domain_id, project_id, query_text, k))
    return _dicts(cur)
```

- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat(db): chunk upsert + RRF hybrid search`

---

### Task 5: `index_jobs_repo` + wire all repos into `operational.py`

**Files:**
- Create: `app/backend/db/repositories/index_jobs_repo.py`
- Modify: `app/backend/db/operational.py`
- Test: `app/backend/tests/test_index_jobs_repo.py`

**Interfaces:**
- Produces: `index_jobs_repo.create_job(conn, job_id, domain_id, project_id, scope, scope_ref, requested_by) -> dict`, `start(conn, job_id)`, `bump(conn, job_id, **counts)`, `finish(conn, job_id, status, error_summary="")`, `get_job(conn, job_id)`, `list_jobs(conn, domain_id, project_id)`.
- `operational.py` gains thin wrappers that call `with lakebase.connection() as c:` and delegate (Lakebase-or-raise `LakebaseUnavailable`), matching the existing facade style.

- [ ] **Step 1: Write failing test** — `bump` accumulates counts (`discovered += n`) via `SET discovered = discovered + %s`.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** repo + operational wrappers.
- [ ] **Step 4: Run to verify pass** — full offline suite: `../../.venv-test/bin/python -m pytest tests/ -q`.
- [ ] **Step 5: Commit** — `feat(db): index_jobs repo + operational facade wiring`

---

### Task 6: Migrate `domain_configs` → Lakebase `use_cases` (live, one-time)

**Files:**
- Create: `app/backend/scripts/migrate_domain_configs_to_lakebase.py`
- Test: none (one-shot script; guarded + idempotent)

**Interfaces:**
- Consumes: `docintel_routes.run_sql` (reads `{CATALOG}.platform.domain_configs`), `db.operational` (writes `use_cases`).

- [ ] **Step 1: Write the script** — read each `domain_configs` row via `run_sql`, JSON-parse the config columns, `upsert_use_case` into Lakebase. Print a per-row diff. Requires `LAKEBASE_ENABLED=true` + LB env (mirror `scripts/migrate_operational_to_lakebase.py`).

```python
# usage: LAKEBASE_ENABLED=true LB_HOST=... LB_EMAIL=... \
#   ../../.venv-test/bin/python scripts/migrate_domain_configs_to_lakebase.py
```

- [ ] **Step 2: Dry-run** locally with `--dry-run` (prints, writes nothing).
- [ ] **Step 3: Run for real** against jai-az-ws; verify `use_cases` has one row per active domain (supply_chain, compliance_due_diligence, supplier_performance, ap_three_way_match).
- [ ] **Step 4: Verify** — `SELECT use_case_id, name, status FROM use_cases` returns the expected 4.
- [ ] **Step 5: Commit** — `feat(migrate): domain_configs -> Lakebase use_cases`

---

## PHASE 2 — Metadata crawl (Google Drive), no copy

### Task 7: Extend `mcp_sources` with metadata tools

**Files:**
- Modify: `app/backend/mcp_sources.py`
- Test: `app/backend/tests/test_mcp_sources_metadata.py`

**Interfaces:**
- Produces (async client fns proxied to the sources MCP server): `list_children(source, folder_id="") -> list[dict]`, `get_file_metadata(source, item_id) -> dict`, `get_changes(source, since_token="") -> dict` (`{items, next_token}`), `check_access(source, item_id) -> dict`, `get_source_url(source, item_id) -> str`. Each returns raw source metadata dicts with at least `{item_id, name, path, mime_type, size, web_url, etag, modified_at, owner, is_folder}`.

- [ ] **Step 1: Write failing test** — monkeypatch `mcp_sources._call` to a fake; assert `list_children` calls tool `"list_children"` with `{"source","folder_id"}` and returns the list.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** thin wrappers over the existing `_call(tool, args)` (same pattern as `list_documents`). NB: no `from __future__ import annotations` already holds here (this module has it — leave it; these are plain async fns, not FastMCP tools).
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat(sources): metadata tools on the MCP client`

> **Executor note:** the *sources MCP server* (`app/mcp-server/server.py`, a separate app) must also expose these tools for the live path. If it only has `list_sources/list_documents/fetch_document` today, add the metadata tools there in the same task and redeploy that app. Tests here mock the client, so they pass regardless; the live P2 demo needs the server side.

### Task 8: `indexer/crawl.py` — metadata → `external_documents`

**Files:**
- Create: `app/backend/indexer/__init__.py`, `app/backend/indexer/crawl.py`
- Test: `app/backend/tests/test_indexer_crawl.py`

**Interfaces:**
- Consumes: `mcp_sources.list_children`, `external_docs_repo.upsert_metadata`, `stable_doc_id`.
- Produces: `async crawl_source(source_id, provider, domain_id, project_id, root_folder="", *, mcp=mcp_sources, repo=external_docs_repo, conn) -> dict` returning `{discovered, folders, seen_ids}`. Recursively walks folders (bounded), upserts one metadata row per file (no content), returns the set of seen ids for diff.

- [ ] **Step 1: Write failing test** — inject a fake `mcp` returning a 2-folder/3-file tree and a fake `repo`; assert 3 files upserted, folders traversed, `seen_ids` has 3 entries.
- [ ] **Step 2–4:** implement recursive walk + verify.
- [ ] **Step 5: Commit** — `feat(indexer): metadata crawl with no content copy`

### Task 9: `/api/sources` + `/api/inventory` routes

**Files:**
- Create: `app/backend/source_routes.py`
- Modify: `app/backend/app.py` (register router)
- Test: `app/backend/tests/test_source_routes.py`

**Interfaces:**
- Produces: `GET /api/sources`, `POST /api/sources` (register: `{source_id, provider, display_name, auth_mode, credential_ref, site, mode}` — rejects any field literally named/containing a secret value by requiring `credential_ref` to look like a reference, e.g. starts with `keeper://` or is empty), `GET /api/sources/{id}/auth-url`, `POST /api/sources/{id}/crawl` (`{domain_id, project_id, root_folder}` → runs `crawl_source`, returns counts), `GET /api/inventory?domain_id=&project_id=` (→ `external_docs_repo.list_for_project`, groups folders/files, includes status chips).

- [ ] **Step 1: Write failing test** — FastAPI `TestClient`; monkeypatch `db.operational` + `indexer.crawl` seams; assert `POST /api/sources` with a raw secret in `credential_ref` (no `keeper://`, non-empty) → 400.
- [ ] **Step 2–4:** implement, following `skill_routes.py` router conventions; register in `app.py`.
- [ ] **Step 5: Commit** — `feat(api): sources + inventory routes (no-copy crawl)`

---

## PHASE 3 — On-demand indexing + hybrid search

### Task 10: `indexer/parse.py` + `chunk.py`

**Files:**
- Create: `app/backend/indexer/parse.py`, `app/backend/indexer/chunk.py`
- Test: `app/backend/tests/test_indexer_parse_chunk.py`

**Interfaces:**
- Produces: `parse.extract_text(filename: str, content: bytes) -> str` (route by extension: `.txt/.md/.csv` decode; `.pdf` via `pypdf` if available else fall back to `ai_parse` seam; `.docx` via `python-docx` if available; unknown → `""` + caller marks `failed`), `chunk.split(text: str, *, size=1200, overlap=150) -> list[str]`, `chunk.chunk_id(external_document_id, ordinal) -> str`.

- [ ] **Step 1: Write failing tests** — `split` produces overlapping windows covering the text; `chunk_id` deterministic; `extract_text` handles `.txt` and `.csv` without any DB/network.
- [ ] **Step 2–4:** implement pure functions (no network for text formats).
- [ ] **Step 5: Commit** — `feat(indexer): text extraction + chunking`

### Task 11: `indexer/embed.py` — Databricks embedding client

**Files:**
- Create: `app/backend/indexer/embed.py`
- Test: `app/backend/tests/test_indexer_embed.py`

**Interfaces:**
- Produces: `embed_texts(texts: list[str], *, model=os.getenv("EMBED_MODEL","databricks-gte-large-en"), client=None) -> list[list[float]]` — calls the Databricks serving endpoint (reuse the model-call seam used by skill_runtime adapters / `docintel_routes`), batches, returns 1024-dim vectors. `client` injectable for tests.

- [ ] **Step 1: Write failing test** — inject a fake client returning canned 1024-vectors; assert batching + shape (len == len(texts), each len 1024).
- [ ] **Step 2–4:** implement with the injectable client seam; real client uses `WorkspaceClient().serving_endpoints.query(...)` or the existing `_get_llm`/embedding helper — **verify the exact embedding call in `docintel_routes.py`/`skill_runtime` before writing** and reuse it.
- [ ] **Step 5: Commit** — `feat(indexer): embedding client (gte-large-en, injectable)`

### Task 12: `indexer/diff.py` — incremental change detection

**Files:**
- Create: `app/backend/indexer/diff.py`
- Test: `app/backend/tests/test_indexer_diff.py`

**Interfaces:**
- Produces: `classify(existing: dict|None, seen: dict|None) -> str` returning one of `new|changed|unchanged|deleted|inaccessible` by comparing `etag`/`content_hash`; `plan_scope(conn, domain_id, project_id, seen_docs: list[dict], repo) -> {to_index: list[str], to_delete: list[str], skipped: int}` using `ids_missing_from` for deletions.

- [ ] **Step 1: Write failing tests** — unchanged etag → `unchanged` (skipped); changed etag → `changed`; id in DB but not seen → `deleted`; `None` existing → `new`.
- [ ] **Step 2–4:** implement pure logic.
- [ ] **Step 5: Commit** — `feat(indexer): incremental diff (etag/hash)`

### Task 13: `indexer/pipeline.py` — orchestrate a job

**Files:**
- Create: `app/backend/indexer/pipeline.py`
- Test: `app/backend/tests/test_indexer_pipeline.py`

**Interfaces:**
- Consumes: `crawl`, `diff`, `mcp_sources.fetch_document`, `parse`, `chunk`, `embed.embed_texts`, `chunks_repo.replace_chunks`, `chunks_repo.delete_for_doc`, `external_docs_repo.mark_indexed`/`set_status`, `index_jobs_repo`.
- Produces: `async run_index_job(job_id, source_id, provider, domain_id, project_id, scope, scope_ref, *, deps=<injectable bundle>, conn) -> dict` — start job → (crawl if scope≥folder) → diff → for each `to_index`: fetch→parse→chunk→embed→`replace_chunks`→`mark_indexed`; for each `to_delete`: `delete_for_doc`+`set_status(deleted)`; discard temp content unless `INDEX_RETAIN_RAW`; `bump` counts throughout; finish. On per-file error: `set_status(failed)`, increment `failed`, continue.

- [ ] **Step 1: Write failing test** — fully injected deps (fakes for mcp/parse/embed/repos); a 3-file scope where 1 unchanged, 1 changed, 1 deleted → asserts embedded=1, skipped=1, deleted=1, and `replace_chunks` called once with the changed doc's chunks.
- [ ] **Step 2–4:** implement orchestration; ensure per-file try/except so one failure doesn't abort the job.
- [ ] **Step 5: Commit** — `feat(indexer): on-demand index-job pipeline`

### Task 14: `search/` module + `/api/search`, `/api/index-jobs` routes

**Files:**
- Create: `app/backend/search/__init__.py`, `app/backend/search/backend.py`, `app/backend/search/lakebase_search.py`
- Modify: `app/backend/source_routes.py`
- Test: `app/backend/tests/test_search_hybrid.py`, extend `test_source_routes.py`

**Interfaces:**
- Produces: `backend.SearchBackend` (Protocol: `search(domain_id, project_id, query, k, folder, types) -> list[dict]`); `lakebase_search.LakebaseSearch` implements it by calling `embed.embed_texts([query])[0]` then `chunks_repo.hybrid_search`. Routes: `POST /api/search` (`{domain_id, project_id, query, k?, folder?, types?}`), `POST /api/index-jobs` (creates job row, launches `run_index_job` as a FastAPI background task, returns `{job_id}`), `GET /api/index-jobs/{job_id}`, `GET /api/index-jobs?domain_id=&project_id=`.

- [ ] **Step 1: Write failing tests** — `LakebaseSearch.search` embeds the query once and forwards to `hybrid_search` (inject fakes); `POST /api/index-jobs` returns a job_id and schedules the background task (assert the task callable was enqueued).
- [ ] **Step 2–4:** implement; background task via `fastapi.BackgroundTasks` (or `asyncio.create_task` with its own Lakebase connection — do NOT reuse the request conn).
- [ ] **Step 5: Commit** — `feat(api): hybrid search + index-job routes`

---

## PHASE 4 — Skills / workflow bridge

### Task 15: Resolve workflow document set from Lakebase

**Files:**
- Modify: `app/backend/skill_routes.py` (the `_project_doc_ids` / doc-set resolution used by `/workflow-run`), `app/backend/workflow_engine/engine.py` (`_build_doc_context`)
- Test: `app/backend/tests/test_workflow_lakebase_docs.py`

**Interfaces:**
- Consumes: `external_docs_repo.list_for_project` (status=`indexed`), `chunks_repo` (snippet text) or `mcp_sources.fetch_document` for full text.
- Produces: `skill_routes._resolve_doc_set(domain_id, project_id) -> list[dict]` returning `[{doc_id, doc_type, text}]` sourced from Lakebase `external_documents` (+ concatenated chunk snippets as `text`), so `engine.run(docs=...)` and `$docs.*` work unchanged.

- [ ] **Step 1: Write failing test** — inject fakes; `/workflow-run` for a project with 2 indexed external docs runs the existing `compliance_audit`-style template and the engine receives `docs=[{doc_id,doc_type,text}, ...]`.
- [ ] **Step 2–4:** implement the Lakebase-sourced doc set behind the existing engine seam; keep the legacy Volume/`parsed_documents` path as fallback when a project has no external docs (cutover safety).
- [ ] **Step 5: Commit** — `feat(workflows): source engine doc-set from Lakebase external docs`

---

## PHASE 5 — Frontend redesign (lean)

### Task 16: Sources connect page

**Files:**
- Create: `app/frontend/src/app/sources/page.tsx`
- Modify: `app/frontend/src/components/SourcePicker.tsx`
- Test: manual + `npm run build` (repo has `typescript.ignoreBuildErrors:true`, so **runtime-test**, not just build).

**Interfaces:** calls `GET /api/sources`, `POST /api/sources`, `GET /api/sources/{id}/auth-url`, `POST /api/sources/{id}/crawl`.

- [ ] **Step 1:** build the page: list connected sources with status; "Connect Google Drive" → auth-url flow; a "Crawl" button that runs metadata sync into the selected project.
- [ ] **Step 2:** `npm run build` clean; then runtime-test against the deployed/dev backend (see Task 18).
- [ ] **Step 3: Commit** — `feat(ui): sources connect page`

### Task 17: Project workspace — Inventory + Search panels

**Files:**
- Create: `app/frontend/src/app/project/page.tsx`, `app/frontend/src/components/InventoryPanel.tsx`, `app/frontend/src/components/SearchPanel.tsx`, `app/frontend/src/components/WhyThisResult.tsx`
- Modify: shell nav to unwire Knowledge Graph / Compliance Map / Action Center.

**Interfaces:** `GET /api/inventory`, `POST /api/index-jobs` + poll `GET /api/index-jobs/{id}`, `POST /api/search`.

- [ ] **Step 1:** InventoryPanel = source tree + file table with status chips + inclusion toggles + "Build/Refresh index" button + job-progress bar (poll job).
- [ ] **Step 2:** SearchPanel = hybrid search box → source-aware result cards (name, path, type, modified, **source link**, status, snippet) + WhyThisResult (matched chunks, retrieval mode).
- [ ] **Step 3:** unwire the three retired tabs from the shell nav (leave component files on disk, as Control Tower already is); add the non-sensitive-data banner.
- [ ] **Step 4:** `npm run build` + runtime-test.
- [ ] **Step 5: Commit** — `feat(ui): lean project workspace (inventory + hybrid search)`

### Task 18: Deploy + live verification (Google Drive demo)

**Files:** none (ops)

- [ ] **Step 1:** ensure app.yaml has `LAKEBASE_ENABLED=true` + LB env + `EMBED_MODEL`/`EMBED_DIM` + `DOCINTEL_MCP_SOURCES_URL`.
- [ ] **Step 2:** `cd app && ./deploy.sh` (profile jai-az-ws). Expect exit 0.
- [ ] **Step 3:** live smoke via app OAuth (`databricks auth token -p jai-az-ws`): `POST /api/sources` (gdrive), `POST /api/sources/gdrive/crawl` for a demo project → inventory shows files, **zero Volume writes**; `POST /api/index-jobs` → poll to `done`; `POST /api/search` returns ranked source-aware results; open-source link resolves; re-run index → `skipped` == unchanged count.
- [ ] **Step 4:** run one `compliance_audit`-style workflow over the indexed project → completes over Lakebase docs.
- [ ] **Step 5: Commit** — `chore: deploy connector-first slice + live verification notes`

---

## Self-Review

**Spec coverage:** §4 data model → Tasks 1–5; §D6 config migration → Task 6; §5.5 MCP metadata tools → Task 7; §5.1 indexer → Tasks 8,10–13; §5.2 search + fallback interface → Task 14; §5.3 routes → Tasks 9,14; §5.4 skills bridge → Task 15; §6 frontend + retired tabs → Tasks 16,17; §7 security banner + credential_ref → Tasks 9,17; §8 cost controls (skip-unchanged, retention, counts) → Tasks 12,13; §10 phasing → phases here. **Deferred to follow-on plans:** §11 SharePoint provider (P6), §8 benchmark notebook + §12 `app/CLAUDE.md` update (P7). Gap noted intentionally; called out at top.

**Placeholder scan:** no TBD/TODO; each code step has real code or a named seam to reuse. Two "verify the exact call before writing" notes (Task 11 embedding call, Task 7 server side) are deliberate — they point at existing code to copy, not invented APIs.

**Type consistency:** `stable_doc_id` signature identical in Tasks 3, 8. `hybrid_search` signature identical in Tasks 4, 14. `run_index_job` deps match the repos defined in Tasks 3–5. `SearchBackend.search` signature matches `LakebaseSearch` + route usage in Task 14. `_resolve_doc_set` returns `{doc_id,doc_type,text}` matching the engine's existing `$docs` contract (Task 15).
