# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Platform Bootstrap
# MAGIC
# MAGIC Creates the `platform` schema in the `jai_docintel` catalog and seeds
# MAGIC the **domain registry** (`domain_configs` table). Run this notebook
# MAGIC **once** before adding a second domain. It is safe to re-run.
# MAGIC
# MAGIC After this notebook runs, the multi-domain setup wizard can create
# MAGIC new domains by inserting rows into `jai_docintel.platform.domain_configs`.

# COMMAND ----------

import json

CATALOG         = "jai_docintel"
SCHEMA_PLATFORM = "platform"

spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
spark.sql(f"USE CATALOG {CATALOG}")

# COMMAND ----------
# MAGIC %md ## 1. Platform schema

# COMMAND ----------

spark.sql(f"""
    CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA_PLATFORM}
    COMMENT 'Platform-level registry for the multi-domain DocIntelligence platform'
""")
print(f"Schema '{CATALOG}.{SCHEMA_PLATFORM}' ready")

# COMMAND ----------
# MAGIC %md ## 2. domain_configs table

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA_PLATFORM}.domain_configs (
    domain_id               STRING  NOT NULL COMMENT 'Unique identifier, e.g. supply_chain, compliance',
    name                    STRING  COMMENT 'Display name',
    description             STRING  COMMENT 'One-paragraph description of what this domain covers',
    status                  STRING  COMMENT 'configuring | active | paused',
    -- Schema names in jai_docintel catalog
    schema_raw              STRING  COMMENT 'Schema holding parsed_documents, extracted_fields',
    schema_ont              STRING  COMMENT 'Schema holding entities, relationships',
    schema_vec              STRING  COMMENT 'Schema holding document_chunks, VS index',
    schema_agt              STRING  COMMENT 'Schema holding action_log, UC functions',
    volume_docs             STRING  COMMENT 'Volume name for document uploads',
    -- AI pipeline configuration (stored as JSON strings)
    classification_labels   STRING  COMMENT 'JSON map: label_key -> description (for ai_classify)',
    extraction_schemas      STRING  COMMENT 'JSON map: label_key -> (schema + instructions) for ai_extract',
    entity_types            STRING  COMMENT 'JSON array of ontology entity type names',
    agent_system_prompt     STRING  COMMENT 'System prompt for the AI agent in this domain',
    analytics_config        STRING  COMMENT 'JSON: which analytics panels to show + key field names',
    suggested_questions     STRING  COMMENT 'JSON array of suggested questions for the AI chat UI',
    -- Metadata
    created_at              TIMESTAMP,
    updated_at              TIMESTAMP
)
USING DELTA
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")
print(f"Table '{CATALOG}.{SCHEMA_PLATFORM}.domain_configs' ready")

# COMMAND ----------
# MAGIC %md ## 3. pipeline_runs table

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA_PLATFORM}.pipeline_runs (
    run_id       STRING NOT NULL,
    domain_id    STRING NOT NULL,
    job_run_id   BIGINT,
    status       STRING,   -- pending | running | succeeded | failed
    triggered_by STRING,
    started_at   TIMESTAMP,
    finished_at  TIMESTAMP,
    error_msg    STRING
)
USING DELTA
""")
print(f"Table '{CATALOG}.{SCHEMA_PLATFORM}.pipeline_runs' ready")

# COMMAND ----------
# MAGIC %md ## 4. Seed the Supply Chain domain (migrates existing hardcoded config)

# COMMAND ----------

SUPPLY_CHAIN_CLASSIFICATION_LABELS = {
    "supplier_contract":       "A legal agreement between a supplier and purchaser defining SLAs, pricing, temperature requirements, and liability/penalty clauses.",
    "bill_of_lading":          "A shipping document listing shipment details, carrier, trailer, pickup/delivery times, product quantity, and lot numbers.",
    "temperature_log":         "A continuous time-series temperature monitoring log from a refrigerated trailer or cold storage unit.",
    "certificate_of_analysis": "A quality document from a supplier certifying product specifications, microbiological test results, lot number, and production/expiry dates.",
    "quality_incident_report": "An internal report documenting a quality or safety incident such as a temperature excursion, product defect, or process failure.",
    "recall_notice":           "An official notice of a voluntary or mandatory product recall specifying lot numbers, affected products, distribution scope, and required actions.",
    "email_chain":             "An email thread between supply chain stakeholders regarding shipment exceptions, conditional release decisions, or supplier escalations.",
    "supplier_scorecard":      "A periodic supplier performance evaluation covering KPIs like on-time delivery, fill rate, defect rate, and temperature compliance.",
    "inspection_report":       "A receiving or facility inspection report documenting visual checks, temperature probes, seal verification, and product condition at a distribution center.",
    "maintenance_report":      "An equipment maintenance or repair report for a trailer, refrigeration unit, or other supply chain asset.",
    "delivery_exception":      "A notification about a delivery exception such as a delay or product hold due to quality issue.",
    "carrier_sla":             "A carrier service level agreement defining transport standards, refrigeration maintenance obligations, and liability terms.",
    "weather_report":          "A contextual weather conditions report for a transit corridor.",
}

SUPPLY_CHAIN_EXTRACTION_SCHEMAS = {
    "supplier_contract": {
        "schema": {
            "supplier_name":           {"type": "string", "description": "Legal name of the supplier company."},
            "contract_number":         {"type": "string", "description": "Agreement or contract reference number."},
            "temperature_limit_f":     {"type": "string", "description": "Maximum temperature threshold in Fahrenheit."},
            "excursion_threshold_min": {"type": "string", "description": "Maximum allowed excursion duration in minutes."},
            "penalty_amount":          {"type": "string", "description": "Penalty amount for temperature violations."},
        },
        "instructions": "This is a supplier contract. Extract contractual terms.",
    },
    "bill_of_lading": {
        "schema": {
            "shipment_id":         {"type": "string", "description": "Shipment or BOL reference number."},
            "lot_number":          {"type": "string", "description": "Product lot number."},
            "carrier_name":        {"type": "string", "description": "Carrier/trucking company name."},
            "trailer_id":          {"type": "string", "description": "Trailer or container identifier."},
            "distribution_center": {"type": "string", "description": "Destination distribution center."},
            "quantity_cases":      {"type": "string", "description": "Number of cases shipped."},
        },
        "instructions": "This is a bill of lading. Extract logistics details.",
    },
    "temperature_log": {
        "schema": {
            "trailer_id":              {"type": "string", "description": "Trailer identifier."},
            "excursion_detected":      {"type": "string", "description": "YES or NO."},
            "excursion_duration_min":  {"type": "string", "description": "Duration in minutes."},
            "peak_temperature_f":      {"type": "string", "description": "Maximum temperature °F."},
            "compliance_status":       {"type": "string", "description": "COMPLIANT or NON-COMPLIANT."},
        },
        "instructions": "This is a temperature monitoring log. Extract excursion details.",
    },
    "quality_incident_report": {
        "schema": {
            "report_number":       {"type": "string", "description": "QI report reference number."},
            "lot_number":          {"type": "string", "description": "Affected lot number."},
            "financial_exposure":  {"type": "string", "description": "Estimated financial exposure."},
            "risk_classification": {"type": "string", "description": "Class I, II, or III."},
        },
        "instructions": "This is a quality incident report. Extract incident details.",
    },
    "recall_notice": {
        "schema": {
            "recall_number":              {"type": "string", "description": "Recall reference number."},
            "lot_number":                 {"type": "string", "description": "Recalled lot number."},
            "product_name":               {"type": "string", "description": "Recalled product name."},
            "recall_class":               {"type": "string", "description": "Class I, II, or III."},
            "num_restaurants_affected":   {"type": "string", "description": "Number of restaurants affected."},
            "estimated_financial_impact": {"type": "string", "description": "Estimated financial impact."},
        },
        "instructions": "This is a recall notice. Extract recall scope and impact.",
    },
}

SUPPLY_CHAIN_ENTITY_TYPES = [
    "Supplier", "Carrier", "Lot", "Shipment", "Equipment",
    "QualityIncident", "RecallEvent", "DistributionCenter",
    "Restaurant", "Product", "Contract",
]

SUPPLY_CHAIN_ANALYTICS_CONFIG = {
    "primary_incident_type": "recall",
    "incident_id_field": "recall_number",
    "incident_ref_example": "RCL-2024-0012",
    "financial_field": "estimated_financial_impact",
    "risk_entity_type": "Supplier",
    "panels": ["overview", "ontology", "actions"],
}

SUPPLY_CHAIN_SUGGESTED_QUESTIONS = [
    "Which restaurants received product from the affected shipment?",
    "What is the total financial exposure from the current recall?",
    "Which contract terms make the supplier liable for this cold chain failure?",
    "What caused the temperature excursion?",
    "How does the supplier's performance compare to others?",
    "Which distribution centers have the highest cold chain failure rate?",
]

SUPPLY_CHAIN_AGENT_PROMPT = (
    "You are the Supply Chain Control Tower AI for a QSR organization. "
    "You have access to supplier contracts, temperature logs, recall notices, "
    "quality reports, shipment records, and restaurant distribution data. "
    "Answer operational questions about supply chain incidents, supplier risk, "
    "financial exposure, and regulatory compliance. "
    "Be precise, cite specific lot numbers, dates, and dollar amounts when known."
)

# Insert or update the supply_chain domain config
from datetime import datetime, timezone
now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

# Check if already exists
existing = spark.sql(f"""
    SELECT COUNT(*) AS cnt FROM {CATALOG}.{SCHEMA_PLATFORM}.domain_configs
    WHERE domain_id = 'supply_chain'
""").collect()[0]["cnt"]

if existing == 0:
    sc_labels = json.dumps(SUPPLY_CHAIN_CLASSIFICATION_LABELS).replace("'", "\\'")
    sc_schemas = json.dumps(SUPPLY_CHAIN_EXTRACTION_SCHEMAS).replace("'", "\\'")
    sc_entity_types = json.dumps(SUPPLY_CHAIN_ENTITY_TYPES).replace("'", "\\'")
    sc_analytics = json.dumps(SUPPLY_CHAIN_ANALYTICS_CONFIG).replace("'", "\\'")
    sc_questions = json.dumps(SUPPLY_CHAIN_SUGGESTED_QUESTIONS).replace("'", "\\'")
    sc_prompt = SUPPLY_CHAIN_AGENT_PROMPT.replace("'", "\\'")

    spark.sql(f"""
        INSERT INTO {CATALOG}.{SCHEMA_PLATFORM}.domain_configs
        VALUES (
            'supply_chain',
            'Supply Chain',
            'QSR supply chain document intelligence — recalls, temperature excursions, supplier risk, and cold chain compliance.',
            'active',
            'raw', 'ontology', 'vectors', 'agents', 'documents',
            '{sc_labels}',
            '{sc_schemas}',
            '{sc_entity_types}',
            '{sc_prompt}',
            '{sc_analytics}',
            '{sc_questions}',
            TIMESTAMP '{now_ts}',
            TIMESTAMP '{now_ts}'
        )
    """)
    print("Supply Chain domain config seeded ✓")
else:
    print("Supply Chain domain already in registry — skipped (run UPDATE manually to refresh config)")

# COMMAND ----------
# MAGIC %md ## 5. Verify

# COMMAND ----------

display(spark.sql(f"SELECT domain_id, name, status, schema_raw, schema_ont FROM {CATALOG}.{SCHEMA_PLATFORM}.domain_configs"))

print(f"""
╔══════════════════════════════════════════════════════════╗
║  DocIntelligence Platform Bootstrap Complete             ║
╠══════════════════════════════════════════════════════════╣
║  Platform schema : {CATALOG}.{SCHEMA_PLATFORM}
║  Tables          : domain_configs, pipeline_runs
║  Domains seeded  : supply_chain (active)
║
║  Next steps:
║  1. Run the setup wizard in the app to add new domains
║  2. Each new domain will INSERT a row into domain_configs
║  3. Re-run the full pipeline with domain_id=<new_domain>
╚══════════════════════════════════════════════════════════╝
""")
