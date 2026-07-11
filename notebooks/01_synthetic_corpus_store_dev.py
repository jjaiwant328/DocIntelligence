# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Compliance Due Diligence Synthetic Corpus (Store Development)
# MAGIC
# MAGIC Generates ~21 realistic RaceTrac store-development feasibility documents and writes
# MAGIC them as plain-text files.
# MAGIC
# MAGIC **Markets covered:** Tampa FL, Dallas TX, Atlanta GA
# MAGIC **Projects:** SD-2024-201 (Tampa), SD-2024-202 (Dallas/v2024), SD-2025-203 (Dallas/v2025), SD-2023-204 (Atlanta)
# MAGIC
# MAGIC **Document types (all 10 classification labels):**
# MAGIC - `feasibility_request` — store-dev feasibility emails (`.eml`)
# MAGIC - `municipal_requirement` — municipal / county requirement summary docs
# MAGIC - `alcohol_license` — DABT / TABC license applications and approvals
# MAGIC - `tobacco_license` — state tobacco dealer permit
# MAGIC - `business_license` — county business tax receipts / occupational licenses
# MAGIC - `zoning_document` — zoning verification / compatibility letters
# MAGIC - `permit` — building / certificate-of-occupancy permits
# MAGIC - `historical_response` — prior feasibility responses with dates (memory / recall)
# MAGIC - `regulatory_change` — before/after regulatory pair (Dallas alcohol v2024→v2025)
# MAGIC - `consultant_correspondence` — consultant status memos
# MAGIC
# MAGIC **Dallas before/after regulatory pair** (change-detection driver):
# MAGIC - v2024 (`muni_req_dallas_TX_alcohol_v2024.txt`): standard TABC process, ~6-week lead time
# MAGIC - v2025 (`muni_req_dallas_TX_alcohol_v2025.txt`): new distance-exception certificate required,
# MAGIC   ~14-week lead time; affects SD-2025-203
# MAGIC - `regulatory_change_dallas_alcohol_v2024_v2025.txt`: structured REGULATORY CHANGE DETECTED doc
# MAGIC
# MAGIC **Bootstrap flow (Databricks):**
# MAGIC   Run after `setup_compliance_due_diligence.py` creates the schema + volume.
# MAGIC   corpus → volume → `00c_generate_pdfs.py` → domain activated.
# MAGIC
# MAGIC **Extraction fields embedded in every doc** (for AI extraction):
# MAGIC   project_id, store_number, address, market, state, municipality, county,
# MAGIC   request_type, requester, priority, requirement_type, authority, license_type,
# MAGIC   issuing_authority, lead_time, renewal_period, effective_date, expiration_date,
# MAGIC   responder, response_date, source_document

# COMMAND ----------

import os
import pathlib

CATALOG     = "jai_docintel"
SCHEMA      = "compliance_due_diligence"
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/documents"

# COMMAND ----------

def _resolve_output_dir() -> str:
    """Return volume path in Databricks, local sample_data directory otherwise."""
    try:
        dbutils  # noqa: F821 — available only in Databricks
        out = VOLUME_PATH
        os.makedirs(out, exist_ok=True)
        return out
    except NameError:
        pass
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    out = str(repo_root / "domains" / "compliance_due_diligence" / "sample_data")
    os.makedirs(out, exist_ok=True)
    return out

OUTPUT_DIR = _resolve_output_dir()
print(f"Output directory: {OUTPUT_DIR}")

# COMMAND ----------

def write_doc(filename: str, content: str):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w") as f:
        f.write(content.strip())
    print(f"Written: {filename}")

# COMMAND ----------
# MAGIC %md ## Tampa FL — Project SD-2024-201 (Store #5201)

# COMMAND ----------

write_doc("feasy_email_tampa_SD201_2024.eml", """
From: Ryan Holloway <r.holloway@racetrac.com>
To: Kendra Patel <k.patel@racetrac.com>
CC: Marcus Dawson <m.dawson@storedevelopmentconsulting.com>
Date: March 15, 2024
Subject: FEASIBILITY REQUEST — Tampa FL — 8820 N Dale Mabry Hwy — Project SD-2024-201
Message-ID: <RT-FEASY-2024-SD201@racetrac.com>

Document ID: FEASY-EMAIL-2024-SD201
Document Type: feasibility_request
Project ID: SD-2024-201
Store Number: 5201
Address: 8820 N Dale Mabry Hwy, Tampa, FL 33614
Market: Tampa FL
State: FL
Municipality: City of Tampa
County: Hillsborough County
Request Type: new_store_feasibility
Requester: Ryan Holloway
Priority: High
Submitted Date: 2024-03-15

Kendra, Marcus —

Please open a full feasibility review for the above site. Real estate has executed an
option on the parcel at 8820 N Dale Mabry Hwy, Tampa, FL 33614 (Hillsborough County).
This is a high-priority new-build convenience/fuel site targeted for a Q1 2025 opening.

SITE SUMMARY
Parcel: 076304-0000 (Hillsborough County Property Appraiser)
Current use: Vacant commercial — former auto-repair shop
Lot size: ~0.98 acres
Current zoning: CI (Commercial Intensive) per City of Tampa Zoning Code
Proposed use: Convenience retail + 8-pump fuel station (canopy and dispenser islands)

FEASIBILITY SCOPE REQUESTED
Please initiate parallel tracks for:
1. Municipal licensing requirements — City of Tampa + Hillsborough County
2. Alcohol (beer/wine off-premise) — Florida DABT 2-APS license
3. Tobacco dealer permit — Florida DOR
4. Business tax receipt — Hillsborough County BOCC
5. Zoning compatibility confirmation — CI zoning vs. fuel station use
6. Building / site plan permit overview — estimated lead times

TARGET MILESTONES
License applications submitted: May 1, 2024
All licenses in hand: September 30, 2024
Store opening: Q1 2025

Please provide a full requirements memo by April 5, 2024.

Ryan Holloway
Store Development Manager — Southeast
RaceTrac Petroleum, Inc.
""")

# COMMAND ----------

write_doc("muni_req_hillsborough_FL_2024.txt", """
MUNICIPAL REQUIREMENTS SUMMARY — STORE DEVELOPMENT FEASIBILITY

Document ID: MUNI-REQ-2024-SD201-HILLSBOROUGH
Document Type: municipal_requirement
Project ID: SD-2024-201
Store Number: 5201
Address: 8820 N Dale Mabry Hwy, Tampa, FL 33614
Market: Tampa FL
State: FL
Municipality: City of Tampa
County: Hillsborough County
Requirement Type: municipal_licensing_summary
Authority: Hillsborough County Development Services; City of Tampa Planning & Development
Prepared By: Kendra Patel, Senior Development Analyst — RaceTrac Store Development
Response Date: 2024-04-03
Source Document: FEASY-EMAIL-2024-SD201
Responder: Kendra Patel

EXECUTIVE SUMMARY
Site at 8820 N Dale Mabry Hwy, Tampa FL (Hillsborough County) is feasible for a
convenience retail / fuel station. CI zoning is compatible with the proposed use. Key
requirements and lead times are listed below. No material obstacles identified.

SECTION 1 — ZONING AND LAND USE
Authority: City of Tampa Development Services, (813) 274-3100
Current Zoning: CI (Commercial Intensive) — Tampa Code of Ordinances § 27-158
Proposed Use: Convenience retail + motor fuel sales (SIC 5541)
Compatibility: CONFIRMED COMPATIBLE. Fuel stations are a permitted-by-right use under CI.
Variance Required: None for principal use. Minor site plan approval required for canopy setback
  if within 10 ft of right-of-way (verify during site plan review).
Requirement Type: zoning_clearance
Lead Time: 2–3 weeks for zoning verification letter
Effective Date: N/A (existing zoning)

SECTION 2 — ALCOHOL LICENSE (BEER & WINE OFF-PREMISE)
Authority: Florida Division of Alcoholic Beverages and Tobacco (DABT)
License Type: 2-APS (Beer and Wine, Package Store, Off-Premise Consumption)
Issuing Authority: Florida DABT — Tampa District
Applicable Law: Florida Statutes Chapter 561–565; § 562.11 (age verification)
Requirements:
  - DABT quota: Hillsborough County is NOT in a quota county for 2-APS. License available.
  - Distance restriction: Must be ≥ 500 ft from schools and churches (Florida Statute § 561.44).
    Site survey confirms nearest school (Carver Elementary) is 0.72 miles away — COMPLIANT.
  - Designated manager background check required.
  - Certificate of Use / CO required before license activation.
Lead Time: 8–10 weeks from complete application submission
Renewal Period: Annual (October 1 renewal deadline)
Effective Date: Upon approval (estimated August 2024)
License Fee: $1,820 (2-APS annual fee)

SECTION 3 — TOBACCO DEALER PERMIT
Authority: Florida Department of Revenue — Division of Taxes
License Type: Tobacco Products Dealer Permit
Applicable Law: Florida Statutes § 210.15–210.185
Requirements:
  - Florida business registration active
  - Sales tax registration (Form DR-1)
  - No prior tobacco tax violations
Lead Time: 2–4 weeks
Renewal Period: Annual (July 1 renewal deadline)
Permit Fee: $50 annual

SECTION 4 — BUSINESS TAX RECEIPT
Authority: Hillsborough County Tax Collector — Business Tax Division
License Type: Occupational License / Business Tax Receipt (BTR)
Applicable Law: Hillsborough County Code § 15 — Business Tax
Requirements:
  - Completed BTR application
  - Certificate of Use from City of Tampa (confirms zoning compliance)
  - State business license copy
Lead Time: 1–2 weeks after Certificate of Use issued
Renewal Period: Annual (September 30 renewal deadline)
License Fee: $125–$200 (convenience retail classification)

SECTION 5 — BUILDING AND SITE PLAN PERMITS
Authority: City of Tampa Construction Services; Hillsborough County EPC
Requirements:
  - Site Plan Review (Development Review Committee) — submit by May 2024
  - Building permit for new construction (canopy, dispensers, store structure)
  - Hillsborough County EPC: UST permit for underground storage tanks (3 tanks)
  - FDEP: UST registration prior to fuel operations
Lead Time: Building permit — 12–16 weeks. UST registration — 4 weeks.
Effective Date: N/A (new construction)

OVERALL FEASIBILITY ASSESSMENT: FEASIBLE — NO MATERIAL OBSTACLES
Recommended next step: Submit alcohol license pre-application; file site plan review by May 1, 2024.

Prepared By: Kendra Patel    Date: April 3, 2024
""")

# COMMAND ----------

write_doc("alcohol_license_hillsborough_SD201_2024.txt", """
FLORIDA DIVISION OF ALCOHOLIC BEVERAGES AND TOBACCO
LICENSE APPLICATION AND APPROVAL

Document ID: LIC-DABT-FL-2024-SD201
Document Type: alcohol_license
Project ID: SD-2024-201
Store Number: 5201
Address: 8820 N Dale Mabry Hwy, Tampa, FL 33614
Market: Tampa FL
State: FL
Municipality: City of Tampa
County: Hillsborough County
License Type: 2-APS (Beer and Wine Package Store, Off-Premise Consumption)
Issuing Authority: Florida Division of Alcoholic Beverages and Tobacco (DABT)
Application Date: 2024-05-06
Approval Date: 2024-08-14
Effective Date: 2024-08-14
Expiration Date: 2025-09-30
Renewal Period: Annual (October 1)
Lead Time: 99 days (application to approval)
License Number: FL-DABT-2APS-HILL-2024-55291
Requirement Type: alcohol_retail_license
Responder: Florida DABT Tampa District Office
Response Date: 2024-08-14
Source Document: MUNI-REQ-2024-SD201-HILLSBOROUGH

LICENSE APPROVAL NOTICE

RaceTrac Petroleum, Inc.
8820 N Dale Mabry Hwy
Tampa, FL 33614

License Type: 2-APS — Alcoholic Beverage Sales Package Store (Beer and Wine)
License Number: FL-DABT-2APS-HILL-2024-55291
Effective: August 14, 2024
Expires: September 30, 2025
Status: ACTIVE

LICENSE CONDITIONS
1. Authorized to sell beer and wine for off-premise consumption only.
2. Sales hours: Monday–Sunday 7:00 AM – 11:00 PM (City of Tampa general retail ordinance).
   No Sunday morning restriction under current Hillsborough County code.
3. Age verification required for all alcohol purchases (Florida Statute § 562.11).
   Customer must be 21 or older. RaceTrac "card under 40" policy applies.
4. Designated manager on record: Kendra Patel (Store Development — activation upon opening).
   Must be updated with store manager name 30 days prior to opening.
5. License must be posted conspicuously at point of sale.
6. Responsible Vendor Program (RVP) certification required within 90 days of opening.
7. No single-serving beer containers of malt beverages sold in quantities creating
   a public nuisance (Hillsborough County ordinance 2018-44).

DISTANCE COMPLIANCE CERTIFICATION
Nearest school (Carver Elementary): 0.72 miles — COMPLIANT (minimum 500 ft)
Nearest church (Holy Trinity): 0.41 miles — COMPLIANT (minimum 500 ft)
No distance exception required.

RENEWAL NOTICE
Renewal application due: August 1, 2025. Annual fee: $1,820.
Failure to renew results in license lapse; 30-day grace period with late fee ($250).

Issued By: Florida DABT Tampa District    Date: August 14, 2024
""")

# COMMAND ----------

write_doc("tobacco_license_hillsborough_SD201_2024.txt", """
FLORIDA DEPARTMENT OF REVENUE — TOBACCO PRODUCTS DEALER PERMIT

Document ID: LIC-TOB-FL-2024-SD201
Document Type: tobacco_license
Project ID: SD-2024-201
Store Number: 5201
Address: 8820 N Dale Mabry Hwy, Tampa, FL 33614
Market: Tampa FL
State: FL
Municipality: City of Tampa
County: Hillsborough County
License Type: Tobacco Products Dealer Permit
Issuing Authority: Florida Department of Revenue — Division of Taxes
Permit Number: FL-TOB-TDP-2024-SD201-88214
Application Date: 2024-05-06
Approval Date: 2024-05-28
Effective Date: 2024-05-28
Expiration Date: 2025-06-30
Renewal Period: Annual (July 1)
Lead Time: 22 days
License Fee Paid: $50
Requirement Type: tobacco_retail_permit
Responder: Florida DOR Tampa Service Center
Response Date: 2024-05-28
Source Document: MUNI-REQ-2024-SD201-HILLSBOROUGH

PERMIT APPROVAL

Permittee: RaceTrac Petroleum, Inc.
Location: 8820 N Dale Mabry Hwy, Tampa, FL 33614

This permit authorizes the sale of tobacco products at the above location pursuant to
Florida Statutes § 210.15–210.185.

AUTHORIZED PRODUCTS
Cigarettes, cigars, smokeless tobacco, pipe tobacco, electronic cigarettes / vapor products,
and other nicotine delivery products as defined under Florida Statute § 210.11.

CONDITIONS
1. No sale of tobacco products to persons under 21 years of age (Federal Tobacco 21 law;
   21 U.S.C. § 387f(d); Florida Statute § 569.101).
2. Age verification required on all tobacco transactions. ID must be verified for all
   purchasers who appear under 30 years of age (company policy).
3. FDA Retailer Registration must be current (Registration required per 21 U.S.C. § 387g).
   RaceTrac corporate FDA registration on file (Registration #FDA-RTL-2024-88442).
4. All tobacco must be sold from behind the counter or a locked display case.
   No self-service tobacco access.
5. Tobacco tax returns and payments required monthly on Form DR-21.

RENEWAL
Renewal due: June 1, 2025. Annual fee: $50.

Issued By: Florida Department of Revenue    Date: May 28, 2024
""")

# COMMAND ----------

write_doc("zoning_hillsborough_SD201_2024.txt", """
ZONING COMPATIBILITY AND LAND USE VERIFICATION

Document ID: ZONE-2024-SD201-TAMPA
Document Type: zoning_document
Project ID: SD-2024-201
Store Number: 5201
Address: 8820 N Dale Mabry Hwy, Tampa, FL 33614
Market: Tampa FL
State: FL
Municipality: City of Tampa
County: Hillsborough County
Requirement Type: zoning_clearance
Authority: City of Tampa Planning & Development Department
Issuing Authority: City of Tampa Development Services
Effective Date: 2024-04-10
Lead Time: 5 days (verification letter)
Responder: City of Tampa Planning Dept
Response Date: 2024-04-10
Source Document: FEASY-EMAIL-2024-SD201

ZONING VERIFICATION LETTER

RaceTrac Petroleum, Inc. — Store Development
c/o Kendra Patel, Senior Development Analyst

RE: Zoning Verification for 8820 N Dale Mabry Hwy, Tampa, FL 33614
    Parcel ID: 076304-0000
    Project: SD-2024-201 / Store #5201

This letter is issued by the City of Tampa Planning & Development Department to verify
the zoning and permitted uses at the above-referenced property.

CURRENT ZONING
District: CI — Commercial Intensive
Reference: City of Tampa Zoning Code, Chapter 27 Land Development Regulations, § 27-158
Effective: Existing zoning designation

PROPOSED USE ANALYSIS
Proposed Use: Convenience retail store with motor fuel dispensing
SIC Code: 5541 (Gasoline Stations with Convenience Stores)
Zoning Status: PERMITTED BY RIGHT under CI district regulations

SITE DEVELOPMENT STANDARDS APPLICABLE
Building setback: 10 ft from all property lines; 25 ft from residential parcels (none adjacent).
Maximum lot coverage: 85% — no restriction issue at 0.98 acres.
Canopy setback: Minimum 10 ft from public right-of-way per City of Tampa § 27-246.5.
  Applicant must demonstrate canopy compliance at site plan review.
Landscaping buffer: 10 ft buffer required along N Dale Mabry Hwy frontage (Class II buffer).
Lighting: Must comply with City of Tampa § 27-283.5 (full-cutoff fixtures required).

SPECIAL USE CONDITIONS
Motor fuel stations within CI require no special exception or variance unless:
  (a) Within 200 ft of a residential district — not applicable at this site.
  (b) Proposing more than 12 fueling positions — proposed 8 positions, no exception required.

ADJACENT ZONING CONTEXT
North: CI (commercial retail)
South: CI (auto dealership)
East: CN (commercial neighborhood — buffer required if structure within 50 ft)
West: I-275 right-of-way

DETERMINATION
The proposed use is COMPATIBLE with the CI zoning district.
No variance or special exception is required for the principal use.
Canopy setback and landscaping buffer must be confirmed during site plan review.

NEXT STEPS
1. Submit Development Review Committee (DRC) site plan application.
2. Certificate of Use will be issued following DRC approval and final inspection.

City Planner: Michael S. Torres, AICP    Date: April 10, 2024
City of Tampa Planning & Development Department
""")

# COMMAND ----------

write_doc("business_license_hillsborough_SD201_2025.txt", """
HILLSBOROUGH COUNTY TAX COLLECTOR — BUSINESS TAX RECEIPT

Document ID: BTR-HILL-2025-SD201
Document Type: business_license
Project ID: SD-2024-201
Store Number: 5201
Address: 8820 N Dale Mabry Hwy, Tampa, FL 33614
Market: Tampa FL
State: FL
Municipality: City of Tampa
County: Hillsborough County
License Type: Business Tax Receipt — Convenience Store / Motor Fuel Retail
Issuing Authority: Hillsborough County Tax Collector
Receipt Number: HILL-BTR-2025-0089241
Application Date: 2024-12-01
Issue Date: 2025-01-02
Effective Date: 2025-01-02
Expiration Date: 2025-09-30
Renewal Period: Annual (September 30)
License Fee Paid: $175
Lead Time: 32 days
Requirement Type: business_tax_receipt
Responder: Hillsborough County Tax Collector Office
Response Date: 2025-01-02
Source Document: MUNI-REQ-2024-SD201-HILLSBOROUGH

BUSINESS TAX RECEIPT

Business Name: RaceTrac Petroleum, Inc.
Trade Name: RaceTrac Store #5201
Location: 8820 N Dale Mabry Hwy, Tampa, FL 33614
Business Classification: Convenience Store with Motor Fuel Retail — Class III
Owner/Agent: Ryan Holloway, Store Development Manager

Pursuant to Hillsborough County Code § 15-2 (Business Tax), this receipt authorizes the
above business to operate at the stated location.

CONDITIONS
1. This receipt is non-transferable to another location or owner.
2. Certificate of Use (City of Tampa) must remain active.
3. Florida state licenses (alcohol, tobacco) must be current and posted on-site.
4. Any material change in business type or operations requires updated BTR application.
5. Annual renewal by September 30. Late renewal fee: $25.

PROFESSIONAL LICENSES ON FILE
- Florida DABT 2-APS License: FL-DABT-2APS-HILL-2024-55291 (beer/wine)
- Florida Tobacco Dealer Permit: FL-TOB-TDP-2024-SD201-88214
- FDEP UST Registration: Applied, in process

This receipt does not waive any other permit or license requirement.

Issued By: Hillsborough County Tax Collector    Date: January 2, 2025
""")

# COMMAND ----------

write_doc("permit_co_tampa_SD201_2025.txt", """
CITY OF TAMPA — CERTIFICATE OF OCCUPANCY

Document ID: PERMIT-CO-TAMPA-2025-SD201
Document Type: permit
Project ID: SD-2024-201
Store Number: 5201
Address: 8820 N Dale Mabry Hwy, Tampa, FL 33614
Market: Tampa FL
State: FL
Municipality: City of Tampa
County: Hillsborough County
License Type: Certificate of Occupancy
Issuing Authority: City of Tampa Construction Services
Permit Number: TAMPA-CO-2025-004412
Building Permit Reference: TAMPA-BP-2024-034892
Application Date: 2024-12-15
Final Inspection Date: 2025-01-08
Issue Date: 2025-01-10
Effective Date: 2025-01-10
Expiration Date: N/A (permanent)
Requirement Type: certificate_of_occupancy
Lead Time: 26 days (final inspection to CO issuance)
Responder: City of Tampa Construction Services
Response Date: 2025-01-10
Source Document: MUNI-REQ-2024-SD201-HILLSBOROUGH

CERTIFICATE OF OCCUPANCY

This is to certify that the building or structure located at:
8820 N Dale Mabry Hwy, Tampa, FL 33614
Parcel ID: 076304-0000

has been inspected by the City of Tampa Construction Services Division and found to comply
with the City of Tampa Building Code, Florida Building Code (2020), and all applicable
ordinances and regulations for the following use:

USE AND OCCUPANCY
Occupancy Classification: M — Mercantile (Convenience retail) + S-1 (Fuel canopy)
Number of Stories: 1
Gross Floor Area: 4,200 sq ft (store) + 5,400 sq ft (canopy footprint)
Fire Suppression: NFPA 13 sprinkler system — INSTALLED AND TESTED
Fire Alarm: Addressable system — INSTALLED AND TESTED
ADA Compliance: Confirmed per 2010 ADA Standards

INSPECTIONS PASSED
- Framing inspection: November 14, 2024
- Electrical rough-in: November 22, 2024
- Plumbing rough-in: November 22, 2024
- Mechanical: December 10, 2024
- UST installation: Hillsborough County EPC inspection — December 5, 2024
- Fire sprinkler final: December 20, 2024
- Electrical final: January 3, 2025
- Building final: January 8, 2025

CONDITIONS
1. This certificate authorizes occupancy for the stated use only.
2. Any change of use requires a new Certificate of Occupancy.
3. Florida DABT alcohol license must be posted before alcohol sales begin.

Building Official: James R. Kowalski, CBO    Date: January 10, 2025
City of Tampa Construction Services
""")

# COMMAND ----------

write_doc("consultant_tampa_SD201_2024.txt", """
CONSULTANT STATUS MEMORANDUM — STORE DEVELOPMENT FEASIBILITY

Document ID: CONSULT-MEMO-2024-SD201
Document Type: consultant_correspondence
Project ID: SD-2024-201
Store Number: 5201
Address: 8820 N Dale Mabry Hwy, Tampa, FL 33614
Market: Tampa FL
State: FL
Municipality: City of Tampa
County: Hillsborough County
Requirement Type: licensing_status_summary
Requester: Ryan Holloway
Responder: Marcus Dawson
Response Date: 2024-08-20
Source Document: FEASY-EMAIL-2024-SD201; MUNI-REQ-2024-SD201-HILLSBOROUGH

From: Marcus Dawson <m.dawson@storedevelopmentconsulting.com>
To: Ryan Holloway <r.holloway@racetrac.com>; Kendra Patel <k.patel@racetrac.com>
Date: August 20, 2024
Subject: SD-2024-201 Tampa FL — Licensing Status Update (All Critical Licenses Secured)

Ryan, Kendra —

Project SD-2024-201 (Store #5201 — 8820 N Dale Mabry Hwy, Tampa) licensing is
substantially complete. Summary below.

LICENSES AND PERMITS — STATUS AS OF AUGUST 20, 2024

1. ZONING VERIFICATION LETTER (City of Tampa)
   Status: COMPLETE — Received April 10, 2024
   Finding: CI zoning — convenience retail + fuel station is permitted-by-right.
   No variance required.

2. FLORIDA DABT 2-APS ALCOHOL LICENSE
   Status: APPROVED — August 14, 2024
   License #: FL-DABT-2APS-HILL-2024-55291
   Distance clearance confirmed (0.72 mi from nearest school).
   Ready to activate upon Certificate of Occupancy.

3. FLORIDA TOBACCO DEALER PERMIT
   Status: APPROVED — May 28, 2024
   Permit #: FL-TOB-TDP-2024-SD201-88214
   No issues. Annual fee paid.

4. SITE PLAN APPROVAL (City of Tampa DRC)
   Status: APPROVED — June 18, 2024
   Canopy setback confirmed at 12 ft from right-of-way (exceeds 10 ft minimum).
   Landscaping buffer plan approved.

5. BUILDING PERMIT
   Status: ISSUED — July 8, 2024 (Permit #TAMPA-BP-2024-034892)
   Construction underway. Target completion: November 2024.

6. UST REGISTRATION (FDEP + Hillsborough County EPC)
   Status: Application submitted — August 15, 2024. Expected approval: September 2024.
   Three (3) USTs: 10,000 gal regular, 10,000 gal premium, 8,000 gal diesel.

7. HILLSBOROUGH COUNTY BUSINESS TAX RECEIPT
   Status: PENDING — will apply after Certificate of Use issued (expected Q4 2024).

OUTSTANDING ITEMS
- BTR application: Submit after CO issued (targeting November 2024)
- DABT designated manager update: Update with store manager name 30 days pre-opening
- RVP training: Schedule all staff for Responsible Vendor Program within 90 days of opening

RISK ASSESSMENT: LOW — No regulatory obstacles. On track for Q1 2025 opening.

Marcus Dawson
Principal Consultant — Store Development Consulting LLC
Phone: (404) 555-0187 | m.dawson@storedevelopmentconsulting.com
""")

# COMMAND ----------

write_doc("hist_response_tampa_SD201_2025.txt", """
HISTORICAL FEASIBILITY RESPONSE — PROJECT COMPLETION RECORD

Document ID: HIST-RESP-2025-SD201
Document Type: historical_response
Project ID: SD-2024-201
Store Number: 5201
Address: 8820 N Dale Mabry Hwy, Tampa, FL 33614
Market: Tampa FL
State: FL
Municipality: City of Tampa
County: Hillsborough County
Request Type: new_store_feasibility
Requester: Ryan Holloway
Responder: Kendra Patel
Response Date: 2025-01-15
Source Document: FEASY-EMAIL-2024-SD201; CONSULT-MEMO-2024-SD201
Priority: High
Status: COMPLETED — STORE OPENED

FEASIBILITY RESPONSE SUMMARY — PROJECT SD-2024-201 (TAMPA FL)

All licensing and permitting for RaceTrac Store #5201 at 8820 N Dale Mabry Hwy, Tampa FL
(Hillsborough County) has been completed. Store opened January 15, 2025.

FINAL LICENSING INVENTORY
1. Zoning Verification (CI — convenience retail): COMPLETE (2024-04-10)
2. City of Tampa Certificate of Occupancy: ISSUED (2025-01-10)
3. Hillsborough County Business Tax Receipt: ISSUED (2025-01-02)
4. Florida DABT 2-APS Beer & Wine License: ACTIVE (eff. 2024-08-14, expires 2025-09-30)
5. Florida Tobacco Dealer Permit: ACTIVE (eff. 2024-05-28, expires 2025-06-30)
6. FDEP UST Registration (3 tanks): REGISTERED (2024-10-01)
7. Hillsborough County EPC UST Operating Permit: ISSUED (2024-10-05)
8. NFPA 30A fuel dispenser permit: ISSUED (2025-01-08)

TIMELINE SUMMARY
Feasibility request submitted: 2024-03-15
Requirements memo completed: 2024-04-03
All license applications submitted: 2024-05-06
Final license (CO) issued: 2025-01-10
Store opened: 2025-01-15
Total elapsed time: 10.1 months

LESSONS LEARNED FOR FUTURE HILLSBOROUGH / TAMPA SITES
- Florida DABT 2-APS license: Expect 10–12 weeks (not the stated 8). Plan accordingly.
- Hillsborough County EPC UST permit: Apply at least 8 weeks before planned installation.
- Certificate of Use (City of Tampa) must precede BTR application — do not try to parallel.
- No distance exception issues in CI zone for this site. Confirm for future sites near churches/schools.

Municipality precedent established: City of Tampa / Hillsborough County — LOW COMPLEXITY.
Recommend this market for future expansion. Prior responses can be used as templates.

Completed By: Kendra Patel, Senior Development Analyst    Date: January 15, 2025
""")

# COMMAND ----------
# MAGIC %md ## Dallas TX — Project SD-2024-202 (Store #5202) — v2024 Regulatory Baseline

# COMMAND ----------

write_doc("feasy_email_dallas_SD202_2024.eml", """
From: Ryan Holloway <r.holloway@racetrac.com>
To: Kendra Patel <k.patel@racetrac.com>
CC: Marcus Dawson <m.dawson@storedevelopmentconsulting.com>
Date: July 8, 2024
Subject: FEASIBILITY REQUEST — Dallas TX — 4210 Lemmon Ave — Project SD-2024-202
Message-ID: <RT-FEASY-2024-SD202@racetrac.com>

Document ID: FEASY-EMAIL-2024-SD202
Document Type: feasibility_request
Project ID: SD-2024-202
Store Number: 5202
Address: 4210 Lemmon Ave, Dallas, TX 75219
Market: Dallas TX
State: TX
Municipality: City of Dallas
County: Dallas County
Request Type: new_store_feasibility
Requester: Ryan Holloway
Priority: High
Submitted Date: 2024-07-08

Kendra, Marcus —

Opening a feasibility review for the Lemmon Ave site in Dallas. Real estate has
executed an option agreement on 4210 Lemmon Ave (Dallas County, TX). Target opening:
Q4 2024 (aggressive — please prioritize).

SITE SUMMARY
Parcel: 00-A003-0000-00400 (Dallas County)
Current use: Vacant pad — prior QSR (demolished)
Lot size: ~1.05 acres
Current zoning: CR Community Retail — Dallas Development Code § 51A-4.211
Proposed use: Convenience retail (4,400 sq ft) + 8-pump fuel station

FEASIBILITY SCOPE REQUESTED
1. Dallas Development Services — zoning and site plan requirements
2. TABC beer/wine off-premise license (BF license) — standard track
3. Texas tobacco permit — Comptroller of Public Accounts
4. Dallas County business license / occupation tax
5. TCEQ PST registration for 3 underground storage tanks
6. Building permit lead times (Dallas permit office — large project queue)

NOTE: We have done prior deals in Dallas (see SD-2022-185 — Gaston Ave). Please
pull that historical response for any applicable precedents.

Priority: High. Please deliver requirements memo by July 22, 2024.

Ryan Holloway
Store Development Manager — Southeast/Southwest
RaceTrac Petroleum, Inc.
""")

# COMMAND ----------

write_doc("muni_req_dallas_TX_alcohol_v2024.txt", """
DALLAS DEVELOPMENT SERVICES — ALCOHOL LICENSE REQUIREMENTS SUMMARY
VERSION: v2024 (Effective through December 31, 2024)

Document ID: MUNI-REQ-2024-SD202-DALLAS-ALCOHOL-V2024
Document Type: municipal_requirement
Project ID: SD-2024-202
Store Number: 5202
Address: 4210 Lemmon Ave, Dallas, TX 75219
Market: Dallas TX
State: TX
Municipality: City of Dallas
County: Dallas County
Requirement Type: alcohol_license_requirements
Authority: City of Dallas Development Services; Texas Alcoholic Beverage Commission (TABC)
Prepared By: Kendra Patel, Senior Development Analyst
Response Date: 2024-07-19
Effective Date: 2024-01-01
Expiration Date: 2024-12-31
Source Document: FEASY-EMAIL-2024-SD202
Responder: Kendra Patel

DALLAS ALCOHOL LICENSE REQUIREMENTS — STANDARD PROCESS (v2024)

This document summarizes the requirements for obtaining a TABC Beer Retailer Off-Premise
License (BF) at a new RaceTrac site in the City of Dallas, Texas, as of January 1, 2024.

SECTION 1 — TABC LICENSE TYPE AND PROCESS
License Required: Beer Retailer Off-Premise (BF)
Issuing Authority: Texas Alcoholic Beverage Commission (TABC)
Applicable Law: Texas Alcoholic Beverage Code § 61 (Beer licenses); TABC Rule 33
License Fee: $394 biennial (every 2 years)
Process: Standard TABC Application — online via mytabc.tabc.texas.gov
  Step 1: File TABC application online ($394 fee)
  Step 2: TABC posts public notice (sign on property) for 30 days
  Step 3: TABC approval (if no protests) — standard track
  Step 4: Local government notification (City of Dallas notified by TABC automatically)

CITY OF DALLAS — ADDITIONAL REQUIREMENTS (v2024)
As of 2024, the City of Dallas does NOT impose additional city-level distance
requirements beyond the TABC state minimum:
  - State minimum distance: 300 ft from a public school (Texas Alcoholic Beverage Code § 109.33)
  - State minimum distance: 300 ft from a church (TABC § 109.33, absent local ordinance override)
  - City of Dallas: No additional distance requirements beyond state minimum for BF licenses.
    No city-level proximity certificate or distance waiver required as of v2024.

DISTANCE COMPLIANCE — SITE 4210 LEMMON AVE
Nearest school: Thomas Jefferson High School — 0.68 miles — COMPLIANT (> 300 ft)
Nearest church: St. Thomas Aquinas Catholic Church — 0.31 miles — COMPLIANT (> 300 ft)
No state or city distance exception required.

PROCESS TIMELINE (v2024 STANDARD)
Day 1: Submit TABC online application
Day 1–30: TABC public notice period (30-day sign posting required)
Day 30–45: TABC review and approval
Total Lead Time: 5–6 weeks from complete application

RENEWAL
License Period: Biennial (2-year license)
First Renewal: 2 years from issue date
Renewal Fee: $394

SECTION 2 — TABC SELLER/SERVER TRAINING
All employees who sell or serve alcohol must complete TABC-approved seller/server training.
Acceptable programs: TABC On the Call (online, ~2 hrs), TIPS, ServSafe Alcohol.
Training must be completed before employee makes first unsupervised alcohol sale.

SECTION 3 — CITY OF DALLAS CERTIFICATE OF OCCUPANCY
City of Dallas CO is required before TABC will activate the license.
CO obtained through Dallas Development Services after final building inspection.
Lead time for CO: 2–3 weeks after final inspection.

OVERALL ASSESSMENT (v2024): STRAIGHTFORWARD — Standard TABC process. No city-level hurdles.
Prepared By: Kendra Patel    Date: July 19, 2024
""")

# COMMAND ----------

write_doc("alcohol_license_dallas_SD202_v2024.txt", """
TEXAS ALCOHOLIC BEVERAGE COMMISSION — LICENSE APPROVAL

Document ID: LIC-TABC-TX-2024-SD202
Document Type: alcohol_license
Project ID: SD-2024-202
Store Number: 5202
Address: 4210 Lemmon Ave, Dallas, TX 75219
Market: Dallas TX
State: TX
Municipality: City of Dallas
County: Dallas County
License Type: Beer Retailer Off-Premise License (BF)
Issuing Authority: Texas Alcoholic Beverage Commission (TABC)
Application Date: 2024-08-05
Approval Date: 2024-09-16
Effective Date: 2024-09-16
Expiration Date: 2026-09-15
Renewal Period: Biennial (2-year)
License Number: TX-TABC-BF-DAL-2024-441892
Lead Time: 42 days
License Fee Paid: $394
Requirement Type: alcohol_retail_license
Responder: TABC Dallas District Office
Response Date: 2024-09-16
Source Document: MUNI-REQ-2024-SD202-DALLAS-ALCOHOL-V2024

TABC LICENSE ISSUANCE NOTICE

Licensee: RaceTrac Petroleum, Inc.
Premises: 4210 Lemmon Ave, Dallas, TX 75219
License Type: BF — Beer Retailer Off-Premise License
License Number: TX-TABC-BF-DAL-2024-441892
Issue Date: September 16, 2024
Expiration: September 15, 2026
Status: ACTIVE

LICENSE CONDITIONS
1. Authorized to sell beer for off-premise consumption only. Cider and malt beverages
   ≤ 5% ABV also authorized under BF license.
2. No sales of wine or spirits under this license (wine sales require separate license).
3. Sales hours: Monday–Sunday 7:00 AM – midnight (City of Dallas general ordinance).
4. Age verification: No sales to persons under 21 (Texas Alcoholic Beverage Code § 106.03).
5. All selling employees must have current TABC seller/server training certificate on file.
6. License must be posted at all times at the licensed premises.
7. No drive-through alcohol sales.

COMPLIANCE NOTE — STANDARD v2024 PROCESS APPLIED
This license was obtained under the standard Dallas BF process effective in 2024.
No city-level distance certification or proximity waiver was required at time of application.
(See MUNI-REQ-2024-SD202-DALLAS-ALCOHOL-V2024 for process documentation.)

RENEWAL
License expires: September 15, 2026
Renewal application must be submitted 30 days prior to expiration.
Biennial fee: $394.

Issued By: Texas Alcoholic Beverage Commission    Date: September 16, 2024
""")

# COMMAND ----------

write_doc("hist_response_dallas_SD202_2024.txt", """
HISTORICAL FEASIBILITY RESPONSE — PROJECT COMPLETION RECORD

Document ID: HIST-RESP-2024-SD202
Document Type: historical_response
Project ID: SD-2024-202
Store Number: 5202
Address: 4210 Lemmon Ave, Dallas, TX 75219
Market: Dallas TX
State: TX
Municipality: City of Dallas
County: Dallas County
Request Type: new_store_feasibility
Requester: Ryan Holloway
Responder: Kendra Patel
Response Date: 2024-12-10
Source Document: FEASY-EMAIL-2024-SD202; MUNI-REQ-2024-SD202-DALLAS-ALCOHOL-V2024
Priority: High
Status: COMPLETED — STORE OPENED 2024-12-05

FEASIBILITY RESPONSE SUMMARY — PROJECT SD-2024-202 (DALLAS TX)

RaceTrac Store #5202 at 4210 Lemmon Ave, Dallas TX opened December 5, 2024.
All licensing and permitting completed on schedule. 5-month timeline (July → December 2024).

FINAL LICENSING INVENTORY
1. City of Dallas Zoning Confirmation (CR Community Retail): COMPLETE (2024-07-25)
   Convenience retail + fuel station: permitted by right under CR.
2. City of Dallas Certificate of Occupancy: ISSUED (2024-11-22)
3. Dallas County Assumed Name / Business Registration: FILED (2024-07-30)
4. TABC BF Beer Retailer Off-Premise License: ACTIVE
   License #: TX-TABC-BF-DAL-2024-441892 (eff. 2024-09-16, expires 2026-09-15)
5. Texas Comptroller Tobacco Permit: ACTIVE (eff. 2024-08-20)
6. TCEQ PST Registration (3 USTs): REGISTERED (2024-10-12)
7. TCEQ UST Operator Certification (Class A/B/C): CURRENT

PROCESS NOTES — DALLAS TX v2024 (important for future projects)
- TABC BF license: Straightforward standard process. 42-day lead time (July 2024).
  No city-level distance certificate required under 2024 Dallas ordinances.
  300 ft state minimum distance from schools/churches — both easily met at this site.
- City of Dallas permitting queue: Building permit took 11 weeks (high backlog). Plan for 12 weeks.
- No distance waiver or special city approval needed for alcohol under current (v2024) rules.
  IMPORTANT: Verify city ordinances for any future Dallas applications — municipal code
  changes are possible. This response reflects requirements as of July–December 2024.

MUNICIPALITY PRECEDENT: City of Dallas — MODERATE COMPLEXITY (permitting queue).
Alcohol process: SIMPLE (v2024 standard track). No city-level alcohol restrictions.

Completed By: Kendra Patel, Senior Development Analyst    Date: December 10, 2024
""")

# COMMAND ----------
# MAGIC %md ## Dallas TX — Project SD-2025-203 (Store #5203) — v2025 New Distance Waiver Requirement

# COMMAND ----------

write_doc("feasy_email_dallas_SD203_2025.eml", """
From: Ryan Holloway <r.holloway@racetrac.com>
To: Kendra Patel <k.patel@racetrac.com>
CC: Marcus Dawson <m.dawson@storedevelopmentconsulting.com>
Date: February 3, 2025
Subject: FEASIBILITY REQUEST — Dallas TX — 6800 Greenville Ave — Project SD-2025-203
Message-ID: <RT-FEASY-2025-SD203@racetrac.com>

Document ID: FEASY-EMAIL-2025-SD203
Document Type: feasibility_request
Project ID: SD-2025-203
Store Number: 5203
Address: 6800 Greenville Ave, Dallas, TX 75231
Market: Dallas TX
State: TX
Municipality: City of Dallas
County: Dallas County
Request Type: new_store_feasibility
Requester: Ryan Holloway
Priority: High
Submitted Date: 2025-02-03

Kendra, Marcus —

New feasibility request for 6800 Greenville Ave, Dallas TX. Site looks great for a
new-build convenience/fuel location in the Greenville Avenue corridor.

Real estate executed an option on 6800 Greenville Ave, Dallas TX 75231 (Dallas County).
Target opening: Q4 2025.

SITE SUMMARY
Parcel: 00-B077-0000-00620 (Dallas County)
Lot: ~1.12 acres, former retail strip (partially demolished)
Current zoning: CR Community Retail
Proposed use: Convenience retail (4,200 sq ft) + 8-pump fuel station

FEASIBILITY SCOPE
1. TABC BF beer/wine license — please check if anything has changed since the Lemmon Ave deal
   (SD-2024-202). Marcus mentioned there may be a new Dallas ordinance affecting alcohol.
2. Full municipal requirements as usual
3. Building permit timeline

Please check the SD-2024-202 historical response for Dallas precedents.
Note: Marcus flagged a potential new city ordinance on alcohol distance requirements
(effective January 2025) — please verify and update requirements accordingly.

Target requirements memo: February 24, 2025.

Ryan Holloway
Store Development Manager — Southeast/Southwest
RaceTrac Petroleum, Inc.
""")

# COMMAND ----------

write_doc("muni_req_dallas_TX_alcohol_v2025.txt", """
DALLAS DEVELOPMENT SERVICES — ALCOHOL LICENSE REQUIREMENTS SUMMARY
VERSION: v2025 (Effective January 1, 2025 — Ordinance No. 32891)

Document ID: MUNI-REQ-2025-SD203-DALLAS-ALCOHOL-V2025
Document Type: municipal_requirement
Project ID: SD-2025-203
Store Number: 5203
Address: 6800 Greenville Ave, Dallas, TX 75231
Market: Dallas TX
State: TX
Municipality: City of Dallas
County: Dallas County
Requirement Type: alcohol_license_requirements
Authority: City of Dallas Development Services; Texas Alcoholic Beverage Commission (TABC)
Prepared By: Kendra Patel, Senior Development Analyst
Response Date: 2025-02-20
Effective Date: 2025-01-01
Expiration Date: 2025-12-31
Source Document: FEASY-EMAIL-2025-SD203
Responder: Kendra Patel

IMPORTANT — REGULATORY CHANGE NOTICE
This version (v2025) reflects a material change from the prior requirements summary
(MUNI-REQ-2024-SD202-DALLAS-ALCOHOL-V2024 dated July 2024).
City of Dallas Ordinance No. 32891, effective January 1, 2025, imposes new
distance-based requirements for off-premise alcohol retail licenses.
See Section 1.5 (Distance Exception Certificate) and the regulatory change document
REGULATORY-CHANGE-DALLAS-ALCOHOL-V2024-V2025.

DALLAS ALCOHOL LICENSE REQUIREMENTS — v2025

SECTION 1 — TABC LICENSE TYPE AND PROCESS
License Required: Beer Retailer Off-Premise (BF) [same as v2024]
Issuing Authority: Texas Alcoholic Beverage Commission (TABC) [same]
License Fee: $394 biennial [same]

SECTION 1.5 — NEW (v2025): CITY OF DALLAS DISTANCE EXCEPTION CERTIFICATE
*** CHANGE FROM v2024 — NEW REQUIREMENT EFFECTIVE JANUARY 1, 2025 ***

Dallas City Ordinance No. 32891 (adopted November 14, 2024; effective January 1, 2025)
amends Dallas City Code § 6-20 to require a "Distance Exception Certificate" (DEC) for
any new off-premise beer/wine retailer license application where the proposed premises
is located within 1,000 feet of:
  (a) A public, private, or charter school (K–12)
  (b) A church, synagogue, mosque, or other recognized place of worship
  (c) A licensed daycare or childcare facility

DISTANCE EXCEPTION CERTIFICATE — PROCESS
If the proposed premises is within 1,000 ft of any of the above protected uses:
  - Applicant MUST obtain a Distance Exception Certificate from Dallas Development Services
    PRIOR TO submitting the TABC application.
  - Application form: Dallas DEC Form 2025-ALC (available at dallascityhall.com/development)
  - Required attachments:
    (a) Certified site survey showing distances to all protected uses within 1,000 ft
    (b) Neighborhood impact statement (2-page max)
    (c) Letter of non-objection from protected use(s) within 500 ft, if obtainable
  - Dallas Development Services review: 30–45 days
  - Dallas City Council vote required if any protected use within 500 ft objects

DISTANCE COMPLIANCE — SITE 6800 GREENVILLE AVE (v2025)
*** DISTANCE EXCEPTION REQUIRED ***
Site survey confirms:
  Nearest school: Sudie L. Williams Elementary — 820 ft (< 1,000 ft threshold) — DEC REQUIRED
  Nearest church: First United Methodist Dallas — 940 ft (< 1,000 ft threshold) — DEC REQUIRED

Both protected uses are within 1,000 ft. Applicant must obtain Distance Exception Certificate
before TABC BF application can be submitted.

If both protected uses cooperate (letter of non-objection), DEC can be approved
administratively. If either objects, Dallas City Council vote required (adds 60–90 days).

REVISED PROCESS TIMELINE (v2025 — with DEC required)
Day 1: Commission site survey and prepare DEC application
Day 1–14: Site survey completed; DEC application prepared
Day 14–15: Submit DEC application to Dallas Development Services
Day 15–60: Dallas Development Services review (30–45 days, or longer if City Council required)
Day 60–61: DEC issued (assuming administrative track, no Council vote)
Day 61: Submit TABC BF application
Day 61–91: TABC public notice period (30 days)
Day 91–106: TABC review and approval
Total Lead Time: 14–16 weeks (vs. 5–6 weeks under v2024)
Additional Lead Time vs. v2024: 8–10 weeks

SECTION 2 — ALL OTHER REQUIREMENTS (unchanged from v2024)
- TABC seller/server training: Required for all selling employees
- City of Dallas Certificate of Occupancy: Required before TABC license activated
- TCEQ PST registration: Required for USTs
- Texas Comptroller tobacco permit: Required for tobacco sales

SECTION 3 — IMPACT ON SD-2025-203
This site REQUIRES a Distance Exception Certificate before TABC application.
Recommend immediate outreach to Sudie L. Williams Elementary and First United Methodist
to request letters of non-objection.
If both non-objection letters are obtained, DEC can be processed administratively (~45 days).
If not, budget for City Council vote process (add 60–90 days) — potential store opening delay
from Q4 2025 to Q1 2026.

ACTION REQUIRED: File DEC application immediately. Do not submit TABC application until DEC is in hand.

Prepared By: Kendra Patel    Date: February 20, 2025
""")

# COMMAND ----------

write_doc("regulatory_change_dallas_alcohol_v2024_v2025.txt", """
REGULATORY CHANGE DETECTED

Document ID: REGULATORY-CHANGE-DALLAS-ALCOHOL-V2024-V2025
Document Type: regulatory_change
Market: Dallas TX
State: TX
Municipality: City of Dallas
County: Dallas County
Requirement Type: alcohol_license_requirements
Authority: City of Dallas Development Services
Effective Date: 2025-01-01
Response Date: 2025-02-20
Responder: Kendra Patel
Source Documents: MUNI-REQ-2024-SD202-DALLAS-ALCOHOL-V2024; MUNI-REQ-2025-SD203-DALLAS-ALCOHOL-V2025

REGULATORY CHANGE DETECTED — City of Dallas Alcohol License Requirements
Municipality: City of Dallas, TX
Requirement Type: off-premise beer/wine retail license (TABC BF)
Change: Dallas City Ordinance No. 32891 (effective 2025-01-01)
Detected On: 2025-02-20
Detection Method: Feasibility review for SD-2025-203 vs. SD-2024-202 historical precedent

PREVIOUS REQUIREMENT (v2024 — effective through 2024-12-31)
Applicable Document: MUNI-REQ-2024-SD202-DALLAS-ALCOHOL-V2024
Summary: Standard TABC BF application process. City of Dallas imposed NO additional
  distance requirements beyond Texas state minimum (300 ft from schools and churches).
  No city-level proximity certificate or distance waiver required.
Lead Time: 5–6 weeks (TABC public notice + approval only)
City Approval Step: NONE beyond TABC notification

NEW REQUIREMENT (v2025 — effective 2025-01-01)
Applicable Document: MUNI-REQ-2025-SD203-DALLAS-ALCOHOL-V2025
Ordinance: City of Dallas Ordinance No. 32891 (adopted 2024-11-14; effective 2025-01-01)
Amends: Dallas City Code § 6-20
Change: New "Distance Exception Certificate" (DEC) required for any new off-premise
  beer/wine retailer within 1,000 ft of a school, church, or licensed daycare.
  If within 1,000 ft, applicant must obtain DEC from Dallas Development Services BEFORE
  submitting TABC application.
  DEC requires: certified site survey, neighborhood impact statement, and letters of
  non-objection from protected uses within 500 ft.
  If protected use within 500 ft objects: City Council vote required.
Lead Time (if DEC required): 14–16 weeks total (8–10 weeks longer than v2024)
City Approval Step: NEW — Distance Exception Certificate required at sites within 1,000 ft.

MATERIAL CHANGE SUMMARY
| Dimension              | v2024 (old)                          | v2025 (new)                             |
|------------------------|--------------------------------------|-----------------------------------------|
| City distance rule     | None (state 300 ft minimum only)     | 1,000 ft from schools/churches/daycares |
| City approval step     | None                                 | Distance Exception Certificate required |
| Lead time (DEC sites)  | 5–6 weeks                            | 14–16 weeks                             |
| Process complexity     | Low — TABC only                      | Moderate–High if DEC required           |
| Council vote risk      | None                                 | Yes, if protected use within 500 ft     |

IMPACT ASSESSMENT
Affected Current Projects:
  - SD-2025-203 (Store #5203, 6800 Greenville Ave, Dallas TX): DEC REQUIRED
    Nearest school 820 ft; nearest church 940 ft — both within 1,000 ft.
    Project opening may slip from Q4 2025 to Q1 2026 if DEC process delayed.

Future Dallas Projects:
  All future Dallas off-premise alcohol applications must check new 1,000 ft threshold.
  Recommend adding distance check to RaceTrac site-selection criteria before option execution.
  Sites within 1,000 ft should be flagged Red (proceed with caution) in site scoring model.

Prior Projects (not affected):
  - SD-2024-202 (Store #5202, 4210 Lemmon Ave): TABC license already obtained under v2024.
    Not subject to retroactive DEC requirement. License remains valid through 2026-09-15.

RECOMMENDED ACTIONS
1. Immediately initiate DEC application for SD-2025-203 (target file date: 2025-02-28).
2. Update site-selection screening model to add 1,000 ft Dallas distance buffer.
3. Notify Real Estate team: future Dallas land options should require confirmed > 1,000 ft
   distance from schools, churches, and daycares (or budget 14-16 week alcohol timeline).
4. Monitor for similar distance-waiver ordinances in other Texas cities (Austin, Houston,
   San Antonio) — trend may spread.

Prepared By: Kendra Patel, Senior Development Analyst    Date: February 20, 2025
""")

# COMMAND ----------

write_doc("consultant_dallas_SD203_2025.txt", """
CONSULTANT ADVISORY MEMORANDUM — REGULATORY CHANGE IMPACT

Document ID: CONSULT-MEMO-2025-SD203
Document Type: consultant_correspondence
Project ID: SD-2025-203
Store Number: 5203
Address: 6800 Greenville Ave, Dallas, TX 75231
Market: Dallas TX
State: TX
Municipality: City of Dallas
County: Dallas County
Requirement Type: alcohol_license_requirements
Requester: Ryan Holloway
Responder: Marcus Dawson
Response Date: 2025-02-18
Source Document: REGULATORY-CHANGE-DALLAS-ALCOHOL-V2024-V2025; FEASY-EMAIL-2025-SD203

From: Marcus Dawson <m.dawson@storedevelopmentconsulting.com>
To: Ryan Holloway <r.holloway@racetrac.com>; Kendra Patel <k.patel@racetrac.com>
Date: February 18, 2025
Subject: SD-2025-203 — Dallas Greenville Ave — ALERT: New Distance Waiver Required (Ordinance 32891)

Ryan, Kendra —

URGENT advisory regarding Project SD-2025-203 (6800 Greenville Ave, Dallas TX).

After the Lemmon Ave deal (SD-2024-202) closed in December, Dallas passed a new ordinance
(Ordinance No. 32891, effective January 1, 2025) that materially changes the alcohol
licensing process for convenience retailers. I want to make sure you are aware before we
file anything.

WHAT CHANGED
Previously (through December 31, 2024): Standard TABC BF application, no city-level
review. We sailed through SD-2024-202 in 42 days with no city approval needed.

Now (January 1, 2025 forward): If the site is within 1,000 feet of a school, church,
or daycare, you must obtain a "Distance Exception Certificate" (DEC) from Dallas
Development Services BEFORE filing the TABC application. The DEC process adds
roughly 8–10 weeks and requires a site survey, neighborhood impact statement, and
outreach to affected institutions.

IMPACT ON SD-2025-203
I ran a preliminary distance check on 6800 Greenville Ave:
  - Sudie L. Williams Elementary School: approximately 820 feet — within 1,000 ft
  - First United Methodist Dallas: approximately 940 feet — within 1,000 ft

Both trigger the DEC requirement. We need the certificate before we can even touch
the TABC application.

MY RECOMMENDATIONS
1. Start the DEC application NOW — I can assist with the site survey and neighborhood
   impact statement. If we file by March 1, we should have the DEC by mid-April.
2. Reach out to both institutions early. A letter of non-objection from each makes
   this administrative (45 days). If either objects, Dallas City Council gets involved
   and we could lose 2–3 additional months.
3. I strongly recommend having someone from RaceTrac meet personally with the principals
   at Sudie L. Williams and the church leadership. Personal outreach is more effective
   than a form letter for obtaining non-objection letters.
4. Update your site-selection model. Any future Dallas sites within 1,000 ft of these
   protected uses should be flagged before option execution. I can help you map the
   exposure across your pipeline.

REVISED SCHEDULE
If DEC filed March 1 and both non-objection letters obtained:
  DEC issued: ~April 15, 2025
  TABC application filed: April 16, 2025
  TABC approval: ~May 26, 2025
  CO + activation: ~July 2025
  Store opening: Q3–Q4 2025 (likely slips from target Q4 2025 to Q3 2025 if DEC is smooth;
    or Q1 2026 if City Council involvement needed)

Please confirm how you want to proceed. I am available for a call this week.

Marcus Dawson
Principal Consultant — Store Development Consulting LLC
""")

# COMMAND ----------
# MAGIC %md ## Atlanta GA — Project SD-2023-204 (Store #5204) — Historical Response

# COMMAND ----------

write_doc("feasy_email_atlanta_SD204_2023.eml", """
From: Ryan Holloway <r.holloway@racetrac.com>
To: Kendra Patel <k.patel@racetrac.com>
Date: September 5, 2023
Subject: FEASIBILITY REQUEST — Atlanta GA — 4900 Roswell Rd NE — Project SD-2023-204
Message-ID: <RT-FEASY-2023-SD204@racetrac.com>

Document ID: FEASY-EMAIL-2023-SD204
Document Type: feasibility_request
Project ID: SD-2023-204
Store Number: 5204
Address: 4900 Roswell Rd NE, Atlanta, GA 30342
Market: Atlanta GA
State: GA
Municipality: City of Atlanta
County: Fulton County
Request Type: new_store_feasibility
Requester: Ryan Holloway
Priority: Medium
Submitted Date: 2023-09-05

Kendra —

Please open a feasibility review for 4900 Roswell Rd NE, Atlanta GA (Fulton County / Sandy Springs corridor).
Site is currently a vacant former gas station. Real estate has an option agreement.

SITE SUMMARY
Address: 4900 Roswell Rd NE, Atlanta, GA 30342 (Fulton County, City of Atlanta jurisdiction)
Parcel: 17-0100-0002-014-2 (Fulton County)
Lot size: ~0.92 acres
Current zoning: C-1 (Light Commercial) per City of Atlanta Zoning Code
Proposed use: Convenience retail + 6-pump fuel station

FEASIBILITY SCOPE
1. City of Atlanta and Fulton County licensing requirements
2. Georgia DABT: Retailer's Beer License (beer/wine off-premise)
3. Georgia DOR tobacco dealer permit
4. Fulton County occupation tax
5. Zoning compatibility for fuel station under C-1

Priority: Medium. Target opening Q1 2024. Please deliver requirements memo by September 22, 2023.

Ryan Holloway
""")

# COMMAND ----------

write_doc("muni_req_fulton_GA_2023.txt", """
MUNICIPAL REQUIREMENTS SUMMARY — STORE DEVELOPMENT FEASIBILITY

Document ID: MUNI-REQ-2023-SD204-FULTON
Document Type: municipal_requirement
Project ID: SD-2023-204
Store Number: 5204
Address: 4900 Roswell Rd NE, Atlanta, GA 30342
Market: Atlanta GA
State: GA
Municipality: City of Atlanta
County: Fulton County
Requirement Type: municipal_licensing_summary
Authority: City of Atlanta Office of Planning; Fulton County Tax Commissioner
Prepared By: Kendra Patel, Senior Development Analyst
Response Date: 2023-09-20
Effective Date: 2023-01-01
Source Document: FEASY-EMAIL-2023-SD204
Responder: Kendra Patel

EXECUTIVE SUMMARY
Site at 4900 Roswell Rd NE, Atlanta GA (Fulton County) is feasible. Former gas-station
use is advantageous — FDEP/EPD remediation clearance may already exist; confirm with
property owner. C-1 zoning supports convenience retail + fuel (by right). No significant
licensing obstacles identified. Alcohol license requires prior-activity review on the parcel.

SECTION 1 — ZONING
Authority: City of Atlanta Planning, (404) 330-6145
Current Zoning: C-1 (Light Commercial)
Proposed Use: Convenience retail + motor fuel dispensing
Compatibility: PERMITTED — fuel stations are accessory to C-1 retail uses when on lots > 0.75 acres.
  Site at 0.92 acres meets threshold.
Variance Required: None for principal use. Confirm canopy setbacks in site plan review.
Lead Time: 2 weeks for written zoning confirmation
Requirement Type: zoning_clearance

SECTION 2 — ALCOHOL LICENSE (BEER AND WINE OFF-PREMISE)
Authority: Georgia Department of Revenue — Alcohol and Tobacco Division; City of Atlanta License
  and Permits Unit
License Type: Retailer's Beer License (off-premise consumption) + Package Wine Dealer License
Issuing Authority: Georgia DOR; City of Atlanta (ATL license required in addition)
Applicable Law: Georgia Code § 3-3; Atlanta Code of Ordinances § 10-36
Requirements:
  - City of Atlanta off-premise alcohol license ($175 application fee; $550 annual)
  - Georgia DOR retailer registration (online; ~$50)
  - Designated manager background check (City of Atlanta requirement)
  - Distance: Must be ≥ 100 ft from schools, churches per Atlanta Code § 10-36.6
    Nearest school: Atlanta International School — 0.38 miles — COMPLIANT
    Nearest church: Johnson Memorial United Methodist — 0.22 miles — COMPLIANT
  - Prior-activity check: Site is former gas station. City of Atlanta requires confirmation
    that prior license at site (if any) was in good standing. Verify with City.
Lead Time: 8–12 weeks
Renewal Period: Annual (January 1 renewal deadline)
License Fee: $550 annual (City of Atlanta)

SECTION 3 — TOBACCO
Authority: Georgia Department of Revenue — Alcohol and Tobacco Division
License Type: Retail Tobacco Dealer License
Applicable Law: Georgia Code § 48-11; Georgia Rule 560-10-1
Lead Time: 2–3 weeks
Renewal Period: Annual
License Fee: $125

SECTION 4 — FULTON COUNTY OCCUPATION TAX
Authority: Fulton County Tax Commissioner
License Type: Occupation Tax Certificate
Applicable Law: Fulton County Code § 22-23 (Occupation Tax)
Requirements: Completed application; Georgia business registration; Certificate of Occupancy
Lead Time: 1–2 weeks
Renewal Period: Annual (January 1)
Fee: $200–$350 (convenience retail category)

SECTION 5 — BUILDING AND SITE
Authority: City of Atlanta Office of Buildings
Key Items:
  - Site plan review and approval (12–16 weeks)
  - Building permit for new construction (10–14 weeks after site plan approval)
  - Georgia EPD UST registration for underground storage tanks
  - Prior-use Phase I/II environmental clearance from prior UST site: Confirm with real estate.

OVERALL ASSESSMENT: FEASIBLE — LOW COMPLEXITY. Former gas-station site may accelerate UST permitting.

Prepared By: Kendra Patel    Date: September 20, 2023
""")

# COMMAND ----------

write_doc("business_license_fulton_GA_SD204_2024.txt", """
FULTON COUNTY TAX COMMISSIONER — OCCUPATION TAX CERTIFICATE

Document ID: OTC-FULTON-2024-SD204
Document Type: business_license
Project ID: SD-2023-204
Store Number: 5204
Address: 4900 Roswell Rd NE, Atlanta, GA 30342
Market: Atlanta GA
State: GA
Municipality: City of Atlanta
County: Fulton County
License Type: Occupation Tax Certificate — Convenience Store with Motor Fuel
Issuing Authority: Fulton County Tax Commissioner
Certificate Number: FULTON-OTC-2024-008412
Application Date: 2024-01-15
Issue Date: 2024-01-29
Effective Date: 2024-01-29
Expiration Date: 2024-12-31
Renewal Period: Annual (January 1)
License Fee Paid: $275
Lead Time: 14 days
Requirement Type: occupation_tax_certificate
Responder: Fulton County Tax Commissioner Office
Response Date: 2024-01-29
Source Document: MUNI-REQ-2023-SD204-FULTON

OCCUPATION TAX CERTIFICATE

Business Name: RaceTrac Petroleum, Inc.
Trade Name: RaceTrac Store #5204
Location: 4900 Roswell Rd NE, Atlanta, GA 30342
Business Classification: Convenience Store with Motor Fuel (SIC 5541)
Owner/Authorized Agent: Ryan Holloway

Pursuant to Fulton County Code § 22-23, this certificate authorizes the conduct
of business at the stated location.

CONDITIONS
1. Certificate must be renewed annually by January 31 of each year.
2. Certificate is non-transferable; change of ownership requires new application.
3. City of Atlanta Certificate of Occupancy must remain active.
4. State licenses (Georgia DOR alcohol, tobacco) must be current and posted.
5. Any material change in business type requires updated occupation tax application.
6. Late renewal fee: $50 per month (after January 31).

ASSOCIATED LICENSES ON FILE
- City of Atlanta Beer & Wine Off-Premise License: ATL-BWO-2024-00291 (active)
- Georgia DOR Tobacco Dealer License: GA-TOB-2024-SD204-00412 (active)
- Georgia EPD UST Registration: GA-EPD-UST-2024-SD204 (active)

Issued By: Fulton County Tax Commissioner    Date: January 29, 2024
""")

# COMMAND ----------

write_doc("hist_response_atlanta_SD204_2024.txt", """
HISTORICAL FEASIBILITY RESPONSE — PROJECT COMPLETION RECORD

Document ID: HIST-RESP-2024-SD204
Document Type: historical_response
Project ID: SD-2023-204
Store Number: 5204
Address: 4900 Roswell Rd NE, Atlanta, GA 30342
Market: Atlanta GA
State: GA
Municipality: City of Atlanta
County: Fulton County
Request Type: new_store_feasibility
Requester: Ryan Holloway
Responder: Kendra Patel
Response Date: 2024-03-08
Source Document: FEASY-EMAIL-2023-SD204; MUNI-REQ-2023-SD204-FULTON
Priority: Medium
Status: COMPLETED — STORE OPENED 2024-02-20

FEASIBILITY RESPONSE SUMMARY — PROJECT SD-2023-204 (ATLANTA GA)

RaceTrac Store #5204 at 4900 Roswell Rd NE, Atlanta GA opened February 20, 2024.
5.5 month timeline (September 2023 → February 2024).

FINAL LICENSING INVENTORY
1. City of Atlanta Zoning Confirmation (C-1): COMPLETE (2023-09-28)
2. City of Atlanta Certificate of Occupancy: ISSUED (2024-02-12)
3. City of Atlanta Beer & Wine Off-Premise License: ACTIVE
   License #: ATL-BWO-2024-00291 (eff. 2024-01-10, expires 2024-12-31)
   Prior-activity check: Former license at site in good standing — no issues.
4. Georgia DOR Tobacco Dealer License: ACTIVE
   License #: GA-TOB-2024-SD204-00412 (eff. 2023-10-25, expires 2024-12-31)
5. Fulton County Occupation Tax Certificate: ISSUED (2024-01-29)
   Certificate #: FULTON-OTC-2024-008412
6. Georgia EPD UST Registration (2 USTs, 10,000 gal + 8,000 gal): REGISTERED (2023-11-18)
7. Phase I ESA: Clean (former UST remediation completed 2019 — no residual contamination)

PROCESS NOTES — ATLANTA / FULTON COUNTY
- City of Atlanta alcohol license: 11 weeks lead time (slightly longer than estimated 8–12).
  Designated manager background check took 3 weeks longer than expected.
  Recommendation: Start background check submission immediately upon site option execution.
- Prior-activity check (former gas station): Resolved smoothly. Prior operator's license
  was in good standing. No issues.
- Phase I ESA on former UST site: Favorable outcome. Saves significant time vs. new UST installation.
  Always confirm prior remediation status during site selection.
- C-1 zoning was confirmed — fuel station accessory use approved on first pass.
- City of Atlanta permitting queue: 11 weeks for building permit. Plan accordingly.

MUNICIPALITY PRECEDENT: City of Atlanta / Fulton County — LOW COMPLEXITY.
Alcohol process: MODERATE (11 weeks; background check is rate-limiting step).
No distance waivers or special city approvals needed.

Completed By: Kendra Patel, Senior Development Analyst    Date: March 8, 2024
""")

# COMMAND ----------
# MAGIC %md ## Summary — Corpus Manifest

# COMMAND ----------

DOCS = [
    # Tampa FL — SD-2024-201
    "feasy_email_tampa_SD201_2024.eml",
    "muni_req_hillsborough_FL_2024.txt",
    "alcohol_license_hillsborough_SD201_2024.txt",
    "tobacco_license_hillsborough_SD201_2024.txt",
    "zoning_hillsborough_SD201_2024.txt",
    "business_license_hillsborough_SD201_2025.txt",
    "permit_co_tampa_SD201_2025.txt",
    "consultant_tampa_SD201_2024.txt",
    "hist_response_tampa_SD201_2025.txt",
    # Dallas TX — SD-2024-202 (v2024 baseline)
    "feasy_email_dallas_SD202_2024.eml",
    "muni_req_dallas_TX_alcohol_v2024.txt",
    "alcohol_license_dallas_SD202_v2024.txt",
    "hist_response_dallas_SD202_2024.txt",
    # Dallas TX — SD-2025-203 (v2025 new distance waiver)
    "feasy_email_dallas_SD203_2025.eml",
    "muni_req_dallas_TX_alcohol_v2025.txt",
    "regulatory_change_dallas_alcohol_v2024_v2025.txt",
    "consultant_dallas_SD203_2025.txt",
    # Atlanta GA — SD-2023-204 (historical)
    "feasy_email_atlanta_SD204_2023.eml",
    "muni_req_fulton_GA_2023.txt",
    "business_license_fulton_GA_SD204_2024.txt",
    "hist_response_atlanta_SD204_2024.txt",
]

present = [d for d in DOCS if os.path.exists(os.path.join(OUTPUT_DIR, d))]
missing = [d for d in DOCS if not os.path.exists(os.path.join(OUTPUT_DIR, d))]

print(f"\n{'='*60}")
print(f"Corpus summary — {len(present)}/{len(DOCS)} documents written")
print(f"Output directory: {OUTPUT_DIR}")
print(f"{'='*60}")
print("\nDocument manifest:")
for fname in present:
    size = os.path.getsize(os.path.join(OUTPUT_DIR, fname))
    print(f"  {fname}  ({size:,} bytes)")
if missing:
    print(f"\nMISSING ({len(missing)}):")
    for fname in missing:
        print(f"  {fname}")
print(f"\n{'='*60}")
print("Classification label coverage:")
label_map = {
    "feasibility_request":       [f for f in present if f.startswith("feasy_")],
    "municipal_requirement":     [f for f in present if f.startswith("muni_req_")],
    "alcohol_license":           [f for f in present if f.startswith("alcohol_")],
    "tobacco_license":           [f for f in present if f.startswith("tobacco_")],
    "business_license":          [f for f in present if f.startswith("business_")],
    "zoning_document":           [f for f in present if f.startswith("zoning_")],
    "permit":                    [f for f in present if f.startswith("permit_")],
    "historical_response":       [f for f in present if f.startswith("hist_")],
    "regulatory_change":         [f for f in present if f.startswith("regulatory_")],
    "consultant_correspondence": [f for f in present if f.startswith("consultant_")],
}
for label, files in label_map.items():
    status = "OK" if files else "MISSING"
    print(f"  {label:30s}: {len(files)} doc(s)  [{status}]")
