"""Tests for index_jobs_repo — fake connection, no live DB."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.repositories import index_jobs_repo


_JOB_COLS = [
    "job_id", "domain_id", "project_id", "scope", "scope_ref",
    "requested_by", "status", "discovered", "embedded", "skipped",
    "deleted", "failed", "started_at", "finished_at", "error_summary",
]


class FakeCur:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.sql = []
        self.params = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self.params.append(params)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    @property
    def description(self):
        return [(c,) for c in _JOB_COLS]


class FakeConn:
    def __init__(self, rows=None):
        self.cur = FakeCur(rows or [])

    def cursor(self):
        return self.cur

    def execute(self, sql, params=None):
        return self.cur.execute(sql, params)


def test_bump_uses_additive_update():
    c = FakeConn()
    index_jobs_repo.bump(c, "job1", discovered=5, embedded=3)
    sql = " ".join(c.cur.sql).lower()
    # Must use accumulator pattern, not SET discovered = 5
    assert "discovered = discovered +" in sql or "discovered=discovered+" in sql
    assert "embedded = embedded +" in sql or "embedded=embedded+" in sql


def test_create_job_returns_dict():
    c = FakeConn([
        ("job1", "d1", "p1", "project", "", "user@x.com",
         "queued", 0, 0, 0, 0, 0, None, None, "")
    ])
    row = index_jobs_repo.create_job(c, "job1", "d1", "p1", "project", "", "user@x.com")
    assert row["job_id"] == "job1"
    assert row["status"] == "queued"


def test_start_sets_started_at():
    c = FakeConn()
    index_jobs_repo.start(c, "job1")
    sql = " ".join(c.cur.sql).lower()
    assert "started_at" in sql and "update index_jobs" in sql


def test_finish_sets_status_and_finished_at():
    c = FakeConn()
    index_jobs_repo.finish(c, "job1", "done")
    sql = " ".join(c.cur.sql).lower()
    assert "finished_at" in sql and "status" in sql


def test_list_jobs_filters_by_domain_project():
    c = FakeConn([
        ("job1", "d1", "p1", "project", "", "", "done", 10, 10, 0, 0, 0, None, None, "")
    ])
    jobs = index_jobs_repo.list_jobs(c, "d1", "p1")
    assert len(jobs) == 1
    sql = " ".join(c.cur.sql).lower()
    assert "domain_id" in sql and "project_id" in sql
