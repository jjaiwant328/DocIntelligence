"""Gold — per-type field extraction + document metadata.

Ports Gold Step 5 + the extracted_fields unpivot of the old `03_idp_pipeline.py`:
  - gold_extracted_fields : long format (doc_id, doc_type, field_name, field_value)
                            with source_file evidence; one row per extracted field.
  - gold_documents        : one row per document (doc_id, doc_type, source_file).

Config-driven: per-doc-type extraction schemas come from
`platform.domain_configs.extraction_schemas` for the pipeline's `domain_id`.
Evidence: each field carries `source_file`; page/bbox-level evidence is resolved
via the parsed elements in `bronze_parsed_raw` (see the evidence view/API).
"""
import json

from pyspark import pipelines as dp
from pyspark.sql import functions as F
from functools import reduce

CATALOG = spark.conf.get("catalog", "jai_docintel")
DOMAIN_ID = spark.conf.get("domain_id", "supply_chain")


def _load_extraction_configs():
    """Read per-doc-type extraction schemas from the domain registry at execution time."""
    rows = spark.sql(
        f"SELECT extraction_schemas FROM {CATALOG}.platform.domain_configs WHERE domain_id = '{DOMAIN_ID}' LIMIT 1"
    ).collect()
    schemas_raw = rows[0]["extraction_schemas"] if rows else None
    if not schemas_raw:
        raise ValueError(f"No extraction_schemas configured for domain '{DOMAIN_ID}' in {CATALOG}.platform.domain_configs")
    parsed = json.loads(schemas_raw)
    # Two storage shapes:
    #  (a) dict  {doc_type: {"schema": {field: {...}}, "instructions": "..."}}   (pipeline format)
    #  (b) list  [{"doc_type": ..., "fields": [{"name","description"}, ...]}]     (UI-saved format)
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        result = {}
        for entry in parsed:
            if not isinstance(entry, dict):
                continue
            doc_type = entry.get("doc_type")
            if not doc_type:
                continue
            schema = {}
            for fld in entry.get("fields", []):
                name = (fld.get("name") or "").strip()
                if name:
                    schema[name] = {"type": "string", "description": fld.get("description") or f"Value of {name}."}
            if schema:
                result[doc_type] = {
                    "schema": schema,
                    "instructions": f"Extract only explicitly stated values from this {doc_type.replace('_', ' ')} document. Return null for fields not found.",
                }
        return result
    return {}


@dp.materialized_view(
    name="gold_documents",
    comment="One row per document with its classified type and source file.",
)
def gold_documents():
    return spark.read.table("silver_classified").select("doc_id", "doc_type", "source_file", "path")


@dp.materialized_view(
    name="gold_extracted_fields",
    comment="Long-format extracted fields (doc_id, doc_type, field_name, field_value) with source_file evidence.",
)
def gold_extracted_fields():
    classified = spark.read.table("silver_classified")
    extraction_configs = _load_extraction_configs()
    per_type_long = []

    for doc_type, cfg in extraction_configs.items():
        schema = cfg.get("schema", {})
        if not schema:
            continue
        schema_json = json.dumps(schema).replace("'", "\\'")
        instructions = (cfg.get("instructions") or f"Extract fields from this {doc_type} document.").replace("'", "\\'")

        extracted = (
            classified.filter(F.col("doc_type") == doc_type)
            .select(
                F.col("doc_id"),
                F.col("doc_type"),
                F.col("source_file"),
                F.expr(
                    f"ai_extract(parsed_content, '{schema_json}', MAP('instructions', '{instructions}'))"
                ).alias("extracted"),
            )
        )
        # unpivot the configured fields into long rows
        field_cols = list(schema.keys())
        # ai_extract returns each field nested as {"value": ...}; pull the scalar value.
        stack_expr = ", ".join(
            [f"'{fn}', TRY_CAST(extracted:response.{fn}.value AS STRING)" for fn in field_cols]
        )
        long_df = extracted.selectExpr(
            "doc_id",
            "doc_type",
            "source_file",
            f"stack({len(field_cols)}, {stack_expr}) AS (field_name, field_value)",
        ).filter(F.col("field_value").isNotNull() & (F.length(F.col("field_value")) > 0))
        per_type_long.append(long_df)

    if not per_type_long:
        # no configured schema matched — emit empty, correctly-typed frame
        return spark.createDataFrame(
            [], "doc_id STRING, doc_type STRING, source_file STRING, field_name STRING, field_value STRING"
        )
    return reduce(lambda a, b: a.unionByName(b), per_type_long)
