# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Ontology Mapping & Entity Resolution
# MAGIC
# MAGIC Transforms extracted document fields into a normalized knowledge graph:
# MAGIC - `ontology.entities` — canonical entity records
# MAGIC - `ontology.relationships` — typed edges between entities
# MAGIC - `ontology.entity_aliases` — alias → canonical ID resolution map

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType
)
import json

# Explicit schemas — required when data lists may be empty
_ALIAS_SCHEMA = StructType([
    StructField("alias_text",         StringType(), True),
    StructField("canonical_id",       StringType(), True),
    StructField("entity_type",        StringType(), True),
    StructField("resolution_method",  StringType(), True),
])
_ENTITY_SCHEMA = StructType([
    StructField("entity_id",    StringType(), True),
    StructField("entity_type",  StringType(), True),
    StructField("canonical_id", StringType(), True),
    StructField("attributes",   StringType(), True),
    StructField("source",       StringType(), True),
    StructField("display_name", StringType(), True),
])
_REL_SCHEMA = StructType([
    StructField("subject_id",    StringType(), True),
    StructField("predicate",     StringType(), True),
    StructField("object_id",     StringType(), True),
    StructField("reference_id",  StringType(), True),
    StructField("confidence",    DoubleType(),  True),
    StructField("source_doc",    StringType(), True),
])

CATALOG = "jai_docintel"

# ── Domain parameter ─────────────────────────────────────────────────────────
try:
    domain_id = dbutils.widgets.get("domain_id")
except Exception:
    domain_id = "supply_chain"

import re

def _domain_schemas(catalog, domain_id):
    try:
        rows = spark.sql(f"""
            SELECT schema_raw, schema_ont, entity_types, analytics_config
            FROM {catalog}.platform.domain_configs
            WHERE domain_id = '{domain_id}' LIMIT 1
        """).collect()
        if rows:
            r = rows[0]
            return (r["schema_raw"] or "raw", r["schema_ont"] or "ontology",
                    r["entity_types"], r["analytics_config"])
    except Exception:
        pass
    return ("raw", "ontology", None, None)

SCHEMA_RAW, SCHEMA_ONT, _entity_types_json, _analytics_config_json = _domain_schemas(CATALOG, domain_id)
print(f"Domain: {domain_id} | raw={SCHEMA_RAW} | ont={SCHEMA_ONT}")
spark.sql(f"USE CATALOG {CATALOG}")

# ── Config-driven ontology mapping ─────────────────────────────────────────────
# Field-name → (entity_type, id_prefix). A domain extends/overrides this map (and
# declares relationship rules) via:
#   domain_configs.analytics_config = {"ontology_config": {
#       "field_entity_map":  {"store_number": ["Project", "PROJ"], ...},
#       "relationship_rules": [{"subject_field": ..., "predicate": ..., "object_field": ...}]}}
# We nest under analytics_config (not a new column) because platform_routes.create_domain
# does a positional INSERT — adding a column would break domain creation.
# DEFAULT_FIELD_ENTITY_MAP preserves current behavior for supply_chain (bespoke branch,
# does not use this map) and compliance (no ontology_config → pure default).
DEFAULT_FIELD_ENTITY_MAP = {
    # Compliance domain
    "store_id":         ("Store",              "STORE"),
    "inspector_id":     ("Inspector",          "INSP"),
    "inspector_name":   ("Inspector",          "INSP"),
    "permit_number":    ("Permit",             "PERM"),
    "vendor_name":      ("Vendor",             "VEND"),
    "regulation_ref":   ("Regulation",         "REG"),
    "violation_code":   ("Violation",          "VIO"),
    "corrective_action":("CorrectiveAction",   "CA"),
    "audit_id":         ("Audit",              "AUDIT"),
    "certification_id": ("Certification",      "CERT"),
    # Generic
    "location_id":      ("Location",           "LOC"),
    "department":       ("Department",         "DEPT"),
    "employee_id":      ("Employee",           "EMP"),
    "supplier_id":      ("Vendor",             "VEND"),
    "contract_number":  ("Contract",           "CONT"),
}

def _load_ontology_config(analytics_config_json):
    try:
        cfg = json.loads(analytics_config_json) if analytics_config_json else {}
        return (cfg or {}).get("ontology_config", {}) or {}
    except Exception:
        return {}

_ont_cfg = _load_ontology_config(_analytics_config_json)
FIELD_ENTITY_MAP = dict(DEFAULT_FIELD_ENTITY_MAP)
for _fname, _spec in (_ont_cfg.get("field_entity_map") or {}).items():
    if isinstance(_spec, (list, tuple)) and len(_spec) == 2:
        FIELD_ENTITY_MAP[_fname] = (_spec[0], _spec[1])
RELATIONSHIP_RULES = _ont_cfg.get("relationship_rules") or []

def safe_id(prefix, val):
    """Build a short, filesystem-safe entity ID."""
    v = re.sub(r"[^A-Za-z0-9_\-]", "_", str(val))[:40]
    return f"{prefix}-{v}"

print(f"  Ontology config: {len(FIELD_ENTITY_MAP)} field mappings, {len(RELATIONSHIP_RULES)} relationship rules")

# COMMAND ----------
# MAGIC %md ## Step 1 — Entity Alias Resolution Table
# MAGIC
# MAGIC Handles cases where documents refer to the same entity with different names:
# MAGIC `Store145`, `Restaurant145`, `ATL145`, `Location145` → `REST-101`

# COMMAND ----------

# Define known alias mappings
if domain_id == "supply_chain":
    alias_records = [
        # Restaurant aliases
        ("Store145",       "REST-101", "Restaurant", "string_match"),
        ("Restaurant145",  "REST-101", "Restaurant", "string_match"),
        ("ATL145",         "REST-101", "Restaurant", "string_match"),
        ("Location145",    "REST-101", "Restaurant", "string_match"),
        ("Marietta Classic","REST-101","Restaurant", "name_match"),
        # Supplier aliases
        ("Tyson",          "SUPP-001", "Supplier", "string_match"),
        ("Tyson Foods",    "SUPP-001", "Supplier", "string_match"),
        ("Tyson Poultry",  "SUPP-001", "Supplier", "string_match"),
        ("Tyson Foods, Inc.","SUPP-001","Supplier","exact_match"),
        ("Tyson Poultry Division","SUPP-001","Supplier","string_match"),
        # Carrier aliases
        ("Swift",          "CAR-001", "Carrier", "string_match"),
        ("Swift Logistics","CAR-001", "Carrier", "string_match"),
        ("Swift Logistics Inc.","CAR-001","Carrier","exact_match"),
        # Distribution center aliases
        ("Atlanta DC",     "DC-001",  "DistributionCenter", "name_match"),
        ("ATL DC",         "DC-001",  "DistributionCenter", "code_match"),
        ("Atlanta Distribution Center","DC-001","DistributionCenter","exact_match"),
    ]
else:
    # For generic domains, build aliases from extracted fields (e.g. store ID variants)
    alias_records = []
    try:
        fields_for_alias = spark.table(f"{CATALOG}.{SCHEMA_RAW}.extracted_fields")\
            .filter("field_name IN ('store_id','inspector_name','permit_number')")\
            .select("field_value","field_name").distinct().collect()
        for row in fields_for_alias:
            fval = _unwrap_field_value(row["field_value"])
            fname = row["field_name"] or ""
            if fval and fname in FIELD_ENTITY_MAP:
                _, prefix = FIELD_ENTITY_MAP[fname]
                canonical = safe_id(prefix, fval)
                alias_records.append((fval, canonical, FIELD_ENTITY_MAP[fname][0], "extracted_field"))
    except Exception as _e:
        print(f"Alias building warning: {_e}")

df_aliases = spark.createDataFrame(alias_records, _ALIAS_SCHEMA)
df_aliases.write.mode("overwrite").format("delta")\
    .saveAsTable(f"{CATALOG}.{SCHEMA_ONT}.entity_aliases")
print(f"entity_aliases: {df_aliases.count()} rows")

# COMMAND ----------
# MAGIC %md ## Step 2 — Build Ontology Entities Table
# MAGIC
# MAGIC Sources: structured tables + extracted document fields

# COMMAND ----------

# Helper: read extracted field value for a given doc and field
def get_extracted_field(doc_id, field_name):
    return spark.sql(f"""
        SELECT field_value FROM {CATALOG}.{SCHEMA_RAW}.extracted_fields
        WHERE doc_id = '{doc_id}' AND field_name = '{field_name}'
        LIMIT 1
    """).collect()

# COMMAND ----------

import json
import re

def json_attr(**kwargs):
    return json.dumps({k: v for k, v in kwargs.items() if v})

def _unwrap_field_value(raw):
    """
    ai_extract may store field_value in several formats:
      - Python dict / Spark Row:  {"value": "X"}  or  Row(value="X")
      - JSON string:              '{"value":"X"}'
      - Plain string:             "Store_128"
    Return a plain scalar string in all cases.
    """
    if raw is None:
        return None

    # Spark Row or dict (field_value stored as STRUCT/MAP in Delta)
    if hasattr(raw, "__class__") and raw.__class__.__name__ == "Row":
        try:
            v = raw["value"] if "value" in raw else raw[0]
            return str(v).strip() if v is not None and str(v).lower() not in ("none","null","") else None
        except Exception:
            return str(raw).strip() or None

    if isinstance(raw, dict):
        v = raw.get("value") or raw.get("text") or raw.get("answer")
        return str(v).strip() if v and str(v).lower() not in ("none","null","") else None

    s = str(raw).strip()
    if not s or s.lower() in ("none","null",""):
        return None

    # JSON string: {"value":"X"} or {'value': 'X'}
    if s.startswith("{"):
        try:
            obj = json.loads(s)
            v = obj.get("value") or obj.get("text") or obj.get("answer")
            return str(v).strip() if v and str(v).lower() not in ("none","null","") else None
        except Exception:
            # Python repr with single quotes — convert and retry
            try:
                import ast
                obj2 = ast.literal_eval(s)
                if isinstance(obj2, dict):
                    v = obj2.get("value") or obj2.get("text") or obj2.get("answer")
                    return str(v).strip() if v and str(v).lower() not in ("none","null","") else None
            except Exception:
                pass

    return s

entity_records = []

# ── Supply-chain-specific structured tables ────────────────────────────────────
if domain_id == "supply_chain":
    for s in spark.table(f"{CATALOG}.{SCHEMA_RAW}.suppliers").collect():
        entity_records.append((s.supplier_id,"Supplier",s.supplier_id,
            json_attr(supplier_name=s.supplier_name,region=s.region,
                      risk_score=str(s.risk_score),contract_id=s.contract_id),
            "structured_tables",s.supplier_name))

    for c in spark.table(f"{CATALOG}.{SCHEMA_RAW}.carriers").collect():
        entity_records.append((c.carrier_id,"Carrier",c.carrier_id,
            json_attr(carrier_name=c.carrier_name,region=c.region,
                      reliability_score=str(c.reliability_score)),
            "structured_tables",c.carrier_name))

    for d in spark.table(f"{CATALOG}.{SCHEMA_RAW}.distribution_centers").collect():
        entity_records.append((d.dc_id,"DistributionCenter",d.dc_id,
            json_attr(dc_name=d.dc_name,region=d.region,dc_code=d.dc_code),
            "structured_tables",d.dc_name))

    for r in spark.table(f"{CATALOG}.{SCHEMA_RAW}.restaurants").collect():
        entity_records.append((r.restaurant_id,"Restaurant",r.restaurant_id,
            json_attr(name=r.restaurant_name,region=r.region,
                      dc_id=r.dc_id,state=r.state),
            "structured_tables",r.restaurant_name))

    for p in spark.table(f"{CATALOG}.{SCHEMA_RAW}.products").collect():
        entity_records.append((p.product_id,"Product",p.product_id,
            json_attr(name=p.product_name,category=p.category,
                      shelf_life_days=str(p.shelf_life_days)),
            "structured_tables",p.product_name))

    # Supply-chain incident-specific hardcoded entities
    entity_records += [
        ("LOT-PP-240315","Lot","LOT-PP-240315",
         json_attr(lot_number="LOT-PP-240315",supplier_id="SUPP-001",
                   product_id="PRD-001",production_date="2024-03-14",
                   expiry_date="2024-03-28",quantity_cases="480"),
         "document_extraction","LOT-PP-240315"),
        ("SHP-20240315","Shipment","SHP-20240315",
         json_attr(shipment_id="SHP-20240315",supplier_id="SUPP-001",
                   carrier_id="CAR-001",dc_id="DC-001",
                   departure="2024-03-15T06:23:00",arrival="2024-03-15T15:47:00"),
         "document_extraction","SHP-20240315"),
        ("TE-20240315-001","TemperatureExcursion","TE-20240315-001",
         json_attr(shipment_id="SHP-20240315",trailer_id="TR-8821",
                   excursion_start="2024-03-15T10:15:00",excursion_end="2024-03-15T11:23:00",
                   duration_minutes="68",peak_temp_f="48.2",threshold_f="40.0",
                   cause="Refrigeration unit compressor failure (HPO)",
                   risk_level="HIGH"),
         "document_extraction","Temp Excursion TR-8821 2024-03-15"),
        ("QIR-2024-0047","QualityIncident","QIR-2024-0047",
         json_attr(report_number="QIR-2024-0047",shipment_id="SHP-20240315",
                   lot_number="LOT-PP-240315",incident_type="Temperature Excursion",
                   classification="Class II",status="Closed",
                   financial_exposure="211000",reported_date="2024-03-15"),
         "document_extraction","Quality Incident Report QIR-2024-0047"),
        ("RCL-2024-0012","RecallEvent","RCL-2024-0012",
         json_attr(recall_number="RCL-2024-0012",lot_number="LOT-PP-240315",
                   product_id="PRD-001",recall_class="Class II",
                   recall_date="2024-03-20",num_restaurants="12",
                   total_cases="240",estimated_cost="211000",
                   status="Active"),
         "document_extraction","Recall RCL-2024-0012"),
        ("CONTRACT-MSA-2024-TF-001","Contract","CONTRACT-MSA-2024-TF-001",
         json_attr(contract_number="MSA-2024-TF-001",supplier_id="SUPP-001",
                   effective_date="2024-01-01",expiry_date="2025-12-31",
                   temp_limit_f="40",excursion_threshold_min="30",
                   penalty_tier1="5000",penalty_tier2="15000",penalty_tier3="25000"),
         "document_extraction","Supplier Contract MSA-2024-TF-001"),
    ]

else:
    # ── Generic entity building from extracted fields (all non-supply-chain domains) ──
    #
    # Strategy:
    #   1. Each unique field value for "identifier" fields becomes an entity.
    #      Field-name → entity-type mapping is defined below; extend per domain as needed.
    #   2. Each parsed document becomes a Document entity.
    #   3. The relationship table captures EXTRACTED_FROM edges.
    #
    # FIELD_ENTITY_MAP and safe_id() are defined once at the top of this notebook,
    # config-driven from domain_configs.analytics_config.ontology_config with
    # DEFAULT_FIELD_ENTITY_MAP as fallback. Not redefined here.

    seen_entities: set = set()

    try:
        fields_rows = spark.table(f"{CATALOG}.{SCHEMA_RAW}.extracted_fields").collect()
    except Exception as _e:
        print(f"Warning: could not read extracted_fields: {_e}")
        fields_rows = []

    # Group extra field data per entity for richer attributes
    entity_extra: dict = {}  # entity_id -> {field_name: value}

    for row in fields_rows:
        fname = row["field_name"] or ""
        fval_raw = row["field_value"]
        fval = _unwrap_field_value(fval_raw)
        if not fval or fname not in FIELD_ENTITY_MAP:
            continue
        etype, prefix = FIELD_ENTITY_MAP[fname]
        eid = safe_id(prefix, fval)
        if eid not in seen_entities:
            seen_entities.add(eid)
            entity_records.append((
                eid, etype, eid,
                json_attr(**{fname: fval, "doc_type": row["doc_type"] or ""}),
                "document_extraction",
                fval,
            ))
        # Accumulate extra attributes from other fields on the same document
        extra = entity_extra.setdefault(eid, {})
        extra[fname] = fval

    # Enrich attributes with accumulated data
    entity_records_enriched = []
    for rec in entity_records:
        eid = rec[0]
        extra = entity_extra.get(eid, {})
        base_attrs = {}
        try:
            base_attrs = json.loads(rec[3])
        except Exception:
            pass
        base_attrs.update(extra)
        entity_records_enriched.append((
            rec[0], rec[1], rec[2],
            json.dumps(base_attrs),
            rec[4], rec[5],
        ))
    entity_records = entity_records_enriched

    # Add Document entities from parsed_documents
    try:
        docs_rows = spark.table(f"{CATALOG}.{SCHEMA_RAW}.parsed_documents").collect()
    except Exception as _e:
        print(f"Warning: could not read parsed_documents: {_e}")
        docs_rows = []

    for doc in docs_rows:
        # Row objects use dict-style access, not .get()
        doc_id = doc["doc_id"] if "doc_id" in doc else ""
        if not doc_id:
            try: doc_id = doc["filename"] or ""
            except Exception: doc_id = ""
        doc_type   = doc["doc_type"]   if "doc_type"   in doc else ""
        char_count = doc["char_count"] if "char_count" in doc else 0
        short_name = re.sub(r"\.pdf$", "", doc_id, flags=re.IGNORECASE)[:50]
        eid = safe_id("DOC", short_name)
        entity_records.append((
            eid, "Document", eid,
            json_attr(filename=doc_id, doc_type=doc_type or "",
                      char_count=str(char_count or 0)),
            "parsed_documents",
            short_name,
        ))

    print(f"  Built {len(entity_records)} entities from extracted fields + documents")

df_entities = spark.createDataFrame(entity_records, _ENTITY_SCHEMA)
df_entities.write.mode("overwrite").format("delta")\
    .saveAsTable(f"{CATALOG}.{SCHEMA_ONT}.entities")
print(f"entities: {df_entities.count()} rows")

# COMMAND ----------
# MAGIC %md ## Step 3 — Build Ontology Relationships Table

# COMMAND ----------

if domain_id == "supply_chain":
    rel_records = [
        # Core shipment chain
        ("SUPP-001",           "SUPPLIES",          "PRD-001",         "MSA-2024-TF-001", 1.0, "CONTRACT-MSA-2024-TF-001"),
        ("SUPP-001",           "GOVERNED_BY",       "CONTRACT-MSA-2024-TF-001", None, 1.0, "CONTRACT-MSA-2024-TF-001"),
        ("SHP-20240315",       "CONTAINS",          "LOT-PP-240315",   "SHP-20240315",    1.0, "bill_of_lading_SHP-20240315.txt"),
        ("LOT-PP-240315",      "USED_IN",           "PRD-001",         None,              1.0, "certificate_of_analysis_LOT-PP-240315.txt"),
        ("SHP-20240315",       "DELIVERED_TO",      "DC-001",          "SHP-20240315",    1.0, "bill_of_lading_SHP-20240315.txt"),
        ("CAR-001",            "TRANSPORTED",       "SHP-20240315",    "SHP-20240315",    1.0, "bill_of_lading_SHP-20240315.txt"),
        # Incident chain
        ("SHP-20240315",       "EXPERIENCED",       "TE-20240315-001", "TE-20240315-001", 1.0, "temperature_log_TR-8821_SHP-20240315.txt"),
        ("TE-20240315-001",    "GENERATED",         "QIR-2024-0047",   "QIR-2024-0047",   1.0, "quality_incident_report_QIR-2024-0047.txt"),
        ("RCL-2024-0012",      "IMPACTED",          "LOT-PP-240315",   "RCL-2024-0012",   1.0, "recall_notice_RCL-2024-0012.txt"),
        # Distribution chain
        ("DC-001",             "DISTRIBUTES_TO",    "REST-101",        "RCL-2024-0012",   1.0, "recall_notice_RCL-2024-0012.txt"),
        ("DC-001",             "DISTRIBUTES_TO",    "REST-102",        "RCL-2024-0012",   1.0, "recall_notice_RCL-2024-0012.txt"),
        ("DC-001",             "DISTRIBUTES_TO",    "REST-103",        "RCL-2024-0012",   1.0, "recall_notice_RCL-2024-0012.txt"),
        ("DC-001",             "DISTRIBUTES_TO",    "REST-104",        "RCL-2024-0012",   1.0, "recall_notice_RCL-2024-0012.txt"),
        ("DC-001",             "DISTRIBUTES_TO",    "REST-105",        "RCL-2024-0012",   1.0, "recall_notice_RCL-2024-0012.txt"),
        ("DC-001",             "DISTRIBUTES_TO",    "REST-106",        "RCL-2024-0012",   1.0, "recall_notice_RCL-2024-0012.txt"),
        ("DC-001",             "DISTRIBUTES_TO",    "REST-107",        "RCL-2024-0012",   1.0, "recall_notice_RCL-2024-0012.txt"),
        ("DC-001",             "DISTRIBUTES_TO",    "REST-108",        "RCL-2024-0012",   1.0, "recall_notice_RCL-2024-0012.txt"),
        ("DC-001",             "DISTRIBUTES_TO",    "REST-109",        "RCL-2024-0012",   1.0, "recall_notice_RCL-2024-0012.txt"),
        ("DC-001",             "DISTRIBUTES_TO",    "REST-110",        "RCL-2024-0012",   1.0, "recall_notice_RCL-2024-0012.txt"),
        ("DC-001",             "DISTRIBUTES_TO",    "REST-111",        "RCL-2024-0012",   1.0, "recall_notice_RCL-2024-0012.txt"),
        ("DC-001",             "DISTRIBUTES_TO",    "REST-112",        "RCL-2024-0012",   1.0, "recall_notice_RCL-2024-0012.txt"),
        # Product sold
        ("REST-101",           "SOLD",              "PRD-001",         "RCL-2024-0012",   1.0, "recall_notice_RCL-2024-0012.txt"),
        # Liability
        ("SUPP-001",           "LIABLE_FOR",        "QIR-2024-0047",   "MSA-2024-TF-001", 1.0, "supplier_contract_tyson_poultry.txt"),
        ("CAR-001",            "CONTRIBUTED_TO",    "TE-20240315-001", "CAR-001",         0.8, "maintenance_report_TR-8821.txt"),
    ]
else:
    # ── Generic relationships: entity EXTRACTED_FROM document, entity RELATES_TO entity ──
    rel_records = []
    seen_rels: set = set()

    # EXTRACTED_FROM: each entity → the document(s) it was extracted from
    try:
        fields_rows2 = spark.table(f"{CATALOG}.{SCHEMA_RAW}.extracted_fields").collect()
    except Exception:
        fields_rows2 = []

    for row in fields_rows2:
        fname = row["field_name"] or ""
        fval  = _unwrap_field_value(row["field_value"])
        doc_id = row["doc_id"] or ""
        if not fval or fname not in FIELD_ENTITY_MAP:
            continue
        _, prefix = FIELD_ENTITY_MAP[fname]
        eid      = safe_id(prefix, fval)
        short_doc= re.sub(r"\.pdf$", "", doc_id, flags=re.IGNORECASE)[:50]
        doc_eid  = safe_id("DOC", short_doc)
        rel_key  = (eid, "EXTRACTED_FROM", doc_eid)
        if rel_key not in seen_rels:
            seen_rels.add(rel_key)
            rel_records.append((eid, "EXTRACTED_FROM", doc_eid, doc_id, 1.0, doc_id))

    # INSPECTS: Inspector → Store (from inspection_report extracted fields)
    # Build a mapping from doc_id → {store_id, inspector_id}
    doc_store:    dict = {}
    doc_inspector: dict = {}
    doc_permit:   dict = {}
    for row in fields_rows2:
        fname = row["field_name"] or ""
        fval  = _unwrap_field_value(row["field_value"])
        doc_id = row["doc_id"] or ""
        if not fval: continue
        if fname == "store_id":    doc_store[doc_id]     = fval
        if fname in ("inspector_id","inspector_name"): doc_inspector[doc_id] = fval
        if fname == "permit_number": doc_permit[doc_id]  = fval

    for doc_id, store_val in doc_store.items():
        store_eid = safe_id("STORE", store_val)
        doc_eid   = safe_id("DOC", re.sub(r"\.pdf$","",doc_id,flags=re.IGNORECASE)[:50])
        # Document COVERS Store
        rk = (doc_eid, "COVERS", store_eid)
        if rk not in seen_rels:
            seen_rels.add(rk); rel_records.append((doc_eid, "COVERS", store_eid, doc_id, 1.0, doc_id))
        # Inspector INSPECTED Store
        if doc_id in doc_inspector:
            insp_val = doc_inspector[doc_id]
            insp_eid = safe_id("INSP", insp_val)
            rk2 = (insp_eid, "INSPECTED", store_eid)
            if rk2 not in seen_rels:
                seen_rels.add(rk2); rel_records.append((insp_eid, "INSPECTED", store_eid, doc_id, 1.0, doc_id))
        # Permit ASSOCIATED_WITH Store
        if doc_id in doc_permit:
            perm_val = doc_permit[doc_id]
            perm_eid = safe_id("PERM", perm_val)
            rk3 = (perm_eid, "ASSOCIATED_WITH", store_eid)
            if rk3 not in seen_rels:
                seen_rels.add(rk3); rel_records.append((perm_eid, "ASSOCIATED_WITH", store_eid, doc_id, 1.0, doc_id))

    # ── Config-driven relationship rules (field-based edges within a document) ──
    # Each rule: {"subject_field", "predicate", "object_field"}. Both fields must be
    # in FIELD_ENTITY_MAP and present on the same document. No-op when a domain
    # declares no relationship_rules (backward compatible with supply_chain / compliance).
    if RELATIONSHIP_RULES:
        doc_fields: dict = {}
        for row in fields_rows2:
            did = row["doc_id"] or ""
            fn  = row["field_name"] or ""
            fv  = _unwrap_field_value(row["field_value"])
            if did and fn and fv:
                doc_fields.setdefault(did, {})[fn] = fv
        for did, fmap in doc_fields.items():
            for rule in RELATIONSHIP_RULES:
                sf   = rule.get("subject_field")
                pred = rule.get("predicate")
                of   = rule.get("object_field")
                if not (sf and pred and of):
                    continue
                sval = fmap.get(sf); oval = fmap.get(of)
                if not (sval and oval):
                    continue
                if sf not in FIELD_ENTITY_MAP or of not in FIELD_ENTITY_MAP:
                    continue
                s_eid = safe_id(FIELD_ENTITY_MAP[sf][1], sval)
                o_eid = safe_id(FIELD_ENTITY_MAP[of][1], oval)
                rk = (s_eid, pred, o_eid)
                if rk not in seen_rels:
                    seen_rels.add(rk)
                    rel_records.append((s_eid, pred, o_eid, did, 1.0, did))

    print(f"  Built {len(rel_records)} relationships")

df_rels = spark.createDataFrame(rel_records, _REL_SCHEMA)
df_rels.write.mode("overwrite").format("delta")\
    .saveAsTable(f"{CATALOG}.{SCHEMA_ONT}.relationships")
print(f"relationships: {df_rels.count()} rows")

# COMMAND ----------
# MAGIC %md ## Step 4 — Verify: Trace recall impact path

# COMMAND ----------

if domain_id == "supply_chain":
    display(spark.sql(f"""
        SELECT
            r1.subject_id AS recall_event,
            r1.predicate AS step1,
            r1.object_id AS lot,
            r2.predicate AS step2,
            r2.subject_id AS shipment,
            r3.predicate AS step3,
            r3.object_id AS distribution_center,
            r4.predicate AS step4,
            r4.object_id AS restaurant
        FROM {CATALOG}.{SCHEMA_ONT}.relationships r1
        JOIN {CATALOG}.{SCHEMA_ONT}.relationships r2
            ON r1.object_id = r2.object_id AND r2.predicate = 'CONTAINS'
        JOIN {CATALOG}.{SCHEMA_ONT}.relationships r3
            ON r2.subject_id = r3.subject_id AND r3.predicate = 'DELIVERED_TO'
        JOIN {CATALOG}.{SCHEMA_ONT}.relationships r4
            ON r3.object_id = r4.subject_id AND r4.predicate = 'DISTRIBUTES_TO'
        WHERE r1.predicate = 'IMPACTED'
          AND r1.subject_id = 'RCL-2024-0012'
    """))
else:
    # Generic verification: show entity-type distribution
    display(spark.sql(f"""
        SELECT entity_type, COUNT(*) AS entity_count
        FROM {CATALOG}.{SCHEMA_ONT}.entities
        GROUP BY entity_type
        ORDER BY entity_count DESC
    """))
    display(spark.sql(f"""
        SELECT predicate, COUNT(*) AS rel_count
        FROM {CATALOG}.{SCHEMA_ONT}.relationships
        GROUP BY predicate
        ORDER BY rel_count DESC
    """))

# COMMAND ----------

print("Ontology knowledge graph built:")
print(f"  {spark.table(f'{CATALOG}.{SCHEMA_ONT}.entities').count()} entities")
print(f"  {spark.table(f'{CATALOG}.{SCHEMA_ONT}.relationships').count()} relationships")
print(f"  {spark.table(f'{CATALOG}.{SCHEMA_ONT}.entity_aliases').count()} alias mappings")
