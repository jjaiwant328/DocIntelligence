"""
Unit tests for the ai_similarity retrieval helper and its SQL-injection guards.

These tests stub out the heavy runtime deps (fastapi / pydantic / databricks-sdk)
so the module imports without a Databricks environment, then exercise the pure
helpers: `_safe_ident`, `_sql_lit`, and `_vs_search`.

Run:  python -m pytest app/backend/tests/test_vs_search.py
  or:  python app/backend/tests/test_vs_search.py   (self-contained runner)
"""
import os
import sys
import types
import importlib.util

# ── Stub heavy deps so docintel_routes imports without a live environment ──────
def _install_stubs():
    if "fastapi" not in sys.modules:
        fastapi = types.ModuleType("fastapi")
        class APIRouter:
            def __init__(self, *a, **k): pass
            def __getattr__(self, _name):
                # get / post / put / delete / patch → decorator no-ops
                def _decorator(*a, **k):
                    return lambda f: f
                return _decorator
        class HTTPException(Exception):
            def __init__(self, status_code=500, detail=""):
                self.status_code = status_code
                self.detail = detail
                super().__init__(detail)
        fastapi.APIRouter = APIRouter
        fastapi.HTTPException = HTTPException
        sys.modules["fastapi"] = fastapi

    if "pydantic" not in sys.modules:
        pydantic = types.ModuleType("pydantic")
        class BaseModel:  # minimal stand-in
            pass
        pydantic.BaseModel = BaseModel
        sys.modules["pydantic"] = pydantic

    if "databricks" not in sys.modules:
        databricks = types.ModuleType("databricks")
        sys.modules["databricks"] = databricks
    if "databricks.sdk" not in sys.modules:
        sdk = types.ModuleType("databricks.sdk")
        class WorkspaceClient:
            def __init__(self, *a, **k): pass
        sdk.WorkspaceClient = WorkspaceClient
        sys.modules["databricks.sdk"] = sdk
    if "databricks.sdk.service" not in sys.modules:
        svc = types.ModuleType("databricks.sdk.service")
        sys.modules["databricks.sdk.service"] = svc
    if "databricks.sdk.service.sql" not in sys.modules:
        sqlmod = types.ModuleType("databricks.sdk.service.sql")
        class StatementState:
            PENDING = "PENDING"; RUNNING = "RUNNING"
            SUCCEEDED = "SUCCEEDED"; FAILED = "FAILED"
        sqlmod.StatementState = StatementState
        sys.modules["databricks.sdk.service.sql"] = sqlmod


def _load_module():
    _install_stubs()
    here = os.path.dirname(os.path.abspath(__file__))
    mod_path = os.path.join(here, "..", "docintel_routes.py")
    spec = importlib.util.spec_from_file_location("docintel_routes", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dr = _load_module()


# ── _safe_ident ────────────────────────────────────────────────────────────────
def test_safe_ident_accepts_valid():
    for name in ("vectors", "compliance_due_diligence", "raw", "_x", "a1_b2"):
        assert dr._safe_ident(name) == name


def test_safe_ident_rejects_injection():
    bad = [
        "vectors; DROP TABLE x",
        "a.b",
        "a-b",
        "a b",
        "1abc",
        "",
        "va`cktick",
        "sch'ema",
    ]
    for name in bad:
        try:
            dr._safe_ident(name)
            raise AssertionError(f"expected ValueError for {name!r}")
        except ValueError:
            pass


# ── _sql_lit ────────────────────────────────────────────────────────────────────
def test_sql_lit_escapes_quotes():
    out = dr._sql_lit("O'Brien")
    assert "\\'" in out and "O" in out and "Brien" in out


def test_sql_lit_escapes_backslash():
    out = dr._sql_lit("a\\b")
    assert "\\\\" in out


def test_sql_lit_caps_length():
    out = dr._sql_lit("x" * 100, 10)
    assert len(out) == 10


def test_sql_lit_handles_none():
    assert dr._sql_lit(None) == ""


# ── _vs_search ───────────────────────────────────────────────────────────────────
def test_vs_search_builds_expected_sql_and_shape(monkeypatch=None):
    captured = {}

    def fake_run_sql(query, timeout_secs=50):
        captured["query"] = query
        return [
            {"chunk_id": "c1", "doc_id": "d1", "doc_type": "permit", "chunk_to_retrieve": "hello"},
            {"chunk_id": "c2", "doc_id": "d2", "doc_type": "license", "chunk_to_retrieve": "world"},
        ]

    orig = dr.run_sql
    dr.run_sql = fake_run_sql
    try:
        rows = dr._vs_search("open a store", "compliance_due_diligence", k=6)
    finally:
        dr.run_sql = orig

    q = captured["query"]
    # per-domain schema resolved, not hardcoded to vectors
    assert "compliance_due_diligence.document_chunks" in q
    assert "ai_similarity(chunk_to_retrieve" in q
    assert "ORDER BY ai_similarity" in q
    assert "LIMIT 6" in q
    # drop-in shape: [chunk_id, doc_id, doc_type, chunk_to_retrieve]
    assert rows[0] == ["c1", "d1", "permit", "hello"]
    assert rows[1][1] == "d2" and rows[1][3] == "world"


def test_vs_search_escapes_malicious_query():
    captured = {}

    def fake_run_sql(query, timeout_secs=50):
        captured["query"] = query
        return []

    orig = dr.run_sql
    dr.run_sql = fake_run_sql
    try:
        dr._vs_search("'; DROP TABLE document_chunks; --", "vectors", k=3)
    finally:
        dr.run_sql = orig

    q = captured["query"]
    # the raw closing quote must be escaped, so the statement stays intact
    assert "\\'; DROP TABLE" in q


def test_vs_search_rejects_bad_schema_returns_empty():
    def fake_run_sql(query, timeout_secs=50):
        raise AssertionError("run_sql should not be called for an invalid schema")

    orig = dr.run_sql
    dr.run_sql = fake_run_sql
    try:
        # _safe_ident raises inside _vs_search → caught → [] (graceful)
        assert dr._vs_search("q", "vectors; DROP TABLE x", k=3) == []
    finally:
        dr.run_sql = orig


def test_vs_search_empty_query_returns_empty():
    assert dr._vs_search("   ", "vectors", k=3) == []


def test_vs_search_sql_failure_is_graceful():
    def boom(query, timeout_secs=50):
        raise RuntimeError("warehouse down")

    orig = dr.run_sql
    dr.run_sql = boom
    try:
        assert dr._vs_search("q", "vectors", k=3) == []
    finally:
        dr.run_sql = orig


def test_vs_search_doc_type_filter():
    captured = {}

    def fake_run_sql(query, timeout_secs=50):
        captured["query"] = query
        return []

    orig = dr.run_sql
    dr.run_sql = fake_run_sql
    try:
        dr._vs_search("q", "vectors", k=3, doc_type_filter="historical_response")
    finally:
        dr.run_sql = orig

    assert "WHERE doc_type = 'historical_response'" in captured["query"]


# ── get_action_reports count coercion ────────────────────────────────────────────
def test_action_reports_coerces_string_counts():
    """run_sql returns cnt as strings (e.g. "6"); aggregation must not raise
    TypeError and must produce correct int totals."""
    import asyncio

    def fake_run_sql(query, timeout_secs=30):
        if "GROUP BY status, priority" in query:
            # API-shaped rows: every value is a raw string
            return [
                {"status": "OPEN", "priority": "HIGH", "cnt": "6"},
                {"status": "OPEN", "priority": "LOW", "cnt": "3"},
                {"status": "CLOSED", "priority": "HIGH", "cnt": "5"},
            ]
        return []  # overdue + all_actions queries

    orig_run_sql = dr.run_sql
    orig_master = dr._ensure_action_master_table
    orig_hist = dr._ensure_action_history_table
    dr.run_sql = fake_run_sql
    dr._ensure_action_master_table = lambda: None
    dr._ensure_action_history_table = lambda: None
    try:
        result = asyncio.run(dr.get_action_reports("compliance_due_diligence"))
    finally:
        dr.run_sql = orig_run_sql
        dr._ensure_action_master_table = orig_master
        dr._ensure_action_history_table = orig_hist

    assert result["by_status"] == {"OPEN": 9, "CLOSED": 5}
    assert result["by_priority"] == {"HIGH": 11, "LOW": 3}
    assert result["total"] == 14
    assert all(isinstance(v, int) for v in result["by_status"].values())


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
