# Databricks notebook source
# MAGIC %md
# MAGIC # Parse Documents — Auto Loader + TXT support
# MAGIC
# MAGIC Uses **Auto Loader** (`cloudFiles`) with `trigger(availableNow=True)` so only
# MAGIC **new files** (not previously seen) are processed on each run.  This prevents
# MAGIC duplicates in `parsed_documents_raw` and makes every scheduled run truly incremental.
# MAGIC
# MAGIC **Supported file types**
# MAGIC | Type | Processing |
# MAGIC |------|-----------|
# MAGIC | PDF / JPG / PNG / JPEG | `ai_parse_document` → VARIANT |
# MAGIC | TXT | direct text read → synthetic VARIANT |
# MAGIC
# MAGIC **Auto Loader modes**
# MAGIC | `use_notifications` | Behaviour |
# MAGIC |---------------------|-----------|
# MAGIC | `false` (default) | Directory-listing mode — Auto Loader periodically lists the volume to find new files. No extra Azure setup required. |
# MAGIC | `true` | **File-notification mode** — Azure Event Grid pushes arrival events to a queue; Auto Loader picks them up with sub-minute latency. Requires Azure Event Grid + queue subscription pre-configured for the storage account. |

# COMMAND ----------

dbutils.widgets.text("catalog",             "fins_genai",               "Catalog name")
dbutils.widgets.text("schema",              "unstructured_documents",    "Schema name")
dbutils.widgets.text(
    "source_volume_path",
    "/Volumes/fins_genai/unstructured_documents/ai_parse_document_workflow/inputs/",
    "Source volume path",
)
# volume_path — alias sent by the DocIntelligence job trigger (job_parameters broadcast)
dbutils.widgets.text("volume_path", "", "Volume path override (from job trigger; overrides source_volume_path)")
dbutils.widgets.text(
    "output_volume_path",
    "/Volumes/fins_genai/unstructured_documents/ai_parse_document_workflow/outputs/",
    "Output volume path (images from ai_parse_document)",
)
dbutils.widgets.text("table_name",          "parsed_documents_raw",     "Output Delta table")
dbutils.widgets.text(
    "checkpoint_location",
    "",
    "Auto Loader checkpoint path (leave blank to auto-derive under source_volume_path)",
)
dbutils.widgets.dropdown("use_notifications", "false", ["false", "true"],
    "File-notification mode (true = Azure Event Grid; requires cloud-side setup)")
# mode — batch (default) | interactive.  In interactive mode a temp checkpoint is used so
# already-seen files are re-processed (Auto Loader normally skips them after first run).
dbutils.widgets.text("mode", "batch", "Processing mode: batch | interactive")

catalog             = dbutils.widgets.get("catalog")
schema              = dbutils.widgets.get("schema")
mode                = dbutils.widgets.get("mode").strip().lower() or "batch"
use_notifications   = dbutils.widgets.get("use_notifications").lower() == "true"

# volume_path (job param) takes precedence over source_volume_path (task base param)
_vol_override = dbutils.widgets.get("volume_path").strip()
if _vol_override:
    source_volume_path = _vol_override.rstrip("/") + "/"
else:
    source_volume_path = dbutils.widgets.get("source_volume_path").rstrip("/") + "/"

output_volume_path  = dbutils.widgets.get("output_volume_path").rstrip("/") + "/"
table_name          = dbutils.widgets.get("table_name")

_ckpt_base = dbutils.widgets.get("checkpoint_location").strip()

if mode == "interactive":
    # In interactive mode always use a throwaway checkpoint so Auto Loader re-reads all
    # files in the volume regardless of what was previously checkpointed.
    # The stable batch checkpoint at _ckpt_base is left completely untouched.
    _ckpt_raw = f"/tmp/docintel_interactive_{catalog}_{schema}/checkpoints/01_parse_documents"
elif _ckpt_base:
    _ckpt_raw = _ckpt_base
else:
    # Derive a stable checkpoint path adjacent to the source volume
    _ckpt_raw = source_volume_path.rstrip("/").rsplit("/", 2)[0] + "/checkpoints/01_parse_documents"

checkpoint_pdf    = _ckpt_raw + "/pdf"
checkpoint_txt    = _ckpt_raw + "/txt"
checkpoint_office = _ckpt_raw + "/office"   # .eml / .html / .docx branch

# COMMAND ----------

spark.sql(f"USE CATALOG {catalog}")
spark.sql(f"USE SCHEMA {schema}")

print("=" * 70)
print("  DocIntelligence — Parse Documents (Auto Loader)")
print("=" * 70)
print(f"  Mode           : {mode}")
print(f"  Source volume  : {source_volume_path}")
print(f"  Output table   : {catalog}.{schema}.{table_name}")
print(f"  Checkpoint PDF : {checkpoint_pdf}")
print(f"  Checkpoint TXT : {checkpoint_txt}")
print(f"  Checkpoint OFF : {checkpoint_office}")
print(f"  Notifications  : {'YES (file-notification mode)' if use_notifications else 'NO (directory-listing mode)'}")
if mode == "interactive":
    print("  ⚡ Interactive mode: using temp checkpoint — all volume files will be re-parsed")
print("=" * 70)

# COMMAND ----------

# MAGIC %md ## Step 1 — Process PDF / image files with ai_parse_document

# COMMAND ----------

from pyspark.sql import functions as F

# Base cloudFiles options shared across all readers
_base_opts = {
    "cloudFiles.format":                "binaryFile",
    "cloudFiles.includeExistingFiles":  "true",
    "cloudFiles.useNotifications":      str(use_notifications).lower(),
}

# ── PDF / image stream ────────────────────────────────────────────────────────
print("Reading PDF/image files via Auto Loader …")

pdf_stream = (
    spark.readStream
        .format("cloudFiles")
        .options(**_base_opts)
        .option("pathGlobFilter", "*.{pdf,jpg,jpeg,png}")
        .load(source_volume_path)
)

# Apply ai_parse_document (produces a VARIANT column `parsed`)
pdf_parsed = (
    pdf_stream
    .withColumn(
        "parsed",
        F.expr(f"""
            ai_parse_document(
                content,
                map(
                    'version', '2.0',
                    'imageOutputPath', '{output_volume_path}',
                    'descriptionElementTypes', '*'
                )
            )
        """),
    )
    .withColumn("parsed_at", F.current_timestamp())
    .select("path", "parsed", "parsed_at")
)

# Write incrementally — trigger(availableNow=True) processes all pending files then stops
(
    pdf_parsed.writeStream
        .trigger(availableNow=True)
        .option("checkpointLocation", checkpoint_pdf)
        .format("delta")
        .outputMode("append")
        .option("delta.feature.variantType-preview", "supported")
        .option("mergeSchema", "true")
        .toTable(f"{catalog}.{schema}.{table_name}")
        .awaitTermination()
)
print("✅ PDF/image Auto Loader stream finished.")

# COMMAND ----------

# MAGIC %md ## Step 2 — Process TXT files (plain text — ai_parse_document not required)
# MAGIC
# MAGIC TXT files are read as plain text and wrapped in a **synthetic VARIANT** that
# MAGIC matches the `ai_parse_document` output schema so the rest of the pipeline
# MAGIC (`ai_classify`, `ai_extract`, manual chunking) works identically.
# MAGIC
# MAGIC Synthetic VARIANT structure:
# MAGIC ```json
# MAGIC {
# MAGIC   "document": {
# MAGIC     "elements": [{"type":"NarrativeText","content":"<full text>","confidence":1.0,"id":0,"bbox":[]}],
# MAGIC     "pages": []
# MAGIC   },
# MAGIC   "metadata": {"id":"<filename>","version":"txt_direct"},
# MAGIC   "error_status": null
# MAGIC }
# MAGIC ```

# COMMAND ----------

print("Reading TXT files via Auto Loader …")

txt_stream = (
    spark.readStream
        .format("cloudFiles")
        .option("cloudFiles.format",               "text")
        .option("cloudFiles.includeExistingFiles",  "true")
        .option("cloudFiles.useNotifications",      str(use_notifications).lower())
        .option("pathGlobFilter",                   "*.txt")
        .option("wholetext",                        "true")   # read each file as a single string
        .load(source_volume_path)
)

# `value` = whole file content; `_metadata.file_path` = full path
txt_with_meta = txt_stream.select(
    F.col("_metadata.file_path").alias("path"),
    F.col("value").alias("_txt_content"),
    F.current_timestamp().alias("parsed_at"),
)

# Build synthetic VARIANT from text content.
# parse_json(to_json(named_struct(...))) is the most compatible approach (DBR 12+):
#   to_json converts the struct → JSON string (properly escaping content)
#   parse_json converts the JSON string → VARIANT (same type as ai_parse_document output)
txt_parsed = txt_with_meta.withColumn(
    "parsed",
    F.expr("""
        parse_json(
            to_json(
                named_struct(
                    'document', named_struct(
                        'elements', array(
                            named_struct(
                                'type',        'NarrativeText',
                                'content',     _txt_content,
                                'confidence',  CAST(1.0 AS DOUBLE),
                                'id',          CAST(0 AS BIGINT),
                                'bbox',        CAST(array() AS ARRAY<STRING>),
                                'description', CAST(NULL AS STRING)
                            )
                        ),
                        'pages', CAST(array() AS ARRAY<STRING>)
                    ),
                    'metadata', named_struct(
                        'id',      element_at(split(path, '/'), -1),
                        'version', CAST('txt_direct' AS STRING)
                    ),
                    'error_status', CAST(NULL AS STRING)
                )
            )
        )
    """)
).select("path", "parsed", "parsed_at")

(
    txt_parsed.writeStream
        .trigger(availableNow=True)
        .option("checkpointLocation", checkpoint_txt)
        .format("delta")
        .outputMode("append")
        .option("mergeSchema", "true")
        .toTable(f"{catalog}.{schema}.{table_name}")
        .awaitTermination()
)
print("✅ TXT Auto Loader stream finished.")

# COMMAND ----------

# MAGIC %md ## Step 2b — Process EML / HTML / DOCX files (email, web pages, office docs)
# MAGIC
# MAGIC Municipal/government sources arrive as feasibility **emails** (`.eml`), municode /
# MAGIC `.gov` **web pages** (`.html`/`.htm`), and **office docs** (`.docx`). Each is read
# MAGIC as a binary file, text is extracted with a stdlib-only UDF (no external deps, so it
# MAGIC runs on serverless), then wrapped in the **same synthetic VARIANT** as the TXT branch
# MAGIC so the rest of the pipeline is unchanged. Backward-compatible: for domains whose
# MAGIC volume holds no such files this glob matches nothing and the stream is a no-op.

# COMMAND ----------

from pyspark.sql.types import StringType


def _extract_office_web_email(path: str, content: bytes) -> str:
    """Extract plain text from .eml / .html|.htm / .docx. Stdlib only."""
    import re, html as _html, io, zipfile, email
    from email import policy

    def _strip_html(s: str) -> str:
        if not s:
            return ""
        s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", s)
        s = re.sub(r"(?i)<br\s*/?>", "\n", s)
        s = re.sub(r"(?i)</p\s*>", "\n", s)
        s = re.sub(r"<[^>]+>", " ", s)
        s = _html.unescape(s)
        s = re.sub(r"[ \t]+", " ", s)
        s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
        return s.strip()

    ext = path.lower().rsplit(".", 1)[-1] if "." in path else ""
    try:
        if ext == "eml":
            msg = email.message_from_bytes(bytes(content), policy=policy.default)
            headers = [f"{h}: {msg.get(h)}" for h in ("Subject", "From", "To", "Date") if msg.get(h)]
            plain = htmlpart = None
            if msg.is_multipart():
                for part in msg.walk():
                    ctype = part.get_content_type()
                    if ctype == "text/plain" and plain is None:
                        plain = part.get_content()
                    elif ctype == "text/html" and htmlpart is None:
                        htmlpart = part.get_content()
            else:
                if msg.get_content_type() == "text/html":
                    htmlpart = msg.get_content()
                else:
                    plain = msg.get_content()
            body = plain if plain else _strip_html(htmlpart or "")
            return ("\n".join(headers) + "\n\n" + (body or "")).strip()
        if ext in ("html", "htm"):
            return _strip_html(bytes(content).decode("utf-8", "ignore"))
        if ext == "docx":
            with zipfile.ZipFile(io.BytesIO(bytes(content))) as z:
                xml = z.read("word/document.xml").decode("utf-8", "ignore")
            xml = re.sub(r"(?i)<w:tab\b[^>]*/?>", "\t", xml)
            xml = re.sub(r"(?i)<w:(br|cr)\b[^>]*/?>", "\n", xml)
            xml = re.sub(r"</w:p>", "\n", xml)
            xml = re.sub(r"<[^>]+>", "", xml)   # adjacent runs concatenate (correct OOXML)
            return _html.unescape(xml).strip()
    except Exception as e:  # keep the pipeline moving; surface the failure in-band
        return f"[extract_error:{ext}] {e}"
    return ""


_extract_udf = F.udf(_extract_office_web_email, StringType())

print("Reading EML/HTML/DOCX files via Auto Loader …")

office_stream = (
    spark.readStream
        .format("cloudFiles")
        .options(**_base_opts)
        .option("pathGlobFilter", "*.{eml,html,htm,docx}")
        .load(source_volume_path)
)

office_with_text = office_stream.select(
    F.col("path").alias("path"),
    _extract_udf(F.col("path"), F.col("content")).alias("_txt_content"),
    F.current_timestamp().alias("parsed_at"),
).filter(F.length(F.trim(F.col("_txt_content"))) > 0)   # drop empty extractions

# Same synthetic VARIANT as the TXT branch; version records the source format.
office_parsed = office_with_text.withColumn(
    "parsed",
    F.expr("""
        parse_json(
            to_json(
                named_struct(
                    'document', named_struct(
                        'elements', array(
                            named_struct(
                                'type',        'NarrativeText',
                                'content',     _txt_content,
                                'confidence',  CAST(1.0 AS DOUBLE),
                                'id',          CAST(0 AS BIGINT),
                                'bbox',        CAST(array() AS ARRAY<STRING>),
                                'description', CAST(NULL AS STRING)
                            )
                        ),
                        'pages', CAST(array() AS ARRAY<STRING>)
                    ),
                    'metadata', named_struct(
                        'id',      element_at(split(path, '/'), -1),
                        'version', concat(lower(element_at(split(path, '.'), -1)), '_direct')
                    ),
                    -- surface extraction failures instead of indexing them as clean docs
                    'error_status', CASE WHEN _txt_content LIKE '[extract_error:%'
                                         THEN _txt_content ELSE CAST(NULL AS STRING) END
                )
            )
        )
    """)
).select("path", "parsed", "parsed_at")

(
    office_parsed.writeStream
        .trigger(availableNow=True)
        .option("checkpointLocation", checkpoint_office)
        .format("delta")
        .outputMode("append")
        .option("mergeSchema", "true")
        .toTable(f"{catalog}.{schema}.{table_name}")
        .awaitTermination()
)
print("✅ EML/HTML/DOCX Auto Loader stream finished.")

# COMMAND ----------

# MAGIC %md ## Summary

# COMMAND ----------

total = spark.table(f"{catalog}.{schema}.{table_name}").count()
print("=" * 70)
print(f"  Parse Documents complete — {catalog}.{schema}.{table_name}: {total} total rows")
print(f"  (Auto Loader checkpoints ensure each file is parsed only once)")
print("=" * 70)
