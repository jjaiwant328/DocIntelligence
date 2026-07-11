# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Municipal / Government Source Ingestion (Component 9)
# MAGIC
# MAGIC Feeds the `compliance_due_diligence` demo with municipal/government source docs,
# MAGIC **narrowed to the demo regions**, and exercises the new `.eml/.html/.docx` parse
# MAGIC branches added to `01_parse_documents`.
# MAGIC
# MAGIC ### Modes (`mode` widget)
# MAGIC - **`simulate`** (default): generate representative synthetic municipal docs
# MAGIC   (`.eml` feasibility email, `.html` municode page, `.docx` ordinance) into the
# MAGIC   volume + write provenance rows. No network.
# MAGIC - **`fetch`**: download demo-relevant docs from the allowlisted official sources.
# MAGIC   **Guarded**: `dry_run=true` by default only prints the fetch plan; set
# MAGIC   `dry_run=false` to actually fetch (obeys the allowlist; demo regions only).
# MAGIC
# MAGIC Provenance (`source_url`, `jurisdiction`, `doc_type`, `retrieved_at`,
# MAGIC `effective_date`) is written to `<domain>.document_sources`.

# COMMAND ----------

dbutils.widgets.text("domain_id", "compliance_due_diligence", "Domain id")
dbutils.widgets.dropdown("mode", "simulate", ["simulate", "fetch"], "Mode")
dbutils.widgets.dropdown("dry_run", "true", ["true", "false"], "Fetch dry-run (fetch mode only)")

import re as _re

CATALOG    = "jai_docintel"
domain_id  = dbutils.widgets.get("domain_id")
mode       = dbutils.widgets.get("mode")
dry_run    = dbutils.widgets.get("dry_run").lower() == "true"

# domain_id is interpolated into SQL/paths below — constrain it to a safe identifier.
if not _re.fullmatch(r"[a-z0-9_]+", domain_id or ""):
    raise ValueError(f"Invalid domain_id {domain_id!r}: expected [a-z0-9_]+")

# Resolve the domain's schema + volume from the platform registry (fallback to id).
def _schema_for(domain_id):
    try:
        r = spark.sql(f"""
            SELECT schema_raw, volume_docs FROM {CATALOG}.platform.domain_configs
            WHERE domain_id = '{domain_id}' LIMIT 1
        """).collect()
        if r:
            return (r[0]["schema_raw"] or domain_id, r[0]["volume_docs"] or "documents")
    except Exception:
        pass
    return (domain_id, "documents")

SCHEMA, VOLUME = _schema_for(domain_id)
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
SOURCES_TABLE = f"{CATALOG}.{SCHEMA}.document_sources"

print(f"Domain      : {domain_id}")
print(f"Schema      : {SCHEMA}")
print(f"Volume path : {VOLUME_PATH}")
print(f"Mode        : {mode}  (dry_run={dry_run})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Jurisdiction allowlist — DEMO REGIONS ONLY
# MAGIC Fetching is restricted to these official sources and demo-relevant doc types.
# MAGIC Anything not on this list is never fetched.

# COMMAND ----------

# Official sources for the three demo regions. URLs are the canonical municode / .gov
# roots; the fetch step is confined to these jurisdictions and doc types.
JURISDICTION_ALLOWLIST = [
    {
        "jurisdiction": "Hillsborough County, FL (Tampa)",
        "region": "FL",
        "muni_code_url": "https://library.municode.com/fl/hillsborough_county",
        "gov_url": "https://www.hillsboroughcounty.org",
        "doc_types": ["alcohol_license", "tobacco_license", "business_license", "zoning_document", "municipal_requirement"],
    },
    {
        "jurisdiction": "City of Dallas, TX",
        "region": "TX",
        "muni_code_url": "https://codelibrary.amlegal.com/codes/dallas/latest/dallas_tx",
        "gov_url": "https://www.dallas.gov",
        "doc_types": ["alcohol_license", "municipal_requirement", "regulatory_change", "zoning_document"],
    },
    {
        "jurisdiction": "Fulton County, GA (Atlanta)",
        "region": "GA",
        "muni_code_url": "https://library.municode.com/ga/fulton_county",
        "gov_url": "https://www.fultoncountyga.gov",
        "doc_types": ["business_license", "alcohol_license", "municipal_requirement", "zoning_document"],
    },
]

DEMO_DOC_TYPES = {"alcohol_license", "tobacco_license", "business_license",
                  "zoning_document", "municipal_requirement", "regulatory_change",
                  "permit", "feasibility_request", "historical_response",
                  "consultant_correspondence"}

# COMMAND ----------

# MAGIC %md ## Provenance table

# COMMAND ----------

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {SOURCES_TABLE} (
        filename        STRING,
        jurisdiction    STRING,
        region          STRING,
        doc_type        STRING,
        source_url      STRING,
        source_format   STRING,
        effective_date  STRING,
        retrieved_at    TIMESTAMP,
        ingest_mode     STRING
    )
    USING DELTA
    COMMENT 'Provenance for municipal/government source docs ingested into the domain volume.'
""")

def _record_provenance(rows):
    if not rows:
        return
    df = spark.createDataFrame(rows)
    df.write.mode("append").saveAsTable(SOURCES_TABLE)
    print(f"  recorded {len(rows)} provenance row(s) → {SOURCES_TABLE}")

# COMMAND ----------

# MAGIC %md ## Write helpers (text + binary into the UC volume)

# COMMAND ----------

import os, io, zipfile, datetime

os.makedirs(VOLUME_PATH, exist_ok=True)

def _write_text(name, text):
    path = f"{VOLUME_PATH}/{name}"
    with open(path, "w") as f:
        f.write(text.strip() + "\n")
    print(f"  wrote {name} ({len(text)} chars)")

def _write_docx(name, paragraphs):
    """Minimal valid .docx (Office Open XML) — stdlib zipfile only, no python-docx."""
    def _p(t):
        t = (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        return f"<w:p><w:r><w:t xml:space='preserve'>{t}</w:t></w:r></w:p>"
    body = "".join(_p(p) for p in paragraphs)
    document = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
        f"<w:body>{body}</w:body></w:document>"
    )
    content_types = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
        "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"
        "<Default Extension='xml' ContentType='application/xml'/>"
        "<Override PartName='/word/document.xml' ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'/>"
        "</Types>"
    )
    rels = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
        "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='word/document.xml'/>"
        "</Relationships>"
    )
    path = f"{VOLUME_PATH}/{name}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    print(f"  wrote {name} ({len(paragraphs)} paragraphs, docx)")

# COMMAND ----------

# MAGIC %md ## simulate — generate representative multi-format demo docs

# COMMAND ----------

def run_simulate():
    now = datetime.datetime.utcnow()
    prov = []

    # 1) .eml — Fulton County feasibility email (native .eml, exercises the eml branch)
    eml = f"""From: RealEstateLegal@racetrac.com
To: Licensing@racetrac.com; Engineering@racetrac.com
Subject: Feasibility Due Diligence — Fulton County GA parcel (SD-2024-205)
Date: {now.strftime('%a, %d %b %Y %H:%M:%S +0000')}
Content-Type: text/plain; charset=UTF-8

Team,

New parcel under contract in unincorporated Fulton County, GA (APN 14-0055-LL-0210).
Please confirm feasibility for a new store location. Specific questions:
  1. Can we sell alcohol (beer/wine) at this location? Any distance restrictions
     from schools/churches under the Fulton County code?
  2. Business (occupational) license requirements and lead time?
  3. Zoning classification and whether convenience retail with fuel is permitted.

Response requested by end of week. This refreshes the prior SD-2023-204 research.

Thanks,
Real Estate Legal
"""
    _write_text("feasy_email_fulton_SD205_2024.eml", eml)
    prov.append(dict(filename="feasy_email_fulton_SD205_2024.eml",
                     jurisdiction="Fulton County, GA (Atlanta)", region="GA",
                     doc_type="feasibility_request", source_url="(simulated)",
                     source_format="eml", effective_date="2024-01-01",
                     retrieved_at=now, ingest_mode="simulate"))

    # 2) .html — Hillsborough County municode alcohol distance ordinance (web page)
    html = """<!DOCTYPE html><html><head><title>Hillsborough County Code — Sec. 3-15 Alcoholic Beverages</title></head>
<body>
<h1>Hillsborough County, FL — Land Development Code</h1>
<h2>Sec. 3-15. Distance requirements for alcoholic beverage sales.</h2>
<p>(a) No premises licensed for the retail sale of alcoholic beverages for off-premises
consumption shall be located within <b>500 feet</b> of a public or private school,
measured from the nearest property lines.</p>
<p>(b) No such premises shall be located within <b>250 feet</b> of a church or place of worship.</p>
<p>(c) Convenience stores selling beer and wine (not liquor) for off-premises consumption
are permitted in C-1 and C-2 commercial zoning districts subject to subsection (a) and (b).</p>
<p>(d) A distance waiver may be granted by the Board of County Commissioners upon a
showing of no adverse impact.</p>
<h2>Sec. 3-16. Tobacco retail permits.</h2>
<p>A separate tobacco retail dealer permit is required and must be renewed annually.</p>
<p><em>Effective January 1, 2024.</em></p>
</body></html>"""
    _write_text("municode_hillsborough_alcohol_sec3-15_2024.html", html)
    prov.append(dict(filename="municode_hillsborough_alcohol_sec3-15_2024.html",
                     jurisdiction="Hillsborough County, FL (Tampa)", region="FL",
                     doc_type="municipal_requirement",
                     source_url="https://library.municode.com/fl/hillsborough_county",
                     source_format="html", effective_date="2024-01-01",
                     retrieved_at=now, ingest_mode="simulate"))

    # 3) .docx — City of Dallas alcohol distance ordinance 2025 (regulatory change vs 2024)
    dallas = [
        "CITY OF DALLAS, TEXAS — ORDINANCE NO. 32105",
        "Chapter 6, Alcoholic Beverages — Distance Regulations (2025 Amendment)",
        "Sec. 6-4. Distance from schools. No dealer's premises for off-premises "
        "consumption shall be within 300 feet of a public school. (Reduced from 1,000 "
        "feet under the 2024 ordinance; distance waivers for convenience stores are "
        "now granted administratively rather than by Council.)",
        "Sec. 6-5. Distance from churches and hospitals. 300 feet, measured property "
        "line to property line.",
        "Sec. 6-6. Hours of sale. Beer and wine may be sold 7:00 a.m. to midnight "
        "Monday through Saturday, and 10:00 a.m. to midnight Sunday.",
        "Effective Date: January 1, 2025.",
    ]
    _write_docx("dallas_alcohol_ordinance_2025.docx", dallas)
    prov.append(dict(filename="dallas_alcohol_ordinance_2025.docx",
                     jurisdiction="City of Dallas, TX", region="TX",
                     doc_type="regulatory_change",
                     source_url="https://codelibrary.amlegal.com/codes/dallas/latest/dallas_tx",
                     source_format="docx", effective_date="2025-01-01",
                     retrieved_at=now, ingest_mode="simulate"))

    # 4) .html — Fulton County business license requirements page
    fulton = """<!DOCTYPE html><html><head><title>Fulton County — Business Occupational Tax Certificate</title></head>
<body>
<h1>Fulton County, GA — Business Occupational Tax Certificate (Business License)</h1>
<p>All businesses operating in unincorporated Fulton County must obtain an Occupational
Tax Certificate prior to opening.</p>
<ul>
<li>Application processing time: approximately 15 business days.</li>
<li>Convenience stores with fuel require an additional fire-safety inspection.</li>
<li>Alcohol sales require a separate county alcohol license and state license.</li>
</ul>
<p><em>Effective 2024.</em></p>
</body></html>"""
    _write_text("fulton_business_license_requirements_2024.html", fulton)
    prov.append(dict(filename="fulton_business_license_requirements_2024.html",
                     jurisdiction="Fulton County, GA (Atlanta)", region="GA",
                     doc_type="business_license",
                     source_url="https://www.fultoncountyga.gov",
                     source_format="html", effective_date="2024-01-01",
                     retrieved_at=now, ingest_mode="simulate"))

    _record_provenance(prov)
    print(f"\n✅ simulate complete — {len(prov)} multi-format docs written to {VOLUME_PATH}")

# COMMAND ----------

# MAGIC %md ## fetch — allowlisted live download (guarded; dry-run by default)

# COMMAND ----------

def run_fetch(dry_run=True):
    print("Fetch plan (demo-region allowlist only):")
    plan = []
    for j in JURISDICTION_ALLOWLIST:
        for src in ("muni_code_url", "gov_url"):
            plan.append((j["jurisdiction"], j["region"], src, j[src], j["doc_types"]))
            print(f"  [{j['region']}] {j['jurisdiction']:35} {j[src]}")
    if dry_run:
        print("\n⚠️  dry_run=true — no network calls made. "
              "Set dry_run=false to fetch from the allowlisted sources above.")
        return
    # Live fetch path (allowlist-gated). Kept deliberately conservative: fetch only
    # from allowlisted hosts, record provenance, respect robots/ToS out of band.
    import urllib.request, urllib.error, datetime
    from urllib.parse import urlparse
    allowed_hosts = {urlparse(u).netloc.lower()
                     for j in JURISDICTION_ALLOWLIST for u in (j["muni_code_url"], j["gov_url"])}

    class _AllowlistRedirect(urllib.request.HTTPRedirectHandler):
        """Validate EVERY redirect hop against the allowlist before following it,
        so we never even contact an off-allowlist host (SSRF-safe)."""
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if urlparse(newurl).netloc.lower() not in allowed_hosts:
                raise urllib.error.HTTPError(newurl, code, f"redirect off allowlist: {newurl}", headers, fp)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(_AllowlistRedirect)
    now = datetime.datetime.utcnow()
    prov = []
    for jurisdiction, region, src, url, doc_types in plan:
        host = urlparse(url).netloc.lower()
        if host not in allowed_hosts:
            print(f"  SKIP (not on allowlist): {url}")
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DocIntelligence-demo/1.0"})
            with opener.open(req, timeout=30) as resp:
                body = resp.read()
            name = f"src_{region}_{host.replace('.', '_')}.html"
            with open(f"{VOLUME_PATH}/{name}", "wb") as f:
                f.write(body)
            prov.append(dict(filename=name, jurisdiction=jurisdiction, region=region,
                             doc_type="municipal_requirement", source_url=url,
                             source_format="html", effective_date=None,
                             retrieved_at=now, ingest_mode="fetch"))
            print(f"  fetched {url} → {name} ({len(body)} bytes)")
        except Exception as e:
            print(f"  ERROR fetching {url}: {e}")
    _record_provenance(prov)

# COMMAND ----------

if mode == "simulate":
    run_simulate()
elif mode == "fetch":
    run_fetch(dry_run=dry_run)
else:
    print(f"Unknown mode: {mode}")

# COMMAND ----------

print("Provenance table contents:")
display(spark.sql(f"SELECT filename, jurisdiction, doc_type, source_format, effective_date, ingest_mode FROM {SOURCES_TABLE} ORDER BY retrieved_at DESC"))
