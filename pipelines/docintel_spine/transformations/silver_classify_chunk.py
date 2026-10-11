"""Silver — classify documents and produce search-ready chunks.

Ports Silver Steps 2-3 of the old `03_idp_pipeline.py`:
  - silver_classified : ai_classify → doc_type (labels from domain_configs)
  - silver_chunks     : ai_prep_search → context-enriched chunks for Vector Search

Config-driven: classification labels come from
`platform.domain_configs` for the pipeline's `domain_id`.
"""
import json

from pyspark import pipelines as dp
from pyspark.sql import functions as F

CATALOG = spark.conf.get("catalog", "jai_docintel")
DOMAIN_ID = spark.conf.get("domain_id", "supply_chain")
CLASSIFY_INSTRUCTIONS = "Classify this document into exactly one of the provided types based on its content."


def _load_labels_sql():
    """Read classification labels from the domain registry at execution time."""
    rows = spark.sql(
        f"SELECT classification_labels FROM {CATALOG}.platform.domain_configs WHERE domain_id = '{DOMAIN_ID}' LIMIT 1"
    ).collect()
    labels_raw = rows[0]["classification_labels"] if rows else None
    if not labels_raw:
        raise ValueError(f"No classification_labels configured for domain '{DOMAIN_ID}' in {CATALOG}.platform.domain_configs")
    parsed = json.loads(labels_raw)
    if isinstance(parsed, list):  # normalize a bare list into {label: description}
        parsed = {x: f"A {x.replace('_', ' ')} document." for x in parsed}
    return json.dumps(parsed).replace("'", "\\'")


@dp.materialized_view(
    name="silver_classified",
    comment="Documents with an ai_classify doc_type label (labels from domain_configs).",
)
def silver_classified():
    _labels_sql = _load_labels_sql()
    _instr_sql = CLASSIFY_INSTRUCTIONS.replace("'", "\\'")
    return (
        spark.read.table("bronze_parsed_raw")
        .filter("TRY_CAST(parsed:error_status AS STRING) IS NULL")
        .select(
            F.col("path"),
            F.element_at(F.split(F.col("path"), "/"), -1).alias("doc_id"),
            F.col("parsed").alias("parsed_content"),
            F.col("source_file"),
            F.expr(
                f"ai_classify(parsed, '{_labels_sql}', MAP('instructions', '{_instr_sql}'))"
            ).alias("classification"),
        )
        .withColumn("doc_type", F.expr("classification:response[0]::STRING"))
        .select("path", "doc_id", "doc_type", "parsed_content", "source_file")
    )


CHUNK_SIZE = 2000  # chars per fallback chunk
MIN_CHUNK = 30


@dp.materialized_view(
    name="silver_chunks",
    comment="Search chunks: ai_prep_search where available (PDF/image), content-split fallback otherwise (e.g. TXT).",
)
def silver_chunks():
    classified = spark.read.table("silver_classified")

    # ── Primary: ai_prep_search (works on native ai_parse_document output) ──────
    prep = (
        classified.filter("TRY_CAST(parsed_content:error_status AS STRING) IS NULL")
        .select("doc_id", "doc_type", "source_file", F.expr("ai_prep_search(parsed_content)").alias("prep_result"))
        .filter("TRY_CAST(prep_result:error_status AS STRING) IS NULL")
        .selectExpr(
            "doc_id",
            "doc_type",
            "source_file",
            "explode(try_cast(prep_result:document.contents AS ARRAY<VARIANT>)) AS chunk",
        )
        .selectExpr(
            "doc_id",
            "doc_type",
            "source_file",
            "chunk:chunk_id::STRING          AS chunk_id",
            "chunk:chunk_position::INT       AS chunk_position",
            "chunk:chunk_to_retrieve::STRING AS chunk_to_retrieve",
            "chunk:chunk_to_embed::STRING    AS chunk_to_embed",
        )
        .filter(F.length(F.col("chunk_to_retrieve")) > MIN_CHUNK)
    )

    # ── Fallback: split plain content for docs ai_prep_search did not chunk ──────
    prepped_ids = prep.select("doc_id").distinct()
    content = spark.read.table("bronze_parsed_content").select("path", "content")
    fallback = (
        classified.join(content, on="path", how="inner")
        .join(prepped_ids, on="doc_id", how="left_anti")
        .filter(F.col("content").isNotNull() & (F.length("content") > MIN_CHUNK))
        .withColumn("_n", F.expr(f"greatest(1, ceil(length(content) / {CHUNK_SIZE}))"))
        .withColumn("chunk_position", F.explode(F.expr("sequence(0, cast(_n as int) - 1)")))
        .withColumn("chunk_to_retrieve", F.expr(f"substring(content, chunk_position * {CHUNK_SIZE} + 1, {CHUNK_SIZE})"))
        .withColumn("chunk_id", F.concat_ws("_", F.col("doc_id"), F.col("chunk_position")))
        .withColumn("chunk_to_embed", F.col("chunk_to_retrieve"))
        .filter(F.length(F.col("chunk_to_retrieve")) > MIN_CHUNK)
        .select("doc_id", "doc_type", "source_file", "chunk_id", "chunk_position", "chunk_to_retrieve", "chunk_to_embed")
    )

    return prep.unionByName(fallback)
