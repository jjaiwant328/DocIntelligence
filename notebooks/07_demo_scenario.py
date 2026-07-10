# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Demo Scenario: Cold Chain Failure & Recall
# MAGIC
# MAGIC End-to-end walkthrough of the primary demo scenario showing how the
# MAGIC system synthesizes documents + structured data + ontology to answer
# MAGIC executive-level business questions.
# MAGIC
# MAGIC **Scenario:** Tyson Foods shipment SHP-20240315 suffered a refrigeration failure.
# MAGIC Recall RCL-2024-0012 was issued. The system must determine full impact.

# COMMAND ----------

CATALOG    = "jai_docintel"
SCHEMA_RAW = "raw"
SCHEMA_ONT = "ontology"
spark.sql(f"USE CATALOG {CATALOG}")

# COMMAND ----------
# MAGIC %md ## 1. What happened? — The Incident Timeline

# COMMAND ----------

display(spark.sql(f"""
SELECT
    '2024-03-15 06:23' AS event_time,
    'Shipment Departs'  AS event,
    'SHP-20240315 | Tyson Foods → ATL DC | Trailer TR-8821 | 480 cases Chicken Fillet' AS detail
UNION ALL
SELECT '2024-03-15 10:15', 'Temperature Excursion Begins',
    'Trailer TR-8821 temperature exceeds 40°F threshold. Compressor HPO failure.'
UNION ALL
SELECT '2024-03-15 10:45', 'Peak Temperature',
    '48.2°F recorded — 8.2°F above contractual limit of 40°F'
UNION ALL
SELECT '2024-03-15 11:23', 'Temperature Restored',
    'Compressor restarted. Temperature returns to ≤40°F after 68 minutes of excursion.'
UNION ALL
SELECT '2024-03-15 15:47', 'Shipment Arrives Atlanta DC',
    'Product placed on HOLD. Temperature log retrieved. QIR-2024-0047 opened.'
UNION ALL
SELECT '2024-03-16 14:47', 'Conditional Release Approved',
    'Dr. Marcus Williams approves release pending confirmatory Salmonella test. Lot PP-240315 distributed.'
UNION ALL
SELECT '2024-03-20 00:00', 'Recall Issued',
    'RCL-2024-0012 — Class II voluntary recall. LOT-PP-240315 recalled from 12 restaurants.'
ORDER BY event_time
"""))

# COMMAND ----------
# MAGIC %md ## 2. Which restaurants received the recalled product?

# COMMAND ----------

display(spark.sql(f"""
SELECT
    r.restaurant_id,
    r.restaurant_name,
    r.state,
    r.region,
    dc.dc_name,
    inv.quantity_cases,
    ROUND(inv.quantity_cases * 30, 0) AS quantity_lbs,
    inv.delivery_date,
    ROUND(inv.quantity_cases * 450, 2) AS estimated_revenue_usd
FROM {CATALOG}.{SCHEMA_RAW}.inventory_distribution inv
JOIN {CATALOG}.{SCHEMA_RAW}.restaurants r ON inv.restaurant_id = r.restaurant_id
JOIN {CATALOG}.{SCHEMA_RAW}.distribution_centers dc ON r.dc_id = dc.dc_id
WHERE inv.lot_number = 'LOT-PP-240315'
ORDER BY inv.delivery_date, r.state
"""))

# COMMAND ----------
# MAGIC %md ## 3. What is the financial exposure?

# COMMAND ----------

display(spark.sql(f"""
SELECT
    component,
    amount_usd,
    source,
    notes
FROM (VALUES
    ('Contract Penalty — Temp Excursion Tier 2 (44–48°F)',  15000.0,  'MSA-2024-TF-001 Sec 4.1',  'Triggered by 68-min excursion at 48.2°F'),
    ('Recall Product Disposal (240 cases × $100)',          24000.0,  'RCL-2024-0012',             '440 cases shipped, 200 remaining at DC'),
    ('Expedited Microbiological Retesting',                  3500.0,  'QIR-2024-0047',             'Covance Food Solutions contract lab'),
    ('Lost Restaurant Revenue (12 locations)',             187000.0,  'RCL-2024-0012 estimate',    '12 restaurants × avg 3 days sales × $5,200/day'),
    ('Carrier Liability Offset (Swift 20% share)',          -4700.0,  'CSA-2024-SL-007 Sec 3.2',  'Maintenance-related failure: 20% carrier responsibility')
) AS t(component, amount_usd, source, notes)
ORDER BY ABS(amount_usd) DESC
"""))

# COMMAND ----------

total_exposure = spark.sql(f"""
SELECT SUM(ABS(amount_usd)) AS total_gross,
       SUM(amount_usd) AS total_net
FROM (VALUES
    (15000.0),(24000.0),(3500.0),(187000.0),(-4700.0)
) AS t(amount_usd)
""").collect()[0]

print(f"\n{'='*50}")
print(f"  Gross financial exposure:  ${total_exposure.total_gross:>12,.2f}")
print(f"  Net (after carrier offset): ${total_exposure.total_net:>11,.2f}")
print(f"{'='*50}")

# COMMAND ----------
# MAGIC %md ## 4. What are Tyson Foods' contractual obligations?

# COMMAND ----------

display(spark.sql(f"""
SELECT
    e.attributes:contract_number::STRING AS contract,
    'Temperature Limit' AS term_type,
    CONCAT(e.attributes:temp_limit_f::STRING, '°F maximum during transport') AS term_value,
    'MSA-2024-TF-001 Section 3.1' AS source
FROM {CATALOG}.{SCHEMA_ONT}.entities e
WHERE e.entity_type = 'Contract' AND e.entity_id = 'CONTRACT-MSA-2024-TF-001'
UNION ALL
SELECT
    e.attributes:contract_number::STRING,
    'Excursion Liability Threshold',
    CONCAT('Liability triggered if > ', e.attributes:excursion_threshold_min::STRING, ' minutes above 40°F'),
    'MSA-2024-TF-001 Section 3.3'
FROM {CATALOG}.{SCHEMA_ONT}.entities e
WHERE e.entity_type = 'Contract' AND e.entity_id = 'CONTRACT-MSA-2024-TF-001'
UNION ALL
SELECT
    e.attributes:contract_number::STRING,
    'Penalty Tier 2 (44–48°F)',
    CONCAT('$', e.attributes:penalty_tier2::STRING, ' per incident + product rejection rights'),
    'MSA-2024-TF-001 Section 4.1'
FROM {CATALOG}.{SCHEMA_ONT}.entities e
WHERE e.entity_type = 'Contract' AND e.entity_id = 'CONTRACT-MSA-2024-TF-001'
"""))

# COMMAND ----------
# MAGIC %md ## 5. Which menu items are affected?

# COMMAND ----------

display(spark.sql(f"""
SELECT
    p.product_name AS menu_item,
    p.product_id,
    p.category,
    'LOT-PP-240315' AS affected_lot,
    'Classic Chicken Sandwich, Spicy Chicken Sandwich, Chicken Deluxe' AS menu_applications,
    'RECALLED — Do Not Use' AS status
FROM {CATALOG}.{SCHEMA_RAW}.products p
WHERE p.product_id = 'PRD-001'
"""))

# COMMAND ----------
# MAGIC %md ## 6. Supplier Risk Assessment

# COMMAND ----------

display(spark.sql(f"""
SELECT
    s.supplier_name,
    s.supplier_id,
    s.risk_score,
    CASE
        WHEN s.risk_score >= 0.90 THEN 'PREFERRED'
        WHEN s.risk_score >= 0.85 THEN 'ACCEPTABLE'
        WHEN s.risk_score >= 0.75 THEN 'CONDITIONAL'
        ELSE 'HIGH RISK — ESCALATE'
    END AS risk_category,
    s.region,
    s.contract_id
FROM {CATALOG}.{SCHEMA_RAW}.suppliers s
ORDER BY s.risk_score DESC
"""))

# COMMAND ----------
# MAGIC %md ## 7. Distribution Center Cold Chain Performance

# COMMAND ----------

display(spark.sql(f"""
SELECT
    dc.dc_name,
    dc.region,
    COUNT(DISTINCT s.shipment_id) AS total_shipments,
    COUNT(DISTINCT CASE WHEN s.is_incident THEN s.shipment_id END) AS incident_shipments,
    ROUND(
        100.0 * COUNT(DISTINCT CASE WHEN s.is_incident THEN s.shipment_id END) /
        NULLIF(COUNT(DISTINCT s.shipment_id), 0), 2
    ) AS incident_rate_pct
FROM {CATALOG}.{SCHEMA_RAW}.distribution_centers dc
LEFT JOIN {CATALOG}.{SCHEMA_RAW}.shipments s ON s.dc_id = dc.dc_id
GROUP BY dc.dc_name, dc.region
ORDER BY incident_rate_pct DESC NULLS LAST
"""))

# COMMAND ----------
# MAGIC %md ## 8. Ontology Graph — Full Incident Path

# COMMAND ----------

display(spark.sql(f"""
WITH incident_path AS (
    SELECT
        r1.subject_id AS recall,
        r1.predicate  AS p1,
        r1.object_id  AS lot,
        r2.predicate  AS p2,
        r2.subject_id AS shipment,
        r3.predicate  AS p3,
        r3.object_id  AS distribution_center,
        r4.predicate  AS p4,
        r4.object_id  AS restaurant,
        e_r.display_name AS restaurant_name
    FROM {CATALOG}.{SCHEMA_ONT}.relationships r1
    JOIN {CATALOG}.{SCHEMA_ONT}.relationships r2
        ON r1.object_id = r2.object_id AND r2.predicate = 'CONTAINS'
    JOIN {CATALOG}.{SCHEMA_ONT}.relationships r3
        ON r2.subject_id = r3.subject_id AND r3.predicate = 'DELIVERED_TO'
    JOIN {CATALOG}.{SCHEMA_ONT}.relationships r4
        ON r3.object_id = r4.subject_id AND r4.predicate = 'DISTRIBUTES_TO'
    LEFT JOIN {CATALOG}.{SCHEMA_ONT}.entities e_r
        ON e_r.entity_id = r4.object_id
    WHERE r1.predicate = 'IMPACTED'
      AND r1.subject_id = 'RCL-2024-0012'
)
SELECT
    CONCAT(recall, ' → ', lot, ' → ', shipment, ' → ', distribution_center, ' → ', restaurant) AS impact_path,
    restaurant_name
FROM incident_path
ORDER BY restaurant
"""))

# COMMAND ----------

print("""
╔══════════════════════════════════════════════════════════════╗
║  DocIntelligence Demo — Summary                             ║
╠══════════════════════════════════════════════════════════════╣
║  Incident:     SHP-20240315 (cold chain failure, 68 min)    ║
║  Peak Temp:    48.2°F (+8.2°F over 40°F threshold)          ║
║  Lot Recalled: LOT-PP-240315                                ║
║  Recall:       RCL-2024-0012 (Class II)                     ║
║  Restaurants:  12 affected (Southeast region)               ║
║  Exposure:     $224,800 gross / $220,100 net                ║
║  Liable Party: Tyson Foods (80%) + Swift Logistics (20%)    ║
╚══════════════════════════════════════════════════════════════╝
""")
