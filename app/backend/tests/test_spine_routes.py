"""Warehouse-independent tests for the additive thin-spine routes."""
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import spine_routes as s


def test_domain_schema_mapping():
    assert s._schema("supply_chain") == "template"
    assert s._schema("compliance_due_diligence") == "template_cdd"


def test_unknown_domain_raises_404():
    with pytest.raises(HTTPException) as ei:
        s._schema("does_not_exist")
    assert ei.value.status_code == 404


def test_sql_escaping():
    assert s._esc("O'Brien") == "O''Brien"


def test_list_domains_shape():
    out = s.list_spine_domains()
    ids = {d["domain_id"] for d in out["domains"]}
    assert {"supply_chain", "compliance_due_diligence"} <= ids


def test_search_builds_sql_without_warehouse(monkeypatch):
    """search() should compose a cosine query against the domain's gold_chunks."""
    captured = {}
    monkeypatch.setattr(s, "run_sql", lambda sql, wait="50s": captured.setdefault("sql", sql) or [])
    s.search(s.SearchRequest(question="temp excursion", domain_id="supply_chain", k=3))
    sql = captured["sql"]
    assert "vector_cosine_similarity" in sql
    assert "jai_docintel.template.gold_chunks" in sql
    assert "ai_query(" in sql
    assert "LIMIT 3" in sql
