"""Seed a synthetic, cross-referenced document corpus for a use case, with
deliberate discrepancies baked in so the reconcile workflow has real findings.

Creates {catalog}.{use_case}.parsed_documents (the columns the app reads:
doc_id, doc_type, parsed_content, processed_ts), inserts the corpus, and tags
each doc to the use case's project (Lakebase). This is the fast demo path; the
same schema is what the ai_parse → classify pipeline populates from real PDFs.

Usage (repo root):
  export DATABRICKS_CONFIG_PROFILE=jai-az-ws
  P=jai-az-ws
  export LB_HOST=$(databricks postgres list-endpoints projects/docintel/branches/production -p $P -o json | jq -r '.[0].status.hosts.host')
  export LB_TOKEN=$(databricks postgres generate-database-credential projects/docintel/branches/production/endpoints/primary -p $P -o json | jq -r '.token')
  export LB_EMAIL=$(databricks current-user me -p $P -o json | jq -r '.userName')
  .venv-test/bin/python scripts/seed_synthetic_usecase.py supplier_performance
  .venv-test/bin/python scripts/seed_synthetic_usecase.py ap_three_way_match
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "backend"))

CATALOG = os.getenv("DOCINTEL_CATALOG", "jai_docintel")
WH_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "85a4ed5bcff25c0d")

# doc_id, doc_type, content — discrepancies are intentional (see comments)
CORPORA = {
    "supplier_performance": [
        ("C1", "master_contract",
         "SUPPLY AGREEMENT. Supplier: Acme Foods Inc. Contract No. ACME-2026. "
         "SKU-100 canned tomatoes. Agreed unit price: $10.00 per case. Lead time: 5 days. "
         "On-time delivery SLA: 95%. Late-delivery penalty: 2% of line value per day late. "
         "Effective 2026-01-01 to 2026-12-31."),
        ("D1", "delivery_schedule",
         "DELIVERY SCHEDULE. Supplier: Acme Foods Inc. PO-501. SKU-100.\n"
         "Line 1: promised 2026-03-01, actual 2026-03-01, qty 100 (on time).\n"
         "Line 2: promised 2026-03-08, actual 2026-03-15, qty 100 (7 days late).\n"
         "Line 3: promised 2026-03-15, actual 2026-03-16, qty 100 (1 day late)."),
        # matches contract exactly
        ("I1", "invoice",
         "INVOICE INV-9001. Acme Foods Inc. PO-501. SKU-100. Qty 100. Unit price $10.00. "
         "Total $1,000.00. Invoice date 2026-03-02."),
        # overbilled: $12 vs contracted $10 → $200 impact
        ("I2", "invoice",
         "INVOICE INV-9002. Acme Foods Inc. PO-501. SKU-100. Qty 100. Unit price $12.00. "
         "Total $1,200.00. Invoice date 2026-03-16."),
        # over-quantity: billed 120 vs delivered 100
        ("I3", "invoice",
         "INVOICE INV-9003. Acme Foods Inc. PO-501. SKU-100. Qty 120. Unit price $10.00. "
         "Total $1,200.00. Invoice date 2026-03-20."),
    ],
    "ap_three_way_match": [
        ("P1", "purchase_order",
         "PURCHASE ORDER PO-777. Vendor: Globex Parts LLC. SKU-A widget. "
         "Quantity 50. Unit price $20.00. Total $1,000.00."),
        # received only 48 of 50
        ("G1", "goods_receipt",
         "GOODS RECEIPT GRN-500 against PO-777. Vendor: Globex Parts LLC. SKU-A. "
         "Quantity received 48. Received date 2026-04-10."),
        # over-quantity: bills 50 vs 48 received
        ("I1", "invoice",
         "INVOICE INV-3001. Vendor: Globex Parts LLC. PO-777. SKU-A. Qty 50. Unit price $20.00. "
         "Total $1,000.00. Invoice date 2026-04-11."),
        # overbilled price: $25 vs PO $20
        ("I2", "invoice",
         "INVOICE INV-3002. Vendor: Globex Parts LLC. PO-777. SKU-A. Qty 50. Unit price $25.00. "
         "Total $1,250.00. Invoice date 2026-04-12."),
        # no matching PO/GRN (PO-888 not present) → receipt_exists finding
        ("I3", "invoice",
         "INVOICE INV-3003. Vendor: Globex Parts LLC. PO-888. SKU-B. Qty 10. Unit price $5.00. "
         "Total $50.00. Invoice date 2026-04-13."),
        # duplicate of INV-3001 (same PO+SKU+amount)
        ("I4", "invoice",
         "INVOICE INV-3004. Vendor: Globex Parts LLC. PO-777. SKU-A. Qty 50. Unit price $20.00. "
         "Total $1,000.00. Invoice date 2026-04-14."),
    ],
}


def _wh(w, sql):
    from databricks.sdk.service.sql import StatementState
    r = w.statement_execution.execute_statement(warehouse_id=WH_ID, statement=sql, wait_timeout="50s")
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"SQL failed: {r.status.error}\n{sql[:200]}")
    return r


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in CORPORA:
        print(f"usage: seed_synthetic_usecase.py <{'|'.join(CORPORA)}>")
        sys.exit(2)
    use_case = sys.argv[1]
    docs = CORPORA[use_case]
    schema = use_case  # single-schema layout

    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()

    _wh(w, f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{schema}")
    _wh(w, f"""
        CREATE TABLE IF NOT EXISTS {CATALOG}.{schema}.parsed_documents (
            doc_id STRING, doc_type STRING, parsed_content STRING, processed_ts TIMESTAMP
        ) USING DELTA
    """)
    # idempotent: clear this corpus first
    ids = ", ".join("'" + d[0] + "'" for d in docs)
    _wh(w, f"DELETE FROM {CATALOG}.{schema}.parsed_documents WHERE doc_id IN ({ids})")
    values = ",\n".join(
        f"('{d[0]}', '{d[1]}', '{d[2].replace(chr(39), chr(39)+chr(39))}', current_timestamp())"
        for d in docs
    )
    _wh(w, f"INSERT INTO {CATALOG}.{schema}.parsed_documents (doc_id, doc_type, parsed_content, processed_ts) VALUES {values}")
    print(f"seeded {len(docs)} docs into {CATALOG}.{schema}.parsed_documents")

    # tag docs to the use case's project (project_id == use_case_id) in Lakebase
    os.environ["LAKEBASE_ENABLED"] = "true"
    os.environ.setdefault("LAKEBASE_HOST", os.environ.get("LB_HOST", ""))
    os.environ.setdefault("LAKEBASE_USER", os.environ.get("LB_EMAIL", ""))
    from db import lakebase
    tok = os.environ["LB_TOKEN"]
    lakebase._manager = lakebase._Manager(
        token_provider=lambda: (tok, time.time() + 3600),
        user_resolver=lambda: os.environ["LB_EMAIL"])
    from db import operational as opstore
    n = opstore.add_tags(domain_id=use_case, project_id=use_case,
                         doc_ids=[d[0] for d in docs], tagged_by="seed")
    print(f"tagged {n} docs to project '{use_case}' in Lakebase")


if __name__ == "__main__":
    main()
