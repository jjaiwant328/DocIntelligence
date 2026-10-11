"""LIVE integration test: schema DDL + repositories against a real Lakebase.

Exercises the actual SQL (parameterized) that the app runs, in a throwaway
`app_test` schema that is dropped at the end — production `app` is untouched.

Skipped unless LB_HOST / LB_TOKEN / LB_EMAIL are set. Run:

  P=jai-az-ws
  export LB_HOST=$(databricks postgres list-endpoints \
      projects/docintel/branches/production -p $P -o json | jq -r '.[0].status.hosts.host')
  export LB_TOKEN=$(databricks postgres generate-database-credential \
      projects/docintel/branches/production/endpoints/primary -p $P -o json | jq -r '.token')
  export LB_EMAIL=$(databricks current-user me -p $P -o json | jq -r '.userName')
  cd app/backend && ../../.venv-test/bin/python tests/test_db_integration.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import schema  # noqa: E402
from db.repositories import projects_repo, runs_repo, tags_repo  # noqa: E402

TEST_SCHEMA = "app_test"


def main():
    host = os.getenv("LB_HOST")
    token = os.getenv("LB_TOKEN")
    email = os.getenv("LB_EMAIL")
    if not (host and token and email):
        print("test_db_integration: SKIPPED (LB_HOST/LB_TOKEN/LB_EMAIL not set)")
        return

    import psycopg

    with psycopg.connect(
        host=host, port=5432, dbname=os.getenv("LB_DB", "docintel"),
        user=email, password=token, sslmode="require", autocommit=True,
    ) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE')
        conn.execute(f'CREATE SCHEMA {TEST_SCHEMA}')
        conn.execute(f'SET search_path = "{TEST_SCHEMA}", public')
        try:
            # 1. DDL is idempotent
            schema.ensure_schema(conn)
            schema.ensure_schema(conn)

            dom = "supplier_performance"
            # 2. create + list
            projects_repo.create_project(
                conn, domain_id=dom, project_id="acme-perf-001",
                name="Acme Supplier Performance", municipality="Dallas",
                state="TX", owner="jaiwant.jonathan@databricks.com",
            )
            # duplicate insert is a no-op (ON CONFLICT)
            projects_repo.create_project(
                conn, domain_id=dom, project_id="acme-perf-001", name="Dup",
            )
            rows = projects_repo.list_projects(conn, dom)
            assert len(rows) == 1, rows
            assert rows[0]["project_id"] == "acme-perf-001"
            assert rows[0]["name"] == "Acme Supplier Performance"
            assert rows[0]["collaborators"] == []

            # 3. name_exists (case-insensitive)
            assert projects_repo.name_exists(conn, dom, "acme supplier PERFORMANCE")
            assert not projects_repo.name_exists(conn, dom, "nope")

            # 4. members update
            projects_repo.update_members(
                conn, domain_id=dom, project_id="acme-perf-001",
                collaborators=["a@x.com", "b@x.com", ""],
            )
            rows = projects_repo.list_projects(conn, dom)
            assert rows[0]["collaborators"] == ["a@x.com", "b@x.com"], rows[0]["collaborators"]

            # 5. tags: add (idempotent), list, remove
            tags_repo.add_tag(conn, domain_id=dom, project_id="acme-perf-001", doc_id="doc-1")
            tags_repo.add_tag(conn, domain_id=dom, project_id="acme-perf-001", doc_id="doc-1")
            tags_repo.add_tag(conn, domain_id=dom, project_id="acme-perf-001", doc_id="doc-2")
            assert set(tags_repo.doc_ids_for_project(conn, domain_id=dom, project_id="acme-perf-001")) == {"doc-1", "doc-2"}
            tags_repo.remove_tag(conn, domain_id=dom, project_id="acme-perf-001", doc_id="doc-1")
            assert tags_repo.doc_ids_for_project(conn, domain_id=dom, project_id="acme-perf-001") == ["doc-2"]

            # 6. LOSSLESS run round-trip — the regression the old _slim_run hid.
            big_output = "X" * 5000                 # >4KB (old cap: 600 chars)
            evidence = [{"document_id": f"d{i}", "source_text": "E" * 400}
                        for i in range(10)]          # 10 items (old cap: 6 × 160 chars)
            run = {
                "template_id": "supplier_scorecard", "template_version": "1",
                "domain": dom, "status": "completed", "work_object_id": "WO-LOSSLESS-1",
                "steps": [{"id": "s1", "skill": "summarize", "status": "ok",
                           "outputs": {"summary": big_output}, "evidence": evidence}],
            }
            rid = runs_repo.record_run(conn, domain_id=dom, project_id="acme-perf-001",
                                       run=run, label="lossless")
            assert rid == "WO-LOSSLESS-1"
            got = runs_repo.get_run(conn, rid)
            assert got is not None, "run should reopen"
            step = got["steps"][0]
            assert len(step["outputs"]["summary"]) == 5000, "output must NOT be truncated"
            assert len(step["evidence"]) == 10, "all evidence items must survive"
            assert len(step["evidence"][0]["source_text"]) == 400, "evidence text must NOT be truncated"
            runs = runs_repo.list_runs(conn, domain_id=dom, project_id="acme-perf-001")
            assert len(runs) == 1 and runs[0]["run_id"] == "WO-LOSSLESS-1"

            # 7. delete cascades tags
            projects_repo.delete_project(conn, domain_id=dom, project_id="acme-perf-001")
            assert projects_repo.list_projects(conn, dom) == []
            assert tags_repo.doc_ids_for_project(conn, domain_id=dom, project_id="acme-perf-001") == []

            print("test_db_integration: all passed (live Lakebase, incl. lossless run round-trip)")
        finally:
            conn.execute(f'DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE')


if __name__ == "__main__":
    main()
