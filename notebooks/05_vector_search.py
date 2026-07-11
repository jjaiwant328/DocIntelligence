# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Vector Search Index
# MAGIC
# MAGIC Builds a Databricks Vector Search Delta Sync index from `ai_prep_search` chunks.
# MAGIC
# MAGIC ## Pipeline
# MAGIC ```
# MAGIC  ai_parse_document
# MAGIC      │  (upstream: unstructured_workflow or 03_idp_pipeline)
# MAGIC      ▼
# MAGIC  ai_prep_search   ──►  document_chunks table
# MAGIC      │               chunk_id  (PK)
# MAGIC      │               chunk_to_embed   ← fed to embedding model
# MAGIC      │               chunk_to_retrieve ← returned to LLM in RAG
# MAGIC      ▼
# MAGIC  Vector Search Delta Sync Index
# MAGIC      │  embedding_source_column = chunk_to_embed
# MAGIC      │  primary_key             = chunk_id
# MAGIC      ▼
# MAGIC  vector_search()  ──►  top-k chunks for RAG
# MAGIC ```
# MAGIC
# MAGIC **Note:** This notebook requires `ai_prep_search` output in `{SCHEMA_VEC}.document_chunks`.
# MAGIC Run `03_idp_pipeline` first to produce that table.

# COMMAND ----------

# MAGIC %pip install databricks-vectorsearch --quiet

# COMMAND ----------

from pyspark.sql import functions as F
import time

CATALOG = "jai_docintel"

# ── Domain parameter ─────────────────────────────────────────────────────────
try:
    domain_id = dbutils.widgets.get("domain_id")
except Exception:
    domain_id = "supply_chain"

def _domain_schemas_vs(catalog, domain_id):
    try:
        rows = spark.sql(f"""
            SELECT schema_raw, schema_vec
            FROM {catalog}.platform.domain_configs
            WHERE domain_id = '{domain_id}' LIMIT 1
        """).collect()
        if rows:
            return rows[0]["schema_raw"] or "raw", rows[0]["schema_vec"] or "vectors"
    except Exception:
        pass
    return ("raw", "vectors")

SCHEMA_RAW, SCHEMA_VEC = _domain_schemas_vs(CATALOG, domain_id)
VS_ENDPOINT  = "docintel-vs-endpoint"
VS_INDEX     = f"{CATALOG}.{SCHEMA_VEC}.{domain_id}_docs_index"
EMBED_MODEL  = "databricks-gte-large-en"
CHUNKS_TABLE = f"{CATALOG}.{SCHEMA_VEC}.document_chunks"

print(f"Domain      : {domain_id}")
print(f"Chunks table: {CHUNKS_TABLE}")
print(f"VS index    : {VS_INDEX}")
print(f"Embed model : {EMBED_MODEL}")
spark.sql(f"USE CATALOG {CATALOG}")

# COMMAND ----------
# MAGIC %md ## Step 1 — Verify ai_prep_search chunks are available

# COMMAND ----------

try:
    chunks_df   = spark.table(CHUNKS_TABLE)
    chunk_count = chunks_df.count()
    if chunk_count == 0:
        raise ValueError("document_chunks table is empty. Run 03_idp_pipeline first to produce ai_prep_search chunks.")
    print(f"✓ {chunk_count} chunks in {CHUNKS_TABLE}")
    display(chunks_df.select("chunk_id", "doc_type", "chunk_to_embed", "chunk_to_retrieve").limit(5))
except Exception as e:
    print(f"ERROR: {e}")
    print("Run 03_idp_pipeline with ai_prep_search enabled before running this notebook.")
    dbutils.notebook.exit("Prerequisite: run 03_idp_pipeline first")

# COMMAND ----------
# MAGIC %md ## Step 2 — Enrich chunks with extracted metadata (optional but recommended)
# MAGIC
# MAGIC Joins key identifiers from `extracted_fields` so filters like `lot_number = 'X'`
# MAGIC work in vector_search() hybrid queries.

# COMMAND ----------

def _load_chunk_metadata():
    """Pull key identifiers from extracted_fields to attach to chunks."""
    try:
        return spark.sql(f"""
            SELECT doc_id, field_name, field_value
            FROM {CATALOG}.{SCHEMA_RAW}.extracted_fields
            WHERE field_name IN ('shipment_id','lot_number','supplier_name',
                                 'trailer_id','recall_number','reference_number',
                                 'issuing_party','geographic_location',
                                 'entity_name','regulation_id','violation_type')
        """).collect()
    except Exception as e:
        print(f"Could not load extracted metadata ({e}) — skipping enrichment.")
        return []

meta_rows_raw = _load_chunk_metadata()
meta: dict = {}
for r in meta_rows_raw:
    if r.doc_id not in meta:
        meta[r.doc_id] = {}
    meta[r.doc_id][r.field_name] = r.field_value

def _risk_level(doc_type: str) -> str:
    if doc_type in ("recall_notice",):
        return "critical"
    if doc_type in ("temperature_log", "quality_incident_report", "maintenance_report",
                    "violation_notice", "corrective_action_plan"):
        return "high"
    if doc_type in ("certificate_of_analysis", "email_chain", "supplier_scorecard",
                    "inspection_report", "delivery_exception", "permit_application",
                    "regulatory_correspondence", "vendor_audit_report"):
        return "medium"
    return "low"

from pyspark.sql.types import StringType
risk_udf = F.udf(_risk_level, StringType())

# Build metadata DataFrame and join to chunks
META_COLS = ["shipment_id", "lot_number", "supplier", "trailer_id",
             "recall_number", "reference_number", "issuing_party", "location",
             "entity_name", "regulation_id", "risk_level"]

if meta:
    meta_rows = [
        (doc_id,
         v.get("shipment_id"), v.get("lot_number"), v.get("supplier_name"),
         v.get("trailer_id"), v.get("recall_number"),
         v.get("reference_number"), v.get("issuing_party"), v.get("geographic_location"),
         v.get("entity_name"), v.get("regulation_id"), None)
        for doc_id, v in meta.items()
    ]
    meta_df = spark.createDataFrame(
        meta_rows,
        ["doc_id", "shipment_id", "lot_number", "supplier", "trailer_id",
         "recall_number", "reference_number", "issuing_party", "location",
         "entity_name", "regulation_id", "risk_level"]
    )
    enriched_df = chunks_df.join(meta_df.drop("risk_level"), on="doc_id", how="left")
else:
    enriched_df = chunks_df
    for col in META_COLS[:-1]:  # all except risk_level
        if col not in [c.name for c in enriched_df.schema]:
            enriched_df = enriched_df.withColumn(col, F.lit(None).cast("string"))

# A fresh domain's first run has no risk_level yet: 03_idp_pipeline creates
# document_chunks without it, and the meta join above drops it — so guarantee
# the column exists before referencing it (no-op once Step 3 has added it).
if "risk_level" not in enriched_df.columns:
    enriched_df = enriched_df.withColumn("risk_level", F.lit(None).cast("string"))

enriched_df = enriched_df.withColumn(
    "risk_level",
    F.when(F.col("risk_level").isNotNull(), F.col("risk_level"))
     .otherwise(risk_udf(F.col("doc_type")))
)

print(f"Enriched chunks: {enriched_df.count()} rows")

# COMMAND ----------
# MAGIC %md ## Step 3 — Ensure document_chunks table has metadata columns & CDF enabled

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA_VEC}")

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {CHUNKS_TABLE} (
        chunk_id          STRING NOT NULL,
        doc_id            STRING,
        doc_type          STRING,
        chunk_position    INT,
        chunk_to_retrieve STRING,
        chunk_to_embed    STRING,
        source_uri        STRING,
        shipment_id       STRING,
        lot_number        STRING,
        supplier          STRING,
        trailer_id        STRING,
        recall_number     STRING,
        reference_number  STRING,
        issuing_party     STRING,
        location          STRING,
        entity_name       STRING,
        regulation_id     STRING,
        risk_level        STRING
    )
    TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")

# Add any missing metadata columns to the live table (idempotent)
existing_cols = {c.name for c in spark.table(CHUNKS_TABLE).schema}
for col in META_COLS:
    if col not in existing_cols:
        try:
            spark.sql(f"ALTER TABLE {CHUNKS_TABLE} ADD COLUMN IF NOT EXISTS {col} STRING")
            print(f"  Added column: {col}")
        except Exception as _ae:
            print(f"  Could not add {col}: {_ae}")

# Update metadata on the latest batch of chunks (merge by chunk_id)
new_doc_ids = [r.doc_id for r in enriched_df.select("doc_id").distinct().collect()]
if new_doc_ids and meta:
    ids_lit = ", ".join(f"'{d}'" for d in new_doc_ids)
    for doc_id, v in meta.items():
        if doc_id not in new_doc_ids:
            continue
        set_parts = []
        for k, col in [("shipment_id","shipment_id"),("lot_number","lot_number"),
                        ("supplier_name","supplier"),("trailer_id","trailer_id"),
                        ("recall_number","recall_number"),("geographic_location","location")]:
            if v.get(k):
                val = v[k].replace("'", "\\'")
                set_parts.append(f"{col} = '{val}'")
        if set_parts:
            try:
                spark.sql(f"""
                    UPDATE {CHUNKS_TABLE}
                    SET {', '.join(set_parts)}
                    WHERE doc_id = '{doc_id}'
                """)
            except Exception as _ue:
                pass

# Update risk_level where missing
try:
    spark.sql(f"""
        UPDATE {CHUNKS_TABLE}
        SET risk_level = CASE
            WHEN doc_type = 'recall_notice'                             THEN 'critical'
            WHEN doc_type IN ('temperature_log','quality_incident_report',
                              'maintenance_report','violation_notice',
                              'corrective_action_plan')                 THEN 'high'
            WHEN doc_type IN ('certificate_of_analysis','email_chain',
                              'supplier_scorecard','inspection_report',
                              'delivery_exception','permit_application',
                              'regulatory_correspondence','vendor_audit_report') THEN 'medium'
            ELSE 'low'
        END
        WHERE risk_level IS NULL
    """)
except Exception as _re:
    print(f"Risk level update (non-fatal): {_re}")

print(f"document_chunks table ready: {spark.table(CHUNKS_TABLE).count()} total rows")

# COMMAND ----------
# MAGIC %md ## Step 4 — Create or Sync Vector Search Endpoint & Delta Sync Index
# MAGIC
# MAGIC Schema:
# MAGIC - **`chunk_id`** — primary key
# MAGIC - **`chunk_to_embed`** — fed to the embedding model (context-enriched by `ai_prep_search`)
# MAGIC - **`chunk_to_retrieve`** — returned to the LLM in RAG answers

# COMMAND ----------

from databricks.vector_search.client import VectorSearchClient

vsc = VectorSearchClient()

def _wait_ready(endpoint: str, index_name: str, max_sec: int = 600, poll: int = 20):
    print(f"Waiting for '{index_name}' to be READY…")
    waited = 0
    while waited < max_sec:
        desc  = vsc.get_index(endpoint, index_name).describe()
        state = desc.get("status", {})
        if state.get("ready", False):
            print(f"  ✓ READY after {waited}s")
            return True
        print(f"  [{waited}s] {state.get('message','')[:100]}")
        time.sleep(poll)
        waited += poll
    raise TimeoutError(f"Index not READY after {max_sec}s")


# ── Ensure VS endpoint exists ─────────────────────────────────────────────────
existing_endpoints = [e["name"] for e in vsc.list_endpoints().get("endpoints", [])]
if VS_ENDPOINT not in existing_endpoints:
    print(f"Creating VS endpoint: {VS_ENDPOINT}")
    vsc.create_endpoint(name=VS_ENDPOINT, endpoint_type="STANDARD")
    for _ in range(40):
        ep = vsc.get_endpoint(VS_ENDPOINT)
        if ep.get("endpoint_status", {}).get("state") == "ONLINE":
            print("  ✓ Endpoint ONLINE")
            break
        time.sleep(30)
else:
    print(f"✓ VS endpoint '{VS_ENDPOINT}' exists")

# ── Create or sync Delta Sync index ───────────────────────────────────────────
existing_indexes = [
    i.get("name", "")
    for i in vsc.list_indexes(VS_ENDPOINT).get("vector_indexes", [])
]

def _create_index():
    vsc.create_delta_sync_index(
        endpoint_name                 = VS_ENDPOINT,
        index_name                    = VS_INDEX,
        source_table_name             = CHUNKS_TABLE,
        pipeline_type                 = "TRIGGERED",
        primary_key                   = "chunk_id",
        embedding_source_column       = "chunk_to_embed",
        embedding_model_endpoint_name = EMBED_MODEL,
    )
    _wait_ready(VS_ENDPOINT, VS_INDEX)

if VS_INDEX not in existing_indexes:
    print(f"Creating Delta Sync index: {VS_INDEX}")
    _create_index()
else:
    print(f"VS index '{VS_INDEX}' exists — triggering sync…")
    try:
        vsc.get_index(VS_ENDPOINT, VS_INDEX).sync()
        _wait_ready(VS_ENDPOINT, VS_INDEX)
    except Exception as _sync_err:
        print(f"Sync failed ({_sync_err}) — deleting stale index and recreating…")
        try:
            vsc.delete_index(VS_ENDPOINT, VS_INDEX)
            import time as _t; _t.sleep(10)
        except Exception as _del_err:
            print(f"  Delete warning: {_del_err}")
        _create_index()

# COMMAND ----------
# MAGIC %md ## Step 5 — Validate with vector_search() retrieval

# COMMAND ----------

_wait_ready(VS_ENDPOINT, VS_INDEX)
index = vsc.get_index(VS_ENDPOINT, VS_INDEX)

test_query = f"key issues risks violations in {domain_id.replace('_', ' ')} documents"
print(f"Test query: '{test_query}'")

# Build column list from what is actually in the index
_idx_schema_cols = set()
try:
    _idx_desc = index.describe()
    for _ef in _idx_desc.get("delta_sync_index_spec", {}).get("embedding_vector_columns", []):
        pass
    _idx_schema_cols = {c["name"] for c in _idx_desc.get("delta_sync_index_spec", {}).get("columns_to_sync", [])}
except Exception:
    pass

_fetch_cols = [c for c in ["chunk_id", "doc_type", "chunk_to_retrieve", "risk_level"] if not _idx_schema_cols or c in _idx_schema_cols]
if not _fetch_cols:
    _fetch_cols = ["chunk_id", "doc_type"]

try:
    results = index.similarity_search(
        query_text  = test_query,
        columns     = _fetch_cols,
        num_results = 5,
    )
    for r in results.get("result", {}).get("data_array", []):
        print(f"  {dict(zip(_fetch_cols, r))}")
except Exception as _qs_err:
    print(f"Test query warning (non-fatal): {_qs_err}")

# COMMAND ----------
# MAGIC %md ## Summary

# COMMAND ----------

final_count = spark.table(CHUNKS_TABLE).count()
print("=" * 70)
print(f"  Vector Search Setup Complete — domain: {domain_id}")
print("=" * 70)
print(f"  Pipeline       : ai_parse_document → ai_prep_search → VS index → vector_search()")
print(f"  Chunks table   : {CHUNKS_TABLE}  ({final_count} rows)")
print(f"  Embed column   : chunk_to_embed   (context-enriched by ai_prep_search)")
print(f"  Retrieve column: chunk_to_retrieve")
print(f"  Primary key    : chunk_id")
print(f"  VS endpoint    : {VS_ENDPOINT}")
print(f"  VS index       : {VS_INDEX}")
print(f"  Embed model    : {EMBED_MODEL}")
print("=" * 70)
