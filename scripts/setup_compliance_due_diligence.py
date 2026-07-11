#!/usr/bin/env python3
"""
setup_compliance_due_diligence.py

Bootstrap the Compliance Due Diligence (Store Development) domain.
Run with:  python3 scripts/setup_compliance_due_diligence.py

Steps executed:
  1. Register the domain config row in jai_docintel.platform.domain_configs
     (schema: compliance_due_diligence — distinct from the operational 'compliance' domain)
  2. Trigger the 'docintel_setup_domain' job (creates UC schema + volume)
  3. Activate the domain (status='active') so it appears in the UI

Prerequisites:
  - databricks-sdk installed: pip install databricks-sdk
  - Databricks CLI profile 'jai-az-ws' configured
  - 00_platform_setup.py must have run (creates platform.domain_configs)

NOTE: corpus upload (notebooks/01_synthetic_corpus_store_dev.py) and pipeline
execution are owned by separate tasks in Phase 2. This script is config-only.
"""

import json
import time
from pathlib import Path
from datetime import datetime, timezone

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import RunLifeCycleState, RunResultState

# ── Config ────────────────────────────────────────────────────────────────────
PROFILE         = "jai-az-ws"
CATALOG         = "jai_docintel"
PLATFORM_SCHEMA = "platform"
DOMAIN_ID       = "compliance_due_diligence"

JOB_SETUP_DOMAIN  = "DocIntelligence — Setup New Domain"
JOB_FULL_PIPELINE = "DocIntelligence — Full Pipeline"

# ── Classification labels ─────────────────────────────────────────────────────

CLASSIFICATION_LABELS = json.dumps({
    "feasibility_request": (
        "A feasibility request email or memo asking whether a new store location is viable — "
        "includes site address, market, municipality, requester, and project/store number."
    ),
    "municipal_requirement": (
        "A document describing regulatory requirements imposed by a municipality or county for "
        "operating a fuel/convenience retail store — zoning rules, setbacks, operational conditions."
    ),
    "alcohol_license": (
        "A state or local alcohol beverage license application, approval, or renewal document "
        "for a retail store (beer/wine/spirits)."
    ),
    "tobacco_license": (
        "A tobacco dealer permit, license, or renewal document issued to a retail store by a "
        "state or county authority."
    ),
    "business_license": (
        "A general business license, occupational license, or business tax receipt issued by a "
        "municipality or county allowing commercial operations at a store location."
    ),
    "zoning_document": (
        "A zoning certificate, zoning verification letter, conditional-use permit, or variance "
        "approval related to a store's land-use classification."
    ),
    "permit": (
        "Any operational permit required for a store opening or continued operation — including "
        "building permits, signage permits, fire/safety permits, or fuel-dispensing permits."
    ),
    "historical_response": (
        "A prior formal or informal response to a feasibility request or municipal inquiry — "
        "captures what was answered, by whom, and for which municipality/project."
    ),
    "regulatory_change": (
        "A notice, ordinance amendment, or memo documenting a change in municipal or state "
        "regulatory requirements that affects store opening or operations."
    ),
    "consultant_correspondence": (
        "Correspondence (email, letter, memo) between the company and an external consultant, "
        "attorney, or government liaison regarding store-development feasibility or compliance."
    ),
})

# ── Extraction schemas ────────────────────────────────────────────────────────

EXTRACTION_SCHEMAS = json.dumps({
    "feasibility_request": {
        "schema": {
            "project_id":     {"type": "string", "description": "Internal project identifier (e.g. PRJ-2025-0041)."},
            "store_number":   {"type": "string", "description": "Proposed store number or site code."},
            "address":        {"type": "string", "description": "Full street address of the proposed site."},
            "market":         {"type": "string", "description": "Market or region name (e.g. Tampa FL, Dallas TX)."},
            "state":          {"type": "string", "description": "Two-letter state abbreviation."},
            "municipality":   {"type": "string", "description": "City or municipality name."},
            "county":         {"type": "string", "description": "County name."},
            "request_type":   {"type": "string", "description": "Type of feasibility request (e.g. initial, re-evaluation, expedited)."},
            "requester":      {"type": "string", "description": "Name and title of the person submitting the request."},
            "priority":       {"type": "string", "description": "Priority level: CRITICAL, HIGH, STANDARD, or LOW."},
            "source_document":{"type": "string", "description": "Originating document name or email subject line."},
        },
        "instructions": (
            "This is a store feasibility request. Extract project identifiers, location details, "
            "the requester, priority, and request type. If multiple stores are mentioned, extract "
            "the primary store being evaluated."
        ),
    },
    "municipal_requirement": {
        "schema": {
            "project_id":         {"type": "string", "description": "Project or store number this requirement applies to."},
            "store_number":       {"type": "string", "description": "Store number or site code."},
            "municipality":       {"type": "string", "description": "Municipality imposing the requirement."},
            "county":             {"type": "string", "description": "County name."},
            "state":              {"type": "string", "description": "State abbreviation."},
            "requirement_type":   {"type": "string", "description": "Type of requirement (zoning, setback, operational, environmental, etc.)."},
            "authority":          {"type": "string", "description": "Regulatory authority (e.g. City of Tampa Planning Division)."},
            "effective_date":     {"type": "string", "description": "Date the requirement became effective."},
            "lead_time":          {"type": "string", "description": "Estimated lead time to satisfy the requirement (e.g. 90 days)."},
            "source_document":    {"type": "string", "description": "Name or reference of the source regulation or document."},
        },
        "instructions": (
            "This is a municipal regulatory requirement document for a store-development project. "
            "Extract the requirement type, the authority that imposes it, effective date, and "
            "estimated lead time. Focus on actionable requirements."
        ),
    },
    "alcohol_license": {
        "schema": {
            "store_number":     {"type": "string", "description": "Store number the license covers."},
            "address":          {"type": "string", "description": "Licensed premises address."},
            "municipality":     {"type": "string", "description": "Municipality of the licensed premises."},
            "state":            {"type": "string", "description": "State abbreviation."},
            "license_type":     {"type": "string", "description": "License type (e.g. Beer/Wine Off-Premises, Liquor Retail)."},
            "issuing_authority":{"type": "string", "description": "State or local ABC authority issuing the license."},
            "effective_date":   {"type": "string", "description": "License effective/issue date."},
            "expiration_date":  {"type": "string", "description": "License expiration date."},
            "renewal_period":   {"type": "string", "description": "Renewal frequency (e.g. annual, biennial)."},
            "lead_time":        {"type": "string", "description": "Typical processing time for new application."},
            "source_document":  {"type": "string", "description": "License number or document reference."},
        },
        "instructions": (
            "This is an alcohol beverage license document. Extract the license type, issuing "
            "authority, validity dates, renewal period, and typical lead time for new applications."
        ),
    },
    "tobacco_license": {
        "schema": {
            "store_number":     {"type": "string", "description": "Store number the permit covers."},
            "address":          {"type": "string", "description": "Licensed premises address."},
            "municipality":     {"type": "string", "description": "Municipality."},
            "state":            {"type": "string", "description": "State abbreviation."},
            "license_type":     {"type": "string", "description": "Permit type (e.g. Tobacco Dealer Permit, Vapor Products Dealer)."},
            "issuing_authority":{"type": "string", "description": "Issuing authority (state dept of revenue, county, etc.)."},
            "effective_date":   {"type": "string", "description": "Permit effective date."},
            "expiration_date":  {"type": "string", "description": "Permit expiration date."},
            "renewal_period":   {"type": "string", "description": "Renewal cycle (annual, etc.)."},
            "lead_time":        {"type": "string", "description": "Processing time for new permit."},
            "source_document":  {"type": "string", "description": "Permit number or reference."},
        },
        "instructions": (
            "This is a tobacco dealer permit or license document. Extract permit type, issuing "
            "authority, validity dates, renewal schedule, and lead time."
        ),
    },
    "business_license": {
        "schema": {
            "store_number":     {"type": "string", "description": "Store number or site code."},
            "address":          {"type": "string", "description": "Business address."},
            "municipality":     {"type": "string", "description": "Issuing municipality."},
            "county":           {"type": "string", "description": "County."},
            "state":            {"type": "string", "description": "State abbreviation."},
            "license_type":     {"type": "string", "description": "License type (e.g. Business Tax Receipt, Occupational License)."},
            "issuing_authority":{"type": "string", "description": "Issuing department or agency."},
            "effective_date":   {"type": "string", "description": "Issue date."},
            "expiration_date":  {"type": "string", "description": "Expiration date."},
            "renewal_period":   {"type": "string", "description": "Renewal cycle."},
            "lead_time":        {"type": "string", "description": "Processing time for new license."},
            "source_document":  {"type": "string", "description": "License number."},
        },
        "instructions": (
            "This is a business license or occupational license document. Extract the license "
            "type, issuing authority, validity dates, and typical lead time."
        ),
    },
    "zoning_document": {
        "schema": {
            "project_id":         {"type": "string", "description": "Project or store number."},
            "store_number":       {"type": "string", "description": "Store number or site code."},
            "address":            {"type": "string", "description": "Property address."},
            "municipality":       {"type": "string", "description": "Municipality."},
            "county":             {"type": "string", "description": "County."},
            "state":              {"type": "string", "description": "State abbreviation."},
            "requirement_type":   {"type": "string", "description": "Zoning category or use type (e.g. C-2 Commercial, CU Conditional Use)."},
            "authority":          {"type": "string", "description": "Zoning authority."},
            "effective_date":     {"type": "string", "description": "Effective date of the zoning classification or approval."},
            "lead_time":          {"type": "string", "description": "Estimated time to obtain zoning approval."},
            "source_document":    {"type": "string", "description": "Document reference or case number."},
        },
        "instructions": (
            "This is a zoning document, certificate, or variance approval. Extract the zoning "
            "classification, authority, effective date, and lead time for approval."
        ),
    },
    "permit": {
        "schema": {
            "project_id":       {"type": "string", "description": "Project or store number."},
            "store_number":     {"type": "string", "description": "Store number or site code."},
            "address":          {"type": "string", "description": "Permit premises address."},
            "municipality":     {"type": "string", "description": "Municipality."},
            "state":            {"type": "string", "description": "State abbreviation."},
            "requirement_type": {"type": "string", "description": "Permit type (building, signage, fire, fuel-dispensing, etc.)."},
            "issuing_authority":{"type": "string", "description": "Permitting agency."},
            "effective_date":   {"type": "string", "description": "Permit issue date."},
            "expiration_date":  {"type": "string", "description": "Permit expiration date."},
            "lead_time":        {"type": "string", "description": "Typical processing time."},
            "source_document":  {"type": "string", "description": "Permit number."},
        },
        "instructions": (
            "This is an operational permit. Extract the permit type, issuing authority, validity "
            "dates, and typical lead time for new applications."
        ),
    },
    "historical_response": {
        "schema": {
            "project_id":     {"type": "string", "description": "Project or store number this response references."},
            "store_number":   {"type": "string", "description": "Store number."},
            "municipality":   {"type": "string", "description": "Municipality the response addressed."},
            "state":          {"type": "string", "description": "State abbreviation."},
            "request_type":   {"type": "string", "description": "Type of the original request being answered."},
            "responder":      {"type": "string", "description": "Name/title of the person who provided the response."},
            "response_date":  {"type": "string", "description": "Date the response was issued."},
            "requester":      {"type": "string", "description": "Original requester name/title."},
            "source_document":{"type": "string", "description": "Document or email reference."},
        },
        "instructions": (
            "This is a prior response to a feasibility request or municipal inquiry. Extract who "
            "responded, when, for which municipality and project, and the nature of the original request."
        ),
    },
    "regulatory_change": {
        "schema": {
            "municipality":     {"type": "string", "description": "Municipality where the regulation changed."},
            "county":           {"type": "string", "description": "County."},
            "state":            {"type": "string", "description": "State abbreviation."},
            "requirement_type": {"type": "string", "description": "Type of requirement that changed (zoning, license, setback, etc.)."},
            "authority":        {"type": "string", "description": "Regulatory authority that issued the change."},
            "effective_date":   {"type": "string", "description": "Date the change takes effect."},
            "source_document":  {"type": "string", "description": "Ordinance number, notice reference, or document name."},
        },
        "instructions": (
            "This is a regulatory change notice or ordinance amendment affecting store-development "
            "compliance. Extract the municipality, requirement type that changed, effective date, "
            "and the issuing authority."
        ),
    },
    "consultant_correspondence": {
        "schema": {
            "project_id":     {"type": "string", "description": "Project or store number discussed."},
            "store_number":   {"type": "string", "description": "Store number."},
            "municipality":   {"type": "string", "description": "Municipality discussed."},
            "state":          {"type": "string", "description": "State abbreviation."},
            "requester":      {"type": "string", "description": "Internal contact who engaged the consultant."},
            "responder":      {"type": "string", "description": "Consultant or external party responding."},
            "request_type":   {"type": "string", "description": "Topic of correspondence (zoning, licensing, feasibility, etc.)."},
            "response_date":  {"type": "string", "description": "Date of the correspondence."},
            "source_document":{"type": "string", "description": "Email subject, letter reference, or document title."},
        },
        "instructions": (
            "This is correspondence between company staff and an external consultant, attorney, "
            "or government liaison. Extract the project, municipality, parties, topic, and date."
        ),
    },
})

# ── Entity types ──────────────────────────────────────────────────────────────

ENTITY_TYPES = json.dumps([
    "Project",
    "FeasibilityRequest",
    "Municipality",
    "RegulatoryRequirement",
    "License",
    "Response",
    "Action",
    "Document",
])

# ── Analytics config (includes ontology_config) ───────────────────────────────

ANALYTICS_CONFIG = json.dumps({
    "metrics": [
        {"label": "Open Feasibility Requests", "field": "request_type",  "filter": "doc_type=feasibility_request"},
        {"label": "Expiring Licenses",          "field": "expiration_date","filter": "doc_type IN (alcohol_license,tobacco_license,business_license)"},
        {"label": "Regulatory Changes",         "field": "effective_date", "filter": "doc_type=regulatory_change"},
        {"label": "Open Actions",               "field": "priority",       "filter": "status=OPEN"},
    ],
    "entity_highlight": ["Municipality", "RegulatoryRequirement", "License", "FeasibilityRequest"],
    "default_filters": {"domain": "compliance_due_diligence"},
    "ontology_config": {
        "field_entity_map": {
            "store_number":     ["Project",              "PROJ"],
            "municipality":     ["Municipality",         "MUNI"],
            "requirement_type": ["RegulatoryRequirement","REQ"],
            "license_type":     ["License",              "LIC"],
            "responder":        ["Response",             "RESP"],
            "project_id":       ["Project",              "PROJ"],
            "requester":        ["FeasibilityRequest",   "FREQ"],
        },
        "relationship_rules": [
            {
                "subject_field": "store_number",
                "predicate":     "LOCATED_IN",
                "object_field":  "municipality",
            },
            {
                "subject_field": "municipality",
                "predicate":     "DEFINES",
                "object_field":  "requirement_type",
            },
            {
                "subject_field": "requirement_type",
                "predicate":     "REQUIRES",
                "object_field":  "license_type",
            },
            # Response ANSWERS FeasibilityRequest: co-occurrence of responder + requester on same doc
            {
                "subject_field": "responder",
                "predicate":     "ANSWERS",
                "object_field":  "requester",
            },
            # Project HAS_HISTORY_OF Response: co-occurrence of store_number + responder
            {
                "subject_field": "store_number",
                "predicate":     "HAS_HISTORY_OF",
                "object_field":  "responder",
            },
        ],
    },
})

# ── Agent system prompt ───────────────────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """\
You are the Store Development Compliance Teammate — an AI assistant embedded in RaceTrac's
store-development workflow. Your job is to help feasibility analysts, real-estate teams,
and permit coordinators navigate the regulatory landscape for new store openings.

== Workflow ==
1. CLASSIFY: Identify the document type and extract key fields (project, store, municipality,
   request type, priority). Confirm your classification with a brief rationale.
2. RESEARCH: Retrieve the current municipal requirements and required licenses for the store's
   municipality using the knowledge base. Surface setbacks, zoning rules, license types, lead
   times, and renewal periods.
3. RECALL PRIOR: Check whether we have answered a feasibility question for this municipality
   before. Cite the prior response by date and responder. Highlight anything that has changed
   since the prior response.
4. DETECT CHANGE: If a regulatory_change document is present or the effective dates differ from
   prior responses, flag the change explicitly: what changed, when it took effect, and which
   open projects are affected.
5. CREATE / TRACK ACTIONS: When a requirement or open item is identified, create a tracked
   action via the action system. Summarize: what must be done, by whom, by when.

== Standards ==
- Always cite the specific document(s) you are drawing from (document name, date, store/project).
- Flag LOW CONFIDENCE when the knowledge base does not contain a clear answer — do not guess.
- Distinguish between requirements that are OPEN vs. SATISFIED.
- Highlight time-sensitive items (expirations, lead times, deadlines) explicitly.
- Do not modify or contradict your sources; if two documents conflict, surface the conflict.

== Scope ==
You cover: feasibility requests, municipal requirements, alcohol/tobacco/business licenses,
zoning documents, operational permits, historical responses, regulatory changes, and consultant
correspondence for fuel/convenience retail store development.
"""

# ── Suggested questions ───────────────────────────────────────────────────────

SUGGESTED_QUESTIONS = json.dumps([
    "What are the requirements to open this store?",
    "Have we answered this municipality before?",
    "What changed since the last feasibility request for <municipality>?",
    "What actions remain open for <project>?",
])

# ── Helpers ───────────────────────────────────────────────────────────────────


def run_sql(w: WorkspaceClient, stmt: str, wh_id: str):
    r = w.statement_execution.execute_statement(
        statement=stmt,
        warehouse_id=wh_id,
        wait_timeout="50s",
        catalog=CATALOG,
        schema=PLATFORM_SCHEMA,
    )
    if r.status.state.value != "SUCCEEDED":
        raise RuntimeError(f"SQL failed: {r.status.error}")
    if not r.result or not r.result.data_array:
        return []
    cols = [c.name for c in r.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in r.result.data_array]


def wait_for_run(w: WorkspaceClient, run_id: int, label: str, timeout_min: int = 30):
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
            raise RuntimeError(f"[{label}] FAILED: {state.state_message or 'no message'}")
        time.sleep(15)
    raise TimeoutError(f"[{label}] timed out after {timeout_min} minutes")


def find_job_id(w: WorkspaceClient, job_name: str) -> int | None:
    for job in w.jobs.list(name=job_name):
        if job.settings.name == job_name:
            return job.job_id
    return None


def esc(s: str) -> str:
    """SQL string escaping: double single-quotes (Spark SQL standard)."""
    return s.replace("'", "''")


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    print("=" * 60)
    print("DocIntelligence — Compliance Due Diligence Domain Setup")
    print("=" * 60)

    w = WorkspaceClient(profile=PROFILE)

    # Discover an available SQL warehouse
    wh_id = None
    for wh in w.warehouses.list():
        if wh.state.value in ("RUNNING", "STOPPED"):
            wh_id = wh.id
            break
    if not wh_id:
        raise RuntimeError("No SQL warehouse found")
    print(f"Using warehouse: {wh_id}")

    # ── Step 1: Register domain config ───────────────────────────────────────
    print("\n[Step 1] Registering compliance_due_diligence domain config")

    existing = run_sql(
        w,
        f"SELECT domain_id FROM {CATALOG}.{PLATFORM_SCHEMA}.domain_configs "
        f"WHERE domain_id = '{DOMAIN_ID}' LIMIT 1",
        wh_id,
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    cl  = esc(CLASSIFICATION_LABELS)
    es  = esc(EXTRACTION_SCHEMAS)
    et  = esc(ENTITY_TYPES)
    asp = esc(AGENT_SYSTEM_PROMPT)
    ac  = esc(ANALYTICS_CONFIG)
    sq  = esc(SUGGESTED_QUESTIONS)

    if existing:
        print("  Domain already registered — updating config")
        run_sql(w, f"""
            UPDATE {CATALOG}.{PLATFORM_SCHEMA}.domain_configs
            SET
                name                  = 'Compliance Due Diligence',
                description           = 'AI-powered store-development feasibility due diligence — classify requests, research municipal requirements, recall prior responses, detect regulatory changes, track actions.',
                schema_raw            = '{DOMAIN_ID}',
                schema_ont            = '{DOMAIN_ID}',
                schema_vec            = '{DOMAIN_ID}',
                schema_agt            = '{DOMAIN_ID}',
                volume_docs           = 'documents',
                classification_labels = '{cl}',
                extraction_schemas    = '{es}',
                entity_types          = '{et}',
                agent_system_prompt   = '{asp}',
                analytics_config      = '{ac}',
                suggested_questions   = '{sq}',
                updated_at            = TIMESTAMP '{now}'
            WHERE domain_id = '{DOMAIN_ID}'
        """, wh_id)
    else:
        print("  Inserting new domain row")
        run_sql(w, f"""
            INSERT INTO {CATALOG}.{PLATFORM_SCHEMA}.domain_configs VALUES (
                '{DOMAIN_ID}',
                'Compliance Due Diligence',
                'AI-powered store-development feasibility due diligence — classify requests, research municipal requirements, recall prior responses, detect regulatory changes, track actions.',
                'configuring',
                '{DOMAIN_ID}', '{DOMAIN_ID}', '{DOMAIN_ID}', '{DOMAIN_ID}',
                'documents',
                '{cl}',
                '{es}',
                '{et}',
                '{asp}',
                '{ac}',
                '{sq}',
                TIMESTAMP '{now}',
                TIMESTAMP '{now}'
            )
        """, wh_id)
    print("  Domain config registered.")

    # ── Step 2: Provision UC schema + volume ─────────────────────────────────
    print("\n[Step 2] Provisioning UC schema and volume")

    setup_job_id = find_job_id(w, JOB_SETUP_DOMAIN)
    if not setup_job_id:
        setup_job_id = find_job_id(w, JOB_FULL_PIPELINE)
        if setup_job_id:
            print(f"  Warning: '{JOB_SETUP_DOMAIN}' not found; falling back to '{JOB_FULL_PIPELINE}'")

    if not setup_job_id:
        print("  No setup job found — provisioning schema/volume directly via SQL")
        for stmt in [
            f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{DOMAIN_ID} "
            f"COMMENT '[{DOMAIN_ID}] Compliance Due Diligence Document Intelligence'",
            f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{DOMAIN_ID}.documents "
            f"COMMENT 'Compliance Due Diligence document landing zone'",
        ]:
            run_sql(w, stmt, wh_id)
        print("  Schema and volume created.")
    else:
        print(f"  Triggering job_id={setup_job_id} with domain_id={DOMAIN_ID}")
        setup_run = w.jobs.run_now(
            job_id=setup_job_id,
            job_parameters={"domain_id": DOMAIN_ID},
        )
        wait_for_run(w, setup_run.run_id, "setup_domain", timeout_min=20)

    # ── Step 3: Activate domain ───────────────────────────────────────────────
    print("\n[Step 3] Activating domain")

    now2 = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    run_sql(w, f"""
        UPDATE {CATALOG}.{PLATFORM_SCHEMA}.domain_configs
        SET status = 'active', updated_at = TIMESTAMP '{now2}'
        WHERE domain_id = '{DOMAIN_ID}'
    """, wh_id)
    print("  status='active' — Compliance Due Diligence will appear in the Subject Areas picker.")

    # ── Done ──────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Compliance Due Diligence domain setup COMPLETE")
    print("=" * 60)
    print(f"""
Next steps:
1. Upload the synthetic corpus:
     databricks workspace import notebooks/01_synthetic_corpus_store_dev.py ...
   or run: python3 scripts/setup_compliance_due_diligence.py  (corpus step deferred to B1 task)
2. Open the app — 'Compliance Due Diligence' should appear in Subject Areas
3. Click 'Run Pipeline Now' to run the IDP pipeline (notebooks 03–06)
4. After the pipeline completes, the AI Agent tab will serve the four tools:
     Intake / Research / Historical Knowledge / Action
""")


if __name__ == "__main__":
    main()
