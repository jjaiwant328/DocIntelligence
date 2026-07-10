# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Synthetic Document Corpus
# MAGIC
# MAGIC Generates 13 realistic QSR supply chain documents and writes them to
# MAGIC `/Volumes/jai_docintel/raw/documents/` as plain-text files.
# MAGIC
# MAGIC The documents are designed around a single cold chain incident:
# MAGIC - **Shipment:** SHP-20240315 (Tyson Foods → Atlanta DC)
# MAGIC - **Incident:** Trailer TR-8821 refrigeration failure, 68 minutes, peak 48°F
# MAGIC - **Recall:** Lot PP-240315, 12 restaurants affected

# COMMAND ----------

CATALOG     = "jai_docintel"
SCHEMA_RAW  = "raw"
VOLUME_DOCS = "documents"
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA_RAW}/{VOLUME_DOCS}"

# COMMAND ----------

import os

def write_doc(filename: str, content: str):
    path = f"{VOLUME_PATH}/{filename}"
    with open(path, "w") as f:
        f.write(content.strip())
    print(f"Written: {filename}")

# COMMAND ----------
# MAGIC %md ## Document 1 — Supplier Contract

# COMMAND ----------

write_doc("supplier_contract_tyson_poultry.txt", """
MASTER SUPPLY AGREEMENT

Agreement Number: MSA-2024-TF-001
Effective Date: January 1, 2024
Expiration Date: December 31, 2025

PARTIES
Supplier: Tyson Foods, Inc. (hereinafter "Supplier")
Purchaser: Golden Arch Supply Partners, LLC (hereinafter "Purchaser")

1. PRODUCTS AND SPECIFICATIONS
Supplier agrees to supply fresh and frozen poultry products including chicken sandwich fillets,
spicy crispy chicken, chicken nuggets, and chicken tenders meeting USDA Grade A standards.

2. SERVICE LEVEL AGREEMENT
   2.1 On-Time Delivery (OTD): Minimum 95% within scheduled delivery window
   2.2 Fill Rate: Minimum 98% of ordered quantities per shipment
   2.3 Defect Rate: Maximum 0.5% defective units per lot
   2.4 Cold Chain Compliance: 100% of shipments must maintain temperature ≤ 40°F throughout transit

3. TEMPERATURE AND COLD CHAIN REQUIREMENTS
   3.1 Product must be maintained at or below 40°F (4.4°C) at all times during transport
   3.2 Temperature excursion threshold: Any reading above 40°F constitutes a potential excursion
   3.3 CRITICAL: Supplier assumes full liability if shipment temperature exceeds 40°F
       for a continuous period exceeding 30 minutes during transport
   3.4 Carrier must provide continuous temperature monitoring logs for all refrigerated shipments
   3.5 Temperature data must be available within 24 hours of delivery request

4. LIABILITY AND PENALTY CLAUSES
   4.1 Temperature Excursion Penalty:
       - Excursion 41–44°F for 30–60 min: $5,000 per incident + cost of inspection
       - Excursion 44–48°F for any duration: $15,000 per incident + product rejection rights
       - Excursion above 48°F for any duration: Full lot rejection + $25,000 penalty + recall costs
   4.2 In cases of confirmed temperature excursion causing product recall, Supplier is liable for:
       - Full cost of product recall and disposal
       - Distribution center quarantine costs
       - Customer notification and remediation costs
       - Lost revenue at affected restaurant locations (capped at $500,000 per incident)
   4.3 Supplier must maintain minimum $10,000,000 product liability insurance

5. QUALITY INCIDENTS
   5.1 Any quality incident must be reported within 4 hours of discovery
   5.2 Root cause analysis required within 72 hours
   5.3 Corrective action plan required within 7 business days

6. RECALL PROCEDURES
   6.1 Supplier must immediately notify Purchaser upon suspicion of recall-level quality issue
   6.2 All affected lots must be traceable within 2 hours using provided lot tracking system
   6.3 Supplier bears full financial responsibility for Class I and Class II recalls caused by supplier error

SIGNATURES
For Tyson Foods, Inc.: ___________________  Date: January 1, 2024
For Golden Arch Supply Partners: ___________________  Date: January 1, 2024
""")

# COMMAND ----------
# MAGIC %md ## Document 2 — Bill of Lading

# COMMAND ----------

write_doc("bill_of_lading_SHP-20240315.txt", """
BILL OF LADING — STRAIGHT BILL
Not Negotiable

Shipment ID: SHP-20240315
Date of Issue: March 15, 2024

SHIPPER (FROM)
Company: Tyson Foods, Inc. — Springdale Processing Facility
Address: 2200 Don Tyson Parkway, Springdale, AR 72762
Contact: Logistics Dept — logistics@tysonfoods.com

CONSIGNEE (TO)
Company: Golden Arch Supply Partners — Atlanta Distribution Center
Address: 1850 Distribution Drive, Atlanta, GA 30339
Contact: Receiving Dept — atl-receiving@goldenasp.com

CARRIER
Company: Swift Logistics Inc.
Driver: Marcus Thompson (CDL# GA-MT-2847)
Trailer ID: TR-8821
Tractor ID: SL-4492

PICKUP
Scheduled: March 15, 2024 06:00 AM CST
Actual: March 15, 2024 06:23 AM CST
Facility Temperature at Load: 36°F

DELIVERY
Scheduled: March 15, 2024 02:00 PM EST
Actual: March 15, 2024 03:47 PM EST
Reason for Delay: Traffic congestion I-20 Atlanta corridor

COMMODITY DESCRIPTION
Lot Number: LOT-PP-240315
Product: Fresh Chicken Sandwich Fillets (Item #CSF-001)
Quantity: 480 cases / 14,400 lbs
Pack Size: 30 lbs per case
Temperature Requirement: ≤ 40°F continuous
Pallet Count: 24 pallets

SPECIAL INSTRUCTIONS
Refrigerated freight — maintain temperature ≤ 40°F at all times.
Temperature monitoring logger (DataTrace MPIII) installed in trailer.
Temperature log to be provided to consignee upon delivery.

SEAL NUMBERS
Front Seal: 8842917
Rear Seal: 8842918

FREIGHT CHARGES: Prepaid
DECLARED VALUE: $86,400

Shipper Signature: ___________________ Date: March 15, 2024 06:23 AM
Driver Signature: Marcus Thompson Date: March 15, 2024 06:23 AM
Consignee Signature: ___________________ Date: March 15, 2024 03:47 PM
""")

# COMMAND ----------
# MAGIC %md ## Document 3 — Temperature Monitoring Log

# COMMAND ----------

write_doc("temperature_log_TR-8821_SHP-20240315.txt", """
CONTINUOUS TEMPERATURE MONITORING REPORT
DataTrace MPIII Temperature Logger

Logger Serial: DT-MPIII-448821
Trailer ID: TR-8821
Shipment ID: SHP-20240315
Carrier: Swift Logistics Inc.
Route: Springdale AR → Atlanta GA

Report Period: 2024-03-15 06:23 AM CST to 2024-03-15 03:47 PM EST
Total Runtime: 9 hours 24 minutes
Recording Interval: 5 minutes
Threshold Setting: 40°F (alarm threshold: 41°F)

SUMMARY
Total Readings: 113
Readings In Range (≤ 40°F): 93 (82.3%)
Readings Out of Range (> 40°F): 20 (17.7%)
Maximum Temperature Recorded: 48.2°F
Duration Above Threshold: 68 minutes (EXCURSION CONFIRMED)
Excursion Start: 2024-03-15 10:15 AM CST
Excursion End: 2024-03-15 11:23 AM CST

TEMPERATURE LOG (Selected readings — full log appended)
Timestamp (CST)        Temp (°F)   Status
2024-03-15 06:30       37.1        OK
2024-03-15 06:45       36.8        OK
2024-03-15 07:00       37.2        OK
2024-03-15 07:15       36.9        OK
2024-03-15 07:30       37.4        OK
2024-03-15 08:00       37.1        OK
2024-03-15 08:30       37.8        OK
2024-03-15 09:00       38.2        OK
2024-03-15 09:30       38.7        OK
2024-03-15 10:00       39.1        OK
2024-03-15 10:15       40.8        ALARM — EXCURSION START
2024-03-15 10:20       42.3        EXCURSION
2024-03-15 10:25       44.1        EXCURSION
2024-03-15 10:30       45.6        EXCURSION
2024-03-15 10:35       46.8        EXCURSION
2024-03-15 10:40       47.4        EXCURSION
2024-03-15 10:45       48.2        EXCURSION — PEAK
2024-03-15 10:50       47.8        EXCURSION
2024-03-15 10:55       46.9        EXCURSION
2024-03-15 11:00       45.3        EXCURSION
2024-03-15 11:05       43.8        EXCURSION
2024-03-15 11:10       42.1        EXCURSION
2024-03-15 11:15       41.4        EXCURSION
2024-03-15 11:23       40.2        EXCURSION — END (≤40°F restored)
2024-03-15 11:30       38.9        OK
2024-03-15 12:00       38.1        OK
2024-03-15 12:30       37.8        OK
2024-03-15 01:00       37.3        OK
2024-03-15 01:30       37.1        OK
2024-03-15 02:00       37.4        OK
2024-03-15 02:30       37.2        OK
2024-03-15 03:00       37.8        OK
2024-03-15 03:47       37.6        OK — DELIVERY

EXCURSION DETAIL
Duration: 68 minutes (10:15 AM — 11:23 AM CST)
Peak Temperature: 48.2°F at 10:45 AM CST
Temperature differential from threshold: +8.2°F
Probable cause: Refrigeration unit compressor failure (see maintenance log)
Recovery method: Unit restarted at 11:10 AM CST, temperature recovery confirmed by 11:23 AM

COMPLIANCE STATUS: NON-COMPLIANT
Threshold exceeded by 8.2°F for 68 consecutive minutes.
Per MSA-2024-TF-001 Section 3.3: SUPPLIER LIABILITY TRIGGERED
Recommended action: Hold product, notify QA, initiate quality incident report.
""")

# COMMAND ----------
# MAGIC %md ## Document 4 — Certificate of Analysis

# COMMAND ----------

write_doc("certificate_of_analysis_LOT-PP-240315.txt", """
CERTIFICATE OF ANALYSIS

Document Number: COA-2024-0315-PP
Issue Date: March 14, 2024
Certificate Valid Until: Use-by date on packaging

MANUFACTURER INFORMATION
Facility: Tyson Foods, Inc. — Springdale Processing Facility
Address: 2200 Don Tyson Parkway, Springdale, AR 72762
USDA Establishment: EST. 244
FSSC 22000 Certified: Yes (Cert# FSSC-TF-AR-244)

PRODUCT INFORMATION
Product Name: Fresh Chicken Sandwich Fillets
Item Number: CSF-001
Lot Number: LOT-PP-240315
Production Date: March 14, 2024
Production Run: 06:00 AM — 02:00 PM CST
Quantity Produced: 14,400 lbs (480 cases)
Best-By Date: March 28, 2024
Storage Requirement: Maintain at or below 40°F

PHYSICAL ATTRIBUTES
Appearance: Uniform golden-brown, no visible defects
Texture: Firm, no soft spots
Color (CIE L*): 68.2 (within spec: 62–74)
Average Weight (per fillet): 4.8 oz (within spec: 4.5–5.2 oz)

MICROBIOLOGICAL RESULTS (pre-shipment sampling, March 14, 2024)
Test                    Result        Specification    Status
Total Plate Count       1,200 CFU/g   < 50,000 CFU/g  PASS
Coliform                < 10 CFU/g    < 100 CFU/g     PASS
E. coli                 < 3 MPN/g     < 10 MPN/g      PASS
Salmonella (25g)        Not Detected  Not Detected     PASS
Listeria mono (25g)     Not Detected  Not Detected     PASS
Campylobacter (25g)     Not Detected  Not Detected     PASS
Staphylococcus aureus   < 10 CFU/g    < 100 CFU/g     PASS

NOTE: Microbiological results above reflect pre-shipment condition.
Results may be invalidated if cold chain is compromised during transport.
Any temperature excursion above 40°F for more than 30 minutes requires
re-testing before product release. See QSF-0022 Cold Chain Protocol.

CHEMICAL ATTRIBUTES
Moisture Content: 67.8% (within spec: 65–72%)
Protein: 19.4% (within spec: > 18%)
Fat: 9.2% (within spec: < 12%)
Sodium: 420 mg/100g (within spec: < 450 mg)

QUALITY SIGN-OFF
QA Manager: Dr. Sarah Mitchell, Ph.D.
Signature: ___________________
Date: March 14, 2024

This certificate confirms the above product met all specifications at time of production and release.
""")

# COMMAND ----------
# MAGIC %md ## Document 5 — Quality Incident Report

# COMMAND ----------

write_doc("quality_incident_report_QIR-2024-0047.txt", """
QUALITY INCIDENT REPORT

Report Number: QIR-2024-0047
Incident Classification: Temperature Excursion — Class II (Potential Product Safety Risk)
Status: Under Investigation
Report Date: March 15, 2024
Reported By: Jennifer Okafor, QA Manager — Atlanta Distribution Center

INCIDENT SUMMARY
On March 15, 2024, Shipment SHP-20240315 arrived at the Atlanta Distribution Center at 3:47 PM EST.
Upon review of the continuous temperature monitoring log (Logger DT-MPIII-448821, Trailer TR-8821),
a temperature excursion was detected during transit.

The trailer refrigeration unit failed for approximately 68 minutes during transportation from
Springdale, AR to Atlanta, GA. The maximum internal trailer temperature reached 48.2°F,
exceeding the contractual threshold of 40°F by 8.2°F.

EXCURSION DETAILS
Shipment ID: SHP-20240315
Lot Number: LOT-PP-240315
Product Affected: Fresh Chicken Sandwich Fillets (14,400 lbs, 480 cases)
Excursion Duration: 68 minutes (10:15 AM — 11:23 AM CST, March 15, 2024)
Peak Temperature: 48.2°F at 10:45 AM CST
Contract Threshold: 40°F maximum
Exceedance: +8.2°F above threshold

CARRIER INFORMATION
Carrier: Swift Logistics Inc.
Trailer: TR-8821
Driver: Marcus Thompson
Reported Cause: Refrigeration unit compressor failure; unit restarted at 11:10 AM CST

IMMEDIATE ACTIONS TAKEN
1. Product placed on HOLD upon arrival — not released to inventory
2. Temperature log downloaded and secured as evidence
3. Supplier (Tyson Foods) notified at 4:15 PM EST, March 15, 2024
4. Carrier (Swift Logistics) notified at 4:20 PM EST
5. QA leadership escalation initiated

RISK ASSESSMENT
Based on per FDA/FSIS cold chain guidelines for fresh poultry:
- Temperature excursion of +8.2°F for 68 minutes represents a SIGNIFICANT risk
- Microbial growth acceleration during excursion period estimated at 1.4x baseline rate
- Current COA (issued March 14, 2024) may no longer be valid
- RECOMMENDATION: Full microbiological retesting required before any release decision

PRELIMINARY FINANCIAL EXPOSURE
Per MSA-2024-TF-001 Section 4.1:
- Incident falls under "Excursion 44–48°F" category
- Minimum penalty: $15,000 + inspection costs
- Product rejection rights invoked (Purchaser's discretion)
- If recall required: Full recall costs + up to $500,000 lost revenue

NEXT STEPS
1. Await retesting results (ETA: 48–72 hours)
2. Decision on conditional release vs. full rejection
3. Root cause analysis from carrier (Swift Logistics) due: March 18, 2024
4. Supplier corrective action plan due: March 22, 2024

CONDITIONAL RELEASE REQUEST
Distribution center management has received a conditional release request from
supplier representative David Chen (Tyson Foods Regional VP). Request is under review.
See email chain: EC-SHP-20240315-001

Reported by: Jennifer Okafor, QA Manager
Reviewed by: Dr. Marcus Williams, VP Quality Assurance
""")

# COMMAND ----------
# MAGIC %md ## Document 6 — Recall Notice

# COMMAND ----------

write_doc("recall_notice_RCL-2024-0012.txt", """
VOLUNTARY PRODUCT RECALL NOTICE

Recall Reference Number: RCL-2024-0012
Classification: Class II (May cause temporary adverse health consequences)
Issuing Authority: Golden Arch Supply Partners, LLC Quality Division
Date Issued: March 20, 2024
Last Updated: March 21, 2024

PRODUCT IDENTIFICATION
Product Name: Fresh Chicken Sandwich Fillets
Brand: Tyson Foods for Golden Arch
Item Number: CSF-001
Lot Number: LOT-PP-240315
Production Date: March 14, 2024
Best-By Date: March 28, 2024
Package Description: 30-lb case, vacuum-sealed fillets, 10 per case

REASON FOR RECALL
Microbiological retesting conducted following confirmed temperature excursion during
shipment SHP-20240315 (March 15, 2024) revealed total plate counts exceeding
acceptable limits due to cold chain failure.

Post-excursion Total Plate Count: 48,200 CFU/g (Specification: < 50,000 CFU/g)
The product remains within specification but is within 4% of the upper limit,
representing an unacceptable safety margin given the excursion severity.

Additionally, targeted Salmonella testing on post-excursion re-test returned
an inconclusive result on 1 of 5 samples. Out of an abundance of caution,
a precautionary voluntary recall is being initiated.

DISTRIBUTION SCOPE
Lot PP-240315 was distributed to the following locations after conditional release
on March 16, 2024 (see QIR-2024-0047 conditional release approval):
- Atlanta Distribution Center (40 cases retained at DC)
- Restaurant locations: See attached distribution manifest (12 restaurant locations)
- Distribution region: Southeast US (Georgia, South Carolina, North Carolina, Tennessee)

AFFECTED RESTAURANT LOCATIONS
Restaurant_101 — Marietta, GA (24 cases)
Restaurant_102 — Kennesaw, GA (18 cases)
Restaurant_103 — Alpharetta, GA (20 cases)
Restaurant_104 — Roswell, GA (22 cases)
Restaurant_105 — Smyrna, GA (16 cases)
Restaurant_106 — Sandy Springs, GA (24 cases)
Restaurant_107 — Dunwoody, GA (20 cases)
Restaurant_108 — Norcross, GA (18 cases)
Restaurant_109 — Gwinnett, GA (22 cases)
Restaurant_110 — Columbia, SC (20 cases)
Restaurant_111 — Charlotte, NC (18 cases)
Restaurant_112 — Nashville, TN (16 cases)

MENU ITEMS AFFECTED
Any menu item containing chicken sandwich fillet (Item #CSF-001) from lot PP-240315:
- Classic Chicken Sandwich
- Spicy Chicken Sandwich
- Chicken Deluxe Sandwich

RECOMMENDED ACTIONS
For Distribution Centers:
□ Immediately quarantine all remaining cases of LOT-PP-240315
□ Do not release additional product from this lot
□ Retain temperature logs and chain of custody documentation

For Restaurant Locations:
□ Immediately remove all affected products from inventory
□ Do not use affected product for food preparation
□ Quarantine remaining cases
□ Complete recall acknowledgment form within 24 hours
□ Return product to distribution center for disposal

FINANCIAL IMPACT ESTIMATE
Direct recall costs: $24,000 (product disposal, logistics, testing)
Estimated lost revenue: $187,000 (based on projected sales of affected lot)
Total estimated impact: $211,000
Supplier liability claim being filed under MSA-2024-TF-001 Section 4.2

CONTACT INFORMATION
Recall Coordinator: Patricia Hughes, Director of Food Safety
Phone: 404-555-0192
Email: recall@goldenasp.com (24-hour recall hotline)

REGULATORY NOTIFICATIONS
FDA NRSS notification submitted: March 20, 2024, 11:45 AM ET
State Health Departments notified: GA, SC, NC, TN
""")

# COMMAND ----------
# MAGIC %md ## Document 7 — Email Chain

# COMMAND ----------

write_doc("email_chain_SHP-20240315_conditional_release.txt", """
EMAIL CHAIN — SHIPMENT EXCEPTION REVIEW AND CONDITIONAL RELEASE DECISION
Reference: EC-SHP-20240315-001
Shipment: SHP-20240315 / Lot: LOT-PP-240315

============================================================================================
From: Jennifer Okafor <j.okafor@goldenasp.com>
To: Dr. Marcus Williams <m.williams@goldenasp.com>
CC: Patricia Hughes <p.hughes@goldenasp.com>
Date: March 15, 2024 4:30 PM EST
Subject: URGENT: Temperature Excursion — SHP-20240315 — Hold Decision Required

Marcus,

We've just received SHP-20240315 from Tyson Foods. The DataTrace logger is showing a
68-minute excursion peaking at 48.2°F between approximately 10:15 and 11:23 AM CST.
This clearly triggers the liability clause in MSA-2024-TF-001 (Section 3.3).

Product is on HOLD. 480 cases, 14,400 lbs of fresh chicken sandwich fillets.
Best-by is March 28 — we have about 13 days if we decide to release.

Tyson rep David Chen is already calling me asking about conditional release.
I've told him nothing is moving without your approval. Waiting on your call.

Jennifer Okafor
QA Manager, Atlanta Distribution Center

============================================================================================
From: Dr. Marcus Williams <m.williams@goldenasp.com>
To: Jennifer Okafor <j.okafor@goldenasp.com>
CC: Patricia Hughes <p.hughes@goldenasp.com>; David Chen <d.chen@tysonfoods.com>
Date: March 15, 2024 5:15 PM EST
Subject: RE: URGENT: Temperature Excursion — SHP-20240315 — Hold Decision Required

Jennifer,

I've reviewed the temperature log. This is a serious excursion — 68 minutes at up to 48°F.
Per QSF-0022, we need re-testing before ANY release decision can be made.

I'm authorizing expedited micro testing through our contract lab (Covance Food Solutions).
Results should be available within 48 hours. Product remains on HOLD until then.

David — noted on your conditional release request. We will consider a conditional release
ONLY if all retesting results come back within specification. I want a formal written
request from Tyson Foods acknowledging the liability under Section 4.1 of the MSA.

Marcus Williams, VP Quality Assurance

============================================================================================
From: David Chen <d.chen@tysonfoods.com>
To: Dr. Marcus Williams <m.williams@goldenasp.com>
CC: Jennifer Okafor <j.okafor@goldenasp.com>; Patricia Hughes <p.hughes@goldenasp.com>;
    Lisa Park <l.park@tysonfoods.com> (Tyson Legal)
Date: March 16, 2024 9:00 AM EST
Subject: RE: URGENT: Temperature Excursion — SHP-20240315 — Conditional Release Request

Marcus,

On behalf of Tyson Foods, I am formally requesting conditional release of Shipment SHP-20240315,
Lot LOT-PP-240315, subject to satisfactory re-test results.

Tyson Foods acknowledges the temperature excursion occurred during transit and we are conducting
our own root cause analysis with Swift Logistics regarding the TR-8821 refrigeration failure.

Without prejudice to our ongoing investigation, and to avoid product waste on a near-term
best-by item, we respectfully request conditional release with the following commitments:
1. Tyson accepts penalty per MSA Section 4.1 ($15,000)
2. Tyson will fund full expedited re-testing costs
3. If re-test fails ANY specification, Tyson accepts full product rejection and recall costs

Please advise when retesting results are available.

David Chen, Regional VP Supply Chain
Tyson Foods, Inc.

============================================================================================
From: Dr. Marcus Williams <m.williams@goldenasp.com>
To: David Chen <d.chen@tysonfoods.com>
CC: Jennifer Okafor <j.okafor@goldenasp.com>; Patricia Hughes <p.hughes@goldenasp.com>
Date: March 16, 2024 2:47 PM EST
Subject: RE: URGENT: Temperature Excursion — SHP-20240315 — CONDITIONAL RELEASE APPROVED

David,

Covance has returned initial results. Results are as follows:
- Total Plate Count: 48,200 CFU/g — WITHIN SPEC (< 50,000 CFU/g) but elevated
- Coliform: 45 CFU/g — WITHIN SPEC (< 100 CFU/g)
- E. coli: < 3 MPN/g — PASS
- Salmonella: Inconclusive on 1 of 5 samples (further testing in progress)
- Listeria: Not Detected

Given that primary results are within spec, and Tyson's formal liability acknowledgment,
I am approving CONDITIONAL RELEASE of Lot LOT-PP-240315 for distribution, with the following
conditions:
1. All remaining Salmonella confirmatory tests must be shared with us within 72 hours
2. Product must be prioritized for rapid distribution and use given elevated TPC
3. Tyson formally accepts the $15,000 penalty payment per MSA Section 4.1
4. This release does not waive any future claims if additional testing shows issues

Jennifer — please release the product to distribution. Distribute immediately to Southeast
restaurants. Flag this lot in our systems for expedited recall capability.

Marcus Williams, VP Quality Assurance
Golden Arch Supply Partners, LLC

============================================================================================
From: Jennifer Okafor <j.okafor@goldenasp.com>
To: ATL Distribution Team <atl-dist@goldenasp.com>
CC: Dr. Marcus Williams <m.williams@goldenasp.com>
Date: March 16, 2024 3:15 PM EST
Subject: FWD: LOT-PP-240315 Released for Distribution — PRIORITY DISTRIBUTION

Team,

Lot PP-240315 (Fresh Chicken Sandwich Fillets, 480 cases) has been approved for distribution.
This is a PRIORITY distribution given elevated TPC and March 28 best-by.

Please distribute per the attached manifest to restaurants in the Southeast region immediately.
All shipments should be completed by EOD March 17.

Flag: This lot has an active QI (QIR-2024-0047). Confirmatory Salmonella testing is still
in progress. Do NOT release any remaining cases after March 20 without further QA approval.

Jennifer
""")

# COMMAND ----------
# MAGIC %md ## Document 8 — Supplier Scorecard

# COMMAND ----------

write_doc("supplier_scorecard_tyson_q1_2024.txt", """
SUPPLIER PERFORMANCE SCORECARD — Q1 2024
Quarterly Evaluation Report

Supplier: Tyson Foods, Inc.
Supplier ID: SUPP-001
Evaluation Period: January 1 — March 31, 2024
Report Date: April 5, 2024
Prepared By: Supply Chain Analytics Team
Contract Reference: MSA-2024-TF-001

OVERALL SCORE: 72/100 — CONDITIONAL (Previous Quarter: 88/100)

PERFORMANCE METRICS

1. ON-TIME DELIVERY (OTD)                     Score: 23/25
   Target: ≥ 95%
   Q1 Actual: 93.2%
   Trend: -2.1% vs Q4 2023
   Notes: 3 late deliveries in January due to winter weather; 1 late in March (SHP-20240315, 107 min late)

2. FILL RATE                                  Score: 24/25
   Target: ≥ 98%
   Q1 Actual: 97.6%
   Trend: -0.4% vs Q4 2023
   Notes: One short shipment in February (CSF-001, 12 cases short on SHP-20240218)

3. DEFECT RATE                                Score: 23/25
   Target: ≤ 0.5%
   Q1 Actual: 0.3%
   Trend: +0.1% vs Q4 2023
   Notes: Within specification; minor increase attributed to Q1 volume ramp

4. TEMPERATURE COMPLIANCE                     Score: 0/15
   Target: 100% (zero excursions)
   Q1 Actual: 96.8% (3 temperature violations recorded)
   Trend: -3.2% vs Q4 2023 (0 violations)
   Violations:
   - SHP-20240108: Trailer TR-4421, +2.1°F for 18 min (below liability threshold)
   - SHP-20240202: Trailer TR-7733, +1.4°F for 22 min (below liability threshold)
   - SHP-20240315: Trailer TR-8821, +8.2°F for 68 min (ABOVE LIABILITY THRESHOLD — recall triggered)
   Score: 0 (any violation resulting in recall = automatic zero)

5. CLAIMS FREQUENCY                           Score: 2/10
   Target: ≤ 1 claim per quarter
   Q1 Actual: 3 claims filed
   Claims:
   - CLM-2024-0021: Packaging defect, $2,400 credit issued (January)
   - CLM-2024-0034: Short weight, $1,800 credit issued (February)
   - CLM-2024-0047: Temperature excursion / recall (March) — OPEN, estimated $211,000+

SUPPLIER RISK ASSESSMENT: HIGH RISK
Escalation Required: Yes
Action Required: Supplier must submit corrective action plan by April 15, 2024
Contract Review: MSA-2024-TF-001 renewal scheduled for Q4 2024 — current performance
  may affect renewal terms and pricing.

RECOMMENDATION
Given the significant temperature excursion event in March resulting in a voluntary recall
and estimated $211,000 in costs, Supply Chain leadership recommends:
1. Immediate corrective action plan from Tyson Foods
2. Enhanced temperature monitoring requirements (dual loggers) for Q2 2024
3. Probationary period with monthly performance reviews
4. Evaluation of alternative suppliers (Koch Foods, Wayne Farms) for volume diversification

COMPARATIVE BENCHMARKS (Q1 2024)
Supplier              OTD      Fill Rate  Defect Rate  Temp Compliance  Overall Score
Tyson Foods (SUPP-001) 93.2%   97.6%     0.3%         96.8%            72/100
Koch Foods (SUPP-002)  96.8%   98.9%     0.2%         100%             94/100
Wayne Farms (SUPP-003) 95.4%   98.1%     0.4%         100%             88/100
Martin's Famous (SUPP-004) 97.1% 99.2%  0.1%         100%             96/100
""")

# COMMAND ----------
# MAGIC %md ## Document 9 — Inspection Report

# COMMAND ----------

write_doc("inspection_report_ATL_DC_20240315.txt", """
RECEIVING INSPECTION REPORT
Atlanta Distribution Center

Report Number: IR-ATL-2024-0315-02
Date: March 15, 2024
Inspector: Kevin Rodriguez, Senior Quality Inspector (Badge #QI-ATL-4421)

SHIPMENT INFORMATION
Shipment ID: SHP-20240315
Supplier: Tyson Foods, Inc.
Carrier: Swift Logistics Inc.
Trailer: TR-8821
Arrival Time: 3:47 PM EST
Dock Door: Door 7

VISUAL INSPECTION
Trailer exterior condition: Good, no visible damage
Seal condition: Intact — Front #8842917, Rear #8842918 ✓
Trailer temperature upon arrival (trailer gauge): 37.6°F ✓
Trailer temperature upon arrival (independent probe): 38.1°F ✓

PRODUCT INSPECTION
Cases inspected (random sample): 20 of 480 cases (4.2%)
Product temperature (random case probe): 38.3°F ✓
Packaging condition: 19/20 cases intact; 1 case minor corner crush (non-compromising)
Product appearance: Normal color, no off-odors detected at time of inspection
Weight verification (3 cases): 30.1 lbs, 29.8 lbs, 30.2 lbs — Within spec ✓

TEMPERATURE LOGGER RETRIEVAL
DataTrace logger DT-MPIII-448821 retrieved from trailer
Data downloaded at dock: 4:02 PM EST
Initial review of log: TEMPERATURE EXCURSION DETECTED
Excursion noted: 10:15 AM — 11:23 AM CST (68 minutes, peak 48.2°F)

ACTION TAKEN
Product placed on HOLD at 4:05 PM EST pending QA review
QA Manager Jennifer Okafor notified immediately
Product tagged: HOLD — DO NOT DISTRIBUTE — QIR-2024-0047
Lot tag applied to all 480 cases

DISPOSITION
Status as of report time: ON HOLD — Pending QA decision
Location: Cooler Bay 3, Atlanta DC
Temperature maintained: 37-38°F (active monitoring)

Inspector Signature: Kevin Rodriguez   Date: March 15, 2024   Time: 4:10 PM EST
Supervisor Review: Jennifer Okafor     Date: March 15, 2024   Time: 4:15 PM EST
""")

# COMMAND ----------
# MAGIC %md ## Document 10 — Maintenance Report

# COMMAND ----------

write_doc("maintenance_report_TR-8821.txt", """
EQUIPMENT MAINTENANCE REPORT
Swift Logistics Inc. — Fleet Maintenance Division

Trailer ID: TR-8821
VIN: 1UYVS2535PG445821
Year/Make/Model: 2021 Utility 3000R Refrigerated Trailer
Refrigeration Unit: Thermo King SB-310 (Serial: TK-SB310-2021-44821)

INCIDENT MAINTENANCE REPORT
Date of Failure: March 15, 2024
Reported By: Driver Marcus Thompson
Failure Location: I-20 Westbound near Anniston, AL (approx. mile marker 188)
Failure Time: Approximately 10:12 AM CST
Restoration Time: 11:10 AM CST
Total Downtime: 58 minutes (compressor failure), system cooling restored by 11:23 AM CST

FAILURE DESCRIPTION
Driver reported refrigeration unit alarm at 10:12 AM. Audible alarm and warning light
activated in cab (Thermo King ThermoGuard controller). Driver pulled over at mile marker 188
on I-20 to investigate. Compressor would not restart via normal reset procedure.
Driver contacted Swift Logistics dispatch at 10:18 AM. Remote diagnostic performed.

DIAGNOSIS
Remote diagnostic code: TC-4421 — Compressor high pressure cutout (HPO)
Root cause: Condenser coil partial blockage causing elevated discharge pressure.
Contributing factors: Unit had 847 operating hours since last PM service.
Last PM service was due at 800 hours (overdue by 47 hours).

REPAIR ACTION
10:45 AM: On-road technician (Marcus Hill, Tech ID TK-0847) dispatched from Birmingham, AL
11:05 AM: Technician arrived on-site
11:07 AM: Manual reset of high pressure cutout performed
11:10 AM: Compressor restarted successfully
11:23 AM: Trailer temperature returned to ≤ 40°F
11:35 AM: Driver cleared to continue to Atlanta DC

EQUIPMENT HISTORY (TR-8821, last 12 months)
Date        Service Type          Hours     Notes
2023-03-15  PM Service (800 hr)   12,441   All checks passed
2023-08-22  PM Service (800 hr)   13,247   Condenser cleaning performed
2023-12-10  PM Service (800 hr)   14,102   Minor refrigerant recharge (0.5 lb R-404A)
2024-03-15  Incident repair       14,949   HPO reset; PM overdue by 47 hours

CORRECTIVE ACTIONS
1. Condenser coil deep cleaning performed following compressor restart
2. PM service brought current (service completed at destination upon delivery)
3. Driver training reminder: Pre-trip inspection must include refrigeration unit check
4. Fleet management notified: TR-8821 scheduled for comprehensive PM next available slot

COMPLIANCE NOTE
This maintenance incident contributed to temperature excursion documented in
QIR-2024-0047 and Recall RCL-2024-0012. Carrier acknowledges responsibility for
maintenance-related equipment failure per carrier SLA agreement.
Swift Logistics accepting financial responsibility share per carrier SLA (20% of
incremental recall costs above base $15,000 supplier penalty).

Technician: Marcus Hill (Tech ID TK-0847)   Date: March 15, 2024
Supervisor: Fleet Maintenance Manager       Signature: _______________
""")

# COMMAND ----------
# MAGIC %md ## Documents 11–13

# COMMAND ----------

write_doc("delivery_exception_SHP-20240315.txt", """
DELIVERY EXCEPTION NOTIFICATION

Exception ID: DEX-2024-0847
Date/Time: March 15, 2024 4:30 PM EST
Shipment: SHP-20240315
Exception Type: Temperature Excursion — Product Hold

NOTIFICATION TO: Restaurant Operations Team, Southeast Region

This notification is to advise that Shipment SHP-20240315, Lot LOT-PP-240315
(Fresh Chicken Sandwich Fillets, 480 cases) has been placed on HOLD at the
Atlanta Distribution Center due to a cold chain exception during transit.

A temperature excursion was recorded by the in-transit logger (Trailer TR-8821):
- Duration: 68 minutes
- Peak Temperature: 48.2°F
- Excursion window: 10:15 AM – 11:23 AM CST, March 15, 2024

IMPACT TO RESTAURANTS
Originally scheduled for distribution to Southeast restaurants on March 16-17, 2024.
DISTRIBUTION IS DELAYED pending QA review and retesting (estimated 48-72 hours).

Restaurants with low chicken sandwich fillet inventory should activate contingency protocols:
- Contact your DC representative for temporary substitution options
- Item #CSF-002 (Alternate Fillet, from Koch Foods) may be available as backup
- Update 86 boards if stock runs critically low

STATUS UPDATES
Updates will be provided via the Supply Chain Portal and this distribution list.
Next update expected: March 16, 2024, 10:00 AM EST.

Distribution Operations Team
Atlanta Distribution Center — Golden Arch Supply Partners, LLC
""")

write_doc("carrier_sla_swift_logistics.txt", """
CARRIER SERVICE LEVEL AGREEMENT

Agreement: CSA-2024-SL-007
Carrier: Swift Logistics Inc.
Shipper: Golden Arch Supply Partners, LLC
Effective: January 1, 2024

1. REFRIGERATED TRANSPORT STANDARDS
   - Maintain trailer temperature at or below contracted threshold at all times
   - Pre-trip inspection of refrigeration unit required before each refrigerated load
   - Continuous temperature monitoring required (carrier-provided or shipper-provided logger)
   - Driver must check refrigeration status every 2 hours during transit

2. MAINTENANCE OBLIGATIONS
   - Refrigeration units must be serviced per manufacturer schedule (Thermo King: every 800 hours)
   - Overdue PM constitutes carrier negligence per Section 3.2
   - Carrier must provide maintenance records on demand within 24 hours

3. LIABILITY
   3.1 Carrier is liable for product loss/damage caused by equipment failure
   3.2 Carrier's share of liability where supplier also bears responsibility:
       - Equipment failure (maintenance-related): Carrier 20%, Supplier 80%
       - Force majeure (weather): Carrier 0%, shared claims process
       - Driver error: Carrier 100%

4. INSURANCE
   Carrier maintains $5,000,000 cargo insurance and $10,000,000 general liability.
""")

write_doc("weather_event_report_ATL_20240315.txt", """
WEATHER CONDITIONS REPORT — TRANSIT CORRIDOR
March 15, 2024

Route: Springdale AR → Atlanta GA (via I-49/I-40/I-20)
Transit Date: March 15, 2024
Prepared By: Supply Chain Risk Analytics

WEATHER SUMMARY
Conditions on transit route were clear with no significant weather events.
Temperature range along route: 45–58°F ambient (seasonal normal).
No winter weather, precipitation, or extreme conditions recorded.
No weather events contributed to or caused the refrigeration failure.

CONCLUSION
Weather conditions on March 15, 2024 were within normal seasonal parameters.
The temperature excursion documented in QIR-2024-0047 was caused by
mechanical refrigeration failure (TR-8821 compressor HPO), not weather-related factors.
Carrier liability assessment: Equipment failure, not force majeure.
""")

# COMMAND ----------

print(f"\n✓ All 13 documents written to {VOLUME_PATH}")
print("\nDocument manifest:")
for f in sorted(os.listdir(VOLUME_PATH)):
    size = os.path.getsize(f"{VOLUME_PATH}/{f}")
    print(f"  {f}  ({size:,} bytes)")
