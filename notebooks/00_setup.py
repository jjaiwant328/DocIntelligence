# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Setup
# MAGIC
# MAGIC Creates the `jai_docintel` catalog, all schemas, and the document Volume.
# MAGIC Run this notebook **once** before any other notebook in the project.
# MAGIC
# MAGIC **Workspace:** `jai-az-ws` — `https://adb-4101016551133680.0.azuredatabricks.net`

# COMMAND ----------

# ── Domain parameter ─────────────────────────────────────────────────────────
# Accept domain_id from a job parameter or widget; defaults to supply_chain
try:
    domain_id = dbutils.widgets.get("domain_id")
except Exception:
    domain_id = "supply_chain"

# Supply-chain uses the original schema layout (backward compatible).
# Every other domain gets its own schema prefix: {domain_id}_raw, etc.
if domain_id == "supply_chain":
    CATALOG      = "jai_docintel"
    SCHEMA_RAW   = "raw"
    SCHEMA_ONT   = "ontology"
    SCHEMA_VEC   = "vectors"
    SCHEMA_AGT   = "agents"
    VOLUME_DOCS  = "documents"
    DOMAIN_DESC  = "QSR Supply Chain Document Intelligence"
else:
    CATALOG      = "jai_docintel"
    SCHEMA_RAW   = f"{domain_id}"      # single schema per domain
    SCHEMA_ONT   = f"{domain_id}"
    SCHEMA_VEC   = f"{domain_id}"
    SCHEMA_AGT   = f"{domain_id}"
    VOLUME_DOCS  = "documents"
    DOMAIN_DESC  = f"{domain_id.replace('_', ' ').title()} Document Intelligence"

print(f"Setting up domain: {domain_id}")

# COMMAND ----------
# MAGIC %md ## 1. Catalog

# COMMAND ----------

spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG} COMMENT '{DOMAIN_DESC}'")
spark.sql(f"USE CATALOG {CATALOG}")
print(f"Catalog '{CATALOG}' ready")

# COMMAND ----------
# MAGIC %md ## 2. Schemas

# COMMAND ----------

all_schemas = {SCHEMA_RAW, SCHEMA_ONT, SCHEMA_VEC, SCHEMA_AGT}
schema_comments = {
    SCHEMA_RAW: f"[{domain_id}] Raw documents, parsed text, transactional tables",
    SCHEMA_ONT: f"[{domain_id}] Ontology entities, relationships, canonical identity map",
    SCHEMA_VEC: f"[{domain_id}] Document chunks, embeddings, Vector Search sync table",
    SCHEMA_AGT: f"[{domain_id}] AI agent traces, UC Function tools, evaluation results",
}
for schema in all_schemas:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{schema} COMMENT '{schema_comments[schema]}'")
    print(f"Schema '{CATALOG}.{schema}' ready")

# COMMAND ----------
# MAGIC %md ## 3. Document Volume

# COMMAND ----------

spark.sql(f"""
    CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA_RAW}.{VOLUME_DOCS}
    COMMENT 'Landing zone for {domain_id} documents (PDF, CSV, TXT)'
""")
print(f"Volume '{CATALOG}.{SCHEMA_RAW}.{VOLUME_DOCS}' ready")
print(f"Upload path: /Volumes/{CATALOG}/{SCHEMA_RAW}/{VOLUME_DOCS}/")

# COMMAND ----------
# MAGIC %md ## 4. Governance Tags

# COMMAND ----------

try:
    spark.sql(f"ALTER CATALOG {CATALOG} SET TAGS ('domain' = 'operations', 'project' = 'doc_intelligence')")
    for schema in [SCHEMA_RAW, SCHEMA_ONT, SCHEMA_VEC, SCHEMA_AGT]:
        spark.sql(f"ALTER SCHEMA {CATALOG}.{schema} SET TAGS ('sensitivity' = 'internal', 'owner' = 'operations')")
    print("Governance tags applied")
except Exception as e:
    print(f"Warning: tag policy restricted some tags — skipping ({e}). Pipeline continues.")

# COMMAND ----------
# MAGIC %md ## 5. Verify

# COMMAND ----------

display(spark.sql(f"SHOW SCHEMAS IN {CATALOG}"))

# COMMAND ----------

print(f"""
╔══════════════════════════════════════════════════════╗
║  jai_docintel setup complete                         ║
╠══════════════════════════════════════════════════════╣
║  Catalog : {CATALOG}
║  Schemas : raw, ontology, vectors, agents
║  Volume  : /Volumes/{CATALOG}/{SCHEMA_RAW}/{VOLUME_DOCS}/
╚══════════════════════════════════════════════════════╝
""")
