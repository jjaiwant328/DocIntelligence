"""Tests for use_cases_repo — fake connection, no live DB."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.repositories import use_cases_repo


class FakeCur:
    def __init__(self, rows):
        self._rows = rows
        self.sql = []
        self.params = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self.params.append(params)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    @property
    def description(self):
        return [
            ("use_case_id",), ("name",), ("status",),
            ("classification_labels",), ("extraction_schemas",),
            ("entity_types",), ("agent_system_prompt",),
            ("suggested_questions",), ("enabled_skills",),
            ("reconciliation",), ("created_at",), ("updated_at",),
        ]


class FakeConn:
    def __init__(self, rows):
        self.cur = FakeCur(rows)

    def cursor(self):
        return self.cur

    def execute(self, sql, params=None):
        return self.cur.execute(sql, params)


def test_upsert_use_case_returns_dict():
    c = FakeConn([
        ("uc1", "Supply Chain", "active", {}, {}, [], "", [], [], {}, None, None)
    ])
    row = use_cases_repo.upsert_use_case(c, "uc1", name="Supply Chain")
    assert row["use_case_id"] == "uc1"


def test_list_use_cases_returns_dicts():
    c = FakeConn([
        ("uc1", "Supply Chain", "active", {}, {}, [], "", [], [], {}, None, None),
    ])
    result = use_cases_repo.list_use_cases(c)
    assert len(result) == 1
    assert result[0]["use_case_id"] == "uc1"


def test_get_use_case_missing_returns_none():
    c = FakeConn([])
    assert use_cases_repo.get_use_case(c, "missing") is None


def test_upsert_use_case_encodes_json_fields():
    c = FakeConn([
        ("uc2", "Name", "active", {}, {}, [], "", [], [], {}, None, None)
    ])
    use_cases_repo.upsert_use_case(
        c, "uc2", name="Name",
        classification_labels={"k": "v"},
        entity_types=["person"],
    )
    # INSERT SQL should reference jsonb casting
    sql = " ".join(c.cur.sql).lower()
    assert "jsonb" in sql
