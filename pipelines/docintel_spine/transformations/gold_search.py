"""Gold — search index WITHOUT a Vector Search endpoint.

Embeds each chunk once (batch) using the serverless Foundation Model API
(`databricks-gte-large-en`, pay-per-token, no provisioned endpoint) and stores
the vector as ARRAY<FLOAT>. Retrieval is then plain SQL at query time:

    WITH qy AS (SELECT CAST(ai_query('databricks-gte-large-en', :question) AS ARRAY<FLOAT>) AS qv)
    SELECT doc_id, doc_type, chunk_to_retrieve,
           vector_cosine_similarity(embedding, qy.qv) AS score
    FROM gold_chunks, qy
    ORDER BY score DESC LIMIT :k;

Exact and instant for a demo/template corpus; zero standing infrastructure.
Graduate to a Vector Search Delta Sync index only for large corpora needing ANN.
"""
from pyspark import pipelines as dp
from pyspark.sql import functions as F

EMBED_MODEL = spark.conf.get("embed_model", "databricks-gte-large-en")


@dp.materialized_view(
    name="gold_chunks",
    comment="Search chunks with a precomputed embedding (ARRAY<FLOAT>) — endpoint-free cosine retrieval.",
)
def gold_chunks():
    return spark.read.table("silver_chunks").withColumn(
        "embedding",
        F.expr(f"CAST(ai_query('{EMBED_MODEL}', chunk_to_embed) AS ARRAY<FLOAT>)"),
    )
