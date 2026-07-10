# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Compliance Synthetic Document Corpus
# MAGIC
# MAGIC Generates ~50 realistic compliance documents for a convenience-retail chain
# MAGIC (RaceTrac-style) and writes them as plain-text files to the Compliance UC Volume.
# MAGIC
# MAGIC Covers 6 compliance domains:
# MAGIC - Environmental (UST / SPCC / EPA)
# MAGIC - Food Safety (health inspections / HACCP)
# MAGIC - OSHA / Safety
# MAGIC - Fuel Operations (dispensers / tanks)
# MAGIC - Alcohol & Tobacco licensing
# MAGIC - Vendor / Supplier compliance
# MAGIC
# MAGIC Consistent entity names allow cross-document resolution:
# MAGIC - Stores: Store_101 … Store_150 (Southeast region, GA/FL/TX)
# MAGIC - Inspectors: Maria Chen, James Kowalski, Sandra Osei, Tom Rivera, Priya Nair
# MAGIC - Vendors: PetroChem Supplies LLC, CleanFleet Solutions, SafeServe Foods Inc.
# MAGIC - Regulations: 40 CFR Part 280, 29 CFR 1910, FDA 21 CFR Part 110, NFPA 30A

# COMMAND ----------

CATALOG     = "jai_docintel"
SCHEMA      = "compliance"
VOLUME_DOCS = "documents"
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME_DOCS}"

# COMMAND ----------

import os

def write_doc(filename: str, content: str):
    path = f"{VOLUME_PATH}/{filename}"
    with open(path, "w") as f:
        f.write(content.strip())
    print(f"Written: {filename}")

# COMMAND ----------
# MAGIC %md ## Environmental Compliance Documents

# COMMAND ----------

write_doc("env_ust_inspection_Store101_2025.txt", """
UNDERGROUND STORAGE TANK (UST) INSPECTION REPORT

Document ID: UST-INSP-2025-0101
Document Type: inspection_report
Inspection Type: Annual UST Compliance Inspection
Store ID: Store_101
Store Address: 4821 Peachtree Industrial Blvd, Norcross, GA 30092
Region: Southeast — Georgia
Inspector: Maria Chen, EPA Region IV Certified Inspector #GA-UST-4412
Inspection Date: March 12, 2025
Regulation Reference: 40 CFR Part 280; Georgia Rules for Underground Storage Tanks Chapter 391-3-15
Severity: HIGH
Status: VIOLATIONS FOUND — CORRECTIVE ACTION REQUIRED

SUMMARY
Annual UST compliance inspection conducted at RaceTrac Store 101. The facility operates three (3)
underground storage tanks: Tank T-101A (10,000 gal, regular unleaded), Tank T-101B (10,000 gal,
premium unleaded), Tank T-101C (8,000 gal, diesel).

FINDINGS

Finding ENV-101-001 (CRITICAL):
Overfill protection device on Tank T-101A (regular unleaded) was found non-functional.
Ball float valve failed during drop test. This condition creates imminent risk of product release.
Regulation: 40 CFR § 280.20(c)(1) — Overfill prevention equipment required.
Severity: CRITICAL
Corrective Action Required: Replace overfill protection device immediately. Re-inspection required
within 30 days.
Deadline: April 11, 2025

Finding ENV-101-002 (MODERATE):
Spill containment basin at Tank T-101B shows visible cracks and surface rust. Containment
integrity compromised. Liquid observed pooling after rain event.
Regulation: 40 CFR § 280.20(c)(2) — Spill prevention equipment required.
Severity: MODERATE
Corrective Action Required: Repair or replace spill containment basin.
Deadline: May 12, 2025

Finding ENV-101-003 (LOW):
Monthly walkthrough records for January 2025 missing from the release detection log.
Regulation: 40 CFR § 280.45 — Release detection recordkeeping.
Severity: LOW
Corrective Action Required: Locate or reconstruct records. Implement recordkeeping procedure.
Deadline: March 26, 2025

RELEASE DETECTION STATUS
Automatic Tank Gauging (ATG): Veeder-Root TLS-450PLUS — OPERATIONAL
Interstitial monitoring: OPERATIONAL
Line leak detection: OPERATIONAL

NEXT SCHEDULED INSPECTION: March 2026
Inspector Signature: Maria Chen    Date: March 12, 2025
""")

# COMMAND ----------

write_doc("env_ust_inspection_Store115_2025.txt", """
UNDERGROUND STORAGE TANK (UST) INSPECTION REPORT

Document ID: UST-INSP-2025-0115
Document Type: inspection_report
Inspection Type: Annual UST Compliance Inspection
Store ID: Store_115
Store Address: 7200 W Colonial Dr, Orlando, FL 32818
Region: Southeast — Florida
Inspector: James Kowalski, FDEP UST Inspector License #FL-UST-7734
Inspection Date: April 3, 2025
Regulation Reference: 40 CFR Part 280; Florida Administrative Code Rule 62-761
Severity: LOW
Status: PASS — MINOR OBSERVATIONS NOTED

SUMMARY
Annual UST compliance inspection at RaceTrac Store 115. Facility operates two (2) USTs:
Tank T-115A (12,000 gal, regular unleaded), Tank T-115B (8,000 gal, diesel).

FINDINGS

Finding ENV-115-001 (LOW):
Annual line tightness test certificate for Tank T-115B (diesel) was present but filed under
incorrect document ID (T-115A). Records management issue only; underlying test passed.
Severity: LOW
Corrective Action Required: Correct filing. No re-test needed.
Deadline: April 17, 2025

RELEASE DETECTION STATUS
ATG: Veeder-Root TLS-350 — OPERATIONAL
Interstitial monitoring: OPERATIONAL
Line leak detection: OPERATIONAL

Overall Assessment: COMPLIANT with minor administrative correction required.

NEXT SCHEDULED INSPECTION: April 2026
Inspector Signature: James Kowalski    Date: April 3, 2025
""")

# COMMAND ----------

write_doc("env_spcc_plan_Store101_2024.txt", """
SPILL PREVENTION, CONTROL, AND COUNTERMEASURE (SPCC) PLAN

Document ID: SPCC-2024-0101
Document Type: policy_document
Plan Type: SPCC Tier I Qualified Facility Plan
Store ID: Store_101
Store Address: 4821 Peachtree Industrial Blvd, Norcross, GA 30092
Region: Southeast — Georgia
Prepared By: Environmental Compliance Team
Issue Date: January 15, 2024
Next Review Date: January 15, 2026
Regulation Reference: 40 CFR Part 112
Severity: N/A
Status: ACTIVE

FACILITY DESCRIPTION
RaceTrac Store 101 stores petroleum products in three underground storage tanks with a combined
capacity of 28,000 gallons. Above-ground oil storage (motor oil, hydraulic fluid) totals 275 gallons
in the convenience store stockroom.

POTENTIAL DISCHARGE SCENARIOS
1. UST overfill during fuel delivery
2. Spill containment basin failure
3. Dispenser hose or nozzle failure
4. Above-ground container rupture

PREVENTION MEASURES
- Monthly visual inspections of all UST equipment
- Automatic overfill prevention devices on all tanks
- Dispenser breakaway hoses with automatic shutoff
- Secondary containment for above-ground oil containers
- Driver training: Buckeye Pipeline delivery protocol

RESPONSE PROCEDURES
Tier 1 (minor spill, <5 gallons): Store employee contains with absorbent material.
  Dispose per local hazardous waste guidelines. Log in daily inspection record.
Tier 2 (moderate, 5–50 gallons): Contact District Manager immediately. Engage PetroChem
  Supplies LLC emergency response (24-hr: 1-800-555-0192). Notify GEMA if waterway threatened.
Tier 3 (major, >50 gallons or waterway impact): Activate emergency response plan.
  Notify EPA Region IV National Response Center (1-800-424-8802) within 24 hours.

TRAINING
All Store 101 employees complete annual SPCC awareness training. Records maintained on file.
Trainer: Sandra Osei, Regional EHS Coordinator

Certifying PE: [Signature on file]    Date: January 15, 2024
""")

# COMMAND ----------

write_doc("env_epa_notice_Store101_2025.txt", """
NOTICE OF VIOLATION

Document ID: EPA-NOV-2025-0044
Document Type: incident_report
Issuing Authority: U.S. Environmental Protection Agency, Region IV
Issued To: RaceTrac Petroleum, Inc. — Store 101
Store Address: 4821 Peachtree Industrial Blvd, Norcross, GA 30092
Store ID: Store_101
Region: Southeast — Georgia
Issue Date: March 20, 2025
Regulation Reference: 40 CFR § 280.20(c)(1); Georgia Rules Chapter 391-3-15
Severity: HIGH
Status: OPEN — RESPONSE REQUIRED BY APRIL 10, 2025

NOTICE OF VIOLATION

RaceTrac Petroleum, Inc. is hereby notified that UST inspection conducted on March 12, 2025 at
Store 101 revealed the following violations of federal and state UST regulations:

VIOLATION 1: Non-functional overfill prevention device (Tank T-101A)
Citation: 40 CFR § 280.20(c)(1)
Description: Ball float valve on 10,000-gallon regular unleaded tank found non-functional during
annual compliance inspection. Overfill protection is required equipment under federal UST regulations.
Potential Consequence: Administrative penalty up to $37,500 per day per violation.

REQUIRED RESPONSE
1. Submit written corrective action plan within 10 days (by April 10, 2025).
2. Complete repairs and submit proof of correction within 30 days (by April 20, 2025).
3. Schedule re-inspection with EPA Region IV.

Failure to respond may result in administrative penalties and/or compliance orders.

Issued By: Maria Chen, EPA Region IV Inspector #GA-UST-4412
Date: March 20, 2025
""")

# COMMAND ----------

write_doc("env_leak_detection_Store128_2025.txt", """
LEAK DETECTION MONITORING REPORT

Document ID: LEAK-MON-2025-0128
Document Type: inspection_report
Inspection Type: Monthly Leak Detection Review
Store ID: Store_128
Store Address: 1502 Highway 6 South, Sugar Land, TX 77478
Region: Gulf Coast — Texas
Inspector: Tom Rivera, TCEQ Licensed UST Operator #TX-UST-9921
Report Date: February 28, 2025
Regulation Reference: 40 CFR Part 280 Subpart D; Texas Administrative Code Title 30, Chapter 334
Severity: MODERATE
Status: ANOMALY DETECTED — INVESTIGATION IN PROGRESS

MONITORING EQUIPMENT
ATG System: Franklin Fueling TS-550 Sentinel
Monitoring Frequency: Continuous (24/7 with monthly operator review)

MONTHLY SUMMARY — FEBRUARY 2025
Tank T-128A (Regular Unleaded, 10,000 gal): No anomalies.
Tank T-128B (Diesel, 8,000 gal): ANOMALY DETECTED.
  Inventory discrepancy flag on February 19, 2025.
  Calculated loss: 47 gallons over 3-day monitoring period.
  Discrepancy exceeds ATG alert threshold of 30 gallons/month.
Tank T-128C (Premium, 8,000 gal): No anomalies.

INVESTIGATION STATUS
Delivery records reconciled — no delivery accounting error.
Meter calibration verified — no dispenser variance.
Root cause: INCONCLUSIVE. Soil vapor monitoring initiated.
TCEQ notification filed February 21, 2025 per 30 TAC § 334.125.

RECOMMENDED ACTION
Third-party tank integrity test (precision test) scheduled March 15, 2025.
If confirmed release: Remediation plan required within 45 days.
Environmental consultant: PetroChem Supplies LLC engaged.

Report Prepared By: Tom Rivera    Date: February 28, 2025
""")

# COMMAND ----------

write_doc("env_audit_Store128_2025.txt", """
ENVIRONMENTAL COMPLIANCE AUDIT REPORT

Document ID: ENV-AUDIT-2025-0128
Document Type: audit_report
Audit Type: Comprehensive Environmental Compliance Audit
Store ID: Store_128
Store Address: 1502 Highway 6 South, Sugar Land, TX 77478
Region: Gulf Coast — Texas
Lead Auditor: Sandra Osei, Regional EHS Coordinator
Audit Date: March 5, 2025
Regulation Reference: 40 CFR Parts 112, 280; Texas TAC Title 30
Severity: MODERATE
Status: AUDIT COMPLETE — 2 OPEN FINDINGS

AUDIT SCOPE
Full environmental compliance review triggered by February 2025 inventory discrepancy on Tank T-128B.

AUDIT FINDINGS

Finding ENV-A128-001 (MODERATE — OPEN):
ATG anomaly on Tank T-128B (diesel) remains unresolved. Third-party precision test pending.
Risk: Potential unreported release. TCEQ already notified.
Status: IN PROGRESS

Finding ENV-A128-002 (LOW — OPEN):
Hazardous waste accumulation area lacks secondary containment signage required under 40 CFR § 265.
Store manager unaware of requirement.
Corrective Action: Install RCRA secondary containment signs. Train store manager.
Deadline: April 5, 2025

POSITIVE OBSERVATIONS
- SPCC plan current and available on-site.
- All employees completed annual SPCC awareness training (records on file).
- Stormwater inspection log complete for Q4 2024.
- Dispenser sumps clean and dry.

AUDIT CONCLUSION
Two open findings require follow-up. No imminent release risk confirmed. Continue monitoring T-128B.

Lead Auditor: Sandra Osei    Date: March 5, 2025
""")

# COMMAND ----------
# MAGIC %md ## Food Safety Compliance Documents

# COMMAND ----------

write_doc("food_health_inspection_Store101_2025.txt", """
FOOD SERVICE ESTABLISHMENT HEALTH INSPECTION REPORT

Document ID: FOOD-INSP-2025-0101-A
Document Type: inspection_report
Inspection Type: Routine Health Inspection
Store ID: Store_101
Store Address: 4821 Peachtree Industrial Blvd, Norcross, GA 30092
Region: Southeast — Georgia
Inspector: Priya Nair, Gwinnett County Environmental Health Inspector #GC-EH-5543
Inspection Date: February 14, 2025
Regulation Reference: Georgia Food Service Rules; FDA Food Code 2022
Severity: MODERATE
Status: CONDITIONAL PASS — FOLLOW-UP REQUIRED

INSPECTION SUMMARY
Routine unannounced inspection of food service operations at RaceTrac Store 101.
Establishment serves hot foods, fountain drinks, and packaged foods.

VIOLATIONS FOUND

Violation FOOD-101-V001 (Priority — 3 points):
Roller grill surface temperature recorded at 128°F at time of inspection. Minimum required
holding temperature for hot foods is 135°F (57°C).
Regulation: FDA Food Code 3-501.16(A)(1)
Corrective Action: Adjust roller grill thermostat. Verify with probe thermometer before service.
Corrected On-Site: Yes — temperature adjusted to 140°F during inspection.

Violation FOOD-101-V002 (Priority Foundation — 2 points):
Food handler observed handling ready-to-eat sandwich without gloves after handling raw hot dog.
Regulation: FDA Food Code 3-301.11
Corrective Action: Employee counseling. Require glove use for all ready-to-eat food contact.
Corrected On-Site: Yes.

Violation FOOD-101-V003 (Core — 1 point):
Handwashing station near food prep area lacked paper towels.
Regulation: FDA Food Code 6-301.12
Corrective Action: Restock paper towel dispenser.
Corrected On-Site: Yes.

TOTAL SCORE: 94/100 (6 points deducted)
INSPECTION RESULT: CONDITIONAL PASS
Re-inspection scheduled: March 14, 2025

Inspector Signature: Priya Nair    Date: February 14, 2025
""")

# COMMAND ----------

write_doc("food_health_inspection_Store115_2025.txt", """
FOOD SERVICE ESTABLISHMENT HEALTH INSPECTION REPORT

Document ID: FOOD-INSP-2025-0115-A
Document Type: inspection_report
Inspection Type: Routine Health Inspection
Store ID: Store_115
Store Address: 7200 W Colonial Dr, Orlando, FL 32818
Region: Southeast — Florida
Inspector: James Kowalski, Orange County Health Inspector #OC-EH-2287
Inspection Date: January 22, 2025
Regulation Reference: Florida Administrative Code 64E-11; FDA Food Code 2022
Severity: HIGH
Status: FAILED — RE-INSPECTION REQUIRED

INSPECTION SUMMARY
Routine unannounced inspection. Store 115 has had two prior inspections in the past 18 months
with violations. This is the third inspection in the current cycle.

VIOLATIONS FOUND

Violation FOOD-115-V001 (Priority — 5 points):
Walk-in cooler holding temperature recorded at 48°F. Required maximum is 41°F.
Affected products: pre-packaged sandwiches, dairy items, cut fruit. Approximately 80 lbs of
product voluntarily discarded at inspector direction.
Regulation: FDA Food Code 3-501.16(A)(2)
Corrective Action Required: Repair walk-in cooler refrigeration unit.
Not Corrected On-Site.

Violation FOOD-115-V002 (Priority — 4 points):
Pest activity observed: mouse droppings behind hot food display case. Pest control log shows
last treatment: September 2024 (4+ months prior).
Regulation: FDA Food Code 6-501.111
Corrective Action Required: Immediate pest control treatment. Seal entry points.
Not Corrected On-Site.

Violation FOOD-115-V003 (Priority Foundation — 2 points):
No Certified Food Manager on premises during inspection. Florida requires at least one CFM
per establishment.
Regulation: Florida Administrative Code 64E-11.003(4)
Corrective Action Required: Schedule CFM certification for store manager within 30 days.
Not Corrected On-Site.

TOTAL SCORE: 71/100
INSPECTION RESULT: FAILED
Mandatory Re-inspection: February 22, 2025
Failure to achieve 70+ on re-inspection may result in license suspension.

Inspector Signature: James Kowalski    Date: January 22, 2025
""")

# COMMAND ----------

write_doc("food_haccp_plan_Store101_2024.txt", """
HAZARD ANALYSIS AND CRITICAL CONTROL POINTS (HACCP) PLAN

Document ID: HACCP-2024-CORP-001
Document Type: policy_document
Plan Scope: Hot Food Service — Roller Grill and Hot Holding Operations
Store ID: ALL STORES (Corporate Policy)
Region: All Regions
Prepared By: SafeServe Foods Inc. — Food Safety Consulting
Issue Date: June 1, 2024
Review Date: June 1, 2025
Regulation Reference: FDA Food Code 2022; 21 CFR Part 110
Severity: N/A
Status: ACTIVE — MANDATORY

PRODUCT DESCRIPTION
Hot dogs, taquitos, tornados, and roller grill items. Cooked to internal temperature of 165°F
minimum, held at 135°F minimum.

PROCESS FLOW
Receive frozen product → Cold storage (≤41°F) → Thaw (if applicable) → Cook → Hot hold → Serve/Discard

HAZARD ANALYSIS
Biological: Pathogen survival (Salmonella, E. coli, Listeria) if temperature control fails.
Physical: Foreign objects from packaging contamination.
Chemical: Cleaning chemical residue if equipment improperly sanitized.

CRITICAL CONTROL POINTS

CCP-1: Cooking Temperature
Critical Limit: Internal temperature ≥ 165°F
Monitoring: Probe thermometer check every 2 hours by food handler
Corrective Action: Continue cooking until CL met. Discard if product quality compromised.
Records: Temperature log in POS system

CCP-2: Hot Holding Temperature
Critical Limit: Holding temperature ≥ 135°F
Monitoring: ATG thermostat + manual probe every 4 hours
Corrective Action: Adjust thermostat. Discard product if temp <135°F for >4 hours.
Records: Hot holding log (paper + digital)

CCP-3: Time-Temperature Discard
Critical Limit: Maximum 4-hour hold time at service temperature
Monitoring: Time stamps on all hot food items
Corrective Action: Discard items exceeding 4 hours regardless of temperature.
Records: Discard log

VERIFICATION
Internal audit quarterly by District Manager.
Third-party audit annually by SafeServe Foods Inc.

Approved By: Director of Food Safety, RaceTrac Petroleum, Inc.    Date: June 1, 2024
""")

# COMMAND ----------

write_doc("food_corrective_action_Store115_2025.txt", """
FOOD SAFETY CORRECTIVE ACTION PLAN

Document ID: FOOD-CAP-2025-0115
Document Type: corrective_action_plan
Reference Inspection: FOOD-INSP-2025-0115-A (Failed inspection January 22, 2025)
Store ID: Store_115
Store Address: 7200 W Colonial Dr, Orlando, FL 32818
Region: Southeast — Florida
Prepared By: District Manager — Carlos Mendez
Submitted: January 28, 2025
Deadline: February 22, 2025 (mandatory re-inspection date)
Severity: HIGH
Status: IN PROGRESS

CORRECTIVE ACTIONS

Action FOOD-CAP-115-001 (Violation FOOD-115-V001 — Walk-in Cooler Temperature):
Root Cause: Refrigeration compressor failure identified by HVAC technician on January 23, 2025.
Action Taken:
  - Emergency repair service contacted January 23, 2025. Parts ordered.
  - Temporary refrigeration unit rented for product safety during repair period.
  - Compressor replaced January 27, 2025. Unit verified at 38°F at completion.
  - All new product received under proper temperature conditions.
Verification: Continuous temperature monitoring via ATG. Readings logged daily.
Status: COMPLETED January 27, 2025

Action FOOD-CAP-115-002 (Violation FOOD-115-V002 — Pest Activity):
Root Cause: Gap in rear wall near delivery door identified as entry point.
Action Taken:
  - Orkin Commercial Services treatment conducted January 24, 2025.
  - Entry point sealed with steel wool and foam caulk January 24, 2025.
  - Monitoring stations installed under hot food case and near delivery entrance.
  - Monthly Orkin service contract reinstated (was quarterly; upgraded to monthly).
Verification: Orkin inspection report January 24, 2025 attached.
Status: COMPLETED January 24, 2025

Action FOOD-CAP-115-003 (Violation FOOD-115-V003 — CFM Certification):
Root Cause: Previous CFM (Store Manager Angela Torres) transferred to Store 122 in December 2024.
Action Taken:
  - Store Manager replacement Marcus Webb enrolled in ServSafe Manager course January 27, 2025.
  - Exam scheduled: February 5, 2025.
  - In interim, District Manager Carlos Mendez is on-site for all inspection windows.
Verification: ServSafe certification will be provided upon passing exam.
Status: IN PROGRESS — Exam February 5, 2025

Submitted By: Carlos Mendez, District Manager    Date: January 28, 2025
""")

# COMMAND ----------

write_doc("food_temp_log_Store101_Feb2025.txt", """
FOOD SERVICE TEMPERATURE MONITORING LOG

Document ID: FOOD-TEMP-2025-0101-FEB
Document Type: inspection_report
Log Type: Monthly Temperature Compliance Log
Store ID: Store_101
Store Address: 4821 Peachtree Industrial Blvd, Norcross, GA 30092
Region: Southeast — Georgia
Responsible Employee: Shift Manager (rotating)
Log Period: February 1–28, 2025
Regulation Reference: FDA Food Code 3-501.16; Georgia Food Service Rules
Severity: LOW
Status: COMPLIANT

EQUIPMENT MONITORED
Unit 1: Walk-in Cooler (Target: ≤41°F)
Unit 2: Roller Grill (Target: ≥135°F)
Unit 3: Nacho Cheese Dispenser (Target: ≥135°F)
Unit 4: Hot Holding Case — Taquitos (Target: ≥135°F)
Unit 5: Open-Top Cooler — Beverages (Target: ≤41°F)

WEEKLY SUMMARY (readings taken twice daily, 7AM and 3PM)

Week 1 (Feb 1–7): All units within range. No corrective action required.
Week 2 (Feb 8–14): Roller grill low reading 128°F on Feb 14 at 7AM (noted by county inspector).
  Corrected immediately. Thermostat adjusted. All subsequent readings ≥135°F.
Week 3 (Feb 15–21): All units within range. Walk-in cooler averaging 38–40°F.
Week 4 (Feb 22–28): All units within range. Nacho cheese unit serviced Feb 26 (routine maintenance).

EXCEPTIONS THIS MONTH: 1 (Roller grill temperature low on Feb 14; corrected on-site)

EMPLOYEE SIGNATURES
Week 1: J. Martinez, T. Washington
Week 2: J. Martinez, A. Patel (Feb 14 incident documented)
Week 3: R. Johnson, T. Washington
Week 4: A. Patel, J. Martinez

Monthly Review: Store Manager    Date: March 1, 2025
""")

# COMMAND ----------
# MAGIC %md ## OSHA / Safety Documents

# COMMAND ----------

write_doc("safety_inspection_Store128_2025.txt", """
OSHA / WORKPLACE SAFETY INSPECTION REPORT

Document ID: OSHA-INSP-2025-0128
Document Type: inspection_report
Inspection Type: Annual Safety Walkthrough
Store ID: Store_128
Store Address: 1502 Highway 6 South, Sugar Land, TX 77478
Region: Gulf Coast — Texas
Inspector: Sandra Osei, Regional EHS Coordinator
Inspection Date: March 5, 2025
Regulation Reference: 29 CFR 1910 (General Industry Standards); 29 CFR 1910.1200 (Hazard Communication)
Severity: MODERATE
Status: VIOLATIONS FOUND — CORRECTIVE ACTION REQUIRED

SUMMARY
Annual safety inspection during broader environmental audit visit.

FINDINGS

Finding OSHA-128-001 (MODERATE):
SDS (Safety Data Sheets) binder for hazardous chemicals not current. Three products (new cleaning
solvent, fuel treatment additive, compressed CO2) added in Q4 2024 without corresponding SDS entry.
Regulation: 29 CFR 1910.1200(g) — SDS maintained and accessible.
Corrective Action: Obtain and file SDS for three missing products.
Deadline: March 19, 2025

Finding OSHA-128-002 (LOW):
Emergency exit sign in back stockroom unlit. Battery backup depleted.
Regulation: 29 CFR 1910.37(b)(6) — Exit markings must be illuminated.
Corrective Action: Replace backup battery.
Deadline: March 7, 2025 (immediate)

Finding OSHA-128-003 (LOW):
Fire extinguisher inspection tag for Unit FE-128-02 (back room) shows last inspection: September 2023
(18 months ago). Annual inspection overdue.
Regulation: 29 CFR 1910.157(e)(1)
Corrective Action: Schedule fire extinguisher service.
Deadline: March 19, 2025

Inspector: Sandra Osei    Date: March 5, 2025
""")

# COMMAND ----------

write_doc("safety_incident_report_Store101_2025.txt", """
WORKPLACE INCIDENT REPORT

Document ID: INC-OSHA-2025-0101
Document Type: incident_report
Incident Type: Slip and Fall — Employee Injury
Store ID: Store_101
Store Address: 4821 Peachtree Industrial Blvd, Norcross, GA 30092
Region: Southeast — Georgia
Report Completed By: Store Manager
Incident Date: March 3, 2025
Report Date: March 3, 2025
Regulation Reference: 29 CFR 1904 (Recordkeeping); OSHA 300 Log
Severity: MODERATE
Status: OSHA 300 LOG ENTRY REQUIRED — INVESTIGATION COMPLETE

INCIDENT DESCRIPTION
Employee James R. (last name withheld, Age 34) slipped on wet floor in stockroom while moving
a pallet of beverages at approximately 6:15 AM. Employee fell and sustained a sprained left wrist
and minor contusion to knee. Employee transported to urgent care; X-ray confirmed sprain, no fracture.
Employee cleared to return to light duty in 3 days.

ROOT CAUSE ANALYSIS
1. Wet mop had been used in stockroom but wet floor signs not placed.
2. Pallet moving in low-light pre-opening conditions.

CONTRIBUTING FACTORS
- Wet floor signs were in front of store area during mopping; not moved to stockroom.
- Overhead light bulb in stockroom entry burned out (unreported).

CORRECTIVE ACTIONS
1. Replace burned-out light immediately — COMPLETED March 3, 2025.
2. Update mop procedure: wet floor signs must cover BOTH main floor and stockroom during mopping.
   Training delivered to all current shift staff by Store Manager. Written in shift checklist.
3. Wet floor sign inventory to be checked weekly and documented on opening checklist.

OSHA RECORDABILITY
Days away from work: 0 (light duty arranged)
OSHA 300 Log entry: Required (restricted work case)
Workers' comp claim filed: Yes — claim #WC-2025-0312

Store Manager Signature:     Date: March 3, 2025
""")

# COMMAND ----------

write_doc("safety_ppe_audit_All_2025.txt", """
PERSONAL PROTECTIVE EQUIPMENT (PPE) AUDIT REPORT

Document ID: PPE-AUDIT-2025-Q1
Document Type: audit_report
Audit Type: Quarterly PPE Compliance Audit
Stores Audited: Store_101, Store_115, Store_128, Store_133, Store_145
Region: Southeast + Gulf Coast
Lead Auditor: Sandra Osei, Regional EHS Coordinator
Audit Period: Q1 2025 (January–March)
Regulation Reference: 29 CFR 1910.132–138 (PPE Standards); RaceTrac PPE Policy v3.2
Severity: LOW
Status: AUDIT COMPLETE — 2 STORES REQUIRE FOLLOW-UP

AUDIT CRITERIA
- Cut-resistant gloves available for box-cutter use
- Disposable gloves available for food handling and chemical cleaning
- Safety glasses available for battery/fuel handling
- Hearing protection available (if noise exposure >85 dB)
- Slip-resistant footwear policy communicated to all employees

AUDIT RESULTS BY STORE

Store_101: PASS
All PPE categories stocked and accessible. Training records current.

Store_115: CONDITIONAL PASS
Disposable glove supply depleted (empty box in food prep area). No safety glasses in stockroom.
Action: Restock gloves and safety glasses by April 1, 2025. Confirmed COMPLETED April 2, 2025.

Store_128: MINOR FINDING
Cut-resistant glove sizing: only one size (M) available. No large sizes for fuel technicians.
Action: Order multi-size inventory by March 20, 2025.

Store_133: PASS
All categories compliant. New display stand for PPE near stockroom entrance commended.

Store_145: PASS
All categories compliant. Training records include 2025 refresher sign-off for all employees.

AUDIT CONCLUSION
Minor inventory gaps identified at Store_115 and Store_128. No systemic failures.

Auditor: Sandra Osei    Date: March 28, 2025
""")

# COMMAND ----------

write_doc("safety_training_cert_Employee_2025.txt", """
SAFETY TRAINING COMPLETION RECORD

Document ID: TRAIN-CERT-2025-SAFETY-0047
Document Type: training_certificate
Training Type: OSHA 10-Hour General Industry Safety and Health
Store ID: Store_133
Region: Southeast — Georgia
Employee Name: David Okonkwo
Employee ID: EMP-0047
Position: Senior Sales Associate / Lead Fuel Attendant
Completion Date: February 20, 2025
Expiration Date: February 20, 2028 (3-year validity per RaceTrac policy)
Instructor: OSHA-authorized trainer, SafeServe Foods Inc. Corporate Training Division
Regulation Reference: 29 CFR 1910; OSHA 10 curriculum
Severity: N/A
Status: CERTIFIED

TRAINING MODULES COMPLETED
Module 1: Introduction to OSHA — Worker Rights
Module 2: Walking / Working Surfaces and Fall Prevention
Module 3: Electrical Safety Fundamentals
Module 4: Hazard Communication (GHS/SDS)
Module 5: Personal Protective Equipment
Module 6: Fire Safety and Emergency Evacuation
Module 7: Materials Handling and Ergonomics
Module 8: Environmental Controls
Module 9: Fuel Dispensing Safety (industry-specific)
Module 10: Incident Reporting and Investigation

ASSESSMENT RESULT: PASSED — Score: 88/100

This certificate verifies that David Okonkwo successfully completed the OSHA 10-Hour General
Industry course and demonstrated understanding of all required modules.

Signed: OSHA Authorized Trainer    Date: February 20, 2025
Employee Acknowledgment: David Okonkwo    Date: February 20, 2025
""")

# COMMAND ----------

write_doc("safety_corrective_action_Store128_2025.txt", """
SAFETY CORRECTIVE ACTION PLAN

Document ID: OSHA-CAP-2025-0128
Document Type: corrective_action_plan
Reference Inspection: OSHA-INSP-2025-0128 (March 5, 2025)
Store ID: Store_128
Store Address: 1502 Highway 6 South, Sugar Land, TX 77478
Region: Gulf Coast — Texas
Prepared By: Store Manager — Kevin Nguyen
Submitted: March 7, 2025
Severity: MODERATE
Status: MOSTLY RESOLVED

CORRECTIVE ACTIONS

Action OSHA-CAP-128-001 (Finding OSHA-128-001 — SDS Missing):
SDS for Spartan Chemical #420 (cleaning solvent), Diehard Fuel Stabilizer, and CO2 cylinders
obtained from manufacturer websites and filed in SDS binder.
Completed: March 10, 2025 — CLOSED

Action OSHA-CAP-128-002 (Finding OSHA-128-002 — Exit Sign):
Replacement lithium backup battery installed in exit sign.
Completed: March 6, 2025 — CLOSED

Action OSHA-CAP-128-003 (Finding OSHA-128-003 — Fire Extinguisher):
Annual inspection completed by ABC Fire Equipment Service on March 14, 2025.
All four extinguishers inspected, tagged, and recharged where needed.
Completed: March 14, 2025 — CLOSED

ALL FINDINGS RESOLVED
Store Manager: Kevin Nguyen    Date: March 14, 2025
EHS Coordinator Review: Sandra Osei    Date: March 18, 2025
""")

# COMMAND ----------
# MAGIC %md ## Fuel Operations Documents

# COMMAND ----------

write_doc("fuel_dispenser_inspection_Store101_2025.txt", """
FUEL DISPENSER INSPECTION AND CALIBRATION REPORT

Document ID: FUEL-DISP-2025-0101
Document Type: inspection_report
Inspection Type: Semi-Annual Dispenser Inspection and Calibration
Store ID: Store_101
Store Address: 4821 Peachtree Industrial Blvd, Norcross, GA 30092
Region: Southeast — Georgia
Inspector: Tom Rivera, Certified Weights and Measures Inspector (GA DPS License #WM-4489)
Inspection Date: March 1, 2025
Next Inspection Due: September 1, 2025
Regulation Reference: NFPA 30A; Georgia Weights and Measures Act; 16 CFR Part 680
Severity: LOW
Status: PASS WITH MINOR OBSERVATION

DISPENSERS INSPECTED: 12 dispensers (6 islands, 2 dispensers per island)

Dispenser D-101-01 through D-101-06: PASS — Accuracy within ±6 cubic inches per 5-gallon
  test volume per NIST Handbook 44.

Dispenser D-101-07: MINOR OBSERVATION
  Breakaway hose connection showing wear. No leak observed. Recommend replacement within 60 days.
  Dispenser otherwise accurate. Not removed from service.

Dispenser D-101-08 through D-101-12: PASS

CALIBRATION RESULTS
All 12 dispensers within ±6 cubic inches per 5-gallon test. Mean accuracy: +2.1 cubic inches.

SAFETY EQUIPMENT CHECK
All emergency shutoffs functional. All vapor recovery systems operational.
Canopy lighting fully functional.

REGULATORY COMPLIANCE
Dispenser inspection seals affixed to all 12 units by inspector.
Certificates of inspection available for posting per Georgia law.

Inspector: Tom Rivera    Date: March 1, 2025
""")

# COMMAND ----------

write_doc("fuel_tank_inspection_Store128_2025.txt", """
PETROLEUM STORAGE TANK — ANNUAL INTEGRITY INSPECTION REPORT

Document ID: FUEL-TANK-2025-0128
Document Type: inspection_report
Inspection Type: Third-Party Tank Integrity (Precision) Test
Store ID: Store_128
Store Address: 1502 Highway 6 South, Sugar Land, TX 77478
Region: Gulf Coast — Texas
Inspector: PetroChem Supplies LLC — Licensed Tank Inspector (TCEQ #TX-TANK-8833)
Inspection Date: March 15, 2025
Regulation Reference: 40 CFR Part 280 Subpart D; 30 TAC § 334.46
Severity: HIGH
Status: TANK T-128B FAILED — RELEASE CONFIRMED

TANK INSPECTION SUMMARY

Tank T-128A (Regular Unleaded, 10,000 gal): PASS
  Precision test result: 0.01 gal/hr loss rate. Threshold 0.10 gal/hr. COMPLIANT.

Tank T-128B (Diesel, 8,000 gal): FAILED
  Precision test result: 0.18 gal/hr loss rate. Threshold 0.10 gal/hr. EXCEEDS LIMIT.
  Interpretation: Confirmed release condition. Tank cannot be returned to service.
  Action Required: Tank must be taken out of service immediately. Remediation assessment required.
  TCEQ notification update required within 24 hours.

Tank T-128C (Premium, 8,000 gal): PASS
  Precision test result: 0.03 gal/hr loss rate. COMPLIANT.

POST-TEST ACTIONS
Tank T-128B taken out of service March 15, 2025 (same day as test). Tank emptied and isolated.
TCEQ Site Discovery Report filed March 16, 2025.
Remediation consultant PetroChem Supplies LLC engaged for Phase I Environmental Site Assessment.
Phase I ESA target completion: April 15, 2025.

Inspector: PetroChem Supplies LLC    Date: March 15, 2025
""")

# COMMAND ----------

write_doc("fuel_quality_report_Store101_Q1_2025.txt", """
FUEL QUALITY COMPLIANCE REPORT

Document ID: FUEL-QUAL-2025-Q1-0101
Document Type: audit_report
Report Type: Quarterly Fuel Quality Sampling and Analysis
Store ID: Store_101
Store Address: 4821 Peachtree Industrial Blvd, Norcross, GA 30092
Region: Southeast — Georgia
Sampling Agent: PetroChem Supplies LLC Quality Laboratory
Sampling Date: March 10, 2025
Lab Results Date: March 17, 2025
Regulation Reference: EPA RFG Requirements; ASTM D4814 (gasoline); ASTM D975 (diesel)
Severity: LOW
Status: ALL SAMPLES COMPLIANT

SAMPLES COLLECTED
Sample FUEL-Q1-T101A: Tank T-101A — Regular Unleaded (87 AKI)
Sample FUEL-Q1-T101B: Tank T-101B — Premium Unleaded (93 AKI)
Sample FUEL-Q1-T101C: Tank T-101C — Diesel (ULSD)

LAB RESULTS

Sample FUEL-Q1-T101A (Regular):
  Octane (AKI): 87.2 — PASS (spec: ≥87)
  RVP: 8.1 psi — PASS (summer spec: ≤9.0)
  Sulfur: 8 ppm — PASS (spec: ≤30 ppm)
  Water contamination: None detected

Sample FUEL-Q1-T101B (Premium):
  Octane (AKI): 93.4 — PASS (spec: ≥93)
  RVP: 7.9 psi — PASS
  Sulfur: 6 ppm — PASS
  Water contamination: None detected

Sample FUEL-Q1-T101C (Diesel):
  Cetane Index: 47.2 — PASS (spec: ≥40)
  Sulfur: 10 ppm — PASS ULSD spec (spec: ≤15 ppm)
  Cloud Point: 12°F — PASS (seasonal spec: ≤25°F)
  Water/Sediment: <0.02% — PASS

CONCLUSION: All fuel products at Store 101 meet applicable EPA and ASTM quality specifications.

Lab Director: PetroChem Supplies LLC    Date: March 17, 2025
""")

# COMMAND ----------

write_doc("fuel_corrective_action_Store128_2025.txt", """
FUEL OPERATIONS CORRECTIVE ACTION PLAN — CONFIRMED TANK RELEASE

Document ID: FUEL-CAP-2025-0128
Document Type: corrective_action_plan
Reference Inspection: FUEL-TANK-2025-0128 (March 15, 2025)
Store ID: Store_128
Store Address: 1502 Highway 6 South, Sugar Land, TX 77478
Region: Gulf Coast — Texas
Prepared By: Regional Director — Operations; PetroChem Supplies LLC (Consultant)
Submitted: March 17, 2025
Regulation Reference: 30 TAC § 334 — Petroleum Storage Tank Rules
Severity: HIGH
Status: REMEDIATION IN PROGRESS

INCIDENT SUMMARY
Tank T-128B (8,000 gal diesel) confirmed release at 0.18 gal/hr loss rate. Tank isolated
March 15, 2025. TCEQ notified March 16, 2025. Estimated release volume based on
January–March discrepancy records: 400–600 gallons.

CORRECTIVE ACTIONS

Action FUEL-CAP-128-001: Regulatory Notification
TCEQ Site Discovery Report filed March 16, 2025.
Report No.: TCEQ-SDR-2025-04412

Action FUEL-CAP-128-002: Tank Isolation and Product Transfer
Tank T-128B emptied and isolated March 15. Remaining diesel transferred to emergency tanker.
Diesel sales at Store 128 operating from emergency above-ground supply tank (permitted under
TCEQ emergency permit EP-2025-0128).

Action FUEL-CAP-128-003: Phase I ESA and Remediation Assessment
PetroChem Supplies LLC conducting Phase I ESA and soil/groundwater sampling.
Target completion: April 15, 2025.
If contamination confirmed: Corrective Action Plan (CAP) to be submitted to TCEQ by May 15, 2025.

Action FUEL-CAP-128-004: Tank Replacement
New fiberglass double-wall UST ordered (10,000 gal). Lead time: 8–10 weeks.
Target installation: June 2025 pending TCEQ CAP approval.

Estimated Total Cost: $180,000 – $320,000 (depending on soil remediation scope)

Prepared By: Regional Director of Operations    Date: March 17, 2025
""")

# COMMAND ----------
# MAGIC %md ## Alcohol & Tobacco Compliance Documents

# COMMAND ----------

write_doc("atc_alcohol_license_Store101_2025.txt", """
RETAIL ALCOHOL BEVERAGE LICENSE

Document ID: LIC-ATC-GA-2025-0101
Document Type: license
License Type: Retail Beer and Wine License (Off-Premises Consumption)
Store ID: Store_101
Store Address: 4821 Peachtree Industrial Blvd, Norcross, GA 30092
Region: Southeast — Georgia
Issuing Authority: Gwinnett County Alcohol Control Division
License Number: GC-BWO-2025-1847
Issue Date: January 1, 2025
Expiration Date: December 31, 2025
Regulation Reference: Georgia Code § 3-3; Gwinnett County Code Chapter 4
Severity: N/A
Status: ACTIVE

LICENSE CONDITIONS
1. Sales hours: Monday–Saturday 7:00 AM – 11:45 PM; Sunday 12:30 PM – 11:30 PM.
2. No sales to persons under 21 years of age. Age verification required for all purchases.
   RaceTrac policy: Must verify ID for customers who appear under 40 (company age check policy).
3. No single-serving container sales of malt beverages (county restriction).
4. License must be posted in a visible location within the establishment.

RENEWAL REQUIREMENTS
Renewal application due: October 31, 2025 (60 days prior to expiration).
Required: Background check on designated manager; updated liability insurance certificate.

Annual License Fee Paid: $650
Receipt Number: GC-RCP-2025-0089

Issued By: Gwinnett County Alcohol Control    Date: January 1, 2025
""")

# COMMAND ----------

write_doc("atc_tobacco_license_Store101_2025.txt", """
RETAIL TOBACCO DEALER PERMIT

Document ID: LIC-TOB-GA-2025-0101
Document Type: license
License Type: Retail Tobacco Dealer Permit
Store ID: Store_101
Store Address: 4821 Peachtree Industrial Blvd, Norcross, GA 30092
Region: Southeast — Georgia
Issuing Authority: Georgia Department of Revenue — Alcohol and Tobacco Division
Permit Number: GA-TOB-RTD-2025-44891
Issue Date: January 1, 2025
Expiration Date: December 31, 2025
Regulation Reference: Georgia Code § 48-11; Georgia Rule 560-10-1
Severity: N/A
Status: ACTIVE

AUTHORIZED PRODUCTS
Cigarettes, cigars, smokeless tobacco, e-cigarettes/vaping devices, pipe tobacco.

CONDITIONS
1. No sales to persons under 21 years of age (federal Tobacco 21 law; 21 U.S.C. § 387f(d)).
2. Age verification required for all tobacco product purchases.
3. No self-service tobacco displays (all tobacco must be behind counter or in locked case).
4. FDA retailer registration on file (Registration #FDA-RTL-2024-88442).

RENEWAL: December 15, 2025 renewal deadline.
Annual Permit Fee Paid: $125
Receipt Number: GA-DOR-RCP-2025-0234

Issued By: GA Department of Revenue    Date: January 1, 2025
""")

# COMMAND ----------

write_doc("atc_secret_shopper_Store115_2025.txt", """
SECRET SHOPPER COMPLIANCE AUDIT REPORT — ALCOHOL AND TOBACCO AGE VERIFICATION

Document ID: ATC-SS-2025-0115-02
Document Type: audit_report
Audit Type: Age Verification Compliance — Unannounced Secret Shopper
Store ID: Store_115
Store Address: 7200 W Colonial Dr, Orlando, FL 32818
Region: Southeast — Florida
Auditor: Florida Division of Alcoholic Beverages and Tobacco (ABT) — Compliance Officer
Audit Date: February 28, 2025
Regulation Reference: Florida Statutes § 562.11; § 569.101 (tobacco); 21 U.S.C. § 387f(d)
Severity: CRITICAL
Status: VIOLATION FOUND — LICENSE ACTION POSSIBLE

AUDIT METHODOLOGY
A 20-year-old underage operative (appearance consistent with under-21 individual) attempted to
purchase a 12-pack of beer using a valid, unaltered driver's license showing date of birth
indicating age 20. No ID was requested by the store cashier.

FINDINGS

Violation ATC-115-V001 (CRITICAL):
Store cashier Angela Gomez (Employee ID: EMP-0089) sold a 12-pack of Bud Light to an underage
operative without requesting ID verification.
Purchase amount: $14.99 at 3:42 PM.
Florida Statute § 562.11 requires refusal of alcohol sales to persons under 21.

This is Store 115's SECOND age-verification violation within 18 months.
  Prior violation: August 2023 (ATC-SS-2023-0115-01). Fine of $1,000 imposed.

POTENTIAL CONSEQUENCES (Second Violation within 24 months):
- Fine: Up to $2,500 per violation
- License suspension: 7–30 days
- Mandatory RSVP (Responsible Vendor Program) enrollment

REQUIRED RESPONSE (within 10 days — by March 10, 2025):
1. Submit written explanation and corrective action plan.
2. Confirm disciplinary action taken against employee Angela Gomez.
3. Confirm all employees completed alcohol compliance training.

ABT Case Number: FL-ABT-2025-08812
Auditor: FL ABT Compliance Officer    Date: February 28, 2025
""")

# COMMAND ----------

write_doc("atc_corrective_action_Store115_2025.txt", """
ALCOHOL AND TOBACCO COMPLIANCE CORRECTIVE ACTION PLAN

Document ID: ATC-CAP-2025-0115
Document Type: corrective_action_plan
Reference Audit: ATC-SS-2025-0115-02 (February 28, 2025 secret shopper violation)
Store ID: Store_115
Store Address: 7200 W Colonial Dr, Orlando, FL 32818
Region: Southeast — Florida
Prepared By: District Manager — Carlos Mendez
Submitted: March 7, 2025
Severity: CRITICAL
Status: SUBMITTED TO ABT

CORRECTIVE ACTIONS

Action ATC-CAP-115-001: Employee Discipline
Employee Angela Gomez (EMP-0089) issued formal written warning and placed on probation.
As second age-verification failure at this store, one additional violation within 12 months
will result in termination.
Completed: March 4, 2025

Action ATC-CAP-115-002: Mandatory Retraining — All Staff
All 11 current Store 115 employees completed RSVP (Responsible Vendor Program) alcohol
compliance training on March 6–7, 2025.
Trainer: Florida ABT-approved RSVP instructor
Training records attached. All employees signed acknowledgment form.

Action ATC-CAP-115-003: Point-of-Sale Age Verification Enforcement
POS system updated: Age verification prompt now appears for all alcohol and tobacco scan.
System requires cashier to confirm ID verification before transaction can be completed.
Previously this was a soft prompt; updated to mandatory confirmation step.
IT change deployed: March 6, 2025.

Action ATC-CAP-115-004: RSVP Enrollment
Store 115 enrolled in Florida ABT Responsible Vendor Program.
Enrollment provides reduced penalty exposure for future incidents if program maintained.
Enrollment Number: FL-RSVP-2025-4412.

Submitted By: Carlos Mendez, District Manager    Date: March 7, 2025
""")

# COMMAND ----------

write_doc("atc_state_inspection_Store128_TX_2025.txt", """
TEXAS ALCOHOLIC BEVERAGE COMMISSION COMPLIANCE INSPECTION

Document ID: TABC-INSP-2025-0128
Document Type: inspection_report
Inspection Type: Routine TABC License Verification and Compliance Check
Store ID: Store_128
Store Address: 1502 Highway 6 South, Sugar Land, TX 77478
Region: Gulf Coast — Texas
Inspector: TABC Agent, Houston District
Inspection Date: January 15, 2025
Regulation Reference: Texas Alcoholic Beverage Code; TABC Rule 33.3
Severity: LOW
Status: PASS — FULLY COMPLIANT

LICENSE VERIFIED
License Type: Texas Beer Retailer's Off-Premise License (BF)
License Number: TX-BF-2025-441882
Expiration: December 31, 2025
Status: ACTIVE and POSTED

COMPLIANCE REVIEW

Age Verification: COMPLIANT
  POS system prompts age verification for all alcohol purchases. Date of birth entry required.
  Two mystery shopper tests reviewed — both passed.

Hours of Operation: COMPLIANT
  Sales occurring Monday–Saturday 7 AM–midnight; Sunday noon–midnight. Within TABC allowances.

License Posting: COMPLIANT — license visible at checkout counter.

Product Storage: COMPLIANT — no evidence of unauthorized product or dilution.

Employee Records: COMPLIANT — TABC seller/server training certificates on file for all employees.

INSPECTION RESULT: PASS — NO VIOLATIONS
Next routine inspection: approximately 18 months (July 2026).

TABC Agent (Badge withheld per agency policy)    Date: January 15, 2025
""")

# COMMAND ----------

write_doc("atc_policy_age_verification_2024.txt", """
AGE VERIFICATION AND ALCOHOL/TOBACCO COMPLIANCE POLICY

Document ID: POLICY-ATC-2024-001
Document Type: policy_document
Policy Type: Corporate Compliance Policy — Alcohol and Tobacco Age Verification
Applies To: ALL STORES — ALL EMPLOYEES
Prepared By: RaceTrac Compliance Department
Issue Date: September 1, 2024
Next Review: September 1, 2025
Regulation Reference: 21 U.S.C. § 387f(d) (Tobacco 21); State ABT laws (GA, FL, TX)
Severity: N/A
Status: MANDATORY — ACTIVE

PURPOSE
This policy establishes the mandatory procedures for age verification at all RaceTrac locations
to ensure compliance with federal and state alcohol and tobacco laws.

POLICY STATEMENT
RaceTrac Petroleum, Inc. has a zero-tolerance policy for the sale of alcohol or tobacco products
to persons under the legal age. Any employee who sells alcohol or tobacco to a minor is subject
to immediate termination regardless of circumstances.

AGE VERIFICATION REQUIREMENTS

1. RaceTrac ID Check Policy: Request ID from ANY customer who appears to be under 40 years of age.
   When in doubt, card. If in doubt about doubt, card.

2. Acceptable Forms of ID:
   - Government-issued photo ID (driver's license, state ID, passport, military ID)
   - ID must be valid (not expired)
   - RaceTrac does not accept handwritten, laminated paper, or foreign IDs from unsupported countries

3. Point-of-Sale Process:
   - POS system will prompt for age verification on all alcohol and tobacco scans.
   - Cashier must verify ID and enter customer date of birth to proceed.
   - Transaction cannot be completed without date-of-birth entry.

4. Refusing a Sale:
   - If ID is not presented, appears altered, or customer is visibly intoxicated, REFUSE SALE.
   - Log refusal in daily compliance log.
   - No employee will be disciplined for refusing a sale in good faith.

CONSEQUENCES FOR VIOLATIONS
First violation: Written warning + mandatory retraining.
Second violation: Final written warning + probation.
Third violation: Termination.
Sale to minor resulting in arrest or license action: Immediate termination.

TRAINING
All new employees must complete ATC compliance training before their first solo shift.
All employees must complete annual refresher training.
Training records maintained in HR system.

Approved By: VP of Operations and General Counsel    Date: September 1, 2024
""")

# COMMAND ----------

write_doc("atc_email_Store115_investigation_2025.txt", """
EMAIL THREAD — STORE 115 ABT VIOLATION RESPONSE

Document ID: EMAIL-ATC-2025-0115
Document Type: email_thread
Subject: URGENT: Store 115 ABT Violation — Second Offense
Participants: Carlos Mendez (District Manager), Store 115 Manager Marcus Webb,
              RaceTrac Legal Counsel Sarah Kim, VP Operations Brian Torres
Date Range: February 28 – March 9, 2025
Region: Southeast — Florida
Store ID: Store_115
Severity: CRITICAL
Status: RESOLVED — CAP SUBMITTED

---
FROM: Carlos Mendez <c.mendez@racetrac.com>
TO: Brian Torres, Sarah Kim
DATE: February 28, 2025 5:47 PM
SUBJECT: URGENT: Store 115 ABT Violation — Second Offense

Brian, Sarah —

We received notification from Florida ABT that Store 115 had a second age-verification violation
today. An ABT undercover operative purchased alcohol without ID check. This is the second violation
within 18 months. We are at risk of license suspension.

I am heading to the store now. Will assess and have a preliminary plan by tomorrow morning.

Carlos

---
FROM: Sarah Kim <s.kim@racetrac.com>
TO: Carlos Mendez, Brian Torres
DATE: March 1, 2025 8:12 AM
SUBJECT: RE: URGENT: Store 115 ABT Violation — Second Offense

Carlos —

I've reviewed the ABT file. Consequences for second violation within 24 months:
- Mandatory RSVP enrollment (we should do this regardless)
- Fine $1,000–$2,500
- Possible 7–30 day suspension (ABT has discretion)

To maximize our chance of avoiding suspension:
1. Submit comprehensive CAP within 10 days
2. Enroll in RSVP program proactively
3. Document all corrective actions with timestamps

I recommend we also update the POS system to make the ID confirmation mandatory (currently
it's a soft prompt that employees can bypass). This is our strongest mitigation argument.

Sarah Kim, Legal Counsel

---
FROM: Marcus Webb <m.webb@racetrac.com>
TO: Carlos Mendez
DATE: March 3, 2025 2:15 PM
SUBJECT: RE: Store 115 — Employee Actions Taken

Carlos —

I've completed the following:
- Angela Gomez issued formal written warning today. She is devastated but understands the
  seriousness. I've placed her on probation as discussed.
- Mandatory staff meeting held this morning. All 11 employees reminded of policy.
- IT confirmed POS update will be deployed Thursday March 6.

I'm ready for the RSVP training sessions scheduled Thursday/Friday.

Marcus

---
FROM: Carlos Mendez <c.mendez@racetrac.com>
TO: Sarah Kim, Brian Torres
DATE: March 9, 2025 4:30 PM
SUBJECT: CAP Submitted to ABT

Team —

Corrective Action Plan submitted to ABT today. All four actions completed and documented.
RSVP enrollment confirmed. POS mandatory age check deployed.

Sarah, please review the filed CAP (attached) and advise if you need anything additional for
our ABT defense file. I believe we have a strong case to avoid suspension given the speed
and comprehensiveness of our response.

Carlos
""")

# COMMAND ----------
# MAGIC %md ## Vendor Compliance Documents

# COMMAND ----------

write_doc("vendor_insurance_cert_PetroChem_2025.txt", """
CERTIFICATE OF LIABILITY INSURANCE

Document ID: VEN-INS-2025-PETROCHEM
Document Type: vendor_certification
Certificate Type: Certificate of Liability Insurance
Vendor Name: PetroChem Supplies LLC
Vendor ID: VEN-0012
Store Coverage: ALL RACETRAC STORES — Southeast and Gulf Coast Regions
Region: Southeast + Gulf Coast
Certificate Holder: RaceTrac Petroleum, Inc., 200 Galleria Pkwy SE, Atlanta, GA 30339
Issue Date: January 1, 2025
Expiration Date: December 31, 2025
Regulation Reference: RaceTrac Vendor Requirements; State Contractor Licensing Laws
Severity: N/A
Status: ACTIVE AND CURRENT

COVERAGE SUMMARY

Commercial General Liability:
  Insurer: Travelers Casualty and Surety Company
  Policy Number: TRV-CGL-2025-8847221
  Each Occurrence: $1,000,000
  General Aggregate: $2,000,000
  Products/Completed Operations: $2,000,000

Commercial Auto Liability:
  Each Occurrence: $1,000,000
  Covers: All owned, hired, non-owned vehicles used in service delivery

Workers' Compensation:
  Coverage: Statutory limits per state
  Employer's Liability: $500,000 / $500,000 / $500,000

Environmental Liability (Pollution Liability):
  Each Occurrence: $2,000,000
  Aggregate: $4,000,000
  Critical for UST services

CERTIFICATE HOLDER IS ADDITIONAL INSURED on all above policies.

CONTACT: PetroChem Supplies LLC Risk Management — risk@petrochemsupplies.com
Agent: Marsh & McLennan Companies    Issued: January 1, 2025
""")

# COMMAND ----------

write_doc("vendor_contract_CleanFleet_2025.txt", """
VENDOR SERVICE AGREEMENT — FLEET CLEANING AND FACILITY MAINTENANCE

Document ID: VEN-CONTRACT-2025-CLEANFLEET
Document Type: vendor_certification
Contract Type: Master Services Agreement
Vendor Name: CleanFleet Solutions, Inc.
Vendor ID: VEN-0031
Store Coverage: Store_101, Store_115, Store_128, Store_133, Store_145 and additional SE locations
Region: Southeast
Contract Effective: January 1, 2025
Contract Expiration: December 31, 2026
Regulation Reference: RaceTrac Vendor Standards; OSHA cleaning chemical requirements
Severity: N/A
Status: ACTIVE

SCOPE OF SERVICES
- Monthly exterior facility cleaning (canopy, pavement, fuel islands)
- Quarterly interior deep cleaning (restrooms, food service area, stockroom)
- Fuel island degreasing (quarterly or as-needed)
- Spill kit restocking (monthly check and replenishment)

COMPLIANCE REQUIREMENTS AGREED BY VENDOR
1. All CleanFleet employees working at RaceTrac locations must pass background check.
2. All cleaning chemicals must have SDS on file with RaceTrac EHS Team before use.
3. CleanFleet must maintain current Certificate of Insurance (minimum $1M CGL).
4. Supervisor on-site for all quarterly deep cleans.

SERVICE LEVEL AGREEMENT
Monthly exterior cleaning: Completed by 10th of each month.
Response to emergency spill cleanup request: Within 4 hours.
Quarterly deep clean scheduling: Coordinated with store manager 2 weeks in advance.

INSURANCE ON FILE: CleanFleet COI expires December 31, 2025. Renewal required.

Signed: CleanFleet Solutions, Inc. (signature on file)
Signed: RaceTrac Petroleum, Inc. (signature on file)
Effective: January 1, 2025
""")

# COMMAND ----------

write_doc("vendor_food_cert_SafeServe_2025.txt", """
FOOD SAFETY CERTIFICATION — VENDOR QUALIFICATION

Document ID: VEN-FOOD-CERT-2025-SAFESERVE
Document Type: vendor_certification
Certification Type: Third-Party Food Safety Vendor Approval
Vendor Name: SafeServe Foods Inc.
Vendor ID: VEN-0007
Products Supplied: Hot food items — taquitos, tornados, hot dogs, breakfast sandwiches
Store Coverage: All RaceTrac Southeast and Gulf Coast Locations
Region: National
Certification Body: NSF International — Food Safety Division
Issue Date: February 1, 2025
Expiration Date: January 31, 2026
Regulation Reference: FDA 21 CFR Part 110; FSMA; SQF Level 2
Severity: N/A
Status: ACTIVE — FULLY QUALIFIED

CERTIFICATION BASIS
SafeServe Foods Inc. manufacturing facility (Memphis, TN) successfully completed:
1. SQF (Safe Quality Food) Level 2 Audit — Score: 93/100 (Excellent)
   Auditor: NSF International Certified Auditor
   Audit Date: January 15–16, 2025
2. FDA facility registration current (Registration #FDA-MFG-2025-44218)
3. FSMA Preventive Controls for Human Food — documented and implemented
4. RaceTrac third-party supplier questionnaire completed and approved

PRODUCT RECALLS IN PAST 2 YEARS: None

TRACEABILITY
SafeServe maintains lot-level traceability from raw ingredient to finished product.
Lot traceability records available to RaceTrac within 2 hours of request.

APPROVED PRODUCT LIST
- Tornado Taquitos (chicken, beef, pepperoni)
- Franks — Classic and Jalapeno Cheddar
- Breakfast Rollups (egg and cheese, sausage and egg)
- Breakfast Hot Dogs

Certification Issued By: NSF International    Date: February 1, 2025
""")

# COMMAND ----------

write_doc("vendor_audit_CleanFleet_2025.txt", """
VENDOR COMPLIANCE AUDIT REPORT

Document ID: VEN-AUDIT-2025-CLEANFLEET
Document Type: audit_report
Audit Type: Annual Vendor Compliance Audit
Vendor Name: CleanFleet Solutions, Inc.
Vendor ID: VEN-0031
Audit Scope: Service quality, chemical compliance, employee training, insurance
Region: Southeast
Auditor: Sandra Osei, Regional EHS Coordinator
Audit Date: March 20, 2025
Regulation Reference: RaceTrac Vendor Standards v2.4; 29 CFR 1910.1200
Severity: MODERATE
Status: CONDITIONAL PASS — FINDINGS REQUIRE FOLLOW-UP

AUDIT FINDINGS

Finding VEN-CF-001 (MODERATE):
CleanFleet is using a new floor degreaser product (ZAP Industrial Cleaner) at store locations
without first submitting the SDS to RaceTrac EHS for approval. Requirement per vendor agreement
Section 3.2.
Action Required: Submit SDS for ZAP Industrial Cleaner by April 3, 2025. Discontinue use at
RaceTrac locations until approved.

Finding VEN-CF-002 (LOW):
CleanFleet supervisor was not present during February deep clean at Store 128 (per contract
requirement). Store 128 cleaning report signed by junior technician only.
Action Required: Confirm supervisor accompanies all future quarterly deep cleans.

POSITIVE OBSERVATIONS
- Insurance certificate current (COI confirmed valid through December 31, 2025)
- Background check records complete for all 14 CleanFleet employees serving RaceTrac
- Monthly exterior cleaning completed on-time for all 5 stores in audit sample

OVERALL ASSESSMENT: CONDITIONAL PASS
CleanFleet has been a reliable vendor for 3 years. Minor compliance gap on chemical approval
process. No safety incidents.

Auditor: Sandra Osei    Date: March 20, 2025
""")

# COMMAND ----------

write_doc("vendor_email_insurance_renewal_2025.txt", """
EMAIL THREAD — VENDOR INSURANCE RENEWAL TRACKING

Document ID: EMAIL-VEN-2025-INS-RENEWAL
Document Type: email_thread
Subject: Vendor COI Renewal Tracking — Q1 2025
Participants: Sandra Osei (Regional EHS), Procurement Team, CleanFleet Solutions, SafeServe Foods
Date Range: January 5 – March 15, 2025
Region: Southeast
Store ID: ALL
Severity: LOW
Status: MOSTLY CURRENT — MINOR FOLLOW-UP PENDING

---
FROM: Sandra Osei <s.osei@racetrac.com>
TO: Procurement Team
DATE: January 5, 2025 9:00 AM
SUBJECT: Vendor COI Renewal Tracking — Q1 2025

Team —

Per annual process, please verify COIs from all active vendors are current for 2025.
Vendors expiring December 31, 2024 need renewals immediately. Flagging three vendors
that were on my watch list:
  1. PetroChem Supplies LLC — COI due January 1
  2. CleanFleet Solutions — COI due January 1
  3. SafeServe Foods Inc. — Food safety cert due February 1

Please obtain renewed certificates and file in the vendor compliance portal.

Sandra

---
FROM: Procurement Team <procurement@racetrac.com>
TO: Sandra Osei
DATE: January 12, 2025 11:30 AM
SUBJECT: RE: Vendor COI Renewal Tracking

Sandra —

Update:
- PetroChem Supplies LLC: Renewed COI received and filed January 8. Valid through Dec 31, 2025.
- CleanFleet Solutions: COI received and filed January 10. Valid through Dec 31, 2025.
- SafeServe Foods Inc.: SQF audit scheduled January 15–16. Cert expected by Feb 1.

One additional item: Orkin Commercial Services (pest control for SE stores) COI was NOT
renewed. They transitioned to a new insurer and are 2 weeks behind on issuing updated cert.
Orkin services at Store 115 and Store 128 are proceeding but without current COI on file.
Should we pause services?

---
FROM: Sandra Osei <s.osei@racetrac.com>
TO: Procurement Team
DATE: January 13, 2025 8:45 AM
SUBJECT: RE: Vendor COI Renewal Tracking

Please contact Orkin account manager and give them until January 31 to provide updated COI.
Do not pause services but flag this as a compliance risk. If not received by Jan 31, we escalate
to VP Operations.

Update: Orkin COI received March 5, 2025. Filed in portal. Issue resolved.

Sandra
""")

# COMMAND ----------
# MAGIC %md ## Additional Policy and Permit Documents

# COMMAND ----------

write_doc("permit_ust_operating_Store101_2025.txt", """
UNDERGROUND STORAGE TANK OPERATING PERMIT

Document ID: PERMIT-UST-GA-2025-0101
Document Type: permit
Permit Type: UST Operating Permit — Annual Renewal
Store ID: Store_101
Store Address: 4821 Peachtree Industrial Blvd, Norcross, GA 30092
Region: Southeast — Georgia
Issuing Authority: Georgia Environmental Protection Division — Underground Storage Tank Program
Permit Number: GA-UST-PERM-2025-04412
Issue Date: January 1, 2025
Expiration Date: December 31, 2025
Regulation Reference: Georgia Rules for Underground Storage Tanks Chapter 391-3-15; 40 CFR Part 280
Severity: N/A
Status: ACTIVE

TANKS AUTHORIZED UNDER THIS PERMIT
Tank ID: T-101A — Type: FRP double-wall — Capacity: 10,000 gal — Product: Regular Unleaded
Tank ID: T-101B — Type: FRP double-wall — Capacity: 10,000 gal — Product: Premium Unleaded
Tank ID: T-101C — Type: FRP double-wall — Capacity: 8,000 gal — Product: ULSD Diesel

PERMIT CONDITIONS
1. Annual compliance inspection required (conducted by Georgia EPD certified inspector).
2. Monthly release detection monitoring required; records maintained for minimum 3 years.
3. Overfill prevention device, spill prevention equipment, and corrosion protection required on all tanks.
4. Operator training: Class A, B, and C operators must be current as required by 40 CFR § 280.245.
5. Any confirmed or suspected release must be reported to Georgia EPD within 24 hours.

RENEWAL: Submit renewal application by October 31, 2025.
Annual Permit Fee: $450 per tank ($1,350 total)
Receipt: GA-EPD-RCP-2025-UST-0099

Issued By: Georgia Environmental Protection Division    Date: January 1, 2025
""")

# COMMAND ----------

write_doc("permit_food_service_Store115_2025.txt", """
FOOD SERVICE ESTABLISHMENT PERMIT

Document ID: PERMIT-FOOD-FL-2025-0115
Document Type: permit
Permit Type: Food Service Establishment Permit — Annual Renewal
Store ID: Store_115
Store Address: 7200 W Colonial Dr, Orlando, FL 32818
Region: Southeast — Florida
Issuing Authority: Orange County Health Department — Environmental Health Division
Permit Number: OC-FSE-2025-08812
Issue Date: January 1, 2025
Expiration Date: December 31, 2025
Regulation Reference: Florida Administrative Code 64E-11; FDA Food Code 2022
Severity: N/A
Status: ACTIVE — SUBJECT TO COMPLIANCE CONDITIONS

ESTABLISHMENT DESCRIPTION
Type: Limited food service — hot food (roller grill, hot holding), fountain beverages, packaged foods.
Seating: None (convenience retail — no dine-in).
Food employees: 8–12 per location.

PERMIT CONDITIONS
1. Certified Food Manager (CFM) must be on-site or on-call during all operating hours.
   CFM must be re-certified if certification lapses.
2. All food handlers must complete food handler training within 30 days of hire.
3. Establishment must maintain and follow a written food safety plan (HACCP or equivalent).
4. All refrigeration units must maintain ≤41°F. Temperature logs required.
5. Pest control service contract on file and current.

NOTE: This permit is currently under review following failed inspection on January 22, 2025
(Inspection ID: FOOD-INSP-2025-0115-A). Mandatory re-inspection by February 22, 2025.
Permit status will be revised following re-inspection results.

Renewal: October 31, 2025
Annual Fee Paid: $275
Receipt: OC-HD-RCP-2025-0412

Issued By: Orange County Health Department    Date: January 1, 2025
""")

# COMMAND ----------

write_doc("permit_ust_operating_Store128_TX_2025.txt", """
PETROLEUM STORAGE TANK PERMIT

Document ID: PERMIT-UST-TX-2025-0128
Document Type: permit
Permit Type: Petroleum Storage Tank Registration and Operating Permit
Store ID: Store_128
Store Address: 1502 Highway 6 South, Sugar Land, TX 77478
Region: Gulf Coast — Texas
Issuing Authority: Texas Commission on Environmental Quality (TCEQ) — PST Division
Permit Number: TCEQ-PST-2025-77478-0128
Issue Date: January 1, 2025
Expiration Date: December 31, 2025
Regulation Reference: Texas Administrative Code Title 30, Chapter 334; 40 CFR Part 280
Severity: N/A
Status: CONDITIONALLY ACTIVE — TANK T-128B UNDER ENFORCEMENT ACTION

TANKS REGISTERED
Tank T-128A: FRP double-wall, 10,000 gal, Regular Unleaded — ACTIVE
Tank T-128B: FRP double-wall, 8,000 gal, Diesel — OUT OF SERVICE (confirmed release March 15, 2025)
Tank T-128C: FRP double-wall, 8,000 gal, Premium Unleaded — ACTIVE

ENFORCEMENT NOTATION
Tank T-128B removed from service March 15, 2025 following confirmed release (see TCEQ Site
Discovery Report SDR-2025-04412). Tank T-128B permit is suspended pending corrective action.
Site assessment and Corrective Action Plan required per 30 TAC § 334.

PERMIT CONDITIONS (remaining tanks)
1. Monthly release detection monitoring required for T-128A and T-128C.
2. Annual compliance inspection required.
3. TCEQ operator certifications (Class A/B/C) must be current.
4. Corrective Action Plan for T-128B must be submitted by May 15, 2025.

Annual Fee: $350 per active tank
Receipt: TCEQ-FEE-2025-0128-PST

Issued By: TCEQ Petroleum Storage Tank Division    Date: January 1, 2025
AMENDED: March 18, 2025 (T-128B enforcement notation added)
""")

# COMMAND ----------

write_doc("policy_compliance_program_2024.txt", """
ENTERPRISE COMPLIANCE PROGRAM POLICY

Document ID: POLICY-COMP-2024-001
Document Type: policy_document
Policy Type: Enterprise Compliance Program — Master Policy
Applies To: ALL STORES, DISTRICTS, REGIONS — RaceTrac Petroleum, Inc.
Prepared By: RaceTrac Legal and Compliance Department
Issue Date: October 1, 2024
Next Review: October 1, 2025
Regulation Reference: All applicable federal and state environmental, food safety, safety, and
                      alcohol/tobacco regulations
Severity: N/A
Status: MANDATORY — ACTIVE

POLICY STATEMENT
RaceTrac Petroleum, Inc. is committed to full compliance with all applicable laws and regulations
across all operational areas. This policy establishes the framework for the enterprise compliance
program and the responsibilities of all personnel.

COMPLIANCE DOMAINS
This program covers:
1. Environmental Compliance (UST, SPCC, air, stormwater)
2. Food Safety Compliance (health codes, HACCP, FDA)
3. Workplace Safety (OSHA, workers' compensation)
4. Fuel Operations (weights and measures, tank integrity)
5. Alcohol and Tobacco (ABC/ATB licensing, age verification)
6. Vendor and Contractor Management

ORGANIZATIONAL STRUCTURE
Chief Compliance Officer: Reports to General Counsel
Regional EHS Coordinators: Sandra Osei (Southeast/Gulf Coast)
District Managers: First-line compliance responsibility for their stores
Store Managers: Day-to-day compliance execution

KEY COMPLIANCE OBLIGATIONS

Inspections and Audits:
- Respond to all regulatory inspections cooperatively and professionally.
- Submit corrective action plans within required timeframes.
- Never misrepresent conditions to inspectors.

Recordkeeping:
- Maintain all required records per retention schedules.
- Records must be available for regulatory review within 24 hours.

Incident Reporting:
- Environmental releases: Report within 24 hours to appropriate agency.
- Workplace injuries: OSHA 300 log maintained. Serious injuries reported within 8 hours.
- Food safety incidents: Notify Health Department and Regional EHS within 2 hours.

TRAINING REQUIREMENTS
All employees: Annual compliance awareness training (online, 30 minutes).
Store managers: Comprehensive compliance training (8 hours) upon appointment and annually.
Regional coordinators: Advanced compliance certification maintained.

NON-RETALIATION
RaceTrac strictly prohibits retaliation against any employee who reports a compliance concern
in good faith. Violations of this policy are grounds for termination.

Approved By: General Counsel and CEO    Date: October 1, 2024
""")

# COMMAND ----------

write_doc("training_cert_food_safety_Store115_2025.txt", """
FOOD HANDLER TRAINING COMPLETION RECORD

Document ID: TRAIN-CERT-2025-FOOD-0115-BATCH
Document Type: training_certificate
Training Type: Food Handler Safety Certification (ServSafe Food Handler)
Store ID: Store_115
Store Address: 7200 W Colonial Dr, Orlando, FL 32818
Region: Southeast — Florida
Training Date: March 6–7, 2025
Instructor: SafeServe Foods Inc. Corporate Training Division (Florida Approved Provider)
Regulation Reference: Florida Administrative Code 64E-11.003; FDA Food Code 2022
Severity: N/A
Status: COMPLETED — ALL EMPLOYEES CERTIFIED

EMPLOYEES CERTIFIED

Name: Marcus Webb (Store Manager) — Certificate #SSEC-2025-0115-001
  Exam Score: 91/100 — PASSED    Expiration: March 6, 2028

Name: Angela Gomez (Sales Associate) — Certificate #SSEC-2025-0115-002
  Exam Score: 84/100 — PASSED    Expiration: March 6, 2028

Name: Robert Kim (Sales Associate) — Certificate #SSEC-2025-0115-003
  Exam Score: 88/100 — PASSED    Expiration: March 6, 2028

Name: Diana Reyes (Lead Cashier) — Certificate #SSEC-2025-0115-004
  Exam Score: 90/100 — PASSED    Expiration: March 7, 2028

Name: Carlos Vega (Fuel Attendant) — Certificate #SSEC-2025-0115-005
  Exam Score: 82/100 — PASSED    Expiration: March 7, 2028

Name: Yuki Tanaka (Sales Associate) — Certificate #SSEC-2025-0115-006
  Exam Score: 87/100 — PASSED    Expiration: March 7, 2028

NOTE: Training conducted as corrective action following failed health inspection (FOOD-INSP-2025-0115-A)
and ABT age verification violation (ATC-SS-2025-0115-02).

Certificates submitted to Orange County Health Department and Florida ABT as supporting documentation
for corrective action plans.

Instructor Certification: SafeServe Foods Inc.    Date: March 7, 2025
""")

# COMMAND ----------

write_doc("training_cert_osha_Store133_2025.txt", """
OSHA HAZARD COMMUNICATION TRAINING RECORD

Document ID: TRAIN-CERT-2025-HAZCM-0133
Document Type: training_certificate
Training Type: OSHA Hazard Communication Standard (GHS) — Annual Refresher
Store ID: Store_133
Store Address: 290 Crossroads Pkwy, Savannah, GA 31407
Region: Southeast — Georgia
Training Date: January 30, 2025
Instructor: Sandra Osei, Regional EHS Coordinator
Regulation Reference: 29 CFR 1910.1200 (Hazard Communication Standard)
Severity: N/A
Status: ALL EMPLOYEES CURRENT

TRAINING CONTENT
- GHS hazard classification and labeling (pictograms, signal words, hazard statements)
- How to read and use Safety Data Sheets (SDS)
- Chemicals used at RaceTrac stores: cleaning solvents, fuel, CO2 (fountain), refrigerants
- Proper handling, storage, and disposal of hazardous materials
- Emergency response: spill response, first aid, evacuation

EMPLOYEES TRAINED

Store 133 employees (8 total) — all completed annual HazCom refresher:
Patricia Owens (SM), Jamal Williams, Lucy Park, Michael Torres, Sam Butler,
Destiny Williams, Henry Kim, Rosa Garza.

All employees acknowledged understanding and signed training roster (on file).

Next training due: January 2026

Instructor: Sandra Osei    Date: January 30, 2025
""")

# COMMAND ----------

write_doc("risk_assessment_Store145_2025.txt", """
STORE COMPLIANCE RISK ASSESSMENT

Document ID: RISK-ASSESS-2025-0145
Document Type: audit_report
Assessment Type: Annual Compliance Risk Profile
Store ID: Store_145
Store Address: 8850 Gulf Freeway, Webster, TX 77598
Region: Gulf Coast — Texas
Assessor: Sandra Osei, Regional EHS Coordinator
Assessment Date: March 25, 2025
Regulation Reference: RaceTrac Enterprise Compliance Program (POLICY-COMP-2024-001)
Severity: LOW
Status: LOW RISK — FULLY COMPLIANT

RISK SCORING METHODOLOGY
Domains scored 1–5 (5=highest risk). Overall composite risk score calculated.

DOMAIN SCORES

Environmental (UST/SPCC):
  UST permit current: YES
  Last inspection: January 2025 — PASS
  ATG operational: YES
  No release history: YES
  Score: 1 (LOW RISK)

Food Safety:
  Health inspection — last score: 97/100 (October 2024) — PASS
  CFM on staff: YES (certified through January 2027)
  Walk-in cooler <41°F: YES
  Score: 1 (LOW RISK)

OSHA/Safety:
  Last safety inspection: February 2025 — PASS, no findings
  OSHA 300 log: 0 recordable incidents in 2024
  PPE audit Q1 2025: PASS
  Score: 1 (LOW RISK)

Fuel Operations:
  Dispenser calibration: January 2025 — PASS
  Tank inspection: February 2025 — PASS
  Score: 1 (LOW RISK)

Alcohol/Tobacco:
  TABC license current: YES (TX-BF-2025-441889, expires Dec 31, 2025)
  Age verification violations in past 24 months: 0
  Secret shopper test (Jan 2025): PASSED
  Score: 1 (LOW RISK)

Vendor Compliance:
  All active vendor COIs current
  Score: 1 (LOW RISK)

OVERALL COMPOSITE RISK SCORE: 1.0 / 5.0 — LOW RISK

CONCLUSION
Store 145 is a model compliance store. Zero open findings across all domains.
Recommend Store 145 as a benchmark for district-level best practices training.

Assessor: Sandra Osei    Date: March 25, 2025
""")

# COMMAND ----------

write_doc("risk_assessment_Store115_2025.txt", """
STORE COMPLIANCE RISK ASSESSMENT

Document ID: RISK-ASSESS-2025-0115
Document Type: audit_report
Assessment Type: Compliance Risk Profile — Post-Violation Review
Store ID: Store_115
Store Address: 7200 W Colonial Dr, Orlando, FL 32818
Region: Southeast — Florida
Assessor: Sandra Osei, Regional EHS Coordinator + Carlos Mendez, District Manager
Assessment Date: March 10, 2025
Regulation Reference: RaceTrac Enterprise Compliance Program (POLICY-COMP-2024-001)
Severity: HIGH
Status: HIGH RISK — ENHANCED MONITORING REQUIRED

DOMAIN SCORES

Environmental (UST/SPCC):
  UST permit current: YES (FL-FDEP-2025-0115)
  Last inspection: December 2024 — PASS
  Score: 1 (LOW RISK)

Food Safety:
  Health inspection January 2025: FAILED (score 71/100) — walk-in cooler failure, pest activity
  Re-inspection result February 2025: PASS (score 89/100) — corrective actions completed
  Prior failed inspection history: 1 failure in past 18 months
  Score: 4 (HIGH RISK — prior pattern and recent failure)

OSHA/Safety:
  Last safety inspection: January 2025 — PASS
  OSHA 300 log: 1 recordable incident in 2024 (slip and fall, minor)
  Score: 2 (MODERATE RISK)

Fuel Operations:
  Dispenser calibration: December 2024 — PASS
  Tank inspection: December 2024 — PASS
  Score: 1 (LOW RISK)

Alcohol/Tobacco:
  ABT license current but under review (second age-verification violation February 2025)
  RSVP program enrolled — mitigating factor
  Corrective action plan submitted and accepted by ABT
  Score: 5 (CRITICAL RISK — second violation, license action possible)

Vendor Compliance:
  All COIs current
  Score: 1 (LOW RISK)

OVERALL COMPOSITE RISK SCORE: 2.3 / 5.0 — ELEVATED RISK

CORRECTIVE MONITORING PLAN
Enhanced monitoring requirements for Store 115 for next 12 months:
- Monthly District Manager store visit (vs. quarterly standard)
- Secret shopper test quarterly (vs. annually)
- Food safety temperature log reviewed bi-weekly
- ABT compliance status reviewed monthly

Next risk re-assessment: September 10, 2025

Assessors: Sandra Osei, Carlos Mendez    Date: March 10, 2025
""")

# COMMAND ----------

write_doc("env_spcc_policy_2024.txt", """
ENVIRONMENTAL COMPLIANCE POLICY — UST AND SPCC

Document ID: POLICY-ENV-2024-002
Document Type: policy_document
Policy Type: Environmental Compliance — UST Operations and SPCC
Applies To: ALL STORES with UST operations
Prepared By: RaceTrac Environmental Compliance Team
Issue Date: March 1, 2024
Next Review: March 1, 2026
Regulation Reference: 40 CFR Parts 112 and 280; State UST regulations (GA, FL, TX)
Severity: N/A
Status: MANDATORY — ACTIVE

POLICY OBJECTIVES
1. Ensure all underground storage tanks are operated in full compliance with EPA and state regulations.
2. Prevent spills, leaks, and releases through proactive maintenance and monitoring.
3. Respond quickly and effectively to any release or suspected release.

KEY REQUIREMENTS

Class C Operator Responsibilities (Store Managers):
- Conduct daily walkthrough of UST equipment and complete daily inspection checklist.
- Respond immediately to ATG alarms. Escalate unresolved alarms to District Manager within 4 hours.
- Maintain release detection records for minimum 3 years.
- Do not accept fuel delivery if spill containment basins are damaged or full.

Class B Operator Responsibilities (District Managers):
- Ensure annual compliance inspections are scheduled.
- Review monthly ATG monitoring summaries.
- Ensure SPCC plans are current and available on-site.

Release Reporting Protocol:
- Any confirmed or suspected release: Contact Regional EHS Coordinator immediately.
- If release to water or evidence of off-site migration: Contact EPA Region IV or state agency
  within 24 hours (or applicable state deadline).
- Environmental consultant (PetroChem Supplies LLC) to be engaged for remediation assessment.

ANNUAL COMPLIANCE CALENDAR
January: Renew UST operating permits (all states)
March–April: Annual UST inspections (GA stores); April–May (FL stores); January–March (TX stores)
June: Annual review of SPCC plans
October: UST permit renewal applications due
December: Year-end ATG summary review

Approved By: Chief Compliance Officer    Date: March 1, 2024
""")

# COMMAND ----------

write_doc("food_email_reinspection_Store115_2025.txt", """
EMAIL THREAD — STORE 115 HEALTH INSPECTION FOLLOW-UP

Document ID: EMAIL-FOOD-2025-0115-REINSP
Document Type: email_thread
Subject: Store 115 Health Inspection Results and Re-inspection Scheduling
Participants: Carlos Mendez (District Manager), Marcus Webb (Store 115 Manager),
              Orange County Health Dept (Inspector James Kowalski), Priya Nair (Corporate Food Safety)
Date Range: January 22 – February 23, 2025
Region: Southeast — Florida
Store ID: Store_115
Severity: HIGH
Status: RESOLVED

---
FROM: James Kowalski <j.kowalski@ocfl.net>
TO: Carlos Mendez
DATE: January 22, 2025 5:30 PM
SUBJECT: Store 115 Inspection Results — Score 71 — Re-inspection Required

Mr. Mendez —

Please find attached the inspection report for RaceTrac Store 115 conducted today. The store
received a score of 71/100 with three Priority violations including:
1. Walk-in cooler temperature at 48°F (>41°F required)
2. Pest activity observed (mouse droppings)
3. No Certified Food Manager on premises

Re-inspection is mandatory and will occur on February 22, 2025. The store must demonstrate
all three Priority violations have been resolved. Failure to achieve 70+ may result in permit action.

James Kowalski, Orange County Environmental Health

---
FROM: Priya Nair <p.nair@racetrac.com>
TO: Carlos Mendez
DATE: January 23, 2025 8:00 AM
SUBJECT: RE: Store 115 — Corporate Food Safety Response

Carlos —

I've reviewed the inspection report. Three items are concerning:
1. Walk-in cooler failure: Mechanical issue must be repaired ASAP. Until repaired, no raw or
   perishable product should be stored there. Use temporary unit if available.
2. Pest activity: This is the most urgent. Orkin must be on-site today. I'm escalating this
   within the company as this creates potential PR and liability exposure.
3. CFM: Marcus needs to be enrolled in ServSafe manager course immediately.

Please confirm actions taken by COB today.

Priya Nair, Corporate Food Safety Manager

---
FROM: Carlos Mendez <c.mendez@racetrac.com>
TO: Priya Nair, Marcus Webb
DATE: January 28, 2025 4:15 PM
SUBJECT: Store 115 Corrective Action Update

Priya —

All actions completed per corrective action plan:
1. Walk-in compressor replaced January 27 — verified at 38°F.
2. Orkin treatment and entry-point sealing January 24 — clean inspection by Orkin January 28.
3. Marcus enrolled in ServSafe — exam February 5.

CAP filed with OC Health January 28. Re-inspection is February 22.

---
FROM: James Kowalski <j.kowalski@ocfl.net>
TO: Carlos Mendez
DATE: February 22, 2025 6:00 PM
SUBJECT: Store 115 Re-inspection — PASSED

Mr. Mendez —

Re-inspection conducted today. Score: 89/100. All three Priority violations have been
resolved satisfactorily. Store 115 remains in good standing.

James Kowalski
""")

# COMMAND ----------

write_doc("vendor_insurance_alert_Orkin_2025.txt", """
VENDOR COMPLIANCE ALERT — EXPIRED CERTIFICATE OF INSURANCE

Document ID: VEN-ALERT-2025-ORKIN
Document Type: vendor_certification
Alert Type: Expired COI — Vendor Service Continuation Risk
Vendor Name: Orkin Commercial Services (pest control)
Vendor ID: VEN-0044
Stores Affected: Store_115, Store_128, Store_133 (Southeast pest control contract)
Region: Southeast
Date of Alert: January 13, 2025
Resolved Date: March 5, 2025
Regulation Reference: RaceTrac Vendor Standards v2.4 — Insurance Requirements
Severity: MODERATE
Status: RESOLVED

ALERT DETAILS
Orkin Commercial Services' Certificate of Insurance expired December 31, 2024.
Orkin transitioned to a new insurer (Liberty Mutual from Travelers) in Q4 2024 and was
late issuing updated COI documentation.

Period of non-coverage: January 1, 2025 – March 5, 2025 (64 days).

Services provided during lapse:
- January 2025 monthly service at Store_115: Completed January 14 (no COI on file)
- January 2025 monthly service at Store_128: Completed January 20 (no COI on file)
- Emergency treatment at Store_115: Completed January 24 after failed health inspection

RISK ASSESSMENT
Services performed during lapse create potential uninsured contractor liability risk.
No incidents occurred during this period.

RESOLUTION
Updated COI received March 5, 2025: Liberty Mutual Policy #LM-CGL-2025-882144.
Coverage: CGL $1M per occurrence; Workers' Comp statutory limits.
Valid: January 1, 2025 – December 31, 2025 (backdated to align with contract year).
Filed in vendor compliance portal March 5, 2025.

PREVENTION
Vendor COI expiration dates added to RaceTrac compliance calendar with 60-day advance alerts.

Reported By: Sandra Osei    Date: March 5, 2025
""")

# COMMAND ----------
# MAGIC %md ## Regulatory Change Documents (Gap Fill)

# COMMAND ----------

write_doc("regulatory_change_epa_ust_2025.txt", """
REGULATORY CHANGE NOTICE

Document ID: REG-CHG-2025-EPA-001
Document Type: regulatory_change
Change Type: AMENDED
Jurisdiction: Federal — All States
Statute Number: 40 CFR Part 280 Subpart M
Enforcement Authority: U.S. Environmental Protection Agency (EPA), Office of Underground Storage Tanks
Effective Date: June 1, 2025
Publication Date: January 15, 2025
Risk Level: HIGH
Confidence Level: HIGH
Source: Federal Register Vol. 90, No. 11 (January 15, 2025), pp. 4201–4248
URL: https://www.federalregister.gov/documents/2025/01/15/2025-00821/underground-storage-tanks

SUMMARY OF CHANGE
EPA is amending 40 CFR Part 280 to strengthen underground storage tank (UST) release detection
requirements. The amendment requires all UST operators to upgrade from manual monthly inventory
reconciliation to electronic automatic tank gauging (ATG) with continuous electronic monitoring
and 30-day data retention.

KEY CHANGES

1. Release Detection — Electronic Monitoring Required
   Previous requirement: Monthly manual inventory reconciliation acceptable for USTs installed
   before January 1, 1998.
   New requirement: All USTs must use EPA-approved electronic release detection by June 1, 2025.
   Impact for RaceTrac: Stores using manual reconciliation (estimated 4–6 legacy stores) must
   install ATG systems or upgrade to continuous monitoring by June 1, 2025.

2. Data Retention
   Previous requirement: Records retained 3 years.
   New requirement: Electronic monitoring data retained 5 years in tamper-evident format.

3. Designated Operator Training
   New requirement: Class A/B designated operators must complete updated EPA-approved training
   course by December 31, 2025. Class C operators trained annually.

BUSINESS IMPACT
Stores affected: All RaceTrac locations with UST operations in states covered by federal UST rules
(GA, FL, TX, and all other operating states).
Estimated compliance cost: $8,000–$15,000 per store for ATG upgrades where not already installed.
Non-compliance penalty: Up to $37,500 per day per violation.

REQUIRED ACTIONS
1. Audit all stores for current release detection method by February 28, 2025.
2. Identify stores requiring ATG installation or upgrade.
3. Obtain contractor bids and schedule installations.
4. Confirm ATG compliance for all stores by May 15, 2025 (two-week buffer before effective date).
5. Update Designated Operator training enrollment by October 1, 2025.

JURISDICTIONAL NOTE
States with delegated UST programs (GA, FL, TX) may adopt stricter requirements. Check state
regulations for any additional obligations beyond federal minimums.

Prepared By: RaceTrac Regulatory Affairs Team
Review Date: January 22, 2025
Attorney Review Recommended: YES — significant penalty exposure
""")

# COMMAND ----------

write_doc("regulatory_change_fdep_food_2025.txt", """
REGULATORY CHANGE NOTICE

Document ID: REG-CHG-2025-FDEP-002
Document Type: regulatory_change
Change Type: NEW REQUIREMENT
Jurisdiction: Florida
Statute Number: Florida Administrative Code Chapter 64E-11; Florida Statutes § 500.09
Enforcement Authority: Florida Department of Health (FDOH), Bureau of Environmental Health
Effective Date: April 15, 2025
Publication Date: February 1, 2025
Risk Level: HIGH
Confidence Level: HIGH
Source: Florida Administrative Weekly, Vol. 51, No. 5, February 1, 2025
URL: https://www.flrules.org/gateway/ruleno.asp?id=64E-11.003

SUMMARY OF CHANGE
Florida is adopting a revised inspection scoring methodology for retail food service establishments
effective April 15, 2025. The new system replaces the letter-grade (A/B/C/F) model with a
numerical demerit scoring system and adds two new mandatory inspection checkpoints for high-touch
surfaces and allergen cross-contact.

KEY CHANGES

1. New Scoring System — Demerit Points
   Previous system: Letter grade (A = 90–100, B = 80–89, C = 70–79, F = <70).
   New system: Demerit point accumulation.
     0–14 points: SATISFACTORY (posting required)
     15–29 points: CONDITIONAL (re-inspection within 30 days)
     30+ points: UNSATISFACTORY (mandatory closure until remediated)
   Critical violations (foodborne illness risk): 4 points each.
   Non-critical violations: 1 point each.

2. New Mandatory Checkpoint: Allergen Cross-Contact
   Inspectors will assess written allergen protocols for the 9 FDA major allergens.
   Absence of written protocol = 4-point critical violation.
   Staff unable to identify allergens on request = additional 2-point violation.

3. New Mandatory Checkpoint: High-Touch Surface Sanitization Log
   Inspectors will request 30-day log of counter/register/door-handle sanitization frequency.
   Absence of log = 2-point non-critical violation.

4. Certified Food Manager (CFM) Posting
   CFM certificate must be displayed at food service station (previously only required on file).
   Absence = 1-point non-critical violation.

BUSINESS IMPACT
Stores affected: All RaceTrac Florida locations with active food service operations
(estimated 89 Florida stores).
Recommended action: Conduct internal pre-audit using new demerit scoring sheet before
April 15, 2025 effective date.

REQUIRED ACTIONS
1. Update internal food safety inspection checklist to new demerit scoring format by March 15, 2025.
2. Implement written allergen cross-contact protocols at all FL food service locations.
3. Train store managers on new scoring thresholds and critical violation definitions.
4. Begin maintaining high-touch surface sanitization log by April 1, 2025.
5. Confirm CFM certificates are posted (not just on file) at all FL locations.

Prepared By: RaceTrac Food Safety Compliance Team
Review Date: February 10, 2025
Attorney Review Recommended: NO
""")

# COMMAND ----------

write_doc("regulatory_change_tabc_2025.txt", """
REGULATORY CHANGE NOTICE

Document ID: REG-CHG-2025-TABC-003
Document Type: regulatory_change
Change Type: REPEALED
Jurisdiction: Texas
Statute Number: Texas Administrative Code Title 16, Chapter 45 § 45.100; Texas Alcoholic Beverage
               Code § 106.14
Enforcement Authority: Texas Alcoholic Beverage Commission (TABC)
Effective Date: March 1, 2025
Publication Date: January 6, 2025
Risk Level: CRITICAL
Confidence Level: HIGH
Source: Texas Register, Vol. 50, No. 1, January 6, 2025, pp. 8–14
URL: https://www.sos.state.tx.us/texreg/archive/January62025/Adopted%20Rules/16.ECONOMIC%20REGULATION.html

SUMMARY OF CHANGE
TABC is repealing the "owner-managed establishment" exemption from mandatory TABC-approved
server training. Previously, owner-operated retail alcohol locations with fewer than 3 employees
were exempt from the requirement that all alcohol servers complete TABC-approved Seller-Server
Training. Effective March 1, 2025, this exemption is eliminated.

All persons who sell, serve, or deliver alcoholic beverages at a retail location must complete
TABC-approved Seller-Server Training before performing those duties, regardless of establishment
size or ownership structure.

KEY CHANGES

1. Exemption Removed
   Previous rule: Owner-managed retail locations with <3 employees exempt from Seller-Server
   Training requirement.
   New rule: No exemption. All alcohol sellers and servers must be TABC-trained.

2. Training Recertification Period Shortened
   Previous period: TABC Seller-Server certification valid for 3 years.
   New period: Certification valid for 2 years. All existing 3-year certifications must be
   renewed on the new 2-year schedule at next renewal date.

3. Record-Keeping Enhancement
   New requirement: Training records must be maintained at the licensed premise (not just
   corporate headquarters) for inspection upon TABC request.

BUSINESS IMPACT
RaceTrac Texas operations: All Texas store employees who handle alcohol transactions must
hold current TABC Seller-Server Training certification.
Previously, a small number of Texas stores may have relied on the owner-managed exemption.
Audit required to confirm full compliance.

REQUIRED ACTIONS
1. Audit all Texas store employee training records by February 15, 2025.
2. Identify any employees without current TABC Seller-Server certification.
3. Enroll uncertified employees in TABC-approved training before March 1, 2025.
4. Update record-keeping to maintain training certificates at each store premise.
5. Adjust recertification calendar to 2-year cycle for all Texas certifications.
6. Review hiring protocols to require TABC training before first alcohol transaction.

PENALTY EXPOSURE
First violation: License suspension 3–5 days.
Subsequent violation within 36 months: License suspension up to 30 days or cancellation.
Personal liability: Employee performing alcohol service without certification — Class A misdemeanor.

Prepared By: RaceTrac Alcohol & Tobacco Compliance Team
Review Date: January 14, 2025
Attorney Review Recommended: YES — criminal misdemeanor exposure for uncertified employees
""")

# COMMAND ----------

write_doc("regulatory_change_osha_hazmat_2026.txt", """
REGULATORY CHANGE NOTICE

Document ID: REG-CHG-2026-OSHA-004
Document Type: regulatory_change
Change Type: AMENDED
Jurisdiction: Federal — All States
Statute Number: 29 CFR 1910.1200 (Hazard Communication Standard, HazCom 2024)
Enforcement Authority: U.S. Department of Labor, Occupational Safety and Health Administration (OSHA)
Effective Date: January 1, 2026
Publication Date: May 20, 2025
Risk Level: MEDIUM
Confidence Level: HIGH
Source: Federal Register Vol. 90, No. 97 (May 20, 2025), pp. 21801–21950
URL: https://www.osha.gov/hazcom/faqs

SUMMARY OF CHANGE
OSHA is amending the Hazard Communication Standard (HazCom) at 29 CFR 1910.1200 to align with
the 9th Revised Edition of the United Nations Globally Harmonized System of Classification and
Labelling of Chemicals (GHS Rev. 9). The amendment introduces revised Safety Data Sheet (SDS)
formats, new aerosol classification categories, and updated label requirements.

KEY CHANGES

1. Safety Data Sheet Format Updates
   Previous format: 16-section GHS Rev. 3 SDS format.
   New format: Updated 16-section GHS Rev. 9 format with revised language in Sections 2, 9, 11.
   Section 2 (Hazard Identification): New aerosol categories and flammability classifications added.
   Section 9 (Physical/Chemical Properties): 6 new required data elements added.
   Section 11 (Toxicological Information): Expanded endocrine disruption information required.

2. New Aerosol Classification Categories
   Two new aerosol hazard categories (Category 3 — Flammable Aerosols, Non-Pressurized Aerosols)
   added to the classification system.
   RaceTrac impact: Cleaning products, air fresheners, and similar aerosol products sold in-store
   require updated SDS by supplier or internal reclassification review.

3. Updated Label Requirements
   New signal words and hazard statements required for the new aerosol categories.
   Effective date for new labels on products manufactured after January 1, 2026.
   Products already in stock with old labels acceptable through June 1, 2026 (transition period).

BUSINESS IMPACT
Stores affected: All RaceTrac locations stocking HazCom-covered chemicals (cleaning supplies,
fuel additives, aerosol products).
Estimated effort: Update SDS library and confirm all product SDSs from suppliers are GHS Rev. 9
compliant before January 1, 2026.

REQUIRED ACTIONS
1. Notify all chemical suppliers by July 1, 2025 to provide updated GHS Rev. 9 SDSs.
2. Update digital SDS management system before January 1, 2026.
3. Review aerosol product inventory for reclassification needs.
4. Train Environmental Health & Safety team on new classification system by November 1, 2025.
5. Update employee HazCom training program to reflect GHS Rev. 9 changes.

Prepared By: RaceTrac EHS Compliance Team
Review Date: June 1, 2025
Attorney Review Recommended: NO
""")

# COMMAND ----------

write_doc("multi_jurisdiction_ust_comparison_2025.txt", """
CORPORATE COMPLIANCE BULLETIN

Document ID: CORP-BULL-2025-UST-001
Document Type: regulatory_change
Change Type: COMPARISON — MULTI-JURISDICTION
Jurisdiction: Georgia; Florida; Texas
Statute Number: GA: Georgia Rules for USTs Chapter 391-3-15
               FL: Florida Administrative Code Rule 62-761
               TX: Texas Administrative Code Title 30, Chapter 334
               Federal: 40 CFR Part 280
Enforcement Authority: GA: Georgia Environmental Protection Division (EPD)
                      FL: Florida Department of Environmental Protection (FDEP)
                      TX: Texas Commission on Environmental Quality (TCEQ)
                      Federal: U.S. EPA Office of Underground Storage Tanks
Effective Date: Ongoing — current as of Q1 2025
Risk Level: HIGH
Confidence Level: HIGH
Source: RaceTrac Regulatory Affairs — Multi-Jurisdiction UST Compliance Mapping Q1 2025

PURPOSE
This bulletin summarizes Underground Storage Tank (UST) compliance requirements across RaceTrac's
three primary operating jurisdictions (Georgia, Florida, Texas) to identify differences from
federal baseline requirements and highlight areas requiring jurisdiction-specific actions.

JURISDICTION COMPARISON MATRIX

1. RELEASE DETECTION REQUIREMENTS

Federal (40 CFR § 280.40): Monthly inventory reconciliation OR continuous ATG monitoring.
New federal rule (effective June 1 2025): Continuous ATG required for all USTs.

Georgia (Chapter 391-3-15-0.07):
  - Continuous ATG required since January 1, 2020 (stricter than pre-2025 federal).
  - ATG must provide release detection for product lines AND sumps.
  - Third-party annual calibration verification required.
  - RaceTrac GA status: COMPLIANT — All GA stores on ATG since 2020 program.

Florida (Rule 62-761.600):
  - Continuous ATG required since January 1, 2019 (stricter than pre-2025 federal).
  - 30-day electronic data retention (same as new federal rule).
  - FDEP-approved ATG systems list maintained — only approved systems accepted.
  - RaceTrac FL status: COMPLIANT — All FL stores use FDEP-approved ATG systems.

Texas (TAC Title 30, § 334.50):
  - Continuous ATG required since September 1, 2018.
  - ATG must be tested annually by TCEQ-certified operator.
  - TCEQ maintains approved ATG equipment list.
  - RaceTrac TX status: COMPLIANT — 1 open finding at Store_128 (ATG annual test overdue).

2. FINANCIAL RESPONSIBILITY REQUIREMENTS

Federal (40 CFR Part 280 Subpart H): $1M per occurrence / $2M annual aggregate.

Georgia: Same as federal minimum. No additional state requirement.
Florida: Same as federal minimum. Self-insurance requires FDEP pre-approval.
Texas: Same as federal minimum. TCEQ requires financial responsibility form submission annually.
  RaceTrac TX: Confirm annual TCEQ Form FR-3 submission — due March 31, 2025.

3. OPERATOR TRAINING REQUIREMENTS

Federal (40 CFR § 280.245): Class A/B/C operator training required.

Georgia: Must use Georgia EPD-approved training provider. 3-year recertification cycle.
Florida: Must use FDEP-approved training provider. 3-year recertification cycle.
         New requirement effective July 1, 2025: Online training must include proctored exam.
Texas: Must use TCEQ-licensed training provider. 3-year recertification cycle.
       Class C operators must complete TCEQ-approved refresher annually (stricter than federal).

4. INSPECTION FREQUENCY

Federal: No mandatory inspection frequency — state programs govern.

Georgia: EPD inspects UST facilities every 3 years on average. High-risk stores may be annual.
Florida: FDEP inspects every 3 years. Stores with prior violations inspected annually.
Texas: TCEQ inspects every 2 years. Stores with Class 1 violations inspected annually.
  Note: Store_128 (TX) had Class 1 violation in 2024 — annual inspection expected Q2 2025.

5. REPORTABLE RELEASE THRESHOLD

Federal: 25 gallons or any amount that poses imminent hazard.

Georgia: 25 gallons (same as federal).
Florida: Any confirmed release — no minimum quantity threshold (more stringent than federal).
Texas: 25 gallons confirmed release OR free product detected in monitoring well.

OPEN ITEMS REQUIRING ACTION

| Item | Store(s) | Jurisdiction | Deadline | Owner |
|------|----------|-------------|----------|-------|
| ATG annual test overdue | Store_128 | Texas | March 31, 2025 | EHS Manager |
| TCEQ FR-3 annual submission | All TX stores | Texas | March 31, 2025 | Regulatory Affairs |
| FL operator training — proctored exam update | All FL stores | Florida | July 1, 2025 | Training Dept |
| Federal ATG upgrade (legacy stores) | TBD | Federal | June 1, 2025 | EHS/Capital |

CONFIDENCE ASSESSMENT
All requirements cited above verified against official government sources as of March 2025.
Confidence Level: HIGH for current requirements. Note: regulations subject to amendment —
re-verify before any enforcement action or capital investment decision.

Attorney Review Recommended: YES for financial responsibility and penalty exposure items.

Prepared By: RaceTrac Regulatory Affairs — Ananth Krishnaswamy
Reviewed By: Sarah Kim, Legal Counsel
Date: March 15, 2025
""")

# COMMAND ----------

print("\n" + "="*60)
print("COMPLIANCE CORPUS GENERATION COMPLETE")
print("="*60)

import os
files = os.listdir(VOLUME_PATH)
txt_files = [f for f in files if f.endswith('.txt')]
print(f"\nTotal .txt documents written: {len(txt_files)}")

domains = {
    "env_": "Environmental",
    "food_": "Food Safety",
    "safety_": "OSHA/Safety",
    "fuel_": "Fuel Operations",
    "atc_": "Alcohol & Tobacco",
    "vendor_": "Vendor Compliance",
    "permit_": "Permits",
    "policy_": "Policies",
    "risk_": "Risk Assessments",
    "training_": "Training",
    "regulatory_": "Regulatory Changes",
    "multi_": "Multi-Jurisdiction",
}
for prefix, label in domains.items():
    count = len([f for f in txt_files if f.startswith(prefix)])
    if count > 0:
        print(f"  {label}: {count} documents")

print("\nReady for PDF conversion (run 00c_generate_pdfs.py against compliance volume)")
