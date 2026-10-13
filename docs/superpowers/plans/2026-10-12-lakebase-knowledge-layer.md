# Lakebase Knowledge Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Converge all document knowledge (metadata, chunks, vectors, extracted fields) into Lakebase, add doc-set assembly, and scale no-copy ingestion across Drive/SharePoint/S3/volumes/web.

**Architecture:** Lakebase `app` schema = single knowledge repo. Thin per-source `SourceAdapter`s feed the existing `indexer/pipeline.py`. Search/evidence/agent read Lakebase only; OpenJev rerank/validation unchanged. Spine medallion tables are backfilled once, then kept only for rollback.

**Tech Stack:** Lakebase (pgvector + tsvector), FastAPI, Next.js static export, Databricks Jobs (serverless), AI-Gateway managed MCP, `ai_extract`/`ai_parse_document`, OpenJev System One.

**Spec:** `docs/superpowers/specs/2026-10-12-lakebase-knowledge-layer-design.md`

## Global Constraints

- No content copies: docs stay at source; `external_documents.web_url` is the open-at-source link (reused as source_url — no new column).
- Domain is a column, never a schema.
- Judge calls fail open (search falls back to vector/hybrid order; validation returns `{"error": ...}`).
- Backend suite runs with: `cd app/backend && /Users/Jaiwant.jonathan/DBXApps/DocIntelligence/.venv-test/bin/python -m pytest -q`
- Frontend gate: `cd app/frontend && npm run build` (static export).
- Run git ONLY from the repo root — `app/.git` is a leftover nested repo.
- Commit messages end with: `Co-authored-by: Isaac <no-reply@databricks.com>`
- Databricks profile: `jai-az-ws`.

## Review Focus

1. **Empty corpus domain**: search on a domain with zero Lakebase rows must return `{"results": []}`, not error — test in Task 3.
2. **Query-set filter matching nothing**: `GET /doc-sets/{id}/docs` returns `[]` and search scoped to it returns empty, not a SQL error — test in Task 5.
3. **Backfill rerun**: second run of the backfill script must upsert, not duplicate (idempotent on `external_document_id` / chunk replace) — test in Task 2.
4. **Deleted-at-source doc**: sync marks it `status='deleted'` and it stops appearing in search (hybrid_search excludes via external_documents join) — test in Task 8.
5. **Binary-only folder**: crawl of a folder with zero text-readable files completes with `embedded: 0` and reference-only stubs, no exception — test in Task 8.

---

### Task 1: Lakebase schema — extracted_fields + doc_sets

**Files:**
- Modify: `app/backend/db/schema.py` (append DDL to the `_DDL` list before the closing `]`)
- Create: `app/backend/db/repositories/extracted_fields_repo.py`
- Create: `app/backend/db/repositories/doc_sets_repo.py`
- Test: `app/backend/tests/test_extracted_fields_repo.py`, `app/backend/tests/test_doc_sets_repo.py`

**Interfaces:**
- Produces:
  - `extracted_fields_repo.replace_for_doc(conn, doc_id: str, fields: list[dict]) -> int`
  - `extracted_fields_repo.list_for_doc(conn, doc_id: str) -> list[dict]` → `[{field_name, field_value, page, bbox, source_text, confidence}]`
  - `extracted_fields_repo.set_confidence(conn, doc_id: str, field_name: str, confidence: float) -> None`
  - `doc_sets_repo.create(conn, set_id: str, domain_id: str, name: str, kind: str, filter_json: dict) -> dict`
  - `doc_sets_repo.list_for_domain(conn, domain_id: str) -> list[dict]`
  - `doc_sets_repo.get(conn, set_id: str) -> dict | None`
  - `doc_sets_repo.delete(conn, set_id: str) -> None`
  - `doc_sets_repo.pin(conn, set_id: str, doc_id: str) -> None` / `doc_sets_repo.unpin(conn, set_id: str, doc_id: str) -> None`
  - `doc_sets_repo.pinned_ids(conn, set_id: str) -> list[str]`

- [ ] **Step 1: Write the failing tests**

```python
# app/backend/tests/test_doc_sets_repo.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.repositories import doc_sets_repo as r


class FakeCursor:
    def __init__(self, rows=()):
        self.queries, self.params, self._rows = [], [], list(rows)
    def execute(self, q, p=None):
        self.queries.append(q); self.params.append(p)
    def fetchall(self):
        return self._rows
    @property
    def description(self):
        cols = ["id", "domain_id", "name", "kind", "filter_json", "created_at"]
        return [(c,) for c in cols[:len(self._rows[0])]] if self._rows else []


class FakeConn:
    def __init__(self, rows=()):
        self.cur = FakeCursor(rows)
    def cursor(self):
        return self.cur


def test_create_inserts_pinned_set():
    conn = FakeConn()
    r.create(conn, "s1", "supply_chain", "Q3 suppliers", "pinned", {})
    q = conn.cur.queries[0]
    assert "INSERT INTO doc_sets" in q
    assert conn.cur.params[0][:4] == ("s1", "supply_chain", "Q3 suppliers", "pinned")


def test_pin_and_pinned_ids():
    conn = FakeConn(rows=[("d1",), ("d2",)])
    r.pin(conn, "s1", "d1")
    assert "INSERT INTO doc_set_members" in conn.cur.queries[0]
    ids = r.pinned_ids(conn, "s1")
    assert ids == ["d1", "d2"]
```

```python
# app/backend/tests/test_extracted_fields_repo.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.repositories import extracted_fields_repo as r


class FakeCursor:
    def __init__(self, rows=()):
        self.queries, self.params, self._rows = [], [], list(rows)
    def execute(self, q, p=None):
        self.queries.append(q); self.params.append(p)
    def fetchall(self):
        return self._rows
    @property
    def description(self):
        cols = ["field_name", "field_value", "page", "bbox", "source_text", "confidence"]
        return [(c,) for c in cols]


class FakeConn:
    def __init__(self, rows=()):
        self.cur = FakeCursor(rows)
    def cursor(self):
        return self.cur


def test_replace_for_doc_deletes_then_inserts():
    conn = FakeConn()
    n = r.replace_for_doc(conn, "doc1", [
        {"field_name": "total", "field_value": "$1,100", "page": 1,
         "bbox": [0.1, 0.2, 0.3, 0.4], "source_text": "Total: $1,100"},
    ])
    assert n == 1
    assert "DELETE FROM extracted_fields" in conn.cur.queries[0]
    assert "INSERT INTO extracted_fields" in conn.cur.queries[1]


def test_list_for_doc_maps_rows():
    conn = FakeConn(rows=[("total", "$1,100", 1, [0.1]*4, "Total: $1,100", 0.9)])
    out = r.list_for_doc(conn, "doc1")
    assert out[0]["field_name"] == "total"
    assert out[0]["confidence"] == 0.9
```

- [ ] **Step 2: Run tests, verify fail**

Run: `cd app/backend && ../../.venv-test/bin/python -m pytest tests/test_doc_sets_repo.py tests/test_extracted_fields_repo.py -q`
Expected: FAIL (modules do not exist).

- [ ] **Step 3: Implement schema + repos**

Append to the DDL list in `app/backend/db/schema.py`:

```python
    """
    CREATE TABLE IF NOT EXISTS extracted_fields (
        doc_id        TEXT        NOT NULL,
        field_name    TEXT        NOT NULL,
        field_value   TEXT        NOT NULL DEFAULT '',
        page          INT,
        bbox          JSONB,
        source_text   TEXT        NOT NULL DEFAULT '',
        confidence    DOUBLE PRECISION,
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (doc_id, field_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS doc_sets (
        id          TEXT        PRIMARY KEY,
        domain_id   TEXT        NOT NULL,
        name        TEXT        NOT NULL,
        kind        TEXT        NOT NULL CHECK (kind IN ('pinned','query')),
        filter_json JSONB       NOT NULL DEFAULT '{}'::jsonb,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS doc_set_members (
        doc_set_id  TEXT NOT NULL REFERENCES doc_sets(id) ON DELETE CASCADE,
        doc_id      TEXT NOT NULL,
        pinned_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (doc_set_id, doc_id)
    )
    """,
```

`app/backend/db/repositories/extracted_fields_repo.py`:

```python
"""extracted_fields rows: evidence-linked field values per document."""
from __future__ import annotations
import json
from typing import Any

_COLS = ["field_name", "field_value", "page", "bbox", "source_text", "confidence"]


def _dicts(cur: Any) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def replace_for_doc(conn: Any, doc_id: str, fields: list[dict]) -> int:
    cur = conn.cursor()
    cur.execute("DELETE FROM extracted_fields WHERE doc_id=%s", (doc_id,))
    for f in fields:
        cur.execute(
            """INSERT INTO extracted_fields
               (doc_id, field_name, field_value, page, bbox, source_text, confidence)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (doc_id, f["field_name"], f.get("field_value", ""), f.get("page"),
             json.dumps(f.get("bbox")) if f.get("bbox") is not None else None,
             f.get("source_text", ""), f.get("confidence")),
        )
    return len(fields)


def list_for_doc(conn: Any, doc_id: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        f"SELECT {', '.join(_COLS)} FROM extracted_fields WHERE doc_id=%s ORDER BY field_name",
        (doc_id,),
    )
    return _dicts(cur)


def set_confidence(conn: Any, doc_id: str, field_name: str, confidence: float) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE extracted_fields SET confidence=%s, updated_at=now() WHERE doc_id=%s AND field_name=%s",
        (confidence, doc_id, field_name),
    )
```

`app/backend/db/repositories/doc_sets_repo.py`:

```python
"""doc_sets + doc_set_members: pinned and query-defined document sets."""
from __future__ import annotations
import json
from typing import Any, Optional

_COLS = ["id", "domain_id", "name", "kind", "filter_json", "created_at"]


def _dicts(cur: Any) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def create(conn: Any, set_id: str, domain_id: str, name: str, kind: str, filter_json: dict) -> dict:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO doc_sets (id, domain_id, name, kind, filter_json) VALUES (%s,%s,%s,%s,%s)",
        (set_id, domain_id, name, kind, json.dumps(filter_json or {})),
    )
    return {"id": set_id, "domain_id": domain_id, "name": name, "kind": kind,
            "filter_json": filter_json or {}}


def list_for_domain(conn: Any, domain_id: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        f"SELECT {', '.join(_COLS)} FROM doc_sets WHERE domain_id=%s ORDER BY created_at",
        (domain_id,),
    )
    return _dicts(cur)


def get(conn: Any, set_id: str) -> Optional[dict]:
    cur = conn.cursor()
    cur.execute(f"SELECT {', '.join(_COLS)} FROM doc_sets WHERE id=%s", (set_id,))
    rows = _dicts(cur)
    return rows[0] if rows else None


def delete(conn: Any, set_id: str) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM doc_sets WHERE id=%s", (set_id,))


def pin(conn: Any, set_id: str, doc_id: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO doc_set_members (doc_set_id, doc_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (set_id, doc_id),
    )


def unpin(conn: Any, set_id: str, doc_id: str) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM doc_set_members WHERE doc_set_id=%s AND doc_id=%s", (set_id, doc_id))


def pinned_ids(conn: Any, set_id: str) -> list[str]:
    cur = conn.cursor()
    cur.execute("SELECT doc_id FROM doc_set_members WHERE doc_set_id=%s ORDER BY pinned_at", (set_id,))
    return [row[0] for row in cur.fetchall()]
```

- [ ] **Step 4: Run tests + full suite, verify pass**

Run: `cd app/backend && ../../.venv-test/bin/python -m pytest -q`
Expected: PASS (suite + new tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/db app/backend/tests/test_extracted_fields_repo.py app/backend/tests/test_doc_sets_repo.py
git commit -m "feat(db): extracted_fields + doc_sets tables and repos

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 2: Backfill spine medallion → Lakebase

**Files:**
- Create: `app/backend/scripts/backfill_spine_to_lakebase.py`
- Test: `app/backend/tests/test_backfill.py`

**Interfaces:**
- Consumes: `template.gold_documents/gold_extracted_fields/gold_chunks`, `template_cdd.*` (via SQL warehouse), repos from Task 1, `external_docs_repo.upsert_metadata`, `chunks_repo.replace_chunks`, `db.lakebase.connection()`.
- Produces: runnable script `python scripts/backfill_spine_to_lakebase.py [--domain supply_chain]`; Lakebase rows with `source_id='uc_volume'`, `web_url=source_file` (volume path).

- [ ] **Step 1: Write the failing test**

```python
# app/backend/tests/test_backfill.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import backfill_spine_to_lakebase as bf


def test_doc_row_shape():
    row = bf._doc_row("supply_chain", {
        "doc_id": "a.txt", "doc_type": "invoice", "source_file": "/Volumes/jai_docintel/raw/documents/a.txt",
    })
    assert row["external_document_id"] == "a.txt"
    assert row["source_id"] == "uc_volume"
    assert row["domain_id"] == "supply_chain"
    assert row["web_url"] == "/Volumes/jai_docintel/raw/documents/a.txt"
    assert row["status"] == "indexed"


def test_field_row_shape():
    f = bf._field_row("a.txt", {"field_name": "total", "field_value": "$5"})
    assert f == {"field_name": "total", "field_value": "$5", "page": None,
                 "bbox": None, "source_text": "", "confidence": None}


def test_chunk_row_carries_embedding():
    c = bf._chunk_row("a.txt", {
        "doc_id": "a.txt", "chunk_position": 0,
        "chunk_to_retrieve": "hello world", "embedding": [0.1, 0.2],
    })
    assert c["external_document_id"] == "a.txt"
    assert c["ordinal"] == 0
    assert c["embedding"] == [0.1, 0.2]
    assert c["snippet"] == "hello world"
```

- [ ] **Step 2: Run test, verify fail**

Run: `cd app/backend && ../../.venv-test/bin/python -m pytest tests/test_backfill.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement the backfill script**

```python
# app/backend/scripts/backfill_spine_to_lakebase.py
"""One-shot backfill: spine medallion tables (template/template_cdd) → Lakebase.

Idempotent: docs upsert on external_document_id, chunks/fields use
replace_for_doc. Vectors are carried over — no re-embedding.

Run:  python scripts/backfill_spine_to_lakebase.py [--domain supply_chain]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from databricks.sdk import WorkspaceClient

from db import lakebase
from db.repositories import external_docs_repo, chunks_repo, extracted_fields_repo

CATALOG = "jai_docintel"
SCHEMA_BY_DOMAIN = {
    "supply_chain": "template",
    "compliance_due_diligence": "template_cdd",
}


def _doc_row(domain_id: str, r: dict) -> dict:
    return {
        "external_document_id": r["doc_id"],
        "source_id": "uc_volume",
        "source_item_id": r["doc_id"],
        "domain_id": domain_id,
        "project_id": "default",
        "parent_folder_id": "",
        "path": r.get("source_file", ""),
        "name": r["doc_id"],
        "mime_type": "text/plain",
        "size_bytes": 0,
        "web_url": r.get("source_file", ""),
        "etag": "",
        "content_hash": "",
        "owner": "backfill",
        "source_created_at": None,
        "source_modified_at": None,
        "status": "indexed",
        "included": True,
        "doc_type": r.get("doc_type", ""),
    }


def _field_row(doc_id: str, r: dict) -> dict:
    return {"field_name": r["field_name"], "field_value": r.get("field_value", ""),
            "page": r.get("page"), "bbox": r.get("bbox"),
            "source_text": r.get("source_text", ""), "confidence": None}


def _chunk_row(doc_id: str, r: dict) -> dict:
    return {"external_document_id": doc_id, "ordinal": r.get("chunk_position", 0),
            "location": "", "snippet": r.get("chunk_to_retrieve", ""),
            "embedding": r.get("embedding")}


def _sql(w, warehouse_id: str, stmt: str) -> list[dict]:
    res = w.statement_execution.execute_statement(
        statement=stmt, warehouse_id=warehouse_id, wait_timeout="50s")
    cols = [c.name for c in res.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (res.result.data_array or [])]


def backfill_domain(w, warehouse_id: str, domain_id: str) -> dict:
    schema = SCHEMA_BY_DOMAIN[domain_id]
    docs = _sql(w, warehouse_id, f"SELECT doc_id, doc_type, source_file FROM {CATALOG}.{schema}.gold_documents")
    counts = {"docs": 0, "fields": 0, "chunks": 0}
    with lakebase.connection() as conn:
        for d in docs:
            did = d["doc_id"]
            external_docs_repo.upsert_metadata(conn, _doc_row(domain_id, d))
            counts["docs"] += 1
            fields = _sql(w, warehouse_id,
                f"SELECT * FROM {CATALOG}.{schema}.gold_extracted_fields WHERE doc_id = '{did}'")
            counts["fields"] += extracted_fields_repo.replace_for_doc(
                conn, did, [_field_row(did, f) for f in fields])
            chunks = _sql(w, warehouse_id,
                f"SELECT * FROM {CATALOG}.{schema}.gold_chunks WHERE doc_id = '{did}' ORDER BY chunk_position")
            counts["chunks"] += chunks_repo.replace_chunks(
                conn, did, [_chunk_row(did, c) for c in chunks])
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", choices=list(SCHEMA_BY_DOMAIN), default=None)
    args = ap.parse_args()
    w = WorkspaceClient()
    warehouse_id = os.environ["DATABRICKS_WAREHOUSE_ID"]
    domains = [args.domain] if args.domain else list(SCHEMA_BY_DOMAIN)
    for domain_id in domains:
        counts = backfill_domain(w, warehouse_id, domain_id)
        print(f"{domain_id}: {counts}")


if __name__ == "__main__":
    main()
```

Note: `chunks_repo.replace_chunks` expects chunk dicts with keys `external_document_id, ordinal, location, snippet, embedding` — verify against its INSERT column list before running live; adjust `_chunk_row` keys if the repo names differ (e.g. `chunk_id` computed inside the repo).

- [ ] **Step 4: Run tests, verify pass**

Run: `cd app/backend && ../../.venv-test/bin/python -m pytest tests/test_backfill.py -q`
Expected: PASS.

- [ ] **Step 5: Run backfill live + idempotency check**

```bash
cd app/backend && DATABRICKS_CONFIG_PROFILE=jai-az-ws DATABRICKS_WAREHOUSE_ID=85a4ed5bcff25c0d ../../.venv-test/bin/python scripts/backfill_spine_to_lakebase.py
```
Run twice; second run prints identical counts (upsert, no dupes). Verify:
`SELECT count(*) FROM external_documents WHERE source_id='uc_volume';` ≈ 61 (supply_chain) + 24 (compliance).

- [ ] **Step 6: Commit**

```bash
git add app/backend/scripts/backfill_spine_to_lakebase.py app/backend/tests/test_backfill.py
git commit -m "feat(db): backfill spine medallion into Lakebase knowledge store

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 3: Search v2 — Lakebase hybrid + judge, project-optional

**Files:**
- Modify: `app/backend/db/repositories/chunks_repo.py` (`hybrid_search`: `project_id: Optional[str] = None` — drop project filter when None)
- Modify: `app/backend/search/lakebase_search.py` (`search(..., project_id: Optional[str] = None)`)
- Modify: `app/backend/spine_routes.py` (`search` reads Lakebase via `LakebaseSearch`; judge rerank kept; per-hit `source` block)
- Test: `app/backend/tests/test_spine_routes.py` (extend), `app/backend/tests/test_chunks_repo.py`

**Interfaces:**
- Consumes: Task 2 Lakebase rows; `JudgeClient.relevance` (existing).
- Produces: `POST /api/spine/search {question, domain_id, k, rerank, doc_set_id?}` → `{results: [{doc_id, doc_type, source_file, chunk_to_retrieve, score, judge_score?, source: {provider, url}}]}`. Response keys unchanged for existing clients (`doc_id`, `chunk_to_retrieve`, `score`); `source` added.

- [ ] **Step 1: Write the failing tests**

```python
# app/backend/tests/test_chunks_repo.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.repositories import chunks_repo


class FakeCursor:
    def __init__(self):
        self.sql, self.params = "", ()
    def execute(self, q, p=None):
        self.sql, self.params = q, p
    def fetchall(self):
        return []
    @property
    def description(self):
        return []


class FakeConn:
    def __init__(self):
        self.cur = FakeCursor()
    def cursor(self):
        return self.cur


def test_hybrid_search_without_project_omits_project_filter():
    conn = FakeConn()
    chunks_repo.hybrid_search(conn, "supply_chain", None, [0.1] * 1024, "invoice", k=3)
    assert "project_id=%s" not in conn.cur.sql
    assert "domain_id=%s" in conn.cur.sql


def test_hybrid_search_with_project_keeps_filter():
    conn = FakeConn()
    chunks_repo.hybrid_search(conn, "supply_chain", "default", [0.1] * 1024, "invoice", k=3)
    assert conn.cur.sql.count("project_id=%s") == 2  # vec + kw CTEs
```

```python
# appended to app/backend/tests/test_spine_routes.py

def test_search_uses_lakebase_backend(monkeypatch):
    hits = [{"chunk_id": "c1", "external_document_id": "a.txt", "name": "a.txt",
             "path": "/v/a.txt", "web_url": "https://drive/x", "mime_type": "text/plain",
             "status": "indexed", "ordinal": 0, "location": "", "snippet": "hello",
             "score": 0.5}]

    class FakeBackend:
        def search(self, domain_id, project_id, query, k=10, folder="", types=None):
            assert project_id is None
            return hits

    monkeypatch.setattr(s, "_backend", lambda: FakeBackend())
    monkeypatch.setattr(s, "_rerank", lambda q, rows: rows)
    out = s.search(s.SearchRequest(question="q", domain_id="supply_chain", k=3))
    r = out["results"][0]
    assert r["doc_id"] == "a.txt"
    assert r["chunk_to_retrieve"] == "hello"
    assert r["source"] == {"provider": "lakebase", "url": "https://drive/x"}


def test_search_empty_corpus_returns_empty(monkeypatch):
    class FakeBackend:
        def search(self, *a, **k):
            return []

    monkeypatch.setattr(s, "_backend", lambda: FakeBackend())
    monkeypatch.setattr(s, "_rerank", lambda q, rows: rows)
    out = s.search(s.SearchRequest(question="q", domain_id="supply_chain", k=3))
    assert out["results"] == []
```

- [ ] **Step 2: Run tests, verify fail**

Run: `cd app/backend && ../../.venv-test/bin/python -m pytest tests/test_chunks_repo.py -q`
Expected: FAIL (project filter unconditional).

- [ ] **Step 3: Implement**

In `chunks_repo.hybrid_search`, change signature to `project_id: Optional[str] = None` and build the CTE filters dynamically:

```python
    doc_filter = "domain_id=%s" + (" AND project_id=%s" if project_id else "")
    doc_params: tuple = (domain_id, project_id) if project_id else (domain_id,)
```

then use `{doc_filter}` inside both `vec` and `kw` CTEs and splice `doc_params` into the parameter tuple in place of the two hardcoded `(domain_id, project_id)` pairs.

In `search/lakebase_search.py`, widen `search` to `project_id: Optional[str] = None` and pass through.

In `spine_routes.py`, replace the SQL-cosine body of `search()` with:

```python
def _backend():
    from search.lakebase_search import LakebaseSearch
    return LakebaseSearch()


def _to_hit(row: dict) -> dict:
    return {
        "doc_id": row["external_document_id"],
        "doc_type": row.get("mime_type", ""),
        "source_file": row.get("path", ""),
        "chunk_to_retrieve": row.get("snippet", ""),
        "score": round(float(row.get("score", 0.0)), 4),
        "source": {"provider": "lakebase", "url": row.get("web_url", "")},
    }


@router.post("/search")
def search(req: SearchRequest):
    """Lakebase hybrid search over all ingested sources + OpenJev rerank."""
    _schema(req.domain_id)  # 404 unknown domain
    k = max(1, min(req.k, 25))
    cand = max(k, min(2 * k, RERANK_CANDIDATES)) if req.rerank else k
    rows = _backend().search(req.domain_id, None, req.question, k=cand)
    hits = [_to_hit(r) for r in rows]
    if req.rerank:
        hits = _rerank(req.question, hits)
    return {"domain_id": req.domain_id, "question": req.question, "results": hits[:k]}
```

Delete the now-unused `run_sql`-based query inside `search` (keep `run_sql` for evidence until Task 4).

- [ ] **Step 4: Run tests + full suite, verify pass**

Run: `cd app/backend && ../../.venv-test/bin/python -m pytest -q`
Expected: PASS (older SQL-shape search tests updated to the new seam).

- [ ] **Step 5: Parity gate (live)**

With bearer token, POST 5 probe questions (`invoice price mismatch`, `refrigeration temperature excursion`, `supplier contract termination clause`, `temperature log`, `payment terms`) to `/api/spine/search`. Expect: supply_chain hits include backfilled `uc_volume` docs (and any Drive docs), HTTP 200, `judge_score` present when rerank on. Record overlap vs pre-swap results in the PR description.

- [ ] **Step 6: Commit**

```bash
git add app/backend/db/repositories/chunks_repo.py app/backend/search/lakebase_search.py app/backend/spine_routes.py app/backend/tests
git commit -m "feat(spine): search v2 — Lakebase hybrid over all sources + judge rerank

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 4: Evidence v2 — Lakebase fields + open-at-source

**Files:**
- Modify: `app/backend/spine_routes.py` (`evidence`, `_validate`)
- Test: `app/backend/tests/test_spine_routes.py` (extend)

**Interfaces:**
- Consumes: Task 1 `extracted_fields_repo`, `external_docs_repo`, `chunks_repo.list_for_doc`.
- Produces: `GET /api/spine/evidence?doc_id&domain_id&validate` → `{document: {doc_id, doc_type, source_file, source_url}, extracted_fields: [...], source_chunks: [...], validation?}`.

- [ ] **Step 1: Write the failing test**

```python
# appended to app/backend/tests/test_spine_routes.py

def test_evidence_reads_lakebase(monkeypatch):
    doc = {"external_document_id": "a.txt", "mime_type": "text/plain",
           "path": "/v/a.txt", "web_url": "https://drive/x", "name": "a.txt"}
    monkeypatch.setattr(s, "_lakebase_doc", lambda did, dom: doc)
    monkeypatch.setattr(s.extracted_fields_repo, "list_for_doc",
                        lambda conn, did: [{"field_name": "total", "field_value": "$5",
                                            "page": 1, "bbox": None,
                                            "source_text": "Total $5", "confidence": None}])
    monkeypatch.setattr(s.chunks_repo, "list_for_doc",
                        lambda conn, did: [{"chunk_id": "c1", "external_document_id": did,
                                            "ordinal": 0, "location": "", "snippet": "hello"}])

    class FakeLB:
        from contextlib import contextmanager
        @contextmanager
        def connection(self):
            yield object()

    monkeypatch.setattr(s, "lakebase", FakeLB())
    out = s.evidence("a.txt", "supply_chain")
    assert out["document"]["source_url"] == "https://drive/x"
    assert out["extracted_fields"][0]["field_name"] == "total"
    assert out["source_chunks"][0]["source_text"] == "hello"
```

- [ ] **Step 2: Run test, verify fail** — evidence still reads UC tables via run_sql.

- [ ] **Step 3: Implement**

In `spine_routes.py`:

```python
from db import lakebase
from db.repositories import external_docs_repo, extracted_fields_repo, chunks_repo


def _lakebase_doc(doc_id: str, domain_id: str) -> dict | None:
    with lakebase.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT external_document_id, mime_type, path, web_url, name "
            "FROM external_documents WHERE external_document_id=%s AND domain_id=%s",
            (doc_id, domain_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"external_document_id": row[0], "mime_type": row[1],
            "path": row[2], "web_url": row[3], "name": row[4]}


@router.get("/evidence")
def evidence(doc_id: str, domain_id: str = "supply_chain", validate: bool = False):
    """Evidence trail from Lakebase: doc, extracted fields, source chunks, source URL."""
    _schema(domain_id)
    doc = _lakebase_doc(doc_id, domain_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"No document '{doc_id}' in {domain_id}")
    with lakebase.connection() as conn:
        fields = extracted_fields_repo.list_for_doc(conn, doc_id)
        chunks = chunks_repo.list_for_doc(conn, doc_id)
    out = {
        "document": {"doc_id": doc_id, "doc_type": doc["mime_type"],
                     "source_file": doc["path"], "source_url": doc["web_url"]},
        "extracted_fields": fields,
        "source_chunks": [{"chunk_position": c["ordinal"], "source_text": c["snippet"]}
                          for c in chunks],
    }
    if validate:
        out["validation"] = _validate(
            {"doc_type": doc["mime_type"]}, fields, out["source_chunks"], domain_id)
    return out
```

Update `_validate` signature: `(doc, fields, chunks, domain_id)` — candidate types become `SELECT DISTINCT mime_type FROM external_documents WHERE domain_id=%s` via Lakebase (drop the old gold_documents query); `run_sql` and the UC-schema evidence path are deleted.

- [ ] **Step 4: Run suite, verify pass; live smoke evidence on a backfilled doc (`?validate=true` returns field confidences).**

- [ ] **Step 5: Commit**

```bash
git add app/backend/spine_routes.py app/backend/tests/test_spine_routes.py
git commit -m "feat(spine): evidence v2 — Lakebase fields/chunks + open-at-source

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 5: Doc-sets API

**Files:**
- Create: `app/backend/doc_set_routes.py`
- Modify: `app/backend/app.py` (mount after spine router, same try/except pattern)
- Test: `app/backend/tests/test_doc_set_routes.py`

**Interfaces:**
- Consumes: Task 1 `doc_sets_repo`.
- Produces: `GET/POST /api/doc-sets`, `GET /api/doc-sets/{id}/docs`, `POST /api/doc-sets/{id}/pin`, `DELETE /api/doc-sets/{id}/pin/{doc_id}`, `DELETE /api/doc-sets/{id}`. Query-set resolution SQL (`_resolve_query_set(conn, filter_json) -> list[dict]`).

- [ ] **Step 1: Write the failing tests**

```python
# app/backend/tests/test_doc_set_routes.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import doc_set_routes as d
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client():
    app = FastAPI()
    app.include_router(d.router)
    return TestClient(app)


def test_create_pinned_set(monkeypatch):
    created = {}
    monkeypatch.setattr(d.doc_sets_repo, "create",
                        lambda conn, **kw: created.update(kw) or kw)

    class FakeLB:
        from contextlib import contextmanager
        @contextmanager
        def connection(self):
            yield object()

    monkeypatch.setattr(d, "lakebase", FakeLB())
    resp = _client().post("/api/doc-sets", json={
        "domain_id": "supply_chain", "name": "Q3", "kind": "pinned"})
    assert resp.status_code == 200
    assert created["kind"] == "pinned"
    assert resp.json()["id"]


def test_query_set_resolve_empty_match(monkeypatch):
    monkeypatch.setattr(d.doc_sets_repo, "get", lambda conn, sid: {
        "id": sid, "kind": "query",
        "filter_json": {"source_ids": ["nope"], "doc_types": [], "text": "", "labels": []}})

    class FakeCur:
        def execute(self, q, p=None): self.q = q
        def fetchall(self): return []
        @property
        def description(self): return []

    class FakeConn:
        def cursor(self): return FakeCur()

    class FakeLB:
        from contextlib import contextmanager
        @contextmanager
        def connection(self):
            yield FakeConn()

    monkeypatch.setattr(d, "lakebase", FakeLB())
    resp = _client().get("/api/doc-sets/s1/docs")
    assert resp.status_code == 200
    assert resp.json()["documents"] == []
```

- [ ] **Step 2: Run tests, verify fail.**

- [ ] **Step 3: Implement `doc_set_routes.py`**

```python
"""Doc-set assembly: pinned + query-defined sets over Lakebase documents."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import lakebase
from db.repositories import doc_sets_repo

router = APIRouter(prefix="/api/doc-sets", tags=["doc-sets"])


class DocSetCreate(BaseModel):
    domain_id: str
    name: str
    kind: str = "pinned"
    filter_json: dict = {}


class PinRequest(BaseModel):
    doc_ids: list[str]


@router.get("")
def list_sets(domain_id: str):
    with lakebase.connection() as conn:
        return {"doc_sets": doc_sets_repo.list_for_domain(conn, domain_id)}


@router.post("")
def create_set(req: DocSetCreate):
    if req.kind not in ("pinned", "query"):
        raise HTTPException(status_code=400, detail="kind must be pinned|query")
    set_id = uuid.uuid4().hex[:12]
    with lakebase.connection() as conn:
        return doc_sets_repo.create(conn, set_id, req.domain_id, req.name,
                                    req.kind, req.filter_json)


@router.delete("/{set_id}")
def delete_set(set_id: str):
    with lakebase.connection() as conn:
        if not doc_sets_repo.get(conn, set_id):
            raise HTTPException(status_code=404, detail=f"no doc-set '{set_id}'")
        doc_sets_repo.delete(conn, set_id)
    return {"deleted": set_id}


def _resolve_query_set(conn, filter_json: dict) -> list[dict]:
    wheres, params = ["TRUE"], []
    if filter_json.get("source_ids"):
        wheres.append("source_id = ANY(%s)")
        params.append(filter_json["source_ids"])
    if filter_json.get("doc_types"):
        wheres.append("mime_type = ANY(%s)")
        params.append(filter_json["doc_types"])
    if filter_json.get("text"):
        wheres.append("(name ILIKE %s OR path ILIKE %s)")
        like = f"%{filter_json['text']}%"
        params += [like, like]
    cur = conn.cursor()
    cur.execute(
        f"""SELECT external_document_id, name, path, web_url, mime_type, status
            FROM external_documents WHERE {' AND '.join(wheres)}
            ORDER BY name LIMIT 500""",
        params,
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


@router.get("/{set_id}/docs")
def set_docs(set_id: str):
    with lakebase.connection() as conn:
        s = doc_sets_repo.get(conn, set_id)
        if not s:
            raise HTTPException(status_code=404, detail=f"no doc-set '{set_id}'")
        if s["kind"] == "pinned":
            ids = doc_sets_repo.pinned_ids(conn, set_id)
            if not ids:
                return {"documents": []}
            cur = conn.cursor()
            cur.execute(
                """SELECT external_document_id, name, path, web_url, mime_type, status
                   FROM external_documents WHERE external_document_id = ANY(%s)""",
                (ids,),
            )
            cols = [c[0] for c in cur.description]
            return {"documents": [dict(zip(cols, row)) for row in cur.fetchall()]}
        fj = s["filter_json"]
        if isinstance(fj, str):
            fj = json.loads(fj)
        return {"documents": _resolve_query_set(conn, fj)}


@router.post("/{set_id}/pin")
def pin(set_id: str, req: PinRequest):
    with lakebase.connection() as conn:
        s = doc_sets_repo.get(conn, set_id)
        if not s:
            raise HTTPException(status_code=404, detail=f"no doc-set '{set_id}'")
        if s["kind"] != "pinned":
            raise HTTPException(status_code=400, detail="cannot pin into a query set")
        for did in req.doc_ids:
            doc_sets_repo.pin(conn, set_id, did)
    return {"pinned": len(req.doc_ids)}


@router.delete("/{set_id}/pin/{doc_id}")
def unpin(set_id: str, doc_id: str):
    with lakebase.connection() as conn:
        doc_sets_repo.unpin(conn, set_id, doc_id)
    return {"unpinned": doc_id}
```

Mount in `app.py` after the spine block:

```python
try:
    from doc_set_routes import router as doc_set_router
    app.include_router(doc_set_router)
    print("✅ Doc-set routes registered at /api/doc-sets")
except Exception as _e:
    import traceback as _tb
    print(f"⚠️ Doc-set routes not loaded: {type(_e).__name__}: {_e}\n{_tb.format_exc()}")
```

- [ ] **Step 4: Run suite, verify pass; live smoke: create pinned set, pin 2 docs, list docs.**

- [ ] **Step 5: Commit**

```bash
git add app/backend/doc_set_routes.py app/backend/app.py app/backend/tests/test_doc_set_routes.py
git commit -m "feat(doc-sets): pinned + query-defined doc-set API

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 6: Search doc_set scoping + Doc-Sets UI

**Files:**
- Modify: `app/backend/spine_routes.py` (`SearchRequest.doc_set_id: str = ""`; candidate ids narrowed before hybrid search)
- Modify: `app/frontend/src/components/SpineSearchPanel.tsx` (doc-set selector, pin button per hit, open-at-source link)
- Create: `app/frontend/src/components/DocSetsPanel.tsx`
- Modify: `app/frontend/src/app/page.tsx` (add "doc-sets" tab)
- Test: `app/backend/tests/test_spine_routes.py` (extend)

**Interfaces:**
- Consumes: Task 5 API; Task 3 search.
- Produces: search scoped by doc-set (pinned ids or query-resolved ids passed as candidate filter); UI tab id `doc-sets`.

- [ ] **Step 1: Failing test**

```python
# appended to app/backend/tests/test_spine_routes.py

def test_search_scoped_to_doc_set(monkeypatch):
    captured = {}

    class FakeBackend:
        def search(self, domain_id, project_id, query, k=10, doc_ids=None, **kw):
            captured["doc_ids"] = doc_ids
            return []

    monkeypatch.setattr(s, "_backend", lambda: FakeBackend())
    monkeypatch.setattr(s, "_doc_set_ids", lambda conn, sid: ["d1", "d2"])

    class FakeLB:
        from contextlib import contextmanager
        @contextmanager
        def connection(self):
            yield object()

    monkeypatch.setattr(s, "lakebase", FakeLB())
    monkeypatch.setattr(s, "_rerank", lambda q, rows: rows)
    out = s.search(s.SearchRequest(question="q", domain_id="supply_chain",
                                   k=3, doc_set_id="set1"))
    assert captured["doc_ids"] == ["d1", "d2"]
    assert out["results"] == []
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement**

`chunks_repo.hybrid_search` and `LakebaseSearch.search` gain `doc_ids: Optional[list[str]] = None` → `AND external_document_id = ANY(%s)` in both CTEs when set. `spine_routes`:

```python
def _doc_set_ids(conn, set_id: str) -> list[str]:
    from db.repositories import doc_sets_repo
    s = doc_sets_repo.get(conn, set_id)
    if not s:
        raise HTTPException(status_code=404, detail=f"no doc-set '{set_id}'")
    if s["kind"] == "pinned":
        return doc_sets_repo.pinned_ids(conn, set_id)
    from doc_set_routes import _resolve_query_set
    fj = s["filter_json"]
    if isinstance(fj, str):
        import json
        fj = json.loads(fj)
    return [d["external_document_id"] for d in _resolve_query_set(conn, fj)]
```

In `search()`: when `req.doc_set_id`, resolve ids inside a `lakebase.connection()` and pass `doc_ids` to `_backend().search(...)`; empty id list → return empty results immediately.

UI: `DocSetsPanel.tsx` — list sets for domain, create (name + kind; query kind shows 3 inputs: source_ids csv, doc_types csv, text), member list via `/docs`, delete. `SpineSearchPanel` — doc-set `<select>` fed from `/api/doc-sets?domain_id=` (empty option = all docs), `source.url` rendered as "open ↗" link per hit, "Pin" button per hit when a pinned set is selected. `page.tsx` — add `{ id: "doc-sets", icon: "🗂", label: "Doc-Sets", description: "Assemble pinned or query-defined document sets" }` to TABS and render `DocSetsPanel` with `domain` prop.

- [ ] **Step 4: Suite + `npm run build` pass; live: create query set `text=invoice`, search scoped to it.**

- [ ] **Step 5: Commit**

```bash
git add app/backend app/frontend/src
git commit -m "feat(doc-sets): search scoping + Doc-Sets tab + pin-from-search

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 7: Agent re-grounding on Lakebase search

**Files:**
- Modify: `app/backend/docintel_routes.py` (agent_query `search_documents` tool, ~line 640 region)
- Test: `app/backend/tests/test_agent_grounding.py`

**Interfaces:**
- Consumes: `LakebaseSearch.search(domain_id, None, query, k=5)`.
- Produces: agent answers cite `external_document_id` + `web_url`.

- [ ] **Step 1: Failing test**

```python
# app/backend/tests/test_agent_grounding.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import docintel_routes as dr


def test_agent_doc_context_uses_lakebase(monkeypatch):
    calls = {}

    class FakeBackend:
        def search(self, domain_id, project_id, query, k=10, **kw):
            calls["args"] = (domain_id, project_id, query, k)
            return [{"external_document_id": "a.txt", "mime_type": "text/plain",
                     "snippet": "hello world", "web_url": "https://drive/x",
                     "name": "a.txt", "path": "/v/a.txt", "status": "indexed",
                     "chunk_id": "c1", "ordinal": 0, "location": "", "score": 0.9}]

    monkeypatch.setattr(dr, "_agent_search_backend", lambda: FakeBackend())
    ctx, cited = dr._agent_doc_context("invoice terms", "compliance_due_diligence")
    assert "hello world" in ctx
    assert cited == ["a.txt"]
    assert calls["args"][1] is None
```

- [ ] **Step 2: Run, verify fail (helpers don't exist).**

- [ ] **Step 3: Implement**

In `docintel_routes.py` extract the direct-LLM context assembly (agent_query step "1. Try semantic (ai_similarity) search first") into:

```python
def _agent_search_backend():
    from search.lakebase_search import LakebaseSearch
    return LakebaseSearch()


def _agent_doc_context(question: str, domain_id: str) -> tuple[str, list[str]]:
    """Lakebase hybrid search → context text + cited doc ids. Empty on failure."""
    try:
        rows = _agent_search_backend().search(domain_id, None, question, k=6)
    except Exception:
        return "", []
    cited, chunks = [], []
    for r in rows:
        did = r["external_document_id"]
        if did not in cited:
            cited.append(did)
        chunks.append(f"[Source: {did} | Type: {r.get('mime_type','')} | {r.get('web_url','')}]\n{r.get('snippet','')}")
    return "\n\n---\n\n".join(chunks), cited
```

In `agent_query`'s direct-LLM branch replace the `_vs_search` block with `context_text, cited_docs = _agent_doc_context(req.question, domain_id)`; keep the SQL fallback block as-is. In the supply_chain UC-toolkit branch, swap the `search_documents` tool body to call `_agent_doc_context(query, domain_id)` (keep the `@tool` wrapper).

- [ ] **Step 4: Suite pass; live: ask agent a question in compliance domain, confirm cited doc ids resolve in evidence.**

- [ ] **Step 5: Commit**

```bash
git add app/backend/docintel_routes.py app/backend/tests/test_agent_grounding.py
git commit -m "feat(agent): ground on Lakebase hybrid search with source links

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 8: Sync runner — `indexer/sync.py`

**Files:**
- Create: `app/backend/indexer/sync.py`
- Test: `app/backend/tests/test_sync.py`

**Interfaces:**
- Consumes: `PipelineDeps` (indexer/pipeline.py), `external_docs_repo.ids_missing_from`, adapter registry.
- Produces: `run_sync(source_id: str, adapter, conn) -> dict` — `{discovered, indexed, deleted, skipped_binary}`; CLI `python -m indexer.sync --source-id X` (resolves adapter from the source row's provider). Deleted-at-source docs get `status='deleted'` via `external_docs_repo.set_status`.

- [ ] **Step 1: Failing test**

```python
# app/backend/tests/test_sync.py
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from indexer import sync


class FakeAdapter:
    def __init__(self, docs):
        self._docs = docs
    async def list_docs(self, checkpoint):
        return self._docs, checkpoint
    async def fetch_text(self, doc):
        return doc.get("text")


def test_sync_marks_deleted_and_binary_skipped(monkeypatch):
    docs = [
        {"source_item_id": "1", "name": "a.txt", "mime_type": "text/plain", "text": "hello"},
        {"source_item_id": "2", "name": "b.pdf", "mime_type": "application/pdf", "text": None},
    ]
    adapter = FakeAdapter(docs)
    result = asyncio.run(sync.run_sync("src1", adapter, conn=object(), domain_id="d",
                                       project_id="default", _index_fn=lambda **kw: {"embedded": 1}))
    assert result["discovered"] == 2
    assert result["skipped_binary"] == 1
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** — `run_sync(source_id, adapter, conn, domain_id, project_id, _index_fn=None)`:
  1. `docs, checkpoint = await adapter.list_docs(checkpoint={})`
  2. Upsert metadata rows (`external_docs_repo.upsert_metadata`); count discovered.
  3. `stale = external_docs_repo.ids_missing_from(conn, source_id, seen_ids)` → `set_status(..., 'deleted')`; count.
  4. For text-readable docs (`indexer.managed_gdrive.is_text_readable`), call `_index_fn` (default: the existing `_run_index_job` pipeline path with `PipelineDeps`); non-text → `set_included(False)`, count `skipped_binary`.
  5. CLI `__main__`: argparse `--source-id`, load row via `opstore.get_source`, build adapter via `sync.build_adapter(row, token=None)` (managed providers need an OBO token — CLI scheduled runs pass `None` and skip user-private sources with a printed notice).

- [ ] **Step 4: Suite pass; binary-only-folder review-focus case asserted (`embedded: 0`, no exception).**

- [ ] **Step 5: Commit**

```bash
git add app/backend/indexer/sync.py app/backend/tests/test_sync.py
git commit -m "feat(ingest): sync runner — incremental crawl + delete marking + binary stubs

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 9: `docintel_sync` job + on-demand via run_now

**Files:**
- Modify: `databricks.yml` (add `docintel_sync` job resource)
- Modify: `app/backend/source_routes.py` (`managed-crawl` enqueues `jobs.run_now` instead of inline `_run_index_job`; keep inline path behind `?inline=true` for demo debugging)
- Test: `app/backend/tests/test_source_routes.py` (extend)

**Interfaces:**
- Consumes: Task 8 CLI.
- Produces: job `docintel_sync` (serverless, hourly cron, param `source_id`); route returns `{job_id, run_id, status: "queued"}`.

- [ ] **Step 1: Failing test**

```python
# appended to app/backend/tests/test_source_routes.py

def test_managed_crawl_enqueues_job(monkeypatch):
    monkeypatch.setattr(source_routes.opstore, "get_source",
                        lambda sid: {"source_id": sid, "provider": "gdrive_managed"})
    captured = {}

    class FakeJobs:
        def run_now(self, job_id, notebook_params=None, python_params=None):
            captured["job_id"] = job_id
            return type("R", (), {"run_id": 123})()

    class FakeW:
        jobs = FakeJobs()

    monkeypatch.setattr(source_routes, "_ws", lambda: FakeW())
    monkeypatch.setattr(source_routes, "_SYNC_JOB_ID", "42")
    client = _make_client()
    resp = client.post("/api/sources/gdrive_managed/managed-crawl",
                       json={"domain_id": "d", "project_id": "p", "root_folder": ""})
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert captured["job_id"] == "42"
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** — add to `databricks.yml` under `resources.jobs`:

```yaml
    docintel_sync:
      name: "DocIntelligence — Source Sync"
      description: "Incremental no-copy sync of registered sources into the Lakebase knowledge layer."
      parameters:
        - name: source_id
          default: ""
      tasks:
        - task_key: sync
          notebook_task:
            notebook_path: ./notebooks/02_sync_source.py
            base_parameters:
              source_id: "{{job.parameters.source_id}}"
      schedule:
        quartz_cron_expression: "0 0 * * * ?"
        timezone_id: "UTC"
        pause_status: UNPAUSED
```

Create `notebooks/02_sync_source.py` (thin: widget `source_id`, empty = loop all sources; calls `indexer.sync` CLI via `%run` or subprocess against the backend package deployed in the bundle — simplest: the notebook inserts the backend dir on `sys.path` from the bundle files and calls `run_sync` per source, building adapters; SP-auth sources only).

`source_routes.py`: module constant `_SYNC_JOB_ID = os.getenv("DOCINTEL_SYNC_JOB_ID", "")`, `_ws()` returning a cached `WorkspaceClient`; in `managed_crawl_route`, when `request.query_params.get("inline") != "true"` and `_SYNC_JOB_ID` set → `run = _ws().jobs.run_now(job_id=int(_SYNC_JOB_ID), notebook_params={"source_id": source_id})` → return `{"job_id": _SYNC_JOB_ID, "run_id": run.run_id, "status": "queued"}`. Else keep the existing inline OBO path (user-private drives need the caller's token anyway — this stays the default for `gdrive_managed`; enqueue is the path for SP-readable sources).

- [ ] **Step 4: Suite pass; `databricks bundle validate` OK; deploy bundle; set `DOCINTEL_SYNC_JOB_ID` in `app/backend/app.yaml` env.**

- [ ] **Step 5: Commit**

```bash
git add databricks.yml notebooks/02_sync_source.py app/backend/source_routes.py app/backend/app.yaml app/backend/tests/test_source_routes.py
git commit -m "feat(sync): docintel_sync hourly job + on-demand run_now enqueue

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

### Task 10: SharePoint managed adapter

**Files:**
- Create: `app/backend/indexer/managed_sharepoint.py`
- Modify: `app/backend/indexer/sync.py` (adapter registry)
- Modify: `app/frontend/src/app/sources/page.tsx` (provider option label)
- Test: `app/backend/tests/test_managed_sharepoint.py`

**Interfaces:**
- Consumes: same `AsyncManagedDriveSource` pattern (indexer/managed_gdrive.py) against the SharePoint managed MCP endpoint (probe `system.ai.sharepoint` at execution; if absent, adapter ships disabled with a clear registry note).
- Produces: provider `sharepoint_managed` registrable + syncable.

- [ ] **Step 1: Probe live** — `databricks serving-endpoints list -p jai-az-ws | grep -i sharepoint` and AI-Gateway MCP services list; record endpoint URL or absence.
- [ ] **Step 2: Failing adapter contract test** (mirror `test_managed_gdrive.py` shape: fake injected transport, list_children → DocMeta rows, fetch_text returns str|None).
- [ ] **Step 3: Implement** — clone `managed_gdrive.py` with endpoint/tool names swapped; register `"sharepoint_managed"` in `sync.build_adapter`.
- [ ] **Step 4: Suite pass; live register + managed-crawl a test SharePoint folder (or recorded as blocked-by-platform with evidence).**
- [ ] **Step 5: Commit** `feat(sources): SharePoint managed adapter`.

---

### Task 11: S3/GCS adapter via external location

**Files:**
- Create: `app/backend/indexer/object_store.py`
- Modify: `app/backend/indexer/sync.py` (registry)
- Test: `app/backend/tests/test_object_store.py`

**Interfaces:**
- Consumes: UC external location (user creates once) + `w.files` listing on the external-location path.
- Produces: provider `s3_gcs` (bucket URL stored on the source row's `site` field): `list_docs` walks prefix (etag from object metadata), `fetch_text` reads text objects only.

- [ ] **Step 1: Failing contract test** (fake `w.files`: `list_directory_contents` yields FileInfo objects; verify DocMeta mapping and binary skip).
- [ ] **Step 2: Implement** — adapter takes `site` (e.g. `s3://bucket/prefix/`); lists via `w.files.list_directory_contents`, recursive one level per folder; `fetch_text` downloads via `w.files.download` for text extensions only.
- [ ] **Step 3: Suite pass; live: register a source against a test external location, run sync, verify rows.**
- [ ] **Step 4: Commit** `feat(sources): S3/GCS object-store adapter via external locations`.

---

### Task 12: Extraction on crawled docs → Lakebase extracted_fields

**Files:**
- Modify: `app/backend/indexer/pipeline.py` (post-embed hook `extract_fn` in `PipelineDeps`)
- Create: `app/backend/indexer/extract.py`
- Test: `app/backend/tests/test_extract.py`, `app/backend/tests/test_sync.py` (extend)

**Interfaces:**
- Consumes: domain `extraction_schemas` from `platform.domain_configs` (via warehouse SQL, cached per sync run); `extracted_fields_repo.replace_for_doc`.
- Produces: `extract_fields(text: str, schema: dict) -> list[dict]` using `ai_extract` via the SQL warehouse; synced Drive/S3 docs gain evidence-linked fields; judge validation works on them unchanged.

- [ ] **Step 1: Failing test**

```python
# app/backend/tests/test_extract.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from indexer import extract


def test_extract_maps_ai_extract_rows():
    def fake_sql(stmt):
        return [{"field_name": "total", "field_value": "$5"}]
    fields = extract.extract_fields("Invoice total $5", {"total": "invoice total"},
                                    sql_fn=fake_sql)
    assert fields == [{"field_name": "total", "field_value": "$5",
                       "page": None, "bbox": None, "source_text": "", "confidence": None}]
```

- [ ] **Step 2: Implement** — `extract_fields(text, schema_fields, sql_fn)`: single `SELECT ai_extract(%s, %s)` per doc (text truncated to 8000 chars); maps variant result to field rows. Wire into `PipelineDeps` as `extract_fn` (default None = skip); `run_sync` calls it per indexed doc when the domain has `extraction_schemas` configured, then `replace_for_doc`.

- [ ] **Step 3: Suite pass; live: sync Drive folder, evidence on a Drive doc shows extracted fields; `validate=true` returns confidences.**

- [ ] **Step 4: Commit** `feat(extract): ai_extract on crawled docs into Lakebase extracted_fields`.

---

### Task 13: Web/wiki adapter + PDF-at-source

**Files:**
- Create: `app/backend/indexer/web_wiki.py`
- Modify: `app/backend/indexer/sync.py` (registry), `app/backend/indexer/managed_gdrive.py` (PDF path)
- Test: `app/backend/tests/test_web_wiki.py`, `app/backend/tests/test_managed_gdrive.py` (extend)

**Interfaces:**
- Produces: provider `web_wiki` (seed URL list on source row `site`, newline-separated; robots.txt respected, same-domain only, depth 1); Drive PDFs parsed via `ai_parse_document` on fetched bytes (SQL warehouse) — no volume copy.

- [ ] **Step 1: Failing web_wiki contract test** (fake fetcher: robots disallow → skipped; allowed page → DocMeta with text).
- [ ] **Step 2: Implement web_wiki** — stdlib `urllib` + `urllib.robotparser`; HTML→text via regex strip (no new dependency); depth-1 same-domain links.
- [ ] **Step 3: Failing PDF test** — `managed_gdrive.fetch_text` on `application/pdf` calls `parse_pdf_bytes(bytes, sql_fn)` (new helper) instead of returning None.
- [ ] **Step 4: Implement** — `parse_pdf_bytes` writes bytes to a temp path under `/tmp`, reads via `READ_FILES` + `ai_parse_document` on the SQL warehouse (`parsed:document:pages` text concat). No UC volume write.
- [ ] **Step 5: Suite pass; live: re-sync DocIntel folder — the 4 PDFs index; search returns PDF content.**
- [ ] **Step 6: Commit** `feat(sources): web/wiki adapter + PDF-at-source parsing`.

---

## Self-Review

**Spec coverage:** architecture/data model → T1, T2; sync execution → T8, T9 (+ accepted OBO limitation in T9 inline default); doc-sets/consumers → T5, T6, T3, T4, T7; phasing P1=T1–T4, P2=T5–T7, P3=T8–T11, P4=T12–T13; non-goals respected (no entity UI, no event sync). UI changes folded into T6; Sources-tab sync-status column deferred (polish, not acceptance).

**Placeholder scan:** T10/T11/T13 live steps name concrete probes; T10 gates on a platform probe with an explicit blocked outcome. No TBDs.

**Type consistency:** `extracted_fields_repo.replace_for_doc(conn, doc_id, fields)` used identically in T1/T2/T12; `doc_sets_repo` signatures identical in T1/T5/T6; `LakebaseSearch.search(domain_id, project_id, query, k, doc_ids?)` consistent T3/T6/T7; `_doc_set_ids` defined once in T6, reused by search only.

**Review focus wiring:** empty corpus → T3 step 1; empty query-set → T5 step 1; backfill idempotency → T2 step 5; deleted-at-source → T8 steps 3/4; binary-only folder → T8 step 4.
