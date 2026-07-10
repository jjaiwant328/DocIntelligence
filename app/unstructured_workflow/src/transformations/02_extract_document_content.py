# Databricks notebook source
# MAGIC %md
# MAGIC # Extract Text from Parsed Documents (Incremental)
# MAGIC
# MAGIC Reads `parsed_documents_raw` and extracts clean text into `parsed_documents_content`.
# MAGIC Only processes **new paths** — rows whose `path` is not already present in the
# MAGIC output table — so re-running this notebook is always safe and efficient.

# COMMAND ----------

dbutils.widgets.text("catalog",            "fins_genai",                "Catalog name")
dbutils.widgets.text("schema",             "unstructured_documents",    "Schema name")
dbutils.widgets.text("source_table_name",  "parsed_documents_raw",      "Source table name")
dbutils.widgets.text("table_name",         "parsed_documents_content",  "Output table name")

catalog           = dbutils.widgets.get("catalog")
schema            = dbutils.widgets.get("schema")
source_table_name = dbutils.widgets.get("source_table_name")
table_name        = dbutils.widgets.get("table_name")

# COMMAND ----------

spark.sql(f"USE CATALOG {catalog}")
spark.sql(f"USE SCHEMA {schema}")

print("=" * 70)
print("  DocIntelligence — Extract Document Content (Incremental)")
print("=" * 70)
print(f"  Source: {catalog}.{schema}.{source_table_name}")
print(f"  Output: {catalog}.{schema}.{table_name}")

# COMMAND ----------

from pyspark.sql import functions as F

# ── Load source (deduplicated to latest parse per file) ───────────────────────
from pyspark.sql import Window as _W

raw_all = spark.table(f"{catalog}.{schema}.{source_table_name}")
raw_df = (
    raw_all
    .withColumn("_rn", F.row_number().over(
        _W.partitionBy("path").orderBy(F.col("parsed_at").desc())
    ))
    .filter("_rn = 1")
    .drop("_rn")
)

# ── Identify new paths not yet in the content table ──────────────────────────
try:
    existing_paths = {
        r["path"]
        for r in spark.table(f"{catalog}.{schema}.{table_name}").select("path").collect()
    }
    print(f"  Already extracted: {len(existing_paths)} files")
except Exception:
    existing_paths = set()
    print("  Content table does not exist yet — will create it")

new_df = raw_df.filter(~F.col("path").isin(list(existing_paths))) if existing_paths else raw_df
new_count = new_df.count()
print(f"  New files to extract: {new_count}")

if new_count == 0:
    print("  Nothing new to extract — exiting.")
    dbutils.notebook.exit("No new documents to extract")

# COMMAND ----------

# MAGIC %md ## Extract text from parsed VARIANT

# COMMAND ----------

text_df = (
    new_df.withColumn(
        "content",
        F.when(
            F.expr("try_cast(parsed:error_status AS STRING)").isNotNull(),
            F.lit(None).cast("string"),
        ).otherwise(
            F.concat_ws(
                "\n\n",
                F.expr("""
                    transform(
                        try_cast(parsed:document:elements AS ARRAY<VARIANT>),
                        el -> (
                            CASE WHEN try_cast(el:type AS STRING) = 'figure'
                                 THEN try_cast(el:description AS STRING)
                                 ELSE try_cast(el:content AS STRING)
                            END
                        )
                    )
                """),
            )
        ),
    )
    .withColumn("error_status", F.expr("try_cast(parsed:error_status AS STRING)"))
    .withColumn("processed_at",  F.current_timestamp())
    .select("path", "content", "error_status", "parsed_at", "processed_at")
)

text_df.write.format("delta") \
    .mode("append") \
    .option("mergeSchema", "true") \
    .saveAsTable(f"{catalog}.{schema}.{table_name}")

print(f"✅ Extracted content for {new_count} new documents → {catalog}.{schema}.{table_name}")

# COMMAND ----------

total = spark.table(f"{catalog}.{schema}.{table_name}").count()
print("=" * 70)
print(f"  Extraction complete — {catalog}.{schema}.{table_name}: {total} total rows")
print("=" * 70)
