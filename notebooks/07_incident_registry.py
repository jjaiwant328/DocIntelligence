# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Incident Registry Setup
# MAGIC
# MAGIC Creates the `incidents` and `incident_documents` tables in the per-domain
# MAGIC schema, seeds sample incidents for the Supply Chain domain (including the
# MAGIC existing recall RCL-2024-0012 plus two new synthetic incidents), and
# MAGIC generates supporting synthetic PDF documents for the two new incidents.
# MAGIC
# MAGIC Run this notebook once. It is safe to re-run (uses CREATE OR REPLACE).

# COMMAND ----------

CATALOG    = "jai_docintel"
DOMAIN_ID  = "supply_chain"
SCHEMA     = "supply_chain"   # domain data schema
SCHEMA_RAW = "raw"
VOLUME     = f"/Volumes/{CATALOG}/{SCHEMA_RAW}/documents"

spark.sql(f"USE CATALOG {CATALOG}")
print(f"Catalog: {CATALOG}  Schema: {SCHEMA}")

# COMMAND ----------
# MAGIC %md ## 1 — Create `incidents` table

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA}.incidents (
    incident_id            STRING  NOT NULL,
    domain_id              STRING  NOT NULL,
    incident_type          STRING,
    title                  STRING,
    description            STRING,
    status                 STRING,
    severity               STRING,
    primary_entity         STRING,
    primary_entity_label   STRING,
    opened_date            DATE,
    closed_date            DATE,
    assigned_to            STRING,
    financial_exposure_usd DOUBLE,
    affected_count         INT,
    affected_label         STRING,
    tags                   ARRAY<STRING>,
    created_at             TIMESTAMP
)
USING DELTA
COMMENT 'Registry of all incidents across subject areas'
""")

# COMMAND ----------
# MAGIC %md ## 2 — Create `incident_documents` join table

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA}.incident_documents (
    incident_id   STRING     NOT NULL,
    document_path STRING     NOT NULL,
    document_name STRING,
    linked_at     TIMESTAMP  NOT NULL,
    linked_by     STRING
)
USING DELTA
COMMENT 'Many-to-many: incidents <-> parsed documents'
""")

# COMMAND ----------
# MAGIC %md ## 3 — Seed / upsert the three incidents

# COMMAND ----------

from pyspark.sql import Row
from datetime import date, datetime

INCIDENTS = [
    Row(
        incident_id            = "RCL-2024-0012",
        domain_id              = "supply_chain",
        incident_type          = "product_recall",
        title                  = "Class II Voluntary Recall — Fresh Chicken Sandwich Fillets",
        description            = (
            "Lot LOT-PP-240315 (Fresh Chicken Sandwich Fillets) recalled after a 68-minute "
            "cold chain excursion on trailer TR-8821. 240 cases distributed to 12 Southeast "
            "restaurants. Class II FDA voluntary recall filed under 21 CFR Part 7.46."
        ),
        status                 = "active",
        severity               = "critical",
        primary_entity         = "SUPP-001",
        primary_entity_label   = "Tyson Foods",
        opened_date            = date(2024, 3, 20),
        closed_date            = None,
        assigned_to            = "Recall Coordinator",
        financial_exposure_usd = 224800.0,
        affected_count         = 12,
        affected_label         = "restaurants",
        tags                   = ["recall", "cold-chain", "FDA", "Tyson Foods"],
        created_at             = datetime(2024, 3, 20, 9, 0, 0),
    ),
    Row(
        incident_id            = "AUD-2024-0045",
        domain_id              = "supply_chain",
        incident_type          = "supplier_audit",
        title                  = "Critical Cold Chain Audit Failure — Fresh Harvest Farms",
        description            = (
            "Unannounced audit of Fresh Harvest Farms (SUPP-002) Gainesville, GA facility "
            "revealed systematic refrigeration protocol violations: pre-cooling non-compliance "
            "on 6 of 8 lines, missing calibration records, and two units reading 42°F vs. 38°F "
            "max. All 4 of 4 critical findings (FDA Grade 1). Corrective Action Plan required "
            "within 15 business days."
        ),
        status                 = "investigating",
        severity               = "high",
        primary_entity         = "SUPP-002",
        primary_entity_label   = "Fresh Harvest Farms",
        opened_date            = date(2024, 9, 12),
        closed_date            = None,
        assigned_to            = "Supplier Quality Manager",
        financial_exposure_usd = 47500.0,
        affected_count         = 3,
        affected_label         = "distribution centers",
        tags                   = ["audit", "cold-chain", "corrective-action", "Fresh Harvest Farms"],
        created_at             = datetime(2024, 9, 12, 14, 30, 0),
    ),
    Row(
        incident_id            = "CTR-2025-0003",
        domain_id              = "supply_chain",
        incident_type          = "contract_dispute",
        title                  = "Contract Dispute — BluePeak Packaging MSA Renewal Terms",
        description            = (
            "BluePeak Packaging (SUPP-003) has proposed a 23% price increase on tamper-evident "
            "seal SKUs (BE-441, BE-442) effective Q2 2025, citing resin cost increases. Current "
            "MSA (MSA-2024-BP-003) locks pricing through Dec 2024. Legal review of force-majeure "
            "clause §9.2 and commodity price-index clause §7.4 is underway. Alternative suppliers "
            "Sealed Air and Berry Global are being evaluated as contingency."
        ),
        status                 = "investigating",
        severity               = "medium",
        primary_entity         = "SUPP-003",
        primary_entity_label   = "BluePeak Packaging",
        opened_date            = date(2025, 1, 8),
        closed_date            = None,
        assigned_to            = "Procurement Manager",
        financial_exposure_usd = 312000.0,
        affected_count         = 2,
        affected_label         = "product SKUs",
        tags                   = ["contract", "packaging", "pricing", "BluePeak Packaging"],
        created_at             = datetime(2025, 1, 8, 10, 0, 0),
    ),
]

from pyspark.sql.types import (StructType, StructField, StringType, DateType,
                               DoubleType, IntegerType, TimestampType, ArrayType)

schema = StructType([
    StructField("incident_id",            StringType()),
    StructField("domain_id",              StringType()),
    StructField("incident_type",          StringType()),
    StructField("title",                  StringType()),
    StructField("description",            StringType()),
    StructField("status",                 StringType()),
    StructField("severity",               StringType()),
    StructField("primary_entity",         StringType()),
    StructField("primary_entity_label",   StringType()),
    StructField("opened_date",            DateType()),
    StructField("closed_date",            DateType()),
    StructField("assigned_to",            StringType()),
    StructField("financial_exposure_usd", DoubleType()),
    StructField("affected_count",         IntegerType()),
    StructField("affected_label",         StringType()),
    StructField("tags",                   ArrayType(StringType())),
    StructField("created_at",             TimestampType()),
])

df = spark.createDataFrame(INCIDENTS, schema=schema)

# Merge (upsert) by incident_id so re-runs are idempotent
from delta.tables import DeltaTable
target = DeltaTable.forName(spark, f"{CATALOG}.{SCHEMA}.incidents")
(target.alias("t")
    .merge(df.alias("s"), "t.incident_id = s.incident_id")
    .whenMatchedUpdateAll()
    .whenNotMatchedInsertAll()
    .execute())

print("Incidents upserted:")
spark.sql(f"SELECT incident_id, title, status, severity FROM {CATALOG}.{SCHEMA}.incidents ORDER BY opened_date").show(truncate=60)

# COMMAND ----------
# MAGIC %md ## 4 — Auto-link existing documents to RCL-2024-0012

# COMMAND ----------

# All documents currently parsed in the raw schema belong to the recall scenario
existing_docs = spark.sql(f"""
    SELECT DISTINCT path,
           regexp_extract(path, '[^/]+$', 0) AS document_name
    FROM {CATALOG}.{SCHEMA_RAW}.parsed_documents
""")

from pyspark.sql.functions import lit, current_timestamp

rcl_docs = (existing_docs
    .withColumn("incident_id", lit("RCL-2024-0012"))
    .withColumn("linked_at",   current_timestamp())
    .withColumn("linked_by",   lit("system"))
    .select("incident_id", "path", "document_name", "linked_at", "linked_by")
    .withColumnRenamed("path", "document_path"))

# Insert only new rows
rcl_docs.createOrReplaceTempView("new_links")
spark.sql(f"""
    MERGE INTO {CATALOG}.{SCHEMA}.incident_documents t
    USING new_links s
    ON t.incident_id = s.incident_id AND t.document_path = s.document_path
    WHEN NOT MATCHED THEN INSERT *
""")

count = spark.sql(f"SELECT COUNT(*) FROM {CATALOG}.{SCHEMA}.incident_documents").collect()[0][0]
print(f"Documents linked to incidents: {count}")

# COMMAND ----------
# MAGIC %md ## 5 — Generate synthetic PDFs for the two new incidents

# COMMAND ----------

import os, textwrap
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    REPORTLAB = True
except ImportError:
    REPORTLAB = False
    print("reportlab not available — writing plain text files instead")

os.makedirs(VOLUME, exist_ok=True)

def write_text(path, content):
    with open(path, "w") as f:
        f.write(content)

# ── AUD-2024-0045 documents ────────────────────────────────────────────────

AUDIT_DOCS = [
    {
        "filename": "audit_report_fresh_harvest_farms_2024.pdf",
        "title":    "Supplier Audit Report — Fresh Harvest Farms",
        "incident": "AUD-2024-0045",
        "content": [
            ("SUPPLIER AUDIT REPORT", "h1"),
            ("Fresh Harvest Farms — Gainesville, GA Facility", "h2"),
            ("Audit Date: September 12, 2024  |  Auditor: QA Team  |  Reference: AUD-2024-0045", "meta"),
            ("EXECUTIVE SUMMARY", "h2"),
            ("An unannounced audit of the Fresh Harvest Farms Gainesville, GA cold storage and "
             "processing facility was conducted on September 12, 2024. The audit identified "
             "4 critical findings (FDA Grade 1), 6 major findings (FDA Grade 2), and 3 minor "
             "findings (FDA Grade 3). The facility FAILED this audit and is placed on "
             "CONDITIONAL supplier status pending corrective action.", "body"),
            ("CRITICAL FINDINGS (Grade 1)", "h2"),
            ("CF-001: Pre-cooling non-compliance on 6 of 8 processing lines. Required product "
             "core temp ≤38°F before packaging; observed 44.1°F on Line 3 and 45.8°F on Line 7.", "bullet"),
            ("CF-002: Refrigeration unit #4 temperature reading 42.3°F against 38°F maximum. "
             "Last calibration record dated March 2023 — 18 months overdue.", "bullet"),
            ("CF-003: Missing HACCP temperature log entries for 14 consecutive production days "
             "(Aug 29 – Sep 11, 2024). No corrective action documented.", "bullet"),
            ("CF-004: Cold storage dock door seals failing on doors D-3 and D-5; ambient "
             "infiltration measured at 58°F during loading operations.", "bullet"),
            ("CORRECTIVE ACTION REQUIREMENTS", "h2"),
            ("Fresh Harvest Farms must submit a Corrective Action Plan (CAP) within 15 business "
             "days addressing all critical and major findings. A follow-up audit will be "
             "conducted within 60 days of CAP submission. Failure to comply will result in "
             "suspension of the supplier contract.", "body"),
            ("FINANCIAL IMPACT", "h2"),
            ("Estimated cost of enhanced receiving inspection for all Fresh Harvest inbound "
             "shipments (90-day protocol): $47,500. Three distribution centers affected: "
             "Atlanta DC (DC-001), Charlotte DC (DC-003), Nashville DC (DC-007).", "body"),
        ]
    },
    {
        "filename": "corrective_action_plan_fresh_harvest_2024.pdf",
        "title":    "Corrective Action Plan — Fresh Harvest Farms Response",
        "incident": "AUD-2024-0045",
        "content": [
            ("CORRECTIVE ACTION PLAN", "h1"),
            ("In Response to Audit AUD-2024-0045 — Fresh Harvest Farms", "h2"),
            ("Submitted: October 2, 2024  |  Supplier: Fresh Harvest Farms  |  Status: PENDING REVIEW", "meta"),
            ("CAP RESPONSE SUMMARY", "h2"),
            ("Fresh Harvest Farms acknowledges all 4 critical findings identified in audit "
             "AUD-2024-0045 and commits to the following corrective actions:", "body"),
            ("CF-001 RESPONSE: All 8 processing lines recalibrated and pre-cooling protocols "
             "updated. New minimum pre-cool hold time increased from 45 to 90 minutes. "
             "Completion: September 20, 2024. Verified by: Plant Manager.", "bullet"),
            ("CF-002 RESPONSE: Refrigeration unit #4 fully replaced with new Carrier 06DR Series. "
             "All 12 refrigeration units scheduled for quarterly calibration. Next calibration: "
             "December 2024. Calibration contractor: ColdCheck Services.", "bullet"),
            ("CF-003 RESPONSE: HACCP digital logging system installed on all lines. "
             "14-day gap was caused by system migration failure — audit trail reconstructed "
             "from secondary temperature sensors. New logging system live: September 18, 2024.", "bullet"),
            ("CF-004 RESPONSE: Dock doors D-3 and D-5 resealed with Freon-compatible gaskets. "
             "All 11 dock doors inspected; 3 additional doors received minor seal repairs. "
             "Door inspection added to weekly facility checklist.", "bullet"),
            ("FOLLOW-UP AUDIT REQUEST", "h2"),
            ("Fresh Harvest Farms requests follow-up audit scheduling for the week of "
             "November 18, 2024 to demonstrate full compliance.", "body"),
        ]
    },
    {
        "filename": "temperature_excursion_log_fresh_harvest_Q3_2024.pdf",
        "title":    "Temperature Excursion Log — Fresh Harvest Farms Q3 2024",
        "incident": "AUD-2024-0045",
        "content": [
            ("TEMPERATURE EXCURSION LOG", "h1"),
            ("Fresh Harvest Farms — Q3 2024 (July – September 2024)", "h2"),
            ("Facility: Gainesville, GA  |  Prepared for: QA Audit AUD-2024-0045", "meta"),
            ("EXCURSION SUMMARY", "h2"),
            ("Total excursions Q3 2024: 7  |  Grade 1 (>4°F deviation, >30 min): 3  "
             "|  Grade 2 (2–4°F deviation): 4", "body"),
            ("EXCURSION RECORDS", "h2"),
            ("EXC-001: July 14, 2024. Line 3 pre-cool. Duration: 47 min. Peak: 46.2°F. "
             "Root cause: Drain line blockage. Corrective action: Drain cleared, product held.", "bullet"),
            ("EXC-002: July 29, 2024. Cold storage Zone B. Duration: 22 min. Peak: 40.8°F. "
             "Root cause: Door seal gap (D-3). Corrective action: Temporary seal applied.", "bullet"),
            ("EXC-003: August 5, 2024. Refrigeration Unit #4. Duration: 3 hr 18 min. "
             "Peak: 48.7°F. Root cause: Compressor cycling fault. Corrective action: "
             "Manual cooling engaged, unit flagged for service. GRADE 1 — CRITICAL.", "bullet"),
            ("EXC-004: August 22, 2024. Line 7 pre-cool. Duration: 52 min. Peak: 45.8°F. "
             "Root cause: Pre-cool timer malfunction. Corrective action: Timer replaced. GRADE 1 — CRITICAL.", "bullet"),
            ("EXC-005 through EXC-007: Minor deviations (2.1°F – 3.4°F), duration < 20 min. "
             "All within Grade 2 threshold. Documented and resolved same-day.", "bullet"),
            ("TREND ANALYSIS", "h2"),
            ("7 excursions in Q3 2024 vs. 1 excursion in Q3 2023. Upward trend correlated "
             "with aging refrigeration unit #4 (10 years old vs. 7-year replacement cycle). "
             "Replacement authorized September 15, 2024.", "body"),
        ]
    },
]

# ── CTR-2025-0003 documents ────────────────────────────────────────────────

CONTRACT_DOCS = [
    {
        "filename": "contract_dispute_bluepeak_packaging_2025.pdf",
        "title":    "Contract Dispute Summary — BluePeak Packaging Price Increase",
        "incident": "CTR-2025-0003",
        "content": [
            ("CONTRACT DISPUTE NOTICE", "h1"),
            ("BluePeak Packaging — MSA-2024-BP-003 Price Increase Dispute", "h2"),
            ("Date: January 8, 2025  |  Reference: CTR-2025-0003  |  Assigned: Procurement", "meta"),
            ("DISPUTE OVERVIEW", "h2"),
            ("BluePeak Packaging (Supplier ID: SUPP-003) has formally notified of a 23% price "
             "increase on tamper-evident seal SKUs BE-441 and BE-442 effective April 1, 2025. "
             "The current Master Supply Agreement (MSA-2024-BP-003) contains fixed pricing "
             "through December 31, 2024. BluePeak cites resin cost increases under the "
             "force-majeure clause (§9.2) and commodity price index escalation clause (§7.4).", "body"),
            ("CONTRACT CLAUSES UNDER REVIEW", "h2"),
            ("§7.4 Commodity Price Index: Allows price adjustment if the ICIS Polyethylene Index "
             "increases >15% in any rolling 90-day period. ICIS index increased 18.3% in Q4 2024 "
             "— clause may be triggerable. Legal review in progress.", "bullet"),
            ("§9.2 Force Majeure: BluePeak claims global resin supply chain disruption qualifies. "
             "Legal counsel position: force majeure does not apply to market price fluctuations. "
             "Counter-argument prepared.", "bullet"),
            ("§12.1 Termination for Convenience: Either party may terminate with 90-day notice. "
             "BluePeak has not invoked this clause. Procurement evaluating as leverage.", "bullet"),
            ("FINANCIAL EXPOSURE", "h2"),
            ("Annual spend on BE-441/BE-442: $1,354,000 (2024 actuals). "
             "23% increase = $311,420 additional annual cost. "
             "Q2 2025 impact (if increase effective April 1): $77,855.", "body"),
            ("RECOMMENDED ACTIONS", "h2"),
            ("1. Legal to issue formal counter-notice rejecting §9.2 force-majeure claim.", "bullet"),
            ("2. Procurement to obtain competitive bids from Sealed Air Corp and Berry Global.", "bullet"),
            ("3. Negotiate price cap: accept §7.4 escalation (max 8%) in exchange for "
             "2-year extension commitment.", "bullet"),
        ]
    },
    {
        "filename": "bluepeak_msa_amendment_proposal_2025.pdf",
        "title":    "MSA Amendment Proposal — BluePeak Packaging",
        "incident": "CTR-2025-0003",
        "content": [
            ("MASTER SUPPLY AGREEMENT AMENDMENT PROPOSAL", "h1"),
            ("Amendment No. 1 to MSA-2024-BP-003", "h2"),
            ("Parties: DocIntel QSR Corp. and BluePeak Packaging LLC  |  Date: February 14, 2025", "meta"),
            ("PROPOSED AMENDMENT TERMS", "h2"),
            ("Following good-faith negotiation sessions on January 22 and February 7, 2025, "
             "the parties propose the following amendment to MSA-2024-BP-003:", "body"),
            ("SECTION 7.4 REVISION — Price Adjustment Mechanism: Replace existing ICIS index "
             "clause with a blended index (70% ICIS Polyethylene, 30% PPI Packaging Materials). "
             "Annual adjustment cap: 8% per calendar year. Semi-annual review cycle.", "bullet"),
            ("NEW SECTION 7.5 — Volume Commitment Discount: In exchange for a 2-year extension "
             "commitment (through December 31, 2026) and minimum annual volume of 4.2M units, "
             "BluePeak will apply a 3.5% volume discount effective immediately.", "bullet"),
            ("SECTION 9.2 REVISION — Force Majeure: Add specific exclusion: 'market commodity "
             "price fluctuations, whether or not resulting from supply disruption, shall not "
             "constitute force majeure for pricing purposes.'", "bullet"),
            ("NET FINANCIAL OUTCOME", "h2"),
            ("Proposed annual cost increase (blended index): ~$58,000 (vs. $311,420 proposed). "
             "Volume discount offset: ~$47,390. Net impact: ~$10,610 annual increase — "
             "acceptable within FY2025 budget tolerance of $25,000.", "body"),
            ("STATUS", "h2"),
            ("Internal approval required from: VP Supply Chain, Legal Counsel, CFO. "
             "Target execution date: March 1, 2025. Pending final legal review.", "body"),
        ]
    },
    {
        "filename": "supplier_comparison_packaging_2025.pdf",
        "title":    "Packaging Supplier Competitive Analysis — 2025",
        "incident": "CTR-2025-0003",
        "content": [
            ("PACKAGING SUPPLIER COMPETITIVE ANALYSIS", "h1"),
            ("Tamper-Evident Seals SKUs BE-441 / BE-442 — Alternate Supplier Evaluation", "h2"),
            ("Prepared by: Procurement  |  Date: January 28, 2025  |  Ref: CTR-2025-0003", "meta"),
            ("PURPOSE", "h2"),
            ("Evaluate alternative suppliers for tamper-evident seal SKUs BE-441 and BE-442 "
             "as contingency to the BluePeak Packaging contract dispute (CTR-2025-0003).", "body"),
            ("SUPPLIER EVALUATIONS", "h2"),
            ("SEALED AIR CORPORATION: Annual price per unit (BE-441 equiv): $0.142 vs. "
             "BluePeak current $0.148. Lead time: 6 weeks (vs. 3 weeks BluePeak). "
             "Quality rating: 4.7/5.0. FDA compliance: Certified. Min order: 500K units/year. "
             "Switching cost estimate: $28,000 (tooling, validation). RECOMMENDATION: VIABLE.", "bullet"),
            ("BERRY GLOBAL GROUP: Annual price per unit: $0.155 (6.8% above BluePeak current). "
             "Lead time: 4 weeks. Quality rating: 4.9/5.0 — industry leading. "
             "FDA compliance: Certified. Min order: 250K units/year. "
             "Switching cost estimate: $19,500. Better quality, higher unit cost. "
             "RECOMMENDATION: VIABLE as premium alternative.", "bullet"),
            ("AMCOR PLC: Does not produce equivalent spec for BE-442 form factor. "
             "RECOMMENDATION: NOT VIABLE for current SKUs.", "bullet"),
            ("RECOMMENDATION", "h2"),
            ("If BluePeak negotiation fails: award 70% volume to Sealed Air (cost savings), "
             "30% to Berry Global (quality/risk diversification). Total annual savings vs. "
             "BluePeak proposed pricing: ~$178,000. Dual-source strategy also reduces "
             "single-supplier dependency risk.", "body"),
        ]
    },
]

# COMMAND ----------

def pdf_or_text(doc_def, volume_path):
    """Write a structured document as PDF (if reportlab available) else .txt"""
    if REPORTLAB:
        fpath = os.path.join(volume_path, doc_def["filename"])
        doc = SimpleDocTemplate(fpath, pagesize=letter,
                                leftMargin=inch, rightMargin=inch,
                                topMargin=inch, bottomMargin=inch)
        styles = getSampleStyleSheet()
        h1_style   = ParagraphStyle("H1",   parent=styles["Heading1"],   fontSize=16, spaceAfter=6)
        h2_style   = ParagraphStyle("H2",   parent=styles["Heading2"],   fontSize=12, spaceAfter=4)
        meta_style = ParagraphStyle("Meta", parent=styles["Normal"],     fontSize=8,  textColor=colors.gray, spaceAfter=10)
        body_style = ParagraphStyle("Body", parent=styles["Normal"],     fontSize=10, spaceAfter=8, leading=14)
        bull_style = ParagraphStyle("Bull", parent=styles["Normal"],     fontSize=9,  spaceAfter=6, leftIndent=20, leading=13)

        story = []
        for text, kind in doc_def["content"]:
            if kind == "h1":   story.append(Paragraph(text, h1_style))
            elif kind == "h2": story.append(Paragraph(text, h2_style))
            elif kind == "meta": story.append(Paragraph(text, meta_style))
            elif kind == "bullet": story.append(Paragraph(f"• {text}", bull_style))
            else:              story.append(Paragraph(text, body_style))
            story.append(Spacer(1, 4))
        doc.build(story)
        return fpath
    else:
        fname = doc_def["filename"].replace(".pdf", ".txt")
        fpath = os.path.join(volume_path, fname)
        lines = [doc_def["title"], "=" * len(doc_def["title"]), ""]
        for text, kind in doc_def["content"]:
            if kind in ("h1", "h2"):   lines += [text.upper(), "-" * len(text), ""]
            elif kind == "bullet":     lines += [f"  * {text}", ""]
            else:                      lines += [textwrap.fill(text, 100), ""]
        write_text(fpath, "\n".join(lines))
        return fpath

# Write all new incident docs
written = []
for doc_def in AUDIT_DOCS + CONTRACT_DOCS:
    path = pdf_or_text(doc_def, VOLUME)
    written.append((doc_def["incident"], os.path.basename(path)))
    print(f"  ✓ {os.path.basename(path)}")

print(f"\n{len(written)} documents written to {VOLUME}")

# COMMAND ----------
# MAGIC %md ## 6 — Verify

# COMMAND ----------

print("=== Incidents ===")
spark.sql(f"""
    SELECT incident_id, incident_type, title, status, severity,
           financial_exposure_usd, affected_count, opened_date
    FROM {CATALOG}.{SCHEMA}.incidents
    ORDER BY opened_date
""").show(truncate=60)

print("=== Document links ===")
spark.sql(f"""
    SELECT incident_id, COUNT(*) AS linked_docs
    FROM {CATALOG}.{SCHEMA}.incident_documents
    GROUP BY incident_id
    ORDER BY incident_id
""").show()

print(f"\nNew PDFs in volume ({VOLUME}):")
for inc, name in written:
    print(f"  {inc}: {name}")
