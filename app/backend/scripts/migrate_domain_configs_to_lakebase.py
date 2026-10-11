"""Idempotent one-time migration: copy domain_configs → Lakebase use_cases.

Reads every row from {CATALOG}.platform.domain_configs via the SQL warehouse,
JSON-parses the config columns, then upserts each row into the Lakebase
`use_cases` table using use_cases_repo.  Mirrors the style of
scripts/migrate_operational_to_lakebase.py (top-level scripts/ directory).

Usage:
  # Set env (Lakebase creds from CLI):
  export DATABRICKS_CONFIG_PROFILE=jai-az-ws
  P=jai-az-ws
  export LB_HOST=$(databricks postgres list-endpoints projects/docintel/branches/production -p $P -o json | jq -r '.[0].status.hosts.host')
  export LB_TOKEN=$(databricks postgres generate-database-credential projects/docintel/branches/production/endpoints/primary -p $P -o json | jq -r '.token')
  export LB_EMAIL=$(databricks current-user me -p $P -o json | jq -r '.userName')
  export LAKEBASE_ENABLED=true

  # Dry-run (prints, writes nothing):
  ../../.venv-test/bin/python scripts/migrate_domain_configs_to_lakebase.py --dry-run

  # Live run:
  ../../.venv-test/bin/python scripts/migrate_domain_configs_to_lakebase.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Allow imports from app/backend when invoked from that directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CATALOG = os.getenv("DOCINTEL_CATALOG", "jai_docintel")
WH_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "85a4ed5bcff25c0d")


def _warehouse_rows(sql: str) -> list[dict]:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState

    w = WorkspaceClient()
    r = w.statement_execution.execute_statement(
        warehouse_id=WH_ID, statement=sql, wait_timeout="50s"
    )
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"warehouse read failed: {r.status.error}")
    cols = [c.name for c in (r.manifest.schema.columns or [])]
    return [dict(zip(cols, row)) for row in (r.result.data_array or [])]


def _parse_json_col(val, default):
    """Return a parsed Python object from a JSON string column (or default)."""
    if val is None or str(val).strip() in ("", "null"):
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return default


def _domain_name(domain_id: str) -> str:
    """Convert 'supply_chain' → 'Supply Chain' for the use_case name."""
    return " ".join(w.capitalize() for w in domain_id.replace("-", "_").split("_"))


def main(dry_run: bool = False) -> None:
    mode = "DRY-RUN" if dry_run else "LIVE"
    print(f"[migrate_domain_configs] mode={mode} catalog={CATALOG}")

    # ── Step 1: Read domain_configs from the SQL warehouse ────────────────────
    rows = _warehouse_rows(f"""
        SELECT domain_id, classification_labels, extraction_schemas,
               agent_system_prompt
        FROM {CATALOG}.platform.domain_configs
    """)
    print(f"[migrate_domain_configs] read {len(rows)} rows from domain_configs")

    if dry_run:
        for row in rows:
            domain_id = row.get("domain_id", "")
            classification_labels = _parse_json_col(row.get("classification_labels"), {})
            extraction_schemas = _parse_json_col(row.get("extraction_schemas"), {})
            agent_system_prompt = row.get("agent_system_prompt") or ""
            print(
                f"  WOULD upsert use_case: use_case_id={domain_id!r}"
                f" name={_domain_name(domain_id)!r}"
                f" labels={list(classification_labels.keys()) if isinstance(classification_labels, dict) else '...'}"
                f" schemas={list(extraction_schemas.keys()) if isinstance(extraction_schemas, dict) else '...'}"
                f" prompt_len={len(agent_system_prompt)}"
            )
        print("[migrate_domain_configs] dry-run complete; nothing written")
        return

    # ── Step 2: Upsert into Lakebase use_cases ─────────────────────────────────
    import psycopg
    from db import schema as _schema
    from db.repositories import use_cases_repo

    host = os.environ["LB_HOST"]
    token = os.environ["LB_TOKEN"]
    email = os.environ["LB_EMAIL"]
    lb_db = os.getenv("LB_DB", "docintel")

    with psycopg.connect(
        host=host, port=5432, dbname=lb_db,
        user=email, password=token,
        sslmode="require", autocommit=True,
    ) as conn:
        conn.execute('SET search_path = "app", public')
        _schema.ensure_schema(conn)

        ok = 0
        for row in rows:
            domain_id = row.get("domain_id", "")
            if not domain_id:
                continue

            before = use_cases_repo.get_use_case(conn, domain_id)
            classification_labels = _parse_json_col(row.get("classification_labels"), {})
            extraction_schemas = _parse_json_col(row.get("extraction_schemas"), {})
            agent_system_prompt = row.get("agent_system_prompt") or ""

            after = use_cases_repo.upsert_use_case(
                conn,
                domain_id,
                name=_domain_name(domain_id),
                status="active",
                classification_labels=classification_labels,
                extraction_schemas=extraction_schemas,
                agent_system_prompt=agent_system_prompt,
            )

            diff = []
            if before is None:
                diff.append("NEW")
            else:
                for k in ("name", "status", "agent_system_prompt"):
                    if before.get(k) != after.get(k):
                        diff.append(f"{k}: {before.get(k)!r} → {after.get(k)!r}")
            print(
                f"  upserted {domain_id!r}"
                + (f" ({', '.join(diff)})" if diff else " (no change)")
            )
            ok += 1

        n = conn.execute("SELECT count(*) FROM use_cases").fetchone()[0]
        print(f"[migrate_domain_configs] upserted {ok} rows; "
              f"use_cases table now has {n} rows")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Migrate domain_configs rows to Lakebase use_cases."
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be written; make no changes to Lakebase.",
    )
    args = ap.parse_args()
    main(dry_run=args.dry_run)
