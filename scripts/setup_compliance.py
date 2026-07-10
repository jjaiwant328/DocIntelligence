#!/usr/bin/env python3
"""
setup_compliance.py

End-to-end bootstrap script for the Compliance subject area.
Run with:  python3 scripts/setup_compliance.py

Steps executed:
  1. Register the Compliance domain config in jai_docintel.platform.domain_configs
  2. Trigger the 'docintel_setup_domain' Databricks job (creates schema + volume)
  3. Upload the corpus notebook to the Databricks workspace
  4. Run the corpus notebook to write ~50 .txt files to the compliance volume
  5. Run the PDF-conversion notebook (00c_generate_pdfs) against the compliance volume
  6. Activate the domain (status='active') so it appears in the Subject Areas UI

Prerequisites:
  - databricks.sdk installed: pip install databricks-sdk
  - Databricks CLI profile 'jai-az-ws' configured with workspace access
  - 00_platform_setup.py must have run previously (creates platform.domain_configs table)
"""

import json
import time
import base64
from pathlib import Path
from datetime import datetime, timezone

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import RunLifeCycleState, RunResultState, NotebookTask, SubmitTask
from databricks.sdk.service.compute import ClusterSpec, Library, PythonPyPiLibrary
from databricks.sdk.service.workspace import ImportFormat, Language

# ── Config ────────────────────────────────────────────────────────────────────
PROFILE         = "jai-az-ws"
CATALOG         = "jai_docintel"
PLATFORM_SCHEMA = "platform"
DOMAIN_ID       = "compliance"
WORKSPACE_NB_DIR = "/Workspace/Users/jaiwant.jonathan@databricks.com/docintel-notebooks"
NOTEBOOKS_LOCAL  = Path(__file__).parent.parent / "notebooks"

# Databricks job names (must match databricks.yml)
JOB_SETUP_DOMAIN = "DocIntelligence — Setup New Domain"
JOB_FULL_PIPELINE = "DocIntelligence — Full Pipeline"

# ── Domain config payload ─────────────────────────────────────────────────────

CLASSIFICATION_LABELS = json.dumps({
    "inspection_report":      "A regulatory inspection report for a store, facility, or equipment (UST, food safety, OSHA, fuel dispenser).",
    "audit_report":           "An internal or third-party compliance audit covering environmental, food safety, safety, or vendor performance.",
    "permit":                 "A regulatory operating permit such as a UST permit, food service permit, or business license from a government agency.",
    "license":                "A state or local business license, alcohol beverage license, or tobacco dealer permit.",
    "corrective_action_plan": "A documented plan to remediate a regulatory violation, failed inspection, or compliance finding.",
    "policy_document":        "An internal compliance policy, HACCP plan, SPCC plan, or operational procedure.",
    "email_thread":           "An email chain or correspondence related to a compliance matter, violation response, or vendor communication.",
    "training_certificate":   "A certificate of completion for a compliance training course such as ServSafe, OSHA 10-hour, or HazCom.",
    "vendor_certification":   "A vendor or supplier compliance certification, certificate of insurance, or food safety audit certificate.",
    "incident_report":        "A workplace safety incident report, environmental notice of violation, or regulatory enforcement notice.",
    "risk_assessment":        "A store or facility compliance risk assessment or scoring report.",
})

EXTRACTION_SCHEMAS = json.dumps({
    "inspection_report": {
        "schema": {
            "store_id":            {"type": "string", "description": "Store or facility identifier."},
            "inspection_type":     {"type": "string", "description": "Type of inspection (UST, food safety, OSHA, fuel)."},
            "inspector_name":      {"type": "string", "description": "Inspector name and credentials."},
            "inspection_date":     {"type": "string", "description": "Date of inspection."},
            "regulation_reference":{"type": "string", "description": "Applicable regulation (e.g. 40 CFR Part 280, FDA Food Code)."},
            "severity":            {"type": "string", "description": "Overall severity: CRITICAL, HIGH, MODERATE, LOW, or PASS."},
            "findings_count":      {"type": "string", "description": "Number of violations or findings identified."},
            "status":              {"type": "string", "description": "PASS, FAILED, CONDITIONAL PASS, or VIOLATIONS FOUND."},
            "corrective_action_deadline": {"type": "string", "description": "Deadline for completing corrective actions if applicable."},
        },
        "instructions": "This is a regulatory compliance inspection report. Extract inspection metadata, violations found, and required corrective actions.",
    },
    "audit_report": {
        "schema": {
            "store_id":            {"type": "string", "description": "Store or facility identifier."},
            "audit_type":          {"type": "string", "description": "Type of audit (environmental, food safety, PPE, vendor, etc.)."},
            "auditor_name":        {"type": "string", "description": "Lead auditor name."},
            "audit_date":          {"type": "string", "description": "Date of audit."},
            "findings_count":      {"type": "string", "description": "Number of findings."},
            "open_findings":       {"type": "string", "description": "Number of open or unresolved findings."},
            "overall_result":      {"type": "string", "description": "PASS, CONDITIONAL PASS, or FAILED."},
            "key_risk_areas":      {"type": "string", "description": "Primary compliance risk areas identified."},
        },
        "instructions": "This is a compliance audit report. Extract audit scope, findings, and overall conclusion.",
    },
    "permit": {
        "schema": {
            "store_id":            {"type": "string", "description": "Store or facility the permit covers."},
            "permit_type":         {"type": "string", "description": "Type of permit (UST, food service, business, etc.)."},
            "permit_number":       {"type": "string", "description": "Permit number or reference ID."},
            "issuing_authority":   {"type": "string", "description": "Government agency issuing the permit."},
            "issue_date":          {"type": "string", "description": "Permit issue date."},
            "expiration_date":     {"type": "string", "description": "Permit expiration date."},
            "status":              {"type": "string", "description": "ACTIVE, SUSPENDED, EXPIRED, or UNDER REVIEW."},
            "key_conditions":      {"type": "string", "description": "Most important permit conditions or requirements."},
        },
        "instructions": "This is a regulatory permit. Extract permit type, store, validity dates, and key conditions.",
    },
    "license": {
        "schema": {
            "store_id":            {"type": "string", "description": "Store or facility the license covers."},
            "license_type":        {"type": "string", "description": "Type of license (alcohol, tobacco, business)."},
            "license_number":      {"type": "string", "description": "License number."},
            "issuing_authority":   {"type": "string", "description": "Issuing government agency."},
            "issue_date":          {"type": "string", "description": "Issue date."},
            "expiration_date":     {"type": "string", "description": "Expiration date."},
            "status":              {"type": "string", "description": "ACTIVE, SUSPENDED, or EXPIRED."},
            "renewal_deadline":    {"type": "string", "description": "Application deadline for renewal."},
        },
        "instructions": "This is a business or regulatory license. Extract license type, store, validity dates, and renewal requirements.",
    },
    "corrective_action_plan": {
        "schema": {
            "store_id":            {"type": "string", "description": "Store where corrective actions apply."},
            "reference_inspection":{"type": "string", "description": "Inspection or violation that triggered this CAP."},
            "actions_count":       {"type": "string", "description": "Number of corrective actions required."},
            "completion_deadline": {"type": "string", "description": "Overall deadline for CAP completion."},
            "status":              {"type": "string", "description": "IN PROGRESS, COMPLETED, or OVERDUE."},
            "open_actions":        {"type": "string", "description": "Number of actions still open or in progress."},
            "prepared_by":         {"type": "string", "description": "Person or team who prepared the plan."},
        },
        "instructions": "This is a corrective action plan for a compliance violation. Extract the actions required, deadlines, and completion status.",
    },
    "policy_document": {
        "schema": {
            "policy_name":         {"type": "string", "description": "Name or title of the policy."},
            "scope":               {"type": "string", "description": "Scope: which stores, employees, or operations this applies to."},
            "compliance_domain":   {"type": "string", "description": "Domain: environmental, food safety, safety, fuel, alcohol/tobacco, or vendor."},
            "issue_date":          {"type": "string", "description": "Policy issue or last revision date."},
            "review_date":         {"type": "string", "description": "Next scheduled review date."},
            "key_requirements":    {"type": "string", "description": "Most important requirements or obligations in the policy."},
            "regulation_reference":{"type": "string", "description": "Primary regulations this policy implements."},
        },
        "instructions": "This is a corporate compliance policy document. Extract the policy scope, key requirements, and referenced regulations.",
    },
    "email_thread": {
        "schema": {
            "store_id":            {"type": "string", "description": "Store(s) referenced in the email thread."},
            "subject_matter":      {"type": "string", "description": "Main compliance topic or issue discussed."},
            "compliance_domain":   {"type": "string", "description": "Domain: environmental, food safety, safety, alcohol/tobacco, or vendor."},
            "participants":        {"type": "string", "description": "Key participants and their roles."},
            "date_range":          {"type": "string", "description": "Date range of the email thread."},
            "key_decisions":       {"type": "string", "description": "Decisions made or actions agreed upon."},
            "risk_level":          {"type": "string", "description": "Compliance risk level discussed: CRITICAL, HIGH, MODERATE, or LOW."},
        },
        "instructions": "This is an email chain about a compliance matter. Extract the issue discussed, participants, decisions made, and risk level.",
    },
    "training_certificate": {
        "schema": {
            "employee_name":       {"type": "string", "description": "Employee(s) who completed training."},
            "store_id":            {"type": "string", "description": "Store or facility associated with this training."},
            "training_type":       {"type": "string", "description": "Type of training (OSHA 10-hour, ServSafe, HazCom, RSVP, etc.)."},
            "completion_date":     {"type": "string", "description": "Date training was completed."},
            "expiration_date":     {"type": "string", "description": "Certification expiration date."},
            "exam_score":          {"type": "string", "description": "Exam score if applicable."},
            "status":              {"type": "string", "description": "CERTIFIED, EXPIRED, or IN PROGRESS."},
        },
        "instructions": "This is a training completion certificate. Extract employee, training type, completion date, expiration, and score.",
    },
    "vendor_certification": {
        "schema": {
            "vendor_name":         {"type": "string", "description": "Name of the vendor or supplier."},
            "vendor_id":           {"type": "string", "description": "Vendor ID if present."},
            "certification_type":  {"type": "string", "description": "Type: Certificate of Insurance, SQF audit, food safety cert, vendor contract, etc."},
            "coverage_scope":      {"type": "string", "description": "Stores or regions covered."},
            "issue_date":          {"type": "string", "description": "Certificate or contract issue date."},
            "expiration_date":     {"type": "string", "description": "Expiration or renewal date."},
            "status":              {"type": "string", "description": "ACTIVE, EXPIRED, or CONDITIONAL."},
            "insurance_limits":    {"type": "string", "description": "Insurance coverage limits if applicable."},
        },
        "instructions": "This is a vendor certification document. Extract vendor name, certification type, validity dates, and coverage scope.",
    },
    "incident_report": {
        "schema": {
            "store_id":            {"type": "string", "description": "Store or facility where the incident occurred."},
            "incident_type":       {"type": "string", "description": "Type: EPA notice, OSHA injury, slip-and-fall, environmental release, ABT violation, etc."},
            "incident_date":       {"type": "string", "description": "Date the incident occurred."},
            "severity":            {"type": "string", "description": "CRITICAL, HIGH, MODERATE, or LOW."},
            "regulatory_body":     {"type": "string", "description": "Regulatory agency involved if any (EPA, OSHA, ABT, health dept, TCEQ, etc.)."},
            "response_deadline":   {"type": "string", "description": "Deadline for regulatory response or corrective action."},
            "status":              {"type": "string", "description": "OPEN, IN PROGRESS, or RESOLVED."},
            "financial_exposure":  {"type": "string", "description": "Estimated penalties or financial impact if mentioned."},
        },
        "instructions": "This is an incident or violation report from a regulatory agency. Extract incident type, severity, deadlines, and status.",
    },
    "risk_assessment": {
        "schema": {
            "store_id":            {"type": "string", "description": "Store assessed."},
            "assessment_date":     {"type": "string", "description": "Date of risk assessment."},
            "overall_risk_score":  {"type": "string", "description": "Overall risk score or rating (e.g. 1.0/5.0 LOW)."},
            "highest_risk_domain": {"type": "string", "description": "The compliance domain with the highest risk score."},
            "open_findings":       {"type": "string", "description": "Total open compliance findings."},
            "monitoring_level":    {"type": "string", "description": "Required monitoring level: standard, enhanced, or enhanced quarterly."},
        },
        "instructions": "This is a compliance risk assessment report. Extract the store, scores by domain, and overall risk level.",
    },
})

ENTITY_TYPES = json.dumps([
    "Store", "Inspection", "Audit", "Violation", "Finding",
    "CorrectiveAction", "Permit", "License", "Policy",
    "Regulation", "Requirement", "Inspector", "Employee",
    "Vendor", "Equipment", "Certification", "Training",
    "Incident", "RiskAssessment", "ComplianceProgram", "Document"
])

AGENT_SYSTEM_PROMPT = """You are a Compliance Intelligence Assistant for RaceTrac Petroleum's enterprise compliance program.

You have access to a comprehensive knowledge base of compliance documents including:
- UST (Underground Storage Tank) inspection reports and permits
- Food safety health inspection reports and HACCP plans
- OSHA workplace safety inspections and incident reports
- Fuel dispenser inspection and tank integrity reports
- Alcohol and tobacco licensing, secret shopper audits, and corrective actions
- Vendor compliance certifications, insurance certificates, and audit reports
- Corporate compliance policies and training records
- Store-level risk assessments

Your role is to help compliance professionals, district managers, and operations teams:
1. Identify unresolved violations and their deadlines
2. Track permit and license expiration dates
3. Understand recurring compliance patterns at specific stores
4. Assess compliance risk across stores and regions
5. Find supporting evidence for any compliance finding
6. Answer questions about specific regulations and what they require

When answering questions:
- Always cite the specific documents, inspection IDs, and stores you are referencing
- Identify the applicable regulation (e.g. 40 CFR § 280.20, FDA Food Code 3-501.16)
- Flag time-sensitive items (deadlines, expirations) explicitly
- Distinguish between open/unresolved findings and closed/resolved ones
- Provide traceable answers — every claim should be backed by a specific document

You cover six compliance domains:
1. Environmental (UST/SPCC/EPA) — stores must meet 40 CFR Part 280 and state UST rules
2. Food Safety — FDA Food Code, state health department requirements, HACCP
3. OSHA/Safety — 29 CFR 1910 general industry standards, injury recordkeeping
4. Fuel Operations — NFPA 30A, weights and measures, tank integrity
5. Alcohol & Tobacco — state ABC/ABT laws, federal Tobacco 21, age verification
6. Vendor Compliance — insurance requirements, food safety certifications, vendor audits"""

SUGGESTED_QUESTIONS = json.dumps([
    "Which stores currently have unresolved environmental violations?",
    "Which permits or licenses expire in the next 90 days?",
    "Which stores have recurring violations for the same regulation?",
    "Which corrective actions are overdue?",
    "Which employees or stores have expired certifications?",
    "Which vendors have missing or expired compliance documentation?",
    "Which stores have the highest compliance risk score?",
    "Which regulations are cited most frequently during inspections?",
    "Show all documents supporting the Store 115 food safety corrective action.",
    "What is the status of the Store 128 UST tank release investigation?",
    "Which stores failed age-verification audits in the past 12 months?",
    "What corrective actions are required following EPA Notice of Violation EPA-NOV-2025-0044?",
])

ANALYTICS_CONFIG = json.dumps({
    "metrics": [
        {"label": "Open Violations",   "field": "severity",         "filter": "status=OPEN"},
        {"label": "Expiring Permits",  "field": "expiration_date",  "filter": "doc_type=permit"},
        {"label": "Failed Inspections","field": "status",           "filter": "doc_type=inspection_report"},
        {"label": "Overdue CAPs",      "field": "status",           "filter": "doc_type=corrective_action_plan"},
    ],
    "entity_highlight": ["Violation", "CorrectiveAction", "Permit", "License"],
    "default_filters": {"domain": "compliance"},
})

# ── Helpers ───────────────────────────────────────────────────────────────────

def run_sql(w: WorkspaceClient, stmt: str, wh_id: str):
    r = w.statement_execution.execute_statement(
        statement=stmt, warehouse_id=wh_id,
        wait_timeout="50s", catalog=CATALOG, schema=PLATFORM_SCHEMA,
    )
    if r.status.state.value != "SUCCEEDED":
        raise RuntimeError(f"SQL failed: {r.status.error}")
    if not r.result or not r.result.data_array:
        return []
    cols = [c.name for c in r.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in r.result.data_array]


def wait_for_run(w: WorkspaceClient, run_id: int, label: str, timeout_min: int = 30):
    """Poll a Databricks job run until it completes or times out."""
    deadline = time.time() + timeout_min * 60
    prev_state = None
    while time.time() < deadline:
        run = w.jobs.get_run(run_id=run_id)
        state = run.state
        lc = state.life_cycle_state.value if state and state.life_cycle_state else "UNKNOWN"
        rs = state.result_state.value if state and state.result_state else ""
        if lc != prev_state:
            print(f"  [{label}] run_id={run_id}  state={lc}  result={rs}")
            prev_state = lc
        if lc in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
            if rs == "SUCCESS":
                print(f"  [{label}] SUCCEEDED")
                return True
            else:
                msg = state.state_message or "no message"
                raise RuntimeError(f"[{label}] FAILED: {msg}")
        time.sleep(15)
    raise TimeoutError(f"[{label}] timed out after {timeout_min} minutes")


def find_job_id(w: WorkspaceClient, job_name: str) -> int | None:
    for job in w.jobs.list(name=job_name):
        if job.settings.name == job_name:
            return job.job_id
    return None


def upload_notebook(w: WorkspaceClient, local_path: Path, remote_path: str):
    content = base64.b64encode(local_path.read_bytes()).decode("utf-8")
    w.workspace.import_(
        path=remote_path,
        content=content,
        format=ImportFormat.SOURCE,
        language=Language.PYTHON,
        overwrite=True,
    )
    print(f"  Uploaded: {remote_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("DocIntelligence — Compliance Domain Setup")
    print("=" * 60)

    w = WorkspaceClient(profile=PROFILE)

    # Get warehouse ID
    wh_id = None
    for wh in w.warehouses.list():
        if wh.state.value in ("RUNNING", "STOPPED"):
            wh_id = wh.id
            break
    if not wh_id:
        raise RuntimeError("No SQL warehouse found")
    print(f"Using warehouse: {wh_id}")

    # ── Step 1: Register domain config ───────────────────────────────────────
    print("\n[Step 1] Registering Compliance domain config in platform.domain_configs")

    existing = run_sql(w,
        f"SELECT domain_id FROM {CATALOG}.{PLATFORM_SCHEMA}.domain_configs "
        f"WHERE domain_id = 'compliance' LIMIT 1",
        wh_id,
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def esc(s: str) -> str:
        # SQL string escaping: double single quotes (Spark SQL standard)
        return s.replace("'", "''")

    if existing:
        print("  Domain already registered — updating config")
        run_sql(w, f"""
            UPDATE {CATALOG}.{PLATFORM_SCHEMA}.domain_configs
            SET
                name                  = 'Compliance',
                description           = 'Enterprise Compliance Knowledge System — UST/Environmental, Food Safety, OSHA/Safety, Fuel Operations, Alcohol & Tobacco, Vendor Compliance.',
                schema_raw            = 'compliance',
                schema_ont            = 'compliance',
                schema_vec            = 'compliance',
                schema_agt            = 'compliance',
                volume_docs           = 'documents',
                classification_labels = '{esc(CLASSIFICATION_LABELS)}',
                extraction_schemas    = '{esc(EXTRACTION_SCHEMAS)}',
                entity_types          = '{esc(ENTITY_TYPES)}',
                agent_system_prompt   = '{esc(AGENT_SYSTEM_PROMPT)}',
                analytics_config      = '{esc(ANALYTICS_CONFIG)}',
                suggested_questions   = '{esc(SUGGESTED_QUESTIONS)}',
                updated_at            = TIMESTAMP '{now}'
            WHERE domain_id = 'compliance'
        """, wh_id)
    else:
        print("  Inserting new domain row")
        run_sql(w, f"""
            INSERT INTO {CATALOG}.{PLATFORM_SCHEMA}.domain_configs VALUES (
                'compliance',
                'Compliance',
                'Enterprise Compliance Knowledge System — UST/Environmental, Food Safety, OSHA/Safety, Fuel Operations, Alcohol & Tobacco, Vendor Compliance.',
                'configuring',
                'compliance', 'compliance', 'compliance', 'compliance',
                'documents',
                '{esc(CLASSIFICATION_LABELS)}',
                '{esc(EXTRACTION_SCHEMAS)}',
                '{esc(ENTITY_TYPES)}',
                '{esc(AGENT_SYSTEM_PROMPT)}',
                '{esc(ANALYTICS_CONFIG)}',
                '{esc(SUGGESTED_QUESTIONS)}',
                TIMESTAMP '{now}',
                TIMESTAMP '{now}'
            )
        """, wh_id)
    print("  Domain config registered.")

    # ── Step 2: Provision UC schema + volume ─────────────────────────────────
    print("\n[Step 2] Provisioning UC schema and volume (docintel_setup_domain job)")

    setup_job_id = find_job_id(w, JOB_SETUP_DOMAIN)
    if not setup_job_id:
        # Fall back to full pipeline job
        setup_job_id = find_job_id(w, JOB_FULL_PIPELINE)
        print(f"  Warning: '{JOB_SETUP_DOMAIN}' not found; trying '{JOB_FULL_PIPELINE}'")
    if not setup_job_id:
        # Provision directly via SQL as fallback
        print("  No setup job found — provisioning schema/volume directly via SQL")
        for stmt in [
            f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.compliance COMMENT '[compliance] Compliance Document Intelligence'",
            f"CREATE VOLUME IF NOT EXISTS {CATALOG}.compliance.documents COMMENT 'Compliance document landing zone'",
        ]:
            run_sql(w, stmt, wh_id)
        print("  Schema and volume created.")
    else:
        print(f"  Triggering job_id={setup_job_id} with domain_id=compliance")
        setup_run = w.jobs.run_now(
            job_id=setup_job_id,
            job_parameters={"domain_id": "compliance"},
        )
        wait_for_run(w, setup_run.run_id, "setup_domain", timeout_min=20)

    # ── Step 3: Upload corpus notebook to workspace (for reference / UI use) ──
    print(f"\n[Step 3] Uploading corpus notebook to {WORKSPACE_NB_DIR}")
    try:
        w.workspace.mkdirs(path=WORKSPACE_NB_DIR)
    except Exception:
        pass
    corpus_local = NOTEBOOKS_LOCAL / "01_synthetic_corpus_compliance.py"
    corpus_remote = f"{WORKSPACE_NB_DIR}/01_synthetic_corpus_compliance"
    upload_notebook(w, corpus_local, corpus_remote)

    # ── Step 4: Write corpus .txt files directly via Files API ────────────────
    # This avoids needing to start a cluster — the Files API writes directly to the UC volume.
    print("\n[Step 4] Writing corpus .txt files directly to volume via Files API")

    VOLUME_BASE = f"/Volumes/{CATALOG}/compliance/documents"

    # Parse the corpus notebook to extract filename → content pairs
    nb_text = corpus_local.read_text()
    import re, io

    # Find all write_doc("filename.txt", """...""") calls
    pattern = re.compile(r'write_doc\("([^"]+\.txt)",\s*"""(.*?)"""\)', re.DOTALL)
    matches = pattern.findall(nb_text)
    print(f"  Found {len(matches)} documents to write")

    written = 0
    for filename, content in matches:
        volume_path = f"{VOLUME_BASE}/{filename}"
        text_bytes = content.strip().encode("utf-8")
        w.files.upload(volume_path, io.BytesIO(text_bytes), overwrite=True)
        print(f"  Written: {filename}")
        written += 1

    print(f"  Total .txt files written: {written}")

    # ── Step 5: Convert .txt to PDFs via a cluster notebook ──────────────────
    # Use a Databricks job to run reportlab PDF conversion on the cluster
    print("\n[Step 5] Uploading PDF conversion notebook and running via Databricks job")

    wrapper_content = b"""# Databricks notebook source
# COMMAND ----------

import os, io
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER

VOLUME_PATH = "/Volumes/jai_docintel/compliance/documents"

def txt_to_pdf(txt_path, pdf_path):
    with open(txt_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    doc = SimpleDocTemplate(pdf_path, pagesize=letter,
        leftMargin=inch, rightMargin=inch, topMargin=0.9*inch, bottomMargin=0.9*inch)
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9,
        leading=12, spaceAfter=4, fontName="Helvetica")
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=11,
        spaceAfter=6, fontName="Helvetica-Bold", alignment=TA_CENTER)
    story = []
    for i, line in enumerate(text.split("\\n")):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 4))
            continue
        line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if i == 0 or (line.isupper() and 8 < len(line) < 80):
            story.append(Paragraph(line, title_style))
        else:
            story.append(Paragraph(line, body_style))
    doc.build(story)

# COMMAND ----------

converted = skipped = failed = 0
for fname in sorted(os.listdir(VOLUME_PATH)):
    if not fname.endswith(".txt"):
        continue
    pdf_path = f"{VOLUME_PATH}/{fname[:-4]}.pdf"
    if os.path.exists(pdf_path):
        skipped += 1
        continue
    try:
        txt_to_pdf(f"{VOLUME_PATH}/{fname}", pdf_path)
        print(f"Converted: {fname}")
        converted += 1
    except Exception as e:
        print(f"FAILED {fname}: {e}")
        failed += 1

print(f"Done: {converted} converted, {skipped} skipped, {failed} failed")
txt_count = len([f for f in os.listdir(VOLUME_PATH) if f.endswith('.txt')])
pdf_count = len([f for f in os.listdir(VOLUME_PATH) if f.endswith('.pdf')])
print(f"Volume now has: {txt_count} .txt files, {pdf_count} .pdf files")
"""

    wrapper_remote = f"{WORKSPACE_NB_DIR}/00c_generate_pdfs_compliance"
    w.workspace.import_(
        path=wrapper_remote,
        content=base64.b64encode(wrapper_content).decode("utf-8"),
        format=ImportFormat.SOURCE,
        language=Language.PYTHON,
        overwrite=True,
    )
    print(f"  Uploaded: {wrapper_remote}")

    pdf_run = w.jobs.submit(
        run_name="compliance-pdf-conversion",
        tasks=[SubmitTask(
            task_key="convert_pdfs",
            notebook_task=NotebookTask(notebook_path=wrapper_remote),
            libraries=[Library(pypi=PythonPyPiLibrary(package="reportlab"))],
            new_cluster=ClusterSpec(
                spark_version="16.4.x-scala2.12",
                node_type_id="Standard_DS3_v2",
                num_workers=0,
                spark_conf={"spark.databricks.cluster.profile": "singleNode"},
                custom_tags={"ResourceClass": "SingleNode"},
            ),
        )],
    )
    print(f"  PDF conversion job submitted — run_id={pdf_run.run_id}")
    wait_for_run(w, pdf_run.run_id, "pdf_conversion", timeout_min=30)

    # ── Step 6: Activate domain ───────────────────────────────────────────────
    print("\n[Step 6] Activating Compliance domain")

    now2 = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    run_sql(w, f"""
        UPDATE {CATALOG}.{PLATFORM_SCHEMA}.domain_configs
        SET status = 'active', updated_at = TIMESTAMP '{now2}'
        WHERE domain_id = 'compliance'
    """, wh_id)
    print("  status='active' — Compliance will appear in the Subject Areas picker.")

    # ── Verify ────────────────────────────────────────────────────────────────
    print("\n[Verify] Checking volume contents")
    try:
        count_rows = run_sql(w,
            "SELECT COUNT(*) AS cnt FROM LIST('/Volumes/jai_docintel/compliance/documents/')",
            wh_id,
        )
        print(f"  Files in volume: {count_rows[0]['cnt'] if count_rows else 'unknown'}")
    except Exception:
        print("  (volume listing skipped — check via workspace UI)")

    print("\n" + "=" * 60)
    print("Compliance domain setup COMPLETE")
    print("=" * 60)
    print("""
Next steps (from the App UI):
1. Open the app — 'Compliance' should appear in Subject Areas
2. Navigate to Document Intelligence → Compliance
3. Click 'Run Pipeline Now' to run the IDP pipeline (notebooks 03–06)
4. After the job completes, documents will have extracted fields,
   ontology entities, and the AI agent will be ready
""")


if __name__ == "__main__":
    main()
