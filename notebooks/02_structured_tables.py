# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Structured Transactional Tables
# MAGIC
# MAGIC Creates realistic Delta tables representing the QSR supply chain.
# MAGIC All data is seeded around the cold chain incident scenario.

# COMMAND ----------

CATALOG    = "jai_docintel"
SCHEMA_RAW = "raw"
spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA_RAW}")

# COMMAND ----------
from pyspark.sql import Row
from datetime import datetime, timedelta
import random

# COMMAND ----------
# MAGIC %md ## Suppliers

# COMMAND ----------

suppliers = [
    ("SUPP-001", "Tyson Foods",       "Southeast", 0.72, "MSA-2024-TF-001"),
    ("SUPP-002", "Koch Foods",        "Midwest",   0.94, "MSA-2024-KF-002"),
    ("SUPP-003", "Wayne Farms",       "Southeast", 0.88, "MSA-2024-WF-003"),
    ("SUPP-004", "Martin's Famous",   "Northeast", 0.96, "MSA-2024-MF-004"),
    ("SUPP-005", "Pilgrim's Pride",   "Southeast", 0.81, "MSA-2024-PP-005"),
    ("SUPP-006", "Perdue Farms",      "Northeast", 0.91, "MSA-2024-PF-006"),
    ("SUPP-007", "Sanderson Farms",   "Southeast", 0.85, "MSA-2024-SF-007"),
    ("SUPP-008", "Mountaire Farms",   "Mid-Atlantic",0.89,"MSA-2024-MNT-008"),
    ("SUPP-009", "Amick Farms",       "Southeast", 0.87, "MSA-2024-AF-009"),
    ("SUPP-010", "House of Raeford",  "Southeast", 0.83, "MSA-2024-HR-010"),
]
df_suppliers = spark.createDataFrame(suppliers,
    ["supplier_id","supplier_name","region","risk_score","contract_id"])
df_suppliers.write.mode("overwrite").format("delta").saveAsTable("suppliers")
print(f"suppliers: {df_suppliers.count()} rows")

# COMMAND ----------
# MAGIC %md ## Products

# COMMAND ----------

products = [
    ("PRD-001","Chicken Sandwich Fillet","Poultry",14),
    ("PRD-002","Spicy Crispy Chicken",   "Poultry",14),
    ("PRD-003","Chicken Nuggets 10pc",   "Poultry",10),
    ("PRD-004","Chicken Tenders 4pc",    "Poultry",12),
    ("PRD-005","Grilled Chicken Fillet", "Poultry",12),
    ("PRD-006","Chicken Strips",         "Poultry",10),
    ("PRD-007","Beef Patty 4oz",         "Beef",   21),
    ("PRD-008","Beef Patty Quarter Lb",  "Beef",   21),
    ("PRD-009","Fish Fillet",            "Seafood",10),
    ("PRD-010","Bacon Strips",           "Pork",   30),
    ("PRD-011","Brioche Bun",            "Bakery", 7),
    ("PRD-012","Sesame Seed Bun",        "Bakery", 7),
]
df_products = spark.createDataFrame(products,
    ["product_id","product_name","category","shelf_life_days"])
df_products.write.mode("overwrite").format("delta").saveAsTable("products")
print(f"products: {df_products.count()} rows")

# COMMAND ----------
# MAGIC %md ## Carriers

# COMMAND ----------

carriers = [
    ("CAR-001","Swift Logistics Inc.",     "Southeast", 0.78),
    ("CAR-002","Ruan Transport",           "Midwest",   0.91),
    ("CAR-003","Gordon Food Service Dist.","National",  0.94),
    ("CAR-004","McLane Company",           "National",  0.93),
    ("CAR-005","US Foods Delivery",        "National",  0.90),
    ("CAR-006","Cardinal Logistics",       "Southeast", 0.86),
    ("CAR-007","NFI Industries",           "National",  0.88),
    ("CAR-008","Covenant Logistics",       "Southeast", 0.84),
]
df_carriers = spark.createDataFrame(carriers,
    ["carrier_id","carrier_name","region","reliability_score"])
df_carriers.write.mode("overwrite").format("delta").saveAsTable("carriers")
print(f"carriers: {df_carriers.count()} rows")

# COMMAND ----------
# MAGIC %md ## Distribution Centers

# COMMAND ----------

dcs = [
    ("DC-001","Atlanta DC",      "Southeast","ATL"),
    ("DC-002","Dallas DC",       "South Central","DFW"),
    ("DC-003","Los Angeles DC",  "West","LAX"),
    ("DC-004","Chicago DC",      "Midwest","ORD"),
    ("DC-005","New York DC",     "Northeast","NYC"),
    ("DC-006","Miami DC",        "Southeast","MIA"),
    ("DC-007","Denver DC",       "Mountain","DEN"),
    ("DC-008","Seattle DC",      "Northwest","SEA"),
]
df_dcs = spark.createDataFrame(dcs,
    ["dc_id","dc_name","region","dc_code"])
df_dcs.write.mode("overwrite").format("delta").saveAsTable("distribution_centers")
print(f"distribution_centers: {df_dcs.count()} rows")

# COMMAND ----------
# MAGIC %md ## Restaurants (50 locations)

# COMMAND ----------

restaurant_data = [
    # Southeast — served by ATL DC (DC-001)
    ("REST-101","Marietta Classic",        "Southeast","DC-001","GA"),
    ("REST-102","Kennesaw Station",        "Southeast","DC-001","GA"),
    ("REST-103","Alpharetta Mall",         "Southeast","DC-001","GA"),
    ("REST-104","Roswell Road",            "Southeast","DC-001","GA"),
    ("REST-105","Smyrna Village",          "Southeast","DC-001","GA"),
    ("REST-106","Sandy Springs Perimeter", "Southeast","DC-001","GA"),
    ("REST-107","Dunwoody Town Center",    "Southeast","DC-001","GA"),
    ("REST-108","Norcross Park",           "Southeast","DC-001","GA"),
    ("REST-109","Gwinnett Center",         "Southeast","DC-001","GA"),
    ("REST-110","Columbia Main",           "Southeast","DC-001","SC"),
    ("REST-111","Charlotte Uptown",        "Southeast","DC-001","NC"),
    ("REST-112","Nashville Broadway",      "Southeast","DC-001","TN"),
    ("REST-113","Birmingham Galleria",     "Southeast","DC-001","AL"),
    ("REST-114","Chattanooga Downtown",    "Southeast","DC-001","TN"),
    ("REST-115","Greenville SC",           "Southeast","DC-001","SC"),
    # South Central — served by DFW DC (DC-002)
    ("REST-201","Dallas Uptown",           "South Central","DC-002","TX"),
    ("REST-202","Fort Worth Cultural",     "South Central","DC-002","TX"),
    ("REST-203","Austin Domain",           "South Central","DC-002","TX"),
    ("REST-204","Houston Galleria",        "South Central","DC-002","TX"),
    ("REST-205","San Antonio River",       "South Central","DC-002","TX"),
    ("REST-206","Oklahoma City Penn",      "South Central","DC-002","OK"),
    ("REST-207","Tulsa Hills",             "South Central","DC-002","OK"),
    ("REST-208","New Orleans French",      "South Central","DC-002","LA"),
    ("REST-209","Baton Rouge Mall",        "South Central","DC-002","LA"),
    ("REST-210","Memphis Poplar",          "South Central","DC-002","TN"),
    # West — served by LAX DC (DC-003)
    ("REST-301","Los Angeles Beverly",     "West","DC-003","CA"),
    ("REST-302","Los Angeles Hollywood",   "West","DC-003","CA"),
    ("REST-303","San Diego Mission",       "West","DC-003","CA"),
    ("REST-304","San Francisco Market",    "West","DC-003","CA"),
    ("REST-305","Phoenix Scottsdale",      "West","DC-003","AZ"),
    ("REST-306","Las Vegas Strip",         "West","DC-003","NV"),
    ("REST-307","Sacramento Arden",        "West","DC-003","CA"),
    ("REST-308","Portland Lloyd",          "West","DC-003","OR"),
    ("REST-309","Salt Lake City Gateway",  "West","DC-003","UT"),
    ("REST-310","Tucson Oracle",           "West","DC-003","AZ"),
    # Midwest — served by ORD DC (DC-004)
    ("REST-401","Chicago Michigan Ave",    "Midwest","DC-004","IL"),
    ("REST-402","Chicago O'Hare",          "Midwest","DC-004","IL"),
    ("REST-403","Indianapolis Circle",     "Midwest","DC-004","IN"),
    ("REST-404","Columbus Easton",         "Midwest","DC-004","OH"),
    ("REST-405","Cleveland Beachwood",     "Midwest","DC-004","OH"),
    ("REST-406","Detroit Downtown",        "Midwest","DC-004","MI"),
    ("REST-407","Minneapolis Mall",        "Midwest","DC-004","MN"),
    ("REST-408","Milwaukee East Side",     "Midwest","DC-004","WI"),
    ("REST-409","Kansas City Plaza",       "Midwest","DC-004","MO"),
    ("REST-410","St. Louis Galleria",      "Midwest","DC-004","MO"),
    # Northeast — served by NYC DC (DC-005)
    ("REST-501","New York Times Sq",       "Northeast","DC-005","NY"),
    ("REST-502","New York Brooklyn",       "Northeast","DC-005","NY"),
    ("REST-503","Boston Back Bay",         "Northeast","DC-005","MA"),
    ("REST-504","Philadelphia Center",     "Northeast","DC-005","PA"),
    ("REST-505","Washington DC Union",     "Northeast","DC-005","DC"),
    ("REST-506","Baltimore Harbor",        "Northeast","DC-005","MD"),
    ("REST-507","Pittsburgh Station",      "Northeast","DC-005","PA"),
    ("REST-508","Hartford Downtown",       "Northeast","DC-005","CT"),
    ("REST-509","Providence Downtown",     "Northeast","DC-005","RI"),
    ("REST-510","Albany Crossgates",       "Northeast","DC-005","NY"),
]
df_restaurants = spark.createDataFrame(restaurant_data,
    ["restaurant_id","restaurant_name","region","dc_id","state"])
df_restaurants.write.mode("overwrite").format("delta").saveAsTable("restaurants")
print(f"restaurants: {df_restaurants.count()} rows")

# COMMAND ----------
# MAGIC %md ## Shipments (200 shipments including the incident)

# COMMAND ----------

import random
from datetime import datetime, timedelta

random.seed(42)
base_date = datetime(2024, 1, 1)
shipments = []
for i in range(200):
    sid = f"SHP-20240{str(i+1).zfill(3)}"
    sup = random.choice([s[0] for s in suppliers])
    lot = f"LOT-{random.choice(['PP','KF','WF','MF'])}-{str(random.randint(240101,240331)).zfill(6)}"
    car = random.choice([c[0] for c in carriers])
    dc  = random.choice([d[0] for d in dcs])
    dep = base_date + timedelta(days=i//3, hours=random.randint(4,8))
    arr = dep + timedelta(hours=random.randint(6,18))
    shipments.append((sid, sup, lot, car, dc, dep.isoformat(), arr.isoformat(), False))

# Overwrite the 60th entry with the incident shipment
shipments[59] = (
    "SHP-20240315",
    "SUPP-001",        # Tyson Foods
    "LOT-PP-240315",   # The incident lot
    "CAR-001",         # Swift Logistics
    "DC-001",          # Atlanta DC
    "2024-03-15T06:23:00",
    "2024-03-15T15:47:00",
    True               # is_incident
)

df_shipments = spark.createDataFrame(shipments,
    ["shipment_id","supplier_id","lot_number","carrier_id","dc_id",
     "departure_time","arrival_time","is_incident"])
df_shipments.write.mode("overwrite").format("delta").saveAsTable("shipments")
print(f"shipments: {df_shipments.count()} rows  (incident: SHP-20240315)")

# COMMAND ----------
# MAGIC %md ## Inventory Distribution (lot PP-240315 → 12 restaurants)

# COMMAND ----------

# The 12 restaurants that received the recalled lot
incident_distribution = [
    ("LOT-PP-240315", "REST-101", 24, "2024-03-17"),
    ("LOT-PP-240315", "REST-102", 18, "2024-03-17"),
    ("LOT-PP-240315", "REST-103", 20, "2024-03-17"),
    ("LOT-PP-240315", "REST-104", 22, "2024-03-17"),
    ("LOT-PP-240315", "REST-105", 16, "2024-03-17"),
    ("LOT-PP-240315", "REST-106", 24, "2024-03-17"),
    ("LOT-PP-240315", "REST-107", 20, "2024-03-17"),
    ("LOT-PP-240315", "REST-108", 18, "2024-03-16"),
    ("LOT-PP-240315", "REST-109", 22, "2024-03-16"),
    ("LOT-PP-240315", "REST-110", 20, "2024-03-16"),
    ("LOT-PP-240315", "REST-111", 18, "2024-03-16"),
    ("LOT-PP-240315", "REST-112", 16, "2024-03-16"),
]

# Add regular distributions for other lots
regular_dist = []
for lot_suffix in range(1, 60):
    lot = f"LOT-PP-2403{str(lot_suffix).zfill(2)}"
    if lot == "LOT-PP-240315":
        continue
    for rest_id in random.sample([r[0] for r in restaurant_data], random.randint(3, 8)):
        qty = random.randint(12, 36)
        delivery_date = (base_date + timedelta(days=lot_suffix)).strftime("%Y-%m-%d")
        regular_dist.append((lot, rest_id, qty, delivery_date))

all_dist = incident_distribution + regular_dist
df_inv = spark.createDataFrame(all_dist,
    ["lot_number","restaurant_id","quantity_cases","delivery_date"])
df_inv.write.mode("overwrite").format("delta").saveAsTable("inventory_distribution")
print(f"inventory_distribution: {df_inv.count()} rows")
print(f"  Incident lot (PP-240315) distributed to {len(incident_distribution)} restaurants")

# COMMAND ----------
# MAGIC %md ## Verify tables

# COMMAND ----------

for tbl in ["suppliers","products","carriers","distribution_centers","restaurants","shipments","inventory_distribution"]:
    cnt = spark.table(tbl).count()
    print(f"  {CATALOG}.{SCHEMA_RAW}.{tbl}: {cnt:,} rows")
