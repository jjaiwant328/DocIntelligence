# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Supply Chain AI Agent
# MAGIC
# MAGIC Registers 6 Unity Catalog Functions as agent tools and builds a
# MAGIC Databricks AI Agent that answers QSR supply chain business questions
# MAGIC by reasoning across documents, structured data, and the ontology.
# MAGIC
# MAGIC **Agent persona:** Supply Chain Control Tower — QSR Operations Intelligence

# COMMAND ----------

import mlflow
import json

CATALOG = "jai_docintel"

# ── Domain parameter ─────────────────────────────────────────────────────────
try:
    domain_id = dbutils.widgets.get("domain_id")
except Exception:
    domain_id = "supply_chain"

def _domain_cfg_agent(catalog, domain_id):
    try:
        rows = spark.sql(f"""
            SELECT schema_raw, schema_ont, schema_vec, schema_agt,
                   agent_system_prompt
            FROM {catalog}.platform.domain_configs
            WHERE domain_id = '{domain_id}' LIMIT 1
        """).collect()
        if rows:
            r = rows[0]
            return {
                "schema_raw": r["schema_raw"] or "raw",
                "schema_ont": r["schema_ont"] or "ontology",
                "schema_vec": r["schema_vec"] or "vectors",
                "schema_agt": r["schema_agt"] or "agents",
                "agent_system_prompt": r["agent_system_prompt"],
            }
    except Exception:
        pass
    return {}

_cfg = _domain_cfg_agent(CATALOG, domain_id)
SCHEMA_RAW = _cfg.get("schema_raw", "raw")
SCHEMA_ONT = _cfg.get("schema_ont", "ontology")
SCHEMA_VEC = _cfg.get("schema_vec", "vectors")
SCHEMA_AGT = _cfg.get("schema_agt", "agents")
VS_ENDPOINT = "docintel-vs-endpoint"
# VS_INDEX is used by the Copilot backend (docintel_routes.py) for live retrieval;
# this notebook only registers the MLflow model — it does not sync the index.

_agent_system_prompt = _cfg.get("agent_system_prompt") or (
    "You are a Document Intelligence AI assistant. "
    f"You help answer questions about {domain_id.replace('_', ' ')} documents. "
    "Be precise and cite specific values from documents when available."
)

print(f"Domain: {domain_id} | raw={SCHEMA_RAW} | ont={SCHEMA_ONT}")
spark.sql(f"USE CATALOG {CATALOG}")

# COMMAND ----------
# MAGIC %md ## Step 1 — Register Unity Catalog Function Tools (domain-aware)

# COMMAND ----------

if domain_id == "supply_chain":
    # ── Supply-chain specific tools ────────────────────────────────────────────

    spark.sql(f"""
    CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA_AGT}.get_impacted_restaurants(
        lot_number_input STRING COMMENT 'The lot number to trace. Example: LOT-PP-240315'
    )
    RETURNS TABLE (
        restaurant_id   STRING,
        restaurant_name STRING,
        state           STRING,
        region          STRING,
        dc_name         STRING,
        quantity_cases  BIGINT,
        delivery_date   STRING
    )
    COMMENT 'Returns all restaurants that received product from the specified lot number.'
    RETURN
        SELECT
            r.restaurant_id, r.restaurant_name, r.state, r.region,
            dc.dc_name, inv.quantity_cases, inv.delivery_date
        FROM {CATALOG}.{SCHEMA_RAW}.inventory_distribution inv
        JOIN {CATALOG}.{SCHEMA_RAW}.restaurants r ON inv.restaurant_id = r.restaurant_id
        JOIN {CATALOG}.{SCHEMA_RAW}.distribution_centers dc ON r.dc_id = dc.dc_id
        WHERE inv.lot_number = lot_number_input
        ORDER BY inv.delivery_date, r.state
    """)
    print("Tool 1: get_impacted_restaurants ✓")

    spark.sql(f"""
    CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA_AGT}.get_financial_exposure(
        lot_number_input STRING COMMENT 'The recalled lot number. Example: LOT-PP-240315'
    )
    RETURNS TABLE (component STRING, amount_usd DOUBLE, source STRING, notes STRING)
    COMMENT 'Returns itemized financial exposure breakdown for a lot recall.'
    RETURN
        SELECT component, amount_usd, source, notes
        FROM (VALUES
            ('Contract Penalty (Temp Excursion Tier 2)',  15000.0,  'MSA-2024-TF-001 Sec 4.1', 'Excursion 44-48F any duration'),
            ('Recall Logistics & Disposal',              24000.0,  'RCL-2024-0012',            '240 cases × $100/case disposal'),
            ('Expedited Retesting (Covance)',              3500.0,  'QIR-2024-0047',            'Micro retesting costs'),
            ('Lost Restaurant Revenue (estimated)',      187000.0,  'RCL-2024-0012',            '12 restaurants × projected sales'),
            ('Carrier Liability Share (20%)',            -4700.0,   'CSA-2024-SL-007',          'Swift Logistics carrier share offset')
        ) AS t(component, amount_usd, source, notes)
        WHERE lot_number_input LIKE '%PP-240315%'
    """)
    print("Tool 2: get_financial_exposure ✓")

    spark.sql(f"""
    CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA_AGT}.get_supplier_temp_violations(
        supplier_id_input STRING COMMENT 'Supplier ID to query. Example: SUPP-001'
    )
    RETURNS TABLE (
        shipment_id STRING, violation_date STRING, peak_temp_f DOUBLE,
        duration_minutes INT, above_threshold BOOLEAN, incident_id STRING
    )
    COMMENT 'Returns temperature violations for a supplier.'
    RETURN
        SELECT
            s.shipment_id, CAST(s.departure_time AS STRING) AS violation_date,
            CAST(e.attributes:peak_temp_f AS DOUBLE) AS peak_temp_f,
            CAST(e.attributes:duration_minutes AS INT) AS duration_minutes,
            CAST(e.attributes:duration_minutes AS INT) > 30 AS above_threshold,
            e.entity_id AS incident_id
        FROM {CATALOG}.{SCHEMA_RAW}.shipments s
        JOIN {CATALOG}.{SCHEMA_ONT}.relationships r
            ON r.subject_id = s.shipment_id AND r.predicate = 'EXPERIENCED'
        JOIN {CATALOG}.{SCHEMA_ONT}.entities e
            ON e.entity_id = r.object_id AND e.entity_type = 'TemperatureExcursion'
        WHERE s.supplier_id = supplier_id_input
        ORDER BY CAST(s.departure_time AS TIMESTAMP) DESC
    """)
    print("Tool 3: get_supplier_temp_violations ✓")

    spark.sql(f"""
    CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA_AGT}.get_contract_liability(
        supplier_id_input STRING COMMENT 'Supplier ID. Example: SUPP-001'
    )
    RETURNS TABLE (
        contract_number STRING, temp_limit_f STRING, excursion_threshold_min STRING,
        penalty_tier1_usd STRING, penalty_tier2_usd STRING, penalty_tier3_usd STRING,
        effective_date STRING, expiry_date STRING
    )
    COMMENT 'Returns liability and penalty terms from the supplier contract.'
    RETURN
        SELECT
            e.attributes:contract_number::STRING,
            e.attributes:temp_limit_f::STRING,
            e.attributes:excursion_threshold_min::STRING,
            e.attributes:penalty_tier1::STRING,
            e.attributes:penalty_tier2::STRING,
            e.attributes:penalty_tier3::STRING,
            e.attributes:effective_date::STRING,
            e.attributes:expiry_date::STRING
        FROM {CATALOG}.{SCHEMA_ONT}.entities e
        JOIN {CATALOG}.{SCHEMA_ONT}.relationships r
            ON r.object_id = e.entity_id AND r.predicate = 'GOVERNED_BY'
        WHERE r.subject_id = supplier_id_input AND e.entity_type = 'Contract'
    """)
    print("Tool 4: get_contract_liability ✓")

else:
    # ── Generic domain tools (compliance + future domains) ─────────────────────

    spark.sql(f"""
    CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA_AGT}.get_entity_documents(
        entity_id_input STRING COMMENT 'Entity ID to look up (e.g. STORE-Store_128, INSP-Jane_Smith).'
    )
    RETURNS TABLE (
        doc_id      STRING,
        doc_type    STRING,
        predicate   STRING
    )
    COMMENT 'Returns all documents associated with a given entity via the ontology relationship graph.'
    RETURN
        SELECT r.object_id AS doc_id, e2.attributes:doc_type::STRING AS doc_type, r.predicate
        FROM {CATALOG}.{SCHEMA_ONT}.relationships r
        LEFT JOIN {CATALOG}.{SCHEMA_ONT}.entities e2 ON e2.entity_id = r.object_id
        WHERE r.subject_id = entity_id_input
          AND r.predicate IN ('EXTRACTED_FROM', 'COVERS')
        UNION ALL
        SELECT r.subject_id AS doc_id, e2.attributes:doc_type::STRING AS doc_type, r.predicate
        FROM {CATALOG}.{SCHEMA_ONT}.relationships r
        LEFT JOIN {CATALOG}.{SCHEMA_ONT}.entities e2 ON e2.entity_id = r.subject_id
        WHERE r.object_id = entity_id_input
          AND r.predicate IN ('EXTRACTED_FROM', 'COVERS')
    """)
    print("Tool 1: get_entity_documents ✓")

    spark.sql(f"""
    CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA_AGT}.get_extracted_fields_for_doc(
        doc_id_input STRING COMMENT 'Document ID (filename) to retrieve extracted fields for.'
    )
    RETURNS TABLE (
        field_name  STRING,
        field_value STRING,
        doc_type    STRING
    )
    COMMENT 'Returns all AI-extracted fields and values for a specific document.'
    RETURN
        SELECT
            field_name,
            CASE
                WHEN field_value LIKE '{{"value":%' THEN
                    GET_JSON_OBJECT(CAST(field_value AS STRING), '$.value')
                ELSE CAST(field_value AS STRING)
            END AS field_value,
            doc_type
        FROM {CATALOG}.{SCHEMA_RAW}.extracted_fields
        WHERE doc_id = doc_id_input
        ORDER BY field_name
    """)
    print("Tool 2: get_extracted_fields_for_doc ✓")

    spark.sql(f"""
    CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA_AGT}.search_by_field(
        field_name_input  STRING COMMENT 'Field name to search (e.g. store_id, inspection_type, violation_code).',
        field_value_input STRING COMMENT 'Value to match (partial match supported).'
    )
    RETURNS TABLE (
        doc_id     STRING,
        doc_type   STRING,
        field_name STRING,
        field_value STRING
    )
    COMMENT 'Searches extracted fields across all documents for a given field name and value pattern.'
    RETURN
        SELECT
            doc_id, doc_type, field_name,
            CASE
                WHEN field_value LIKE '{{"value":%' THEN
                    GET_JSON_OBJECT(CAST(field_value AS STRING), '$.value')
                ELSE CAST(field_value AS STRING)
            END AS field_value
        FROM {CATALOG}.{SCHEMA_RAW}.extracted_fields
        WHERE field_name = field_name_input
          AND CAST(field_value AS STRING) LIKE CONCAT('%', field_value_input, '%')
        ORDER BY doc_id
    """)
    print("Tool 3: search_by_field ✓")

    spark.sql(f"""
    CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA_AGT}.get_entities_by_type(
        entity_type_input STRING COMMENT 'Entity type to retrieve (e.g. Store, Inspector, Permit, Violation).'
    )
    RETURNS TABLE (
        entity_id    STRING,
        display_name STRING,
        attributes   STRING
    )
    COMMENT 'Returns all entities of the specified type from the ontology.'
    RETURN
        SELECT entity_id, display_name, attributes
        FROM {CATALOG}.{SCHEMA_ONT}.entities
        WHERE entity_type = entity_type_input
        ORDER BY display_name
    """)
    print("Tool 4: get_entities_by_type ✓")

# ── Tool common to ALL domains: ontology traversal ────────────────────────────
spark.sql(f"""
CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA_AGT}.traverse_ontology(
    entity_id_input   STRING COMMENT 'Starting entity ID.',
    relationship_type STRING COMMENT 'Predicate to follow, or NULL for all.'
)
RETURNS TABLE (
    subject_id STRING, predicate STRING, object_id STRING,
    object_type STRING, display_name STRING, attributes STRING
)
COMMENT 'Traverses the ontology graph from a given entity, following a specified relationship type.'
RETURN
    SELECT r.subject_id, r.predicate, r.object_id,
           e.entity_type AS object_type, e.display_name, e.attributes
    FROM {CATALOG}.{SCHEMA_ONT}.relationships r
    LEFT JOIN {CATALOG}.{SCHEMA_ONT}.entities e ON e.entity_id = r.object_id
    WHERE r.subject_id = entity_id_input
      AND (relationship_type IS NULL OR r.predicate = relationship_type)
    UNION ALL
    SELECT r.subject_id, r.predicate, r.object_id,
           e.entity_type AS object_type, e.display_name, e.attributes
    FROM {CATALOG}.{SCHEMA_ONT}.relationships r
    LEFT JOIN {CATALOG}.{SCHEMA_ONT}.entities e ON e.entity_id = r.subject_id
    WHERE r.object_id = entity_id_input
      AND (relationship_type IS NULL OR r.predicate = relationship_type)
""")
print(f"Tool (all domains): traverse_ontology ✓")

# COMMAND ----------
# MAGIC %md
# MAGIC ### Compliance Due Diligence — the four "agents" as UC-function tools
# MAGIC
# MAGIC Additive, domain-gated. The generic tools above still register for this
# MAGIC domain; these add store-development-specific reasoning the CDD agent uses
# MAGIC (mirrors the LangChain tools wired in `docintel_routes.py`):
# MAGIC Intake · Research · Historical Knowledge · Change detection.

# COMMAND ----------

if domain_id == "compliance_due_diligence":

    # Tool: Intake — classify a feasibility request into the domain labels.
    spark.sql(f"""
    CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA_AGT}.cdd_classify_request(
        request_text STRING COMMENT 'Raw feasibility/store-development request text or email body.'
    )
    RETURNS STRING
    COMMENT 'Intake agent: classifies a feasibility request into the CDD document labels.'
    RETURN ai_classify(request_text, ARRAY(
        'feasibility_request', 'municipal_requirement', 'alcohol_license',
        'tobacco_license', 'business_license', 'zoning_document', 'permit',
        'historical_response', 'regulatory_change', 'consultant_correspondence'))
    """)
    print("CDD Tool 1: cdd_classify_request ✓")

    # Tool: Research — requirements/licenses defined for a municipality.
    spark.sql(f"""
    CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA_AGT}.cdd_get_municipality_requirements(
        municipality_input STRING COMMENT 'Municipality name, e.g. Tampa, Dallas, Atlanta.'
    )
    RETURNS TABLE (
        doc_id           STRING,
        doc_type         STRING,
        requirement_type STRING,
        license_type     STRING,
        authority        STRING,
        lead_time        STRING,
        effective_date   STRING
    )
    COMMENT 'Research agent: municipal requirements and licenses for a municipality.'
    RETURN
        WITH d AS (
          SELECT ef.doc_id, pd.doc_type,
            MAX(CASE WHEN ef.field_name='municipality'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS municipality,
            MAX(CASE WHEN ef.field_name='requirement_type'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS requirement_type,
            MAX(CASE WHEN ef.field_name='license_type'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS license_type,
            MAX(CASE WHEN ef.field_name='authority'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS authority,
            MAX(CASE WHEN ef.field_name='lead_time'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS lead_time,
            MAX(CASE WHEN ef.field_name='effective_date'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS effective_date
          FROM {CATALOG}.{SCHEMA_RAW}.extracted_fields ef
          JOIN {CATALOG}.{SCHEMA_RAW}.parsed_documents pd ON pd.doc_id = ef.doc_id
          GROUP BY ef.doc_id, pd.doc_type
        )
        SELECT doc_id, doc_type, requirement_type, license_type,
               authority, lead_time, effective_date
        FROM d
        WHERE LOWER(COALESCE(municipality,'')) LIKE LOWER(CONCAT('%', municipality_input, '%'))
        ORDER BY effective_date DESC NULLS LAST
    """)
    print("CDD Tool 2: cdd_get_municipality_requirements ✓")

    # Tool: Historical Knowledge — prior responses for a municipality, with dates.
    spark.sql(f"""
    CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA_AGT}.cdd_get_municipality_history(
        municipality_input STRING COMMENT 'Municipality name to look up prior responses for.'
    )
    RETURNS TABLE (
        doc_id        STRING,
        doc_type      STRING,
        responder     STRING,
        response_date STRING,
        request_type  STRING
    )
    COMMENT 'Historical Knowledge agent: prior feasibility responses/correspondence with dates.'
    RETURN
        WITH d AS (
          SELECT ef.doc_id, pd.doc_type,
            MAX(CASE WHEN ef.field_name='municipality'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS municipality,
            MAX(CASE WHEN ef.field_name='responder'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS responder,
            MAX(CASE WHEN ef.field_name='response_date'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS response_date,
            MAX(CASE WHEN ef.field_name='request_type'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS request_type
          FROM {CATALOG}.{SCHEMA_RAW}.extracted_fields ef
          JOIN {CATALOG}.{SCHEMA_RAW}.parsed_documents pd ON pd.doc_id = ef.doc_id
          WHERE pd.doc_type IN ('historical_response','consultant_correspondence')
          GROUP BY ef.doc_id, pd.doc_type
        )
        SELECT doc_id, doc_type, responder, response_date, request_type
        FROM d
        WHERE LOWER(COALESCE(municipality,'')) LIKE LOWER(CONCAT('%', municipality_input, '%'))
        ORDER BY response_date DESC NULLS LAST
    """)
    print("CDD Tool 3: cdd_get_municipality_history ✓")

    # Tool: Change detection — versions of a requirement ordered by effective_date.
    spark.sql(f"""
    CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA_AGT}.cdd_get_requirement_versions(
        municipality_input     STRING COMMENT 'Municipality name.',
        requirement_type_input STRING COMMENT 'Requirement or license type substring, e.g. alcohol.'
    )
    RETURNS TABLE (
        doc_id           STRING,
        requirement_type STRING,
        license_type     STRING,
        authority        STRING,
        requirement      STRING,
        effective_date   STRING
    )
    COMMENT 'Change-detection support: requirement versions ordered newest-first by effective_date.'
    RETURN
        WITH d AS (
          SELECT ef.doc_id,
            MAX(CASE WHEN ef.field_name='municipality'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS municipality,
            MAX(CASE WHEN ef.field_name='requirement_type'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS requirement_type,
            MAX(CASE WHEN ef.field_name='license_type'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS license_type,
            MAX(CASE WHEN ef.field_name='authority'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS authority,
            MAX(CASE WHEN ef.field_name='requirement'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS requirement,
            MAX(CASE WHEN ef.field_name='effective_date'
                THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') END) AS effective_date
          FROM {CATALOG}.{SCHEMA_RAW}.extracted_fields ef
          GROUP BY ef.doc_id
        )
        SELECT doc_id, requirement_type, license_type, authority, requirement, effective_date
        FROM d
        WHERE LOWER(COALESCE(municipality,'')) LIKE LOWER(CONCAT('%', municipality_input, '%'))
          AND (LOWER(COALESCE(requirement_type,'')) LIKE LOWER(CONCAT('%', requirement_type_input, '%'))
            OR LOWER(COALESCE(license_type,''))     LIKE LOWER(CONCAT('%', requirement_type_input, '%')))
        ORDER BY effective_date DESC NULLS LAST
    """)
    print("CDD Tool 4: cdd_get_requirement_versions ✓")
    print("Note: the Action agent (create/track + escalation) is served by the "
          "app backend via POST /action-master — no UC function needed.")

# COMMAND ----------
# MAGIC %md ## Step 2 — Verify UC Function Tools

# COMMAND ----------

if domain_id == "supply_chain":
    print("=== Tool 1: get_impacted_restaurants ===")
    display(spark.sql(f"""
        SELECT * FROM {CATALOG}.{SCHEMA_AGT}.get_impacted_restaurants('LOT-PP-240315')
    """))
    print("=== Tool 2: get_financial_exposure ===")
    display(spark.sql(f"""
        SELECT *, SUM(amount_usd) OVER () AS total_exposure
        FROM {CATALOG}.{SCHEMA_AGT}.get_financial_exposure('LOT-PP-240315')
    """))
    print("=== Tool 3: get_supplier_temp_violations ===")
    display(spark.sql(f"SELECT * FROM {CATALOG}.{SCHEMA_AGT}.get_supplier_temp_violations('SUPP-001')"))
    print("=== Tool 4: get_contract_liability ===")
    display(spark.sql(f"SELECT * FROM {CATALOG}.{SCHEMA_AGT}.get_contract_liability('SUPP-001')"))
else:
    # Get the first known store_id from extracted fields for verification
    _sample_store = spark.sql(f"""
        SELECT GET_JSON_OBJECT(CAST(field_value AS STRING), '$.value') AS store_id
        FROM {CATALOG}.{SCHEMA_RAW}.extracted_fields
        WHERE field_name = 'store_id' LIMIT 1
    """).collect()
    _sample_store_id = (_sample_store[0]["store_id"] if _sample_store else "Store_101") or "Store_101"
    _sample_entity = f"STORE-{_sample_store_id}"
    _sample_doc = spark.sql(f"SELECT doc_id FROM {CATALOG}.{SCHEMA_RAW}.extracted_fields LIMIT 1").collect()
    _sample_doc_id = _sample_doc[0]["doc_id"] if _sample_doc else ""

    print(f"=== Tool 1: get_entity_documents ({_sample_entity}) ===")
    display(spark.sql(f"SELECT * FROM {CATALOG}.{SCHEMA_AGT}.get_entity_documents('{_sample_entity}')"))
    if _sample_doc_id:
        print(f"=== Tool 2: get_extracted_fields_for_doc ({_sample_doc_id}) ===")
        display(spark.sql(f"SELECT * FROM {CATALOG}.{SCHEMA_AGT}.get_extracted_fields_for_doc('{_sample_doc_id}')"))
    print("=== Tool 3: search_by_field (store_id = Store_101) ===")
    display(spark.sql(f"SELECT * FROM {CATALOG}.{SCHEMA_AGT}.search_by_field('store_id','Store_101')"))
    print("=== Tool 4: get_entities_by_type (Store) ===")
    display(spark.sql(f"SELECT * FROM {CATALOG}.{SCHEMA_AGT}.get_entities_by_type('Store')"))

print("=== traverse_ontology ===")
_sample_ent = spark.sql(f"SELECT entity_id FROM {CATALOG}.{SCHEMA_ONT}.entities LIMIT 1").collect()
if _sample_ent:
    display(spark.sql(f"SELECT * FROM {CATALOG}.{SCHEMA_AGT}.traverse_ontology('{_sample_ent[0]['entity_id']}', NULL)"))

if domain_id == "compliance_due_diligence":
    # Best-effort verification of the CDD-specific tools against a sample municipality.
    try:
        _muni_row = spark.sql(f"""
            SELECT GET_JSON_OBJECT(CAST(field_value AS STRING),'$.value') AS municipality
            FROM {CATALOG}.{SCHEMA_RAW}.extracted_fields
            WHERE field_name = 'municipality' LIMIT 1
        """).collect()
        _muni = (_muni_row[0]["municipality"] if _muni_row else "Dallas") or "Dallas"
        print(f"=== CDD Tool: cdd_classify_request ===")
        display(spark.sql(f"""
            SELECT {CATALOG}.{SCHEMA_AGT}.cdd_classify_request(
                'We are evaluating a new RaceTrac store in {_muni}. What licenses are required?'
            ) AS request_type
        """))
        print(f"=== CDD Tool: cdd_get_municipality_requirements ({_muni}) ===")
        display(spark.sql(f"SELECT * FROM {CATALOG}.{SCHEMA_AGT}.cdd_get_municipality_requirements('{_muni}')"))
        print(f"=== CDD Tool: cdd_get_municipality_history ({_muni}) ===")
        display(spark.sql(f"SELECT * FROM {CATALOG}.{SCHEMA_AGT}.cdd_get_municipality_history('{_muni}')"))
        print(f"=== CDD Tool: cdd_get_requirement_versions ({_muni}, alcohol) ===")
        display(spark.sql(f"SELECT * FROM {CATALOG}.{SCHEMA_AGT}.cdd_get_requirement_versions('{_muni}','alcohol')"))
    except Exception as _e:
        print(f"[cdd] tool verification skipped: {_e}")

# COMMAND ----------
# MAGIC %md ## Step 3 — Register a Lightweight MLflow Model Entry Point

# COMMAND ----------

# Register a simple MLflow model that wraps ChatDatabricks.
# The full agent (with UC Function tools + VS search) is invoked live from
# the Databricks App backend (docintel_routes.py) using the same pattern.
# This registration provides a versioned model artifact in Unity Catalog.

_AGENT_MODEL_NAME = f"{domain_id}_agent"

class DocIntelChatModel(mlflow.pyfunc.PythonModel):
    """
    Lightweight domain QA model backed by DBRX.
    Full agent tools are wired at serving time via the Databricks App.
    """

    SYSTEM_PROMPT = _agent_system_prompt

    def predict(self, context, model_input):
        import os, requests, json
        import pandas as pd

        question = (
            model_input["question"].iloc[0]
            if isinstance(model_input, pd.DataFrame)
            else str(model_input)
        )

        workspace_url = os.getenv("DATABRICKS_HOST", "")
        token = os.getenv("DATABRICKS_TOKEN", "")
        endpoint = "databricks-dbrx-instruct"

        payload = {
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user",   "content": question},
            ],
            "max_tokens": 1024,
        }
        resp = requests.post(
            f"{workspace_url}/serving-endpoints/{endpoint}/invocations",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


from mlflow.models import ModelSignature
from mlflow.types import Schema, ColSpec

# UC requires an explicit signature with both input and output specs
_signature = ModelSignature(
    inputs=Schema([ColSpec("string", "question")]),
    outputs=Schema([ColSpec("string", "answer")]),
)

mlflow.set_experiment("/Shared/docintel-agent-eval")

_example_q = (
    "Which restaurants received the recalled product?"
    if domain_id == "supply_chain"
    else "What compliance violations were found during store inspections?"
)

with mlflow.start_run(run_name=f"docintel_agent_{domain_id}"):
    mlflow.log_param("domain_id", domain_id)
    mlflow.log_param("model_endpoint", "databricks-dbrx-instruct")
    model_info = mlflow.pyfunc.log_model(
        artifact_path=_AGENT_MODEL_NAME,
        python_model=DocIntelChatModel(),
        signature=_signature,
        input_example={"question": _example_q},
        registered_model_name=f"{CATALOG}.{SCHEMA_AGT}.{_AGENT_MODEL_NAME}",
        pip_requirements=["requests"],
    )

print(f"✓ Agent model registered: {CATALOG}.{SCHEMA_AGT}.{_AGENT_MODEL_NAME}")
print(f"  Model URI: {model_info.model_uri}")
