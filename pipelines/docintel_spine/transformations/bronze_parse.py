"""Bronze — parse source documents in place.

Consolidates the old `01_parse_documents.py` + `02_extract_document_content.py`
into one Lakeflow Declarative Pipeline layer. Reads documents *in place* from the
configured source volume (no upload/copy), parses PDFs/images with
`ai_parse_document` and wraps TXT in a matching synthetic VARIANT, then flattens
clean text — all incrementally via Auto Loader.

Tables produced (in the pipeline's target schema):
  - bronze_parsed_raw      : path, parsed (VARIANT), source_file, parsed_at
  - bronze_parsed_content  : path, content (STRING), error_status, parsed_at

Pipeline configuration params (set in the .pipeline.yml `configuration`):
  - source_volume_path : where the documents already live (read in place)
  - image_output_path  : where ai_parse_document writes page images
"""
from pyspark import pipelines as dp
from pyspark.sql import functions as F

SOURCE_VOLUME_PATH = spark.conf.get("source_volume_path")
IMAGE_OUTPUT_PATH = spark.conf.get("image_output_path")

# ── bronze_parsed_raw : one streaming table, two append flows ──────────────────
# PDF/image → ai_parse_document ; TXT → synthetic VARIANT (same schema) so the
# downstream silver logic is identical regardless of source format.
dp.create_streaming_table(
    name="bronze_parsed_raw",
    comment="Raw parsed documents (VARIANT) — ai_parse_document for PDF/image, synthetic VARIANT for TXT.",
    table_properties={"delta.feature.variantType-preview": "supported"},
)


@dp.append_flow(target="bronze_parsed_raw", name="parse_pdf_images")
def parse_pdf_images():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "binaryFile")
        .option("cloudFiles.includeExistingFiles", "true")
        .option("pathGlobFilter", "*.{pdf,jpg,jpeg,png}")
        .load(SOURCE_VOLUME_PATH)
        .withColumn(
            "parsed",
            F.expr(
                f"""
                ai_parse_document(
                    content,
                    map(
                        'version', '2.0',
                        'imageOutputPath', '{IMAGE_OUTPUT_PATH}',
                        'descriptionElementTypes', '*'
                    )
                )
                """
            ),
        )
        .select(
            F.col("path"),
            F.col("parsed"),
            F.col("path").alias("source_file"),
            F.current_timestamp().alias("parsed_at"),
        )
    )


@dp.append_flow(target="bronze_parsed_raw", name="parse_txt")
def parse_txt():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "text")
        .option("cloudFiles.includeExistingFiles", "true")
        .option("wholetext", "true")
        .option("pathGlobFilter", "*.txt")
        .load(SOURCE_VOLUME_PATH)
        .select(
            F.col("_metadata.file_path").alias("path"),
            F.col("value").alias("_txt_content"),
        )
        .withColumn(
            "parsed",
            F.expr(
                """
                parse_json(to_json(named_struct(
                    'document', named_struct(
                        'elements', array(named_struct(
                            'type',        'NarrativeText',
                            'content',     _txt_content,
                            'confidence',  CAST(1.0 AS DOUBLE),
                            'id',          CAST(0 AS BIGINT),
                            'bbox',        CAST(array() AS ARRAY<STRING>),
                            'description', CAST(NULL AS STRING)
                        )),
                        'pages', CAST(array() AS ARRAY<STRING>)
                    ),
                    'metadata', named_struct('id', element_at(split(path, '/'), -1), 'version', CAST('txt_direct' AS STRING)),
                    'error_status', CAST(NULL AS STRING)
                )))
                """
            ),
        )
        .select(
            F.col("path"),
            F.col("parsed"),
            F.col("path").alias("source_file"),
            F.current_timestamp().alias("parsed_at"),
        )
    )


# ── bronze_parsed_content : clean concatenated text per document ───────────────
@dp.materialized_view(
    name="bronze_parsed_content",
    comment="Clean concatenated text extracted from the parsed VARIANT (figures use their description).",
)
def bronze_parsed_content():
    raw = spark.read.table("bronze_parsed_raw")
    # latest parse per path
    from pyspark.sql import Window as W

    latest = (
        raw.withColumn("_rn", F.row_number().over(W.partitionBy("path").orderBy(F.col("parsed_at").desc())))
        .filter("_rn = 1")
        .drop("_rn")
    )
    return (
        latest.withColumn(
            "content",
            F.when(
                F.expr("try_cast(parsed:error_status AS STRING)").isNotNull(),
                F.lit(None).cast("string"),
            ).otherwise(
                F.concat_ws(
                    "\n\n",
                    F.expr(
                        """
                        transform(
                            try_cast(parsed:document:elements AS ARRAY<VARIANT>),
                            el -> (CASE WHEN try_cast(el:type AS STRING) = 'figure'
                                        THEN try_cast(el:description AS STRING)
                                        ELSE try_cast(el:content AS STRING) END)
                        )
                        """
                    ),
                )
            ),
        )
        .withColumn("error_status", F.expr("try_cast(parsed:error_status AS STRING)"))
        .select("path", "content", "error_status", "parsed_at")
    )
