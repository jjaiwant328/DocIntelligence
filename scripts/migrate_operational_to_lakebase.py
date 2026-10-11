"""One-time backfill: copy operational state from the Lakehouse to Lakebase.

Reads platform.projects + platform.document_project_tags from the SQL warehouse
and upserts them into the app's Lakebase `app` schema, so after the P1 cutover
the deployed app still sees existing projects/cases and their document tags.

Also grants the app service principal full DML on the (owner-created) tables.

Usage (from repo root):
  export DATABRICKS_CONFIG_PROFILE=jai-az-ws
  P=jai-az-ws
  export LB_HOST=$(databricks postgres list-endpoints projects/docintel/branches/production -p $P -o json | jq -r '.[0].status.hosts.host')
  export LB_TOKEN=$(databricks postgres generate-database-credential projects/docintel/branches/production/endpoints/primary -p $P -o json | jq -r '.token')
  export LB_EMAIL=$(databricks current-user me -p $P -o json | jq -r '.userName')
  .venv-test/bin/python scripts/migrate_operational_to_lakebase.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "backend"))

CATALOG = os.getenv("DOCINTEL_CATALOG", "jai_docintel")
WH_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "85a4ed5bcff25c0d")
SP = os.getenv("LAKEBASE_USER", "00ec2ab7-2445-4bc8-b68d-25e463b5bbe3")


def _warehouse_rows(sql: str) -> list[dict]:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState

    w = WorkspaceClient()
    r = w.statement_execution.execute_statement(warehouse_id=WH_ID, statement=sql, wait_timeout="50s")
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"warehouse read failed: {r.status.error}")
    cols = [c.name for c in (r.manifest.schema.columns or [])]
    return [dict(zip(cols, row)) for row in (r.result.data_array or [])]


def main():
    import json
    import psycopg
    from db import schema as _schema

    host, token, email = os.environ["LB_HOST"], os.environ["LB_TOKEN"], os.environ["LB_EMAIL"]

    projects = _warehouse_rows(f"""
        SELECT project_id, domain_id, name, municipality, state, address, parcel_id,
               status, created_by, owner, collaborators,
               CAST(created_at AS STRING) AS created_at,
               CAST(updated_at AS STRING) AS updated_at
        FROM {CATALOG}.platform.projects
    """)
    tags = _warehouse_rows(f"""
        SELECT domain_id, doc_id, project_id, scope, source, tagged_by,
               CAST(tagged_at AS STRING) AS tagged_at
        FROM {CATALOG}.platform.document_project_tags
    """)
    print(f"read {len(projects)} projects, {len(tags)} tags from Lakehouse")

    with psycopg.connect(host=host, port=5432, dbname=os.getenv("LB_DB", "docintel"),
                         user=email, password=token, sslmode="require", autocommit=True) as conn:
        conn.execute('SET search_path = "app", public')
        _schema.ensure_schema(conn)

        p_ok = 0
        for p in projects:
            collab = p.get("collaborators")
            if not collab or not str(collab).strip():
                collab = "[]"
            def _ts(v):
                return v if (v and str(v).strip()) else None
            conn.execute(
                """
                INSERT INTO projects (project_id, domain_id, name, municipality, state,
                    address, parcel_id, status, created_by, owner, collaborators,
                    created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,
                    COALESCE(%s::timestamptz, now()), COALESCE(%s::timestamptz, now()))
                ON CONFLICT (domain_id, project_id) DO UPDATE SET
                    name=EXCLUDED.name, municipality=EXCLUDED.municipality,
                    state=EXCLUDED.state, status=EXCLUDED.status,
                    owner=EXCLUDED.owner, collaborators=EXCLUDED.collaborators,
                    updated_at=EXCLUDED.updated_at
                """,
                (p.get("project_id"), p.get("domain_id"), p.get("name") or "",
                 p.get("municipality") or "", p.get("state") or "", p.get("address") or "",
                 p.get("parcel_id") or "", p.get("status") or "Active", p.get("created_by") or "",
                 p.get("owner") or "", collab, _ts(p.get("created_at")), _ts(p.get("updated_at"))),
            )
            p_ok += 1

        t_ok = 0
        t_skip = 0
        for t in tags:
            # 'universal'-scope legacy tags have no project_id; the project-scoped
            # read path never returns them, so skip rather than invent a sentinel.
            if not (t.get("project_id") and str(t.get("project_id")).strip()):
                t_skip += 1
                continue
            conn.execute(
                """
                INSERT INTO document_project_tags (domain_id, doc_id, project_id, scope,
                    source, tagged_by, tagged_at)
                VALUES (%s,%s,%s,%s,%s,%s, COALESCE(%s::timestamptz, now()))
                ON CONFLICT (domain_id, project_id, doc_id) DO NOTHING
                """,
                (t.get("domain_id"), t.get("doc_id"), t.get("project_id"),
                 t.get("scope") or "project", t.get("source") or "manual",
                 t.get("tagged_by") or "", (t.get("tagged_at") or None)),
            )
            t_ok += 1

        # Let the app SP read/write these owner-created tables (+ future ones).
        conn.execute(f'GRANT ALL ON ALL TABLES IN SCHEMA app TO "{SP}"')
        conn.execute(f'GRANT ALL ON ALL SEQUENCES IN SCHEMA app TO "{SP}"')
        conn.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL ON TABLES TO "{SP}"')
        conn.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL ON SEQUENCES TO "{SP}"')

        n_p = conn.execute("SELECT count(*) FROM projects").fetchone()[0]
        n_t = conn.execute("SELECT count(*) FROM document_project_tags").fetchone()[0]
        print(f"upserted {p_ok} projects, {t_ok} tags ({t_skip} universal tags skipped); "
              f"Lakebase now has {n_p} projects, {n_t} tags")


if __name__ == "__main__":
    main()
