# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Vector Search Index (RETIRED)
# MAGIC
# MAGIC **This notebook is intentionally a no-op.**
# MAGIC
# MAGIC The app no longer depends on Databricks Vector Search. Runtime retrieval is
# MAGIC now served by a SQL keyword shim (`_vs_search`) in
# MAGIC `app/backend/docintel_routes.py`, which queries the plain Delta table
# MAGIC `{catalog}.{schema_vec}.document_chunks` directly (column `chunk_to_retrieve`).
# MAGIC
# MAGIC What this means:
# MAGIC - The `document_chunks` table is **still produced by `03_idp_pipeline.py`** and
# MAGIC   remains the single source of retrievable chunk text — nothing here is needed
# MAGIC   to populate it.
# MAGIC - The VS endpoint (`docintel-vs-endpoint`), the Delta Sync index
# MAGIC   (`{catalog}.{schema_vec}.{domain_id}_docs_index`), the embedding model
# MAGIC   (`databricks-gte-large-en`), and the metadata-enrichment columns that only
# MAGIC   existed to power VS hybrid filters (`risk_level`, `lot_number`, …) are no
# MAGIC   longer created or required.
# MAGIC - This task has been removed from both jobs in `databricks.yml` and from
# MAGIC   `scripts/create_domain_job.py`; the `agent` task now depends on
# MAGIC   `ontology_mapping` only.
# MAGIC
# MAGIC The notebook is kept (rather than deleted) so any externally pinned
# MAGIC `notebook_path` references resolve to a harmless no-op instead of a 404. It is
# MAGIC safe to delete once no orchestration references it.

# COMMAND ----------

print(
    "05_vector_search is retired — Vector Search has been removed. "
    "Retrieval is now SQL keyword search over document_chunks in the app backend. "
    "No action taken."
)

try:
    dbutils.notebook.exit("retired: vector search removed")  # noqa: F821
except Exception:
    pass
