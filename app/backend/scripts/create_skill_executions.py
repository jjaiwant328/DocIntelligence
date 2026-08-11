"""Idempotent DDL: create platform.skill_executions on the workspace.

Usage: python app/backend/scripts/create_skill_executions.py [--profile jai-az-ws]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from databricks.sdk import WorkspaceClient

CATALOG = os.getenv("DOCINTEL_CATALOG", "jai_docintel")
WH_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "85a4ed5bcff25c0d")

DDL = f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.platform.skill_executions (
    execution_id     STRING,
    skill_id         STRING,
    skill_version    STRING,
    workflow_id      STRING,
    workflow_version STRING,
    work_object_id   STRING,
    start_time       TIMESTAMP,
    end_time         TIMESTAMP,
    status           STRING,
    error            STRING,
    model            STRING,
    evidence_count   INT,
    inputs_digest    STRING
) USING DELTA
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="jai-az-ws")
    ap.add_argument("--warehouse", default=WH_ID)
    args = ap.parse_args()

    w = WorkspaceClient(profile=args.profile)
    print(f"Creating {CATALOG}.platform.skill_executions on {args.profile} ...")
    resp = w.statement_execution.execute_statement(
        warehouse_id=args.warehouse, statement=DDL, wait_timeout="30s")
    print("state:", resp.status.state)
    # verify
    check = w.statement_execution.execute_statement(
        warehouse_id=args.warehouse,
        statement=f"SHOW TABLES IN {CATALOG}.platform LIKE 'skill_executions'",
        wait_timeout="30s")
    rows = check.result.data_array if check.result else None
    print("exists:", bool(rows))


if __name__ == "__main__":
    main()
