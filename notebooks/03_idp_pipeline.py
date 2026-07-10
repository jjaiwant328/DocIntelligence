# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — IDP Pipeline
# MAGIC
# MAGIC Intelligent Document Processing using Databricks AI Functions:
# MAGIC
# MAGIC ```
# MAGIC  BRONZE                    SILVER                                 GOLD
# MAGIC  /Volumes/documents  →  parsed_documents  →  classified_documents  →  extracted_entities
# MAGIC  (Auto Loader)           (ai_parse_document)   (ai_classify)              (ai_extract)
# MAGIC                                                     ↓
# MAGIC                                             ai_prep_search
# MAGIC                                        (search-ready chunks for VS)
# MAGIC ```
# MAGIC
# MAGIC **AI Functions used:**
# MAGIC | Function | Purpose |
# MAGIC |---|---|
# MAGIC | `ai_parse_document` | Parse PDF/image → structured VARIANT (run by upstream unstructured_workflow) |
# MAGIC | `ai_classify` | Assign document type label from configured taxonomy |
# MAGIC | `ai_prep_search` | Transform parsed VARIANT → semantic chunks (chunk_to_embed + chunk_to_retrieve) |
# MAGIC | `ai_extract` | Extract structured fields per doc type + schema suggestion for uncharted types |
# MAGIC
# MAGIC **Reference:** https://docs.databricks.com/en/sql/language-manual/functions/ai_prep_search

# COMMAND ----------

import json
import uuid
from datetime import datetime, timezone
from pyspark.sql import functions as F

CATALOG = "jai_docintel"

# ────────────────────────────────────────────────────────────────────────────
# PARAMETERS  (all overridable from Databricks job parameters)
# ────────────────────────────────────────────────────────────────────────────
def _wparam(name: str, default: str = "") -> str:
    try:
        return dbutils.widgets.get(name)
    except Exception:
        return default

# Required
domain_id       = _wparam("domain_id",       "supply_chain")

# Optional overrides — if blank, falls back to domain config or UC volume default
volume_path     = _wparam("volume_path",     "")   # e.g. /Volumes/jai_docintel/compliance/sample_docs
doc_types_param = _wparam("doc_types",       "")   # JSON array ["invoice","purchase_order"] or "" = all configured

# Processing mode
# "batch"       — process all new files (default)
# "interactive" — process up to batch_size files, stop
mode            = _wparam("mode",            "batch")
batch_size      = int(_wparam("batch_size",  "999"))  # 999 = unlimited (interactive "all")

# Incremental behaviour
# "false" (default) — skip files already in file_processing_log with status=success
# "true"  — re-process everything (full rebuild)
force_reprocess = _wparam("force_reprocess", "false").lower() in ("true", "1", "yes")

# Schema mode — controls how extraction schemas are resolved per document
# "hybrid"     (default) — use configured schema when one exists; AI-infer for the rest
# "configured" — strict: only apply pre-built schemas; skip types with no schema
# "ai_infer"   — AI discovers fields for every document via universal SCHEMA_DISCOVERY_SCHEMA
schema_mode     = _wparam("schema_mode", "hybrid").lower().strip()
if schema_mode not in ("hybrid", "configured", "ai_infer"):
    schema_mode = "hybrid"

# Backward-compat: skip_no_schema is derived from schema_mode if not overridden
_skip_param     = _wparam("skip_no_schema", "").lower().strip()
if _skip_param in ("true", "false"):
    skip_no_schema = (_skip_param == "true")
else:
    skip_no_schema = (schema_mode == "configured")

# Job run tracking
job_run_id_str  = _wparam("job_run_id",      "0")
try:
    job_run_id  = int(job_run_id_str)
except Exception:
    job_run_id  = 0

print(f"=== DocIntelligence Pipeline ===")
print(f"  domain_id     : {domain_id}")
print(f"  volume_path   : {volume_path or '(from domain config)'}")
print(f"  doc_types     : {doc_types_param or '(all configured)'}")
print(f"  mode          : {mode}  batch_size={batch_size}")
print(f"  force_reprocess: {force_reprocess}")
print(f"  schema_mode   : {schema_mode}  (skip_no_schema={skip_no_schema})")
print(f"  job_run_id    : {job_run_id}")
print(f"  started_at    : {datetime.now(timezone.utc).isoformat()}")

# ── Load domain config ────────────────────────────────────────────────────────
def _load_domain_config(catalog: str, domain_id: str) -> dict:
    """Load domain config from platform.domain_configs; fall back to supply_chain defaults."""
    try:
        try:
            rows = spark.sql(f"""
                SELECT schema_raw, schema_ont, schema_vec, schema_agt,
                       classification_labels, extraction_schemas, parse_instructions
                FROM {catalog}.platform.domain_configs
                WHERE domain_id = '{domain_id}'
                LIMIT 1
            """).collect()
        except Exception:
            rows = spark.sql(f"""
                SELECT schema_raw, schema_ont, schema_vec, schema_agt,
                       classification_labels, extraction_schemas
                FROM {catalog}.platform.domain_configs
                WHERE domain_id = '{domain_id}'
                LIMIT 1
            """).collect()
        if rows:
            r = rows[0]
            return {
                "schema_raw":            r["schema_raw"]   or "raw",
                "schema_ont":            r["schema_ont"]   or "ontology",
                "schema_vec":            r["schema_vec"]   or "vectors",
                "schema_agt":            r["schema_agt"]   or "agents",
                "classification_labels": r["classification_labels"],
                "extraction_schemas":    r["extraction_schemas"],
                "parse_instructions":    r["parse_instructions"] if "parse_instructions" in r else None,
            }
    except Exception as e:
        print(f"Platform config not found ({e}); using built-in supply_chain defaults.")
    return {}


def _normalize_classification_labels(raw: str, domain_id: str) -> str:
    """Convert UI-saved classification labels (array) to pipeline dict format."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return raw
        if isinstance(parsed, list):
            result = {}
            for item in parsed:
                if isinstance(item, str):
                    name = item
                    result[name] = f"A {name.replace('_', ' ')} document in the {domain_id.replace('_', ' ')} domain."
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("label") or ""
                    example = item.get("example") or f"A {name.replace('_', ' ')} document."
                    if name:
                        result[name] = example
            return json.dumps(result) if result else None
    except Exception as e:
        print(f"Could not normalize classification labels: {e}")
    return raw


def _convert_ui_extraction_schemas(raw: str, parse_instructions: str, domain_id: str) -> dict:
    """Convert UI-saved extraction schemas to EXTRACTION_CONFIGS pipeline format."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        base_instr = (parse_instructions or "").strip()
        if not base_instr:
            base_instr = f"Extract only explicitly stated values from this {domain_id.replace('_', ' ')} document. Do not infer or hallucinate. Return null for fields not found."

        if isinstance(parsed, list):
            result = {}
            for doc_schema in parsed:
                if not isinstance(doc_schema, dict):
                    continue
                doc_type = doc_schema.get("doc_type", "")
                if not doc_type:
                    continue
                fields = doc_schema.get("fields", [])
                schema = {}
                for field in fields:
                    if not isinstance(field, dict):
                        continue
                    name = (field.get("name") or "").strip()
                    if not name:
                        continue
                    desc = field.get("description") or f"Value of {name} from the document."
                    schema[name] = {"type": "string", "description": desc}
                result[doc_type] = {
                    "schema": schema,
                    "instructions": f"{base_instr} This is a {doc_type.replace('_', ' ')} document.",
                }
            return result if result else None

        if isinstance(parsed, dict):
            if base_instr:
                for dt in parsed:
                    if isinstance(parsed[dt], dict):
                        parsed[dt]["instructions"] = base_instr + " " + parsed[dt].get("instructions", "")
            return parsed

    except Exception as e:
        print(f"Could not convert extraction schemas: {e}")
    return None


_cfg = _load_domain_config(CATALOG, domain_id)

SCHEMA_RAW = _cfg.get("schema_raw", "raw")
SCHEMA_ONT = _cfg.get("schema_ont", "ontology")
SCHEMA_VEC = _cfg.get("schema_vec", "vectors")
SCHEMA_AGT = _cfg.get("schema_agt", "agents")

_TMP_SUFFIX = uuid.uuid4().hex[:8]

# ── Apply volume_path override from job parameter ────────────────────────────
# Priority: job parameter > processing_configs table > domain default
if not volume_path:
    try:
        _pc = spark.sql(f"""
            SELECT volume_path FROM {CATALOG}.platform.processing_configs
            WHERE domain_id = '{domain_id}' LIMIT 1
        """).collect()
        if _pc and _pc[0]["volume_path"]:
            volume_path = _pc[0]["volume_path"]
            print(f"  volume_path from processing_configs: {volume_path}")
    except Exception:
        pass

if not volume_path:
    volume_path = f"/Volumes/{CATALOG}/{SCHEMA_RAW}/documents"
    print(f"  volume_path default: {volume_path}")

# ── Apply doc_types filter from job parameter ─────────────────────────────────
# If provided, only process files predicted to be one of these doc types
_filter_doc_types: set = set()
if doc_types_param:
    try:
        _filter_doc_types = set(json.loads(doc_types_param))
        print(f"  doc_types filter: {sorted(_filter_doc_types)}")
    except Exception:
        _filter_doc_types = set(dt.strip() for dt in doc_types_param.split(",") if dt.strip())

print(f"Domain: {domain_id} | raw={SCHEMA_RAW} | ont={SCHEMA_ONT} | vec={SCHEMA_VEC}")
print(f"Volume: {volume_path}")
spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA_RAW}")

# ── Startup cleanup: drop any leftover _tmp_ tables from previous failed runs ──
try:
    _startup_tables = spark.sql(f"SHOW TABLES IN {CATALOG}.{SCHEMA_RAW}").collect()
    _startup_tmps   = [r["tableName"] for r in _startup_tables if r["tableName"].startswith("_tmp_")]
    for _tn in _startup_tmps:
        spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.{SCHEMA_RAW}.`{_tn}`")
        print(f"Startup cleanup: dropped leftover {_tn}")
except Exception as _su_err:
    print(f"Startup cleanup warning (non-fatal): {_su_err}")

# ── Ensure file_processing_log table exists ───────────────────────────────────
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {CATALOG}.platform.file_processing_log (
        file_path        STRING NOT NULL,
        file_name        STRING,
        domain_id        STRING,
        doc_type         STRING,
        status           STRING,
        processed_at     TIMESTAMP,
        job_run_id       BIGINT,
        records_written  INT,
        error_message    STRING,
        file_size_bytes  BIGINT,
        pipeline_version STRING
    ) USING DELTA
    TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")

PIPELINE_VERSION = "2.0"

# COMMAND ----------
# MAGIC %md ## Configuration — Classification Labels & Extraction Schemas

# COMMAND ----------

_parse_instructions = _cfg.get("parse_instructions") or ""

if _cfg.get("classification_labels"):
    _normalized = _normalize_classification_labels(_cfg["classification_labels"], domain_id)
    if _normalized:
        CLASSIFICATION_LABELS = _normalized
        print(f"Classification labels loaded from platform config ({domain_id}): {list(json.loads(CLASSIFICATION_LABELS).keys())}")
    else:
        print(f"Could not normalize classification labels; using built-in defaults")
else:
    CLASSIFICATION_LABELS = json.dumps({
    "supplier_contract":     "A legal agreement between a supplier and purchaser defining SLAs, pricing, temperature requirements, and liability/penalty clauses.",
    "bill_of_lading":        "A shipping document listing shipment details, carrier, trailer, pickup/delivery times, product quantity, and lot numbers.",
    "temperature_log":       "A continuous time-series temperature monitoring log from a refrigerated trailer or cold storage unit, often showing readings over time with alarm events.",
    "certificate_of_analysis": "A quality document from a supplier certifying product specifications, microbiological test results, lot number, and production/expiry dates.",
    "quality_incident_report": "An internal report documenting a quality or safety incident such as a temperature excursion, product defect, or process failure with investigation details.",
    "recall_notice":         "An official notice of a voluntary or mandatory product recall specifying lot numbers, affected products, distribution scope, and required actions.",
    "email_chain":           "An email thread between supply chain stakeholders regarding shipment exceptions, conditional release decisions, or supplier escalations.",
    "supplier_scorecard":    "A periodic supplier performance evaluation covering KPIs like on-time delivery, fill rate, defect rate, temperature compliance, and claims frequency.",
    "inspection_report":     "A receiving or facility inspection report documenting visual checks, temperature probes, seal verification, and product condition at a distribution center.",
    "maintenance_report":    "An equipment maintenance or repair report for a trailer, refrigeration unit, or other supply chain asset, including failure diagnosis and corrective actions.",
    "delivery_exception":    "A notification to distribution or restaurant operations about a delivery exception such as a delay or product hold due to quality issue.",
    "carrier_sla":           "A carrier service level agreement defining transport standards, refrigeration maintenance obligations, and liability terms.",
    "weather_report":        "A contextual weather conditions report for a transit corridor, used to assess whether weather contributed to a supply chain incident.",
})

_doc_types = list(json.loads(CLASSIFICATION_LABELS).keys())
CLASSIFICATION_INSTRUCTIONS = (
    f"You are classifying {domain_id.replace('_', ' ')} documents. "
    "Read the document and assign exactly one of the provided labels. "
    "Give strong weight to the document title, filename, and opening lines. "
    "Return only the single best label."
    + (f" Additional context: {_parse_instructions}" if _parse_instructions else "")
)

# COMMAND ----------
# MAGIC %md ## Extraction Schemas (per document type)

# COMMAND ----------

BASE_INSTRUCTIONS = (
    f"The input is a {domain_id.replace('_', ' ')} document. "
    "Extract only explicitly stated values. "
    "Do not infer or hallucinate values. "
    "Return null for any field not found in the document. "
    + (_parse_instructions + " " if _parse_instructions else "")
)

EXTRACTION_CONFIGS = {
    "supplier_contract": {
        "schema": {
            "supplier_name":        {"type": "string", "description": "Legal name of the supplier company."},
            "purchaser_name":       {"type": "string", "description": "Legal name of the purchaser company."},
            "contract_number":      {"type": "string", "description": "Agreement or contract reference number."},
            "effective_date":       {"type": "string", "description": "Contract start/effective date."},
            "expiration_date":      {"type": "string", "description": "Contract expiry date."},
            "temperature_limit_f":  {"type": "string", "description": "Maximum temperature threshold in Fahrenheit (e.g., '40°F')."},
            "excursion_threshold_min": {"type": "string", "description": "Maximum allowed excursion duration in minutes before liability triggers (e.g., '30 minutes')."},
            "penalty_amount":       {"type": "string", "description": "Penalty amount or range for temperature violations (e.g., '$15,000 per incident')."},
            "otd_target_pct":       {"type": "string", "description": "On-time delivery target percentage (e.g., '95%')."},
        },
        "instructions": f"{BASE_INSTRUCTIONS} This is a supplier contract.",
    },
    "bill_of_lading": {
        "schema": {
            "shipment_id":          {"type": "string", "description": "Shipment or BOL reference number."},
            "lot_number":           {"type": "string", "description": "Product lot number."},
            "supplier_name":        {"type": "string", "description": "Shipper/supplier company name."},
            "carrier_name":         {"type": "string", "description": "Carrier/trucking company name."},
            "trailer_id":           {"type": "string", "description": "Trailer or container identifier."},
            "distribution_center":  {"type": "string", "description": "Destination distribution center name or location."},
            "pickup_datetime":      {"type": "string", "description": "Actual pickup date and time."},
            "delivery_datetime":    {"type": "string", "description": "Actual delivery date and time."},
            "quantity_cases":       {"type": "string", "description": "Number of cases shipped."},
            "product_name":         {"type": "string", "description": "Product description or name."},
        },
        "instructions": f"{BASE_INSTRUCTIONS} This is a bill of lading.",
    },
    "temperature_log": {
        "schema": {
            "trailer_id":           {"type": "string", "description": "Trailer identifier."},
            "shipment_id":          {"type": "string", "description": "Associated shipment ID."},
            "excursion_detected":   {"type": "string", "description": "'YES' if temperature excursion occurred, 'NO' if no excursion."},
            "excursion_duration_min": {"type": "string", "description": "Duration of temperature excursion in minutes."},
            "peak_temperature_f":   {"type": "string", "description": "Maximum temperature reading during excursion (°F)."},
            "excursion_start":      {"type": "string", "description": "Date and time when excursion began."},
            "excursion_end":        {"type": "string", "description": "Date and time when temperature returned to normal."},
            "threshold_f":          {"type": "string", "description": "Set temperature threshold (°F)."},
            "compliance_status":    {"type": "string", "description": "COMPLIANT or NON-COMPLIANT."},
        },
        "instructions": f"{BASE_INSTRUCTIONS} This is a temperature monitoring log.",
    },
    "certificate_of_analysis": {
        "schema": {
            "supplier_name":        {"type": "string", "description": "Manufacturer/supplier name."},
            "lot_number":           {"type": "string", "description": "Product lot number."},
            "product_name":         {"type": "string", "description": "Product name."},
            "production_date":      {"type": "string", "description": "Production date."},
            "expiration_date":      {"type": "string", "description": "Best-by or expiration date."},
            "salmonella_result":    {"type": "string", "description": "Salmonella test result (e.g., 'Not Detected', 'Detected')."},
            "listeria_result":      {"type": "string", "description": "Listeria test result."},
            "total_plate_count":    {"type": "string", "description": "Total plate count result with unit (e.g., '1,200 CFU/g')."},
            "overall_status":       {"type": "string", "description": "Overall QA pass/fail status."},
        },
        "instructions": f"{BASE_INSTRUCTIONS} This is a certificate of analysis.",
    },
    "quality_incident_report": {
        "schema": {
            "report_number":        {"type": "string", "description": "QI report reference number."},
            "shipment_id":          {"type": "string", "description": "Affected shipment ID."},
            "lot_number":           {"type": "string", "description": "Affected lot number."},
            "incident_type":        {"type": "string", "description": "Type of quality incident (e.g., 'Temperature Excursion')."},
            "excursion_duration_min": {"type": "string", "description": "Duration of temperature excursion in minutes."},
            "peak_temperature_f":   {"type": "string", "description": "Peak temperature during incident (°F)."},
            "distribution_center":  {"type": "string", "description": "Distribution center where incident was detected."},
            "supplier_name":        {"type": "string", "description": "Supplier involved."},
            "financial_exposure":   {"type": "string", "description": "Estimated financial exposure or penalty amount."},
            "risk_classification":  {"type": "string", "description": "Risk level: Class I, Class II, or Class III."},
        },
        "instructions": f"{BASE_INSTRUCTIONS} This is a quality incident report.",
    },
    "recall_notice": {
        "schema": {
            "recall_number":        {"type": "string", "description": "Recall reference number."},
            "lot_number":           {"type": "string", "description": "Recalled lot number."},
            "product_name":         {"type": "string", "description": "Recalled product name."},
            "recall_class":         {"type": "string", "description": "Recall class: Class I, Class II, or Class III."},
            "recall_date":          {"type": "string", "description": "Date recall was issued."},
            "supplier_name":        {"type": "string", "description": "Supplier of recalled product."},
            "num_restaurants_affected": {"type": "string", "description": "Number of restaurant locations affected."},
            "total_cases_recalled": {"type": "string", "description": "Total cases subject to recall."},
            "estimated_financial_impact": {"type": "string", "description": "Estimated total financial impact of recall."},
            "affected_menu_items":  {"type": "string", "description": "Comma-separated list of affected menu items."},
        },
        "instructions": f"{BASE_INSTRUCTIONS} This is a recall notice.",
    },
    "email_chain": {
        "schema": {
            "shipment_id":          {"type": "string", "description": "Shipment ID discussed in email chain."},
            "lot_number":           {"type": "string", "description": "Lot number discussed."},
            "conditional_release_approved": {"type": "string", "description": "'YES' if conditional release was approved, 'NO' if rejected, 'PENDING' if undecided."},
            "approver_name":        {"type": "string", "description": "Name of person who approved/rejected the release."},
            "approval_date":        {"type": "string", "description": "Date of approval/rejection decision."},
            "supplier_liability_acknowledged": {"type": "string", "description": "'YES' if supplier acknowledged liability in writing, 'NO' otherwise."},
            "penalty_amount_agreed": {"type": "string", "description": "Penalty amount formally agreed to in email."},
        },
        "instructions": f"{BASE_INSTRUCTIONS} This is an email chain about a shipment exception.",
    },
    "supplier_scorecard": {
        "schema": {
            "supplier_name":        {"type": "string", "description": "Supplier name."},
            "evaluation_period":    {"type": "string", "description": "Evaluation period (e.g., 'Q1 2024')."},
            "overall_score":        {"type": "string", "description": "Overall score (e.g., '72/100')."},
            "otd_actual_pct":       {"type": "string", "description": "On-time delivery actual percentage."},
            "fill_rate_actual_pct": {"type": "string", "description": "Fill rate actual percentage."},
            "temp_violations_count": {"type": "string", "description": "Number of temperature violations."},
            "claims_count":         {"type": "string", "description": "Number of claims filed."},
            "risk_classification":  {"type": "string", "description": "Supplier risk level: HIGH RISK, CONDITIONAL, ACCEPTABLE, PREFERRED."},
        },
        "instructions": f"{BASE_INSTRUCTIONS} This is a supplier performance scorecard.",
    },
}

# Override extraction schemas from platform config if present
if _cfg.get("extraction_schemas"):
    _converted = _convert_ui_extraction_schemas(
        _cfg["extraction_schemas"], _parse_instructions, domain_id
    )
    if _converted:
        EXTRACTION_CONFIGS = _converted
        print(f"Extraction schemas loaded from platform config ({domain_id}): {list(EXTRACTION_CONFIGS.keys())}")

print(f"Configured {len(json.loads(CLASSIFICATION_LABELS))} classification labels")
print(f"Configured {len(EXTRACTION_CONFIGS)} extraction schemas")
print(f"Parse instructions: {'set (' + str(len(_parse_instructions)) + ' chars)' if _parse_instructions else 'not set (using built-in defaults)'}")

# COMMAND ----------
# MAGIC %md ## Bronze + Silver Step 1 — Read from unstructured_workflow tables
# MAGIC
# MAGIC `ai_parse_document` is run by the upstream `unstructured_workflow` bundle.
# MAGIC This step reads its outputs:
# MAGIC
# MAGIC | Table | Content |
# MAGIC |---|---|
# MAGIC | `parsed_documents_raw` | VARIANT output of `ai_parse_document` — used by `ai_classify`, `ai_prep_search`, `ai_extract` |
# MAGIC | `parsed_documents_content` | Extracted plain text |

# COMMAND ----------

from pyspark.sql import Window as _W
import re as _re

_raw_all = spark.table(f"{CATALOG}.{SCHEMA_RAW}.parsed_documents_raw")
_raw_tbl = (
    _raw_all
    .withColumn("_rn", F.row_number().over(
        _W.partitionBy("path").orderBy(F.col("parsed_at").desc())
    ))
    .filter("_rn = 1")
    .drop("_rn")
)

_content_all = spark.table(f"{CATALOG}.{SCHEMA_RAW}.parsed_documents_content")
_content_ts_col = "processed_at" if "processed_at" in [c.name for c in _content_all.schema] else None
if _content_ts_col:
    _content_tbl = (
        _content_all
        .withColumn("_rn", F.row_number().over(
            _W.partitionBy("path").orderBy(F.col(_content_ts_col).desc())
        ))
        .filter("_rn = 1")
        .drop("_rn")
    )
else:
    _content_tbl = _content_all.dropDuplicates(["path"])

parsed_docs_df = (
    _raw_tbl
    .join(
        _content_tbl.select("path", F.col("content").alias("_raw_text")),
        on="path",
        how="left",
    )
    .select(
        F.col("path"),
        F.element_at(F.split(F.col("path"), "/"), -1).alias("filename"),
        F.col("parsed").alias("parsed_content"),   # VARIANT from ai_parse_document
        F.col("_raw_text"),
    )
)

_parsed_table = f"_tmp_docintel_parsed_{_TMP_SUFFIX}"
parsed_docs_df.write.mode("overwrite").saveAsTable(_parsed_table)
parsed_docs_df = spark.table(_parsed_table)

total_available = parsed_docs_df.count()
print(f"Loaded {total_available} documents from unstructured_workflow tables")

# ── Volume filter: restrict to specified volume_path ─────────────────────────
# The unstructured_workflow stores paths with a "dbfs:" prefix (e.g. dbfs:/Volumes/…).
# Normalise both forms so the startswith filter always hits.
if volume_path:
    _vol_prefix      = volume_path.rstrip("/")
    _vol_prefix_dbfs = "dbfs:" + _vol_prefix        # e.g. dbfs:/Volumes/jai_docintel/…
    _before_vol = parsed_docs_df.count()
    parsed_docs_df = parsed_docs_df.filter(
        F.col("path").startswith(_vol_prefix) | F.col("path").startswith(_vol_prefix_dbfs)
    )
    _after_vol = parsed_docs_df.count()
    print(f"Volume filter '{_vol_prefix}': {_before_vol} → {_after_vol} files")

# ── Deduplication via file_processing_log ────────────────────────────────────
# Build a set of file paths already successfully processed for this domain.
# Uses file_processing_log (global tracking table) — more reliable than
# checking parsed_documents which only has doc_id, not original path.
_processed_paths: set = set()
try:
    _log_rows = spark.sql(f"""
        SELECT file_path FROM {CATALOG}.platform.file_processing_log
        WHERE domain_id = '{domain_id}'
          AND status = 'success'
    """).collect()
    _processed_paths = {r.file_path for r in _log_rows}
    print(f"file_processing_log: {len(_processed_paths)} already-processed files for domain '{domain_id}'")
except Exception as _log_err:
    print(f"file_processing_log not available ({_log_err}) — will process all")

if force_reprocess:
    print("force_reprocess=True — reprocessing all documents (ignoring log)")
elif _processed_paths:
    _before = parsed_docs_df.count()
    parsed_docs_df = parsed_docs_df.filter(~F.col("path").isin(list(_processed_paths)))
    _after = parsed_docs_df.count()
    print(f"Dedup: {_before} total → {_after} new (skipped {_before - _after} already processed)")
    if _after == 0:
        print("Nothing new to process. Pipeline complete.")
        dbutils.notebook.exit("No new documents to process")

# ── Interactive batch_size cap ────────────────────────────────────────────────
if mode == "interactive" and batch_size < 999:
    _before_cap = parsed_docs_df.count()
    parsed_docs_df = parsed_docs_df.limit(batch_size)
    print(f"Interactive mode: capped at {batch_size} of {_before_cap} files")

display(parsed_docs_df.select("filename", "_raw_text").limit(3))

# COMMAND ----------
# MAGIC %md ## Silver Step 2 — ai_classify

# COMMAND ----------

labels_sql  = CLASSIFICATION_LABELS.replace("'", "\\'")
instr_sql   = CLASSIFICATION_INSTRUCTIONS.replace("'", "\\'")

classified_docs_df = (
    parsed_docs_df
    .filter("TRY_CAST(parsed_content:error_status AS STRING) IS NULL")
    .select(
        F.col("path"),
        F.col("filename"),
        F.col("parsed_content"),
        F.expr(f"""
            ai_classify(
                parsed_content,
                '{labels_sql}',
                MAP('instructions', '{instr_sql}')
            )
        """).alias("classification"),
    )
    .select(
        F.col("path"),
        F.col("filename"),
        F.col("parsed_content"),
        F.col("classification"),
        F.expr("classification:response[0]::STRING").alias("doc_type"),
    )
)

_classified_table = f"_tmp_docintel_classified_{_TMP_SUFFIX}"
classified_docs_df.write.mode("overwrite").saveAsTable(_classified_table)
classified_docs_df = spark.table(_classified_table)

print(f"Classified {classified_docs_df.count()} documents")
display(classified_docs_df.select("filename", "doc_type"))

# COMMAND ----------
# MAGIC %md ## Silver Step 3 — ai_prep_search
# MAGIC
# MAGIC `ai_prep_search` takes the raw VARIANT output of `ai_parse_document` and produces
# MAGIC semantically chunked, context-enriched text optimized for RAG vector search.
# MAGIC
# MAGIC Each document produces N chunks with:
# MAGIC - **`chunk_to_embed`** — context-enriched (title + headers + page refs injected) — feed to embedding model
# MAGIC - **`chunk_to_retrieve`** — clean passage text — return to the LLM in RAG answers
# MAGIC - **`chunk_id`** / **`chunk_position`** — identity and ordering
# MAGIC
# MAGIC This replaces the manual `semantic_chunk()` UDF in the vector search notebook.
# MAGIC
# MAGIC > Requires: DBR 18.2+ / Serverless Runtime v3+

# COMMAND ----------

# Apply ai_prep_search on the parsed VARIANT.
# The parsed_content VARIANT is the direct output of ai_parse_document,
# stored in parsed_documents_raw.parsed — ai_prep_search consumes it natively.

_prepped_table = f"_tmp_docintel_prepped_{_TMP_SUFFIX}"

try:
    prepped_df = (
        classified_docs_df
        .filter("TRY_CAST(parsed_content:error_status AS STRING) IS NULL")
        .select(
            F.col("filename"),
            F.col("doc_type"),
            F.expr("ai_prep_search(parsed_content)").alias("prep_result"),
        )
    )

    # Explode the chunks array: result:document.contents is ARRAY<VARIANT>
    # Each element has: chunk_id, chunk_position, chunk_to_retrieve, chunk_to_embed, pages
    chunks_df = (
        prepped_df
        .filter("TRY_CAST(prep_result:error_status AS STRING) IS NULL")
        .selectExpr(
            "filename AS doc_id",
            "doc_type",
            "prep_result:document.source_uri::STRING AS source_uri",
            "variant_explode(prep_result:document.contents) AS chunk",
        )
        .selectExpr(
            "doc_id",
            "doc_type",
            "source_uri",
            "chunk.value:chunk_id::STRING         AS chunk_id",
            "chunk.value:chunk_position::INT      AS chunk_position",
            "chunk.value:chunk_to_retrieve::STRING AS chunk_to_retrieve",
            "chunk.value:chunk_to_embed::STRING    AS chunk_to_embed",
        )
        .filter(F.length(F.col("chunk_to_retrieve")) > 30)
    )

    chunks_df.write.mode("overwrite").saveAsTable(_prepped_table)
    chunks_df = spark.table(_prepped_table)
    chunk_count = chunks_df.count()
    prep_search_available = True
    print(f"ai_prep_search: {chunk_count} chunks from {classified_docs_df.count()} documents")
    display(chunks_df.select("doc_id", "doc_type", "chunk_position", "chunk_to_retrieve").limit(5))

except Exception as _prep_err:
    print(f"ai_prep_search not available ({_prep_err})")
    print("Using manual chunking fallback.")
    prep_search_available = False

    # ── Manual chunking fallback ──────────────────────────────────────────────
    # Split raw_text into overlapping ~500-token (~2000-char) chunks.
    # Produces the same schema as ai_prep_search output so document_chunks
    # and the vector search index work identically.
    import hashlib as _hl

    CHUNK_SIZE   = 2000   # characters per chunk
    CHUNK_STEP   = 1500   # step size (500-char overlap)
    MIN_CHUNK    = 30     # discard very short chunks

    try:
        # Pull filename → raw_text → doc_type from the DataFrames
        _text_rows = (
            parsed_docs_df
            .join(classified_docs_df.select("filename", "doc_type"), on="filename", how="left")
            .select("filename", F.col("_raw_text").alias("raw_text"), "doc_type", "path")
            .collect()
        )

        _chunk_rows = []
        for row in _text_rows:
            text     = (row["raw_text"] or "").strip()
            fname    = row["filename"]
            dtype    = row["doc_type"] or "unknown"
            src_uri  = row["path"] or fname
            pos      = 0
            seq      = 0
            while pos < len(text):
                piece = text[pos: pos + CHUNK_SIZE]
                if len(piece) >= MIN_CHUNK:
                    cid = _hl.md5(f"{fname}_{seq}".encode()).hexdigest()
                    _chunk_rows.append((cid, fname, dtype, seq, piece, piece, src_uri))
                pos += CHUNK_STEP
                seq += 1

        if _chunk_rows:
            chunks_df = spark.createDataFrame(
                _chunk_rows,
                ["chunk_id", "doc_id", "doc_type", "chunk_position",
                 "chunk_to_retrieve", "chunk_to_embed", "source_uri"]
            ).filter(F.length(F.col("chunk_to_retrieve")) >= MIN_CHUNK)

            _prepped_table = f"_tmp_docintel_prepped_{_TMP_SUFFIX}"
            chunks_df.write.mode("overwrite").saveAsTable(_prepped_table)
            chunks_df   = spark.table(_prepped_table)
            chunk_count = chunks_df.count()
            prep_search_available = True
            print(f"Manual chunking: {chunk_count} chunks from {len(_text_rows)} documents")
        else:
            chunks_df   = None
            chunk_count = 0
            print("Manual chunking: no text available — document_chunks will be empty.")
    except Exception as _manual_err:
        print(f"Manual chunking also failed ({_manual_err}) — document_chunks skipped.")
        chunks_df   = None
        chunk_count = 0

# COMMAND ----------
# MAGIC %md ## Silver Step 4 — Persist: parsed_documents

# COMMAND ----------

_fallback_text_expr = F.expr("""
    AGGREGATE(
        TRANSFORM(
            FROM_JSON(CAST(parsed_content AS STRING),
                      'document STRUCT<elements ARRAY<STRUCT<content STRING>>>').document.elements,
            e -> COALESCE(e.content, '')
        ),
        CAST('' AS STRING),
        (acc, el) -> CASE WHEN el = '' THEN acc ELSE CONCAT(acc, '\\n', el) END
    )
""")

(
    parsed_docs_df
    .join(classified_docs_df.select("filename", "doc_type"), on="filename", how="left")
    .select(
        F.col("filename").alias("doc_id"),
        F.col("filename"),
        F.col("doc_type"),
        F.col("parsed_content"),
        F.when(
            F.col("_raw_text").isNotNull() & (F.length(F.col("_raw_text")) > 10),
            F.col("_raw_text")
        ).otherwise(_fallback_text_expr).alias("raw_text"),
        F.current_timestamp().alias("processed_ts"),
    )
    .write.mode("append").option("mergeSchema", "true")
    .saveAsTable(f"{CATALOG}.{SCHEMA_RAW}.parsed_documents")
)
print(f"Appended to: {CATALOG}.{SCHEMA_RAW}.parsed_documents")

# COMMAND ----------
# MAGIC %md ## Persist search chunks — document_chunks (Vector Search source table)
# MAGIC
# MAGIC Writes the `ai_prep_search` chunks to the vector schema so that notebook
# MAGIC `05_vector_search.py` can pick them up directly without re-chunking.
# MAGIC
# MAGIC Schema:
# MAGIC | Column | Description |
# MAGIC |---|---|
# MAGIC | `chunk_id` | Unique chunk ID (from ai_prep_search) |
# MAGIC | `doc_id` | Source document filename |
# MAGIC | `doc_type` | Classified document type |
# MAGIC | `chunk_position` | Sequential chunk index within document |
# MAGIC | `chunk_to_retrieve` | Text returned to LLM in RAG answers |
# MAGIC | `chunk_to_embed` | Context-enriched text for embedding (title + headers injected) |
# MAGIC | `source_uri` | Source document URI |
# MAGIC
# MAGIC > The vector search notebook reads this table and creates/syncs the VS index.

# COMMAND ----------

if prep_search_available and chunks_df is not None:
    # Ensure the vector schema exists
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA_VEC}")

    # Ensure table exists with CDF enabled (required for Delta Sync VS index)
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA_VEC}.document_chunks (
            chunk_id          STRING NOT NULL,
            doc_id            STRING,
            doc_type          STRING,
            chunk_position    INT,
            chunk_to_retrieve STRING,
            chunk_to_embed    STRING,
            source_uri        STRING
        )
        TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
    """)

    # Append new chunks (incremental — matching doc_ids already written are cleaned first)
    new_doc_ids = [r.doc_id for r in chunks_df.select("doc_id").distinct().collect()]
    if new_doc_ids:
        ids_lit = ", ".join(f"'{d}'" for d in new_doc_ids)
        spark.sql(f"""
            DELETE FROM {CATALOG}.{SCHEMA_VEC}.document_chunks
            WHERE doc_id IN ({ids_lit})
        """)

    (
        chunks_df
        .select("chunk_id", "doc_id", "doc_type", "chunk_position",
                "chunk_to_retrieve", "chunk_to_embed", "source_uri")
        .write.mode("append").option("mergeSchema", "true")
        .saveAsTable(f"{CATALOG}.{SCHEMA_VEC}.document_chunks")
    )
    final_count = spark.table(f"{CATALOG}.{SCHEMA_VEC}.document_chunks").count()
    print(f"document_chunks: {final_count} total chunks  (added {chunk_count} from this run)")
else:
    print("ai_prep_search chunks not available — document_chunks not updated this run.")
    print("Run notebook 05_vector_search.py to rebuild chunks with the manual chunker.")

# COMMAND ----------
# MAGIC %md ## Gold Step 5 — ai_extract per document type
# MAGIC
# MAGIC For each doc type that has a configured extraction schema, run `ai_extract` to
# MAGIC pull typed fields into Delta gold tables.

# COMMAND ----------

def flatten_extraction(doc_type: str):
    """Filter to doc_type, run ai_extract, flatten JSON fields into columns."""
    config = EXTRACTION_CONFIGS[doc_type]
    schema_json = json.dumps(config["schema"]).replace("'", "\\'")
    instructions = config["instructions"].replace("'", "\\'")

    extracted = (
        classified_docs_df
        .filter(F.col("doc_type") == doc_type)
        .select(
            F.col("filename").alias("doc_id"),
            F.col("doc_type"),
            F.col("parsed_content"),
            F.expr(f"""
                ai_extract(
                    parsed_content,
                    '{schema_json}',
                    MAP('instructions', '{instructions}')
                )
            """).alias("extracted"),
        )
    )

    select_cols = [F.col("doc_id"), F.col("doc_type")]
    for field_name in config["schema"]:
        select_cols.append(
            F.expr(f"extracted:response.{field_name}::STRING").alias(field_name)
        )
    return extracted.select(*select_cols)

# COMMAND ----------

gold_dfs = {}

# In "ai_infer" mode, skip Gold Step 5 (configured schemas) entirely —
# the universal schema discovery in Gold Step 6 will cover all documents.
if schema_mode == "ai_infer":
    print(f"schema_mode=ai_infer → skipping configured-schema extraction (Gold Step 5).")
    print("All documents will be processed by the universal AI-infer schema in Gold Step 6.")
else:
    for doc_type in EXTRACTION_CONFIGS:
        df = flatten_extraction(doc_type)
        count = df.count()
        if count > 0:
            gold_dfs[doc_type] = df
            print(f"\n{'='*60}")
            print(f"  {doc_type.replace('_', ' ').title()}  ({count} documents)")
            print(f"{'='*60}")
            display(df)

# COMMAND ----------
# MAGIC %md ## Gold Step 6 — ai_extract Schema Suggestion (unstructured → structured discovery)
# MAGIC
# MAGIC For doc types that do **not** have a configured extraction schema yet, run
# MAGIC `ai_extract` with a universal "schema discovery" schema.
# MAGIC
# MAGIC This produces:
# MAGIC 1. **Immediate structured output** for every document, even before full schema setup
# MAGIC 2. **`suggested_fields`** — the LLM recommends additional domain-specific fields to add to the schema
# MAGIC 3. Data written to `suggested_extractions` for review in the Schema Setup UI
# MAGIC
# MAGIC > Use the output of this table to refine your extraction schemas in the
# MAGIC > Document Intelligence → Schema Setup step.

# COMMAND ----------

# Universal schema for schema discovery — works on any document type.
# The `suggested_fields` field asks the LLM to recommend domain-specific fields
# that would be valuable to extract, based on what it sees in the document.
SCHEMA_DISCOVERY_SCHEMA = {
    "document_title":       {"type": "string", "description": "Primary title, subject line, or heading of this document."},
    "document_date":        {"type": "string", "description": "Primary date of the document — issued, effective, signed, or created date."},
    "reference_number":     {"type": "string", "description": "Any reference number, case ID, permit number, lot number, invoice number, or tracking ID."},
    "issuing_party":        {"type": "string", "description": "Organization, inspector, author, or person who issued, signed, or created this document."},
    "receiving_party":      {"type": "string", "description": "Organization or person this document is addressed to, regulates, or concerns."},
    "primary_subject":      {"type": "string", "description": "The main subject, product, facility, asset, or matter this document is about."},
    "key_amount":           {"type": "string", "description": "Most important monetary amount, fee, penalty, fine, or financial figure mentioned."},
    "deadline_or_due_date": {"type": "string", "description": "Any deadline, due date, expiration, or response-required date."},
    "action_required":      {"type": "string", "description": "What action is required, recommended, mandated, or has already been taken."},
    "status_or_outcome":    {"type": "string", "description": "Current status, finding, result, pass/fail, or conclusion of this document."},
    "geographic_location":  {"type": "string", "description": "Facility address, city, state, region, or geographic scope mentioned."},
    "suggested_fields":     {
        "type": "string",
        "description": (
            f"Comma-separated list of 5-8 additional specific fields that would be most valuable to extract "
            f"from this type of {domain_id.replace('_', ' ')} document. "
            "Format each as: field_name (brief description). "
            "Example: 'inspection_id (unique inspection reference), violation_code (regulatory code violated), "
            "corrective_deadline (when correction must be completed), severity_level (critical/major/minor)'"
        )
    },
}

_schema_discovery_json = json.dumps(SCHEMA_DISCOVERY_SCHEMA).replace("'", "\\'")
_schema_discovery_instr = (
    f"You are analyzing a {domain_id.replace('_', ' ')} document to discover its structure. "
    "Extract every field you can find and suggest additional fields that would be valuable for this document type. "
    "Be specific with field names — use snake_case. "
    "Do not infer or hallucinate values; return null for absent fields. "
    + (_parse_instructions + " " if _parse_instructions else "")
).replace("'", "\\'")

# Find doc types that DON'T have a configured extraction schema (need discovery)
_all_classified_types = {r.doc_type for r in classified_docs_df.select("doc_type").distinct().collect() if r.doc_type}
_configured_types     = set(EXTRACTION_CONFIGS.keys())
_unconfigured_types   = _all_classified_types - _configured_types

if schema_mode == "ai_infer":
    # AI-Infer All: run universal schema discovery on every document
    print(f"\nschema_mode=ai_infer → running universal AI inference on ALL {len(_all_classified_types)} doc type(s)")
    print(f"  Types: {sorted(_all_classified_types)}")
    _discovery_target = classified_docs_df
elif schema_mode == "configured":
    # Strict mode: no discovery needed — configured schemas already ran; skip unknowns
    print(f"\nschema_mode=configured → skipping schema discovery for unconfigured types ({len(_unconfigured_types)} skipped)")
    _discovery_target = classified_docs_df.filter(F.lit(False))  # empty DF
else:
    # Hybrid: discover only unconfigured types
    print(f"\nSchema discovery (hybrid): {len(_unconfigured_types)} doc type(s) without configured schema")
    if _unconfigured_types:
        print(f"  Types to discover: {sorted(_unconfigured_types)}")
    else:
        print("  All classified doc types have configured schemas — running discovery for schema improvement suggestions")
    _discovery_target = classified_docs_df if not _unconfigured_types else \
        classified_docs_df.filter(F.col("doc_type").isin(list(_unconfigured_types)))

_discovery_count = _discovery_target.count()
print(f"Running schema discovery on {_discovery_count} documents...")

if _discovery_count > 0:
    suggested_df = (
        _discovery_target
        .select(
            F.col("filename").alias("doc_id"),
            F.col("doc_type"),
            F.expr(f"""
                ai_extract(
                    parsed_content,
                    '{_schema_discovery_json}',
                    MAP('instructions', '{_schema_discovery_instr}')
                )
            """).alias("extracted"),
        )
        .select(
            F.col("doc_id"),
            F.col("doc_type"),
            F.expr("extracted:response.document_title::STRING").alias("document_title"),
            F.expr("extracted:response.document_date::STRING").alias("document_date"),
            F.expr("extracted:response.reference_number::STRING").alias("reference_number"),
            F.expr("extracted:response.issuing_party::STRING").alias("issuing_party"),
            F.expr("extracted:response.receiving_party::STRING").alias("receiving_party"),
            F.expr("extracted:response.primary_subject::STRING").alias("primary_subject"),
            F.expr("extracted:response.key_amount::STRING").alias("key_amount"),
            F.expr("extracted:response.deadline_or_due_date::STRING").alias("deadline_or_due_date"),
            F.expr("extracted:response.action_required::STRING").alias("action_required"),
            F.expr("extracted:response.status_or_outcome::STRING").alias("status_or_outcome"),
            F.expr("extracted:response.geographic_location::STRING").alias("geographic_location"),
            F.expr("extracted:response.suggested_fields::STRING").alias("suggested_fields"),
            F.current_timestamp().alias("discovered_at"),
        )
    )

    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA_RAW}.suggested_extractions (
            doc_id              STRING,
            doc_type            STRING,
            document_title      STRING,
            document_date       STRING,
            reference_number    STRING,
            issuing_party       STRING,
            receiving_party     STRING,
            primary_subject     STRING,
            key_amount          STRING,
            deadline_or_due_date STRING,
            action_required     STRING,
            status_or_outcome   STRING,
            geographic_location STRING,
            suggested_fields    STRING,
            discovered_at       TIMESTAMP
        )
    """)

    suggested_df.write.mode("append").option("mergeSchema", "true").saveAsTable(f"{CATALOG}.{SCHEMA_RAW}.suggested_extractions")
    saved_count = suggested_df.count()
    print(f"Saved {saved_count} schema discovery rows → {CATALOG}.{SCHEMA_RAW}.suggested_extractions")
    print("\nSuggested field additions (review to improve your Schema Setup):")
    display(suggested_df.select("doc_id", "doc_type", "suggested_fields").filter(
        F.col("suggested_fields").isNotNull()
    ))
else:
    print("No documents to run schema discovery on.")

# COMMAND ----------
# MAGIC %md ## Persist Gold Tables

# COMMAND ----------

for doc_type, gold_df in gold_dfs.items():
    table_name = f"{CATALOG}.{SCHEMA_RAW}.gold_{doc_type}"
    gold_df.write.mode("append").option("mergeSchema", "true").saveAsTable(table_name)
    print(f"Appended: {table_name}  ({gold_df.count()} rows)")

# COMMAND ----------
# MAGIC %md ## Persist Master: extracted_entities (union of all gold tables for ontology mapping)

# COMMAND ----------

all_fields = []
for doc_type, gold_df in gold_dfs.items():
    for col_name in gold_df.columns:
        if col_name in ("doc_id", "doc_type"):
            continue
        row_df = (
            gold_df
            .filter(F.col(col_name).isNotNull())
            .select(
                F.col("doc_id"),
                F.col("doc_type"),
                F.lit(col_name).alias("field_name"),
                F.col(col_name).alias("field_value"),
            )
        )
        all_fields.append(row_df)

from functools import reduce
from pyspark.sql import DataFrame
if all_fields:
    union_df = reduce(DataFrame.union, all_fields)
    union_df.write.mode("append").option("mergeSchema", "true").saveAsTable(f"{CATALOG}.{SCHEMA_RAW}.extracted_fields")
    print(f"Appended: {CATALOG}.{SCHEMA_RAW}.extracted_fields  ({union_df.count()} rows)")

# COMMAND ----------
# MAGIC %md ## Pipeline Summary

# COMMAND ----------

# ── Write file_processing_log entries for this run ───────────────────────────
# We join the parsed docs dataframe with the classified types so we can log
# each file with its predicted doc_type, status, and job run id.
# NOTE: this must run BEFORE temp table cleanup so parsed_docs_df / classified_docs_df
# lazy references are still valid.
try:
    _log_df = (
        parsed_docs_df
        .join(
            classified_docs_df.select("filename", "doc_type"),
            on="filename", how="left"
        )
        .select(
            F.col("path").alias("file_path"),
            F.col("filename").alias("file_name"),
            F.lit(domain_id).alias("domain_id"),
            F.col("doc_type"),
            F.lit("success").alias("status"),
            F.current_timestamp().alias("processed_at"),
            F.lit(job_run_id).cast("long").alias("job_run_id"),
            F.lit(None).cast("int").alias("records_written"),
            F.lit(None).cast("string").alias("error_message"),
            F.lit(None).cast("long").alias("file_size_bytes"),
            F.lit(PIPELINE_VERSION).alias("pipeline_version"),
        )
    )
    _log_count = _log_df.count()

    # Remove any previous entries for these files (force_reprocess case)
    _log_paths = [r.file_path for r in _log_df.select("file_path").collect()]
    if _log_paths:
        _log_paths_sql = ", ".join(f"'{p}'" for p in _log_paths)
        spark.sql(f"""
            DELETE FROM {CATALOG}.platform.file_processing_log
            WHERE file_path IN ({_log_paths_sql})
              AND domain_id = '{domain_id}'
        """)

    _log_df.write.mode("append").saveAsTable(f"{CATALOG}.platform.file_processing_log")
    print(f"file_processing_log: logged {_log_count} files as 'success'")
except Exception as _log_write_err:
    print(f"file_processing_log write warning (non-fatal): {_log_write_err}")

# ── Temp table cleanup (after log write so lazy DF refs are still valid above) ──
try:
    all_tbl_rows = spark.sql(f"SHOW TABLES IN {CATALOG}.{SCHEMA_RAW}").collect()
    tmp_rows = [r for r in all_tbl_rows if r["tableName"].startswith("_tmp_")]
    for row in tmp_rows:
        tname = row["tableName"]
        spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.{SCHEMA_RAW}.`{tname}`")
        print(f"Dropped temp table: {CATALOG}.{SCHEMA_RAW}.{tname}")
    print(f"Temp table cleanup: removed {len(tmp_rows)} tables.")
except Exception as _e:
    print(f"Temp table cleanup warning (non-fatal): {_e}")

print("=" * 70)
print(f"  IDP Pipeline Complete — domain: {domain_id}")
print(f"  mode: {mode}  |  force_reprocess: {force_reprocess}  |  skip_no_schema: {skip_no_schema}")
print("=" * 70)
print(f"  parsed_documents    → {CATALOG}.{SCHEMA_RAW}.parsed_documents")
print(f"  document_chunks     → {CATALOG}.{SCHEMA_VEC}.document_chunks  ({chunk_count} chunks, ai_prep_search={'YES' if prep_search_available else 'NO - manual fallback needed'})")
print(f"  gold tables         → {CATALOG}.{SCHEMA_RAW}.gold_*  ({len(gold_dfs)} types)")
print(f"  extracted_fields    → {CATALOG}.{SCHEMA_RAW}.extracted_fields")
print(f"  suggested_extractions → {CATALOG}.{SCHEMA_RAW}.suggested_extractions  (schema discovery)")
print(f"  file_processing_log → {CATALOG}.platform.file_processing_log")
print("=" * 70)

display(spark.sql(f"""
    SELECT doc_type, COUNT(*) AS doc_count
    FROM {CATALOG}.{SCHEMA_RAW}.parsed_documents
    GROUP BY doc_type
    ORDER BY doc_type
"""))

display(spark.sql(f"""
    SELECT domain_id, status, COUNT(*) AS files, MAX(processed_at) AS last_run
    FROM {CATALOG}.platform.file_processing_log
    WHERE domain_id = '{domain_id}'
    GROUP BY domain_id, status
"""))
