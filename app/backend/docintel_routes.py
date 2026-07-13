"""
DocIntelligence extended routes for the ai-parse-document-app.

All routes now accept an optional ?domain_id= query parameter (defaults to
'supply_chain') so that the same endpoints serve any configured domain.

Adds supply chain intelligence endpoints on top of the base app:
  POST /api/docintel/classify-extract   - ai_classify + ai_extract on a parsed document
  GET  /api/docintel/ontology           - Entity/relationship graph for a document or entity
  POST /api/docintel/agent-query        - Supply chain AI agent query
  GET  /api/docintel/recall-impact      - Recall impact: restaurants + financial exposure
  GET  /api/docintel/supplier-risk      - Supplier scorecard + risk ranking
  GET  /api/docintel/incident-timeline  - Full incident timeline for a shipment
"""

import os
import json
import threading
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState
import time

router = APIRouter(prefix="/api/docintel", tags=["DocIntelligence"])

# ── Config ──────────────────────────────────────────────────────────────────
CATALOG   = os.getenv("DOCINTEL_CATALOG", "jai_docintel")
SCH_RAW   = os.getenv("DOCINTEL_SCHEMA_RAW", "raw")       # supply_chain default
SCH_ONT   = os.getenv("DOCINTEL_SCHEMA_ONT", "ontology")
SCH_AGT   = os.getenv("DOCINTEL_SCHEMA_AGT", "agents")
SCH_VEC   = os.getenv("DOCINTEL_SCHEMA_VEC", "vectors")
WH_ID     = os.getenv("DATABRICKS_WAREHOUSE_ID", "")
VS_ENDPOINT = os.getenv("DOCINTEL_VS_ENDPOINT", "docintel-vs-endpoint")
VS_INDEX    = os.getenv("DOCINTEL_VS_INDEX", "jai_docintel.vectors.docintel_docs_index")
AGENT_MODEL = os.getenv("DOCINTEL_AGENT_MODEL", "databricks-claude-sonnet-4-5")

# Ordered fallback list tried when the primary model endpoint is unavailable
_MODEL_FALLBACKS = [
    AGENT_MODEL,
    "databricks-claude-sonnet-4-5",
    "databricks-claude-haiku-4-5",
    "databricks-gpt-5-4-mini",
    "databricks-gpt-5-4",
    "databricks-claude-opus-4-6",
]

_available_models_cache: list = []

def _resolve_model() -> str:
    """Return the first available model from the fallback list (cached after first lookup)."""
    global _available_models_cache
    if _available_models_cache:
        return _available_models_cache[0]
    try:
        w = WorkspaceClient()
        ready = {ep.name for ep in w.serving_endpoints.list() if ep.state and str(ep.state.ready) in ("READY", "EndpointStateReady.READY")}
        for m in dict.fromkeys(_MODEL_FALLBACKS):  # deduplicated, order preserved
            if m in ready:
                _available_models_cache = [m]
                print(f"[model] Using endpoint: {m}")
                return m
    except Exception as e:
        print(f"[model] Endpoint listing failed ({e}), defaulting to primary")
    _available_models_cache = [_MODEL_FALLBACKS[0]]
    return _MODEL_FALLBACKS[0]

def _get_llm(max_tokens: int = 2048):
    """Return a ChatDatabricks LLM using the first available model."""
    try:
        from databricks_langchain import ChatDatabricks
    except ImportError:
        from langchain_community.chat_models import ChatDatabricks  # type: ignore
    model = _resolve_model()
    return ChatDatabricks(endpoint=model, max_tokens=max_tokens), model

# ── Domain config cache ───────────────────────────────────────────────────────
_domain_cache: dict = {}
_domain_cache_lock = threading.Lock()

_SUPPLY_CHAIN_DEFAULT = {
    "schema_raw":  "raw",
    "schema_ont":  "ontology",
    "schema_vec":  "vectors",
    "schema_agt":  "agents",
    "classification_labels": None,  # use module-level hardcoded
    "extraction_schemas":    None,
    "agent_system_prompt":   None,
}

def _get_domain_schemas(domain_id: str) -> dict:
    """
    Return schema names for the given domain_id.
    Results are cached in-process for the app lifetime.
    Falls back to supply_chain defaults ONLY if the domain truly does not exist.

    Robustness: tries full query (with parse_instructions) first; if that column
    doesn't exist yet (ALTER TABLE not yet applied) retries without it so that
    schema routing (schema_raw / schema_vec / …) always works correctly.
    """
    if not domain_id or domain_id == "supply_chain":
        return _SUPPLY_CHAIN_DEFAULT.copy()

    with _domain_cache_lock:
        if domain_id in _domain_cache:
            return _domain_cache[domain_id]

    def _run_query(stmt: str):
        w = WorkspaceClient()
        resp = w.statement_execution.execute_statement(
            warehouse_id=WH_ID,
            statement=stmt,
            wait_timeout="30s",
        )
        rows = resp.result.data_array or []
        if not rows:
            return None
        cols = [c.name for c in resp.manifest.schema.columns]
        return dict(zip(cols, rows[0]))

    cfg = None

    # Attempt 1: full select including parse_instructions + volume_path
    try:
        cfg = _run_query(f"""
            SELECT schema_raw, schema_ont, schema_vec, schema_agt,
                   classification_labels, extraction_schemas,
                   parse_instructions, volume_path, agent_system_prompt
            FROM {CATALOG}.platform.domain_configs
            WHERE domain_id = '{domain_id}' LIMIT 1
        """)
    except Exception as e1:
        # Attempt 2: without new columns (may not exist yet)
        try:
            cfg = _run_query(f"""
                SELECT schema_raw, schema_ont, schema_vec, schema_agt,
                       classification_labels, extraction_schemas, agent_system_prompt
                FROM {CATALOG}.platform.domain_configs
                WHERE domain_id = '{domain_id}' LIMIT 1
            """)
        except Exception as e2:
            print(f"[domain_config] lookup failed for '{domain_id}': {e1}; retry: {e2}")

    if cfg:
        result = {
            "schema_raw":            cfg.get("schema_raw")  or "raw",
            "schema_ont":            cfg.get("schema_ont")  or "ontology",
            "schema_vec":            cfg.get("schema_vec")  or "vectors",
            "schema_agt":            cfg.get("schema_agt")  or "agents",
            "classification_labels": cfg.get("classification_labels"),
            "extraction_schemas":    cfg.get("extraction_schemas"),
            "parse_instructions":    cfg.get("parse_instructions"),
            "volume_path":           cfg.get("volume_path"),
            "agent_system_prompt":   cfg.get("agent_system_prompt"),
        }
        with _domain_cache_lock:
            _domain_cache[domain_id] = result
        return result

    print(f"[domain_config] no row found for '{domain_id}' — using supply_chain defaults")
    return _SUPPLY_CHAIN_DEFAULT.copy()

# ── Pydantic models ──────────────────────────────────────────────────────────

class ClassifyExtractRequest(BaseModel):
    parsed_content: str           # JSON string from ai_parse_document (VARIANT as string)
    doc_id: str                   # filename or unique ID
    doc_type_hint: Optional[str] = None  # optional override

class AgentQueryRequest(BaseModel):
    question: str
    chat_history: Optional[List[dict]] = []
    incident_ref: Optional[str] = None  # inject into system prompt for incident-focused queries

class LogActionRequest(BaseModel):
    action_type: str          # e.g. "RECALL_NOTIFICATION", "SUPPLIER_CONTACT", "INSPECTION"
    description: str
    priority: str = "MEDIUM"  # LOW | MEDIUM | HIGH | CRITICAL
    incident_ref: str = "RCL-2024-0012"
    logged_by: str = "app_user"

# ── Robust JSON parser (handles common LLM output quirks) ─────────────────────

def _robust_json_loads(raw: str) -> dict:
    """
    Try to parse JSON from LLM output with multiple fallback strategies.
    Handles: markdown fences, trailing commas, Python None/True/False,
    single-quoted strings, unquoted keys, ellipsis placeholders.
    """
    import json as _json, re as _re

    def _try(s: str):
        return _json.loads(s)

    def _strip_fences(s: str) -> str:
        s = s.strip()
        if s.startswith("```"):
            lines = s.split("\n")
            # Remove first line (```json or ```) and last line (```)
            inner = lines[1:] if lines[0].startswith("```") else lines
            if inner and inner[-1].strip() == "```":
                inner = inner[:-1]
            s = "\n".join(inner).strip()
        return s

    def _extract_json_block(s: str) -> str:
        """Extract the first {...} block."""
        start = s.find("{")
        if start == -1:
            return s
        depth = 0
        for i, ch in enumerate(s[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return s[start:i+1]
        return s[start:]

    def _fix_common_issues(s: str) -> str:
        # Replace Python/JS literals
        s = _re.sub(r'\bNone\b', 'null', s)
        s = _re.sub(r'\bTrue\b', 'true', s)
        s = _re.sub(r'\bFalse\b', 'false', s)
        # Remove trailing commas before ] or }
        s = _re.sub(r',\s*([\]}])', r'\1', s)
        # Replace single-quoted strings with double-quoted (simple heuristic)
        # Only replace if not inside a double-quoted string
        s = _re.sub(r"(?<![\\\"'])'([^'\\]*(?:\\.[^'\\]*)*)'\s*:", r'"\1":', s)
        s = _re.sub(r":\s*'([^'\\]*(?:\\.[^'\\]*)*)'(?=[,\n}\]])", r': "\1"', s)
        # Remove JS/Python comments
        s = _re.sub(r'//[^\n]*', '', s)
        s = _re.sub(r'#[^\n]*', '', s)
        # Remove ellipsis/placeholder lines
        s = _re.sub(r'\.\.\.,?', '', s)
        return s

    s = _strip_fences(raw)

    # Strategy 1: direct parse
    try:
        return _try(s)
    except Exception:
        pass

    # Strategy 2: extract first JSON block
    block = _extract_json_block(s)
    try:
        return _try(block)
    except Exception:
        pass

    # Strategy 3: fix common issues then parse
    fixed = _fix_common_issues(block)
    try:
        return _try(fixed)
    except Exception:
        pass

    # Strategy 4: extract block from fixed full string
    fixed_full = _fix_common_issues(s)
    block2 = _extract_json_block(fixed_full)
    try:
        return _try(block2)
    except Exception as final_e:
        raise ValueError(f"Could not parse JSON from LLM response. Last error: {final_e}. Raw (first 300): {raw[:300]!r}")


# ── SQL helper ───────────────────────────────────────────────────────────────

def run_sql(query: str, timeout_secs: int = 50) -> list:
    """Execute SQL on the configured warehouse and return rows as list of dicts."""
    try:
        w = WorkspaceClient()
        resp = w.statement_execution.execute_statement(
            warehouse_id=WH_ID,
            statement=query,
            wait_timeout=f"{timeout_secs}s",
        )
        while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(1)
            resp = w.statement_execution.get_statement(resp.statement_id)

        if resp.status.state != StatementState.SUCCEEDED:
            raise HTTPException(status_code=500, detail=f"SQL failed: {resp.status.error}")

        schema = [col.name for col in (resp.manifest.schema.columns or [])]
        rows = resp.result.data_array or []
        return [dict(zip(schema, row)) for row in rows]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _unwrap_value(raw):
    """Normalize an ai_extract field_value into a clean scalar string (or None).

    field_value may be a dict {"value": X}, a JSON/Python-repr string, or a plain
    string. Null/empty forms (including the raw wrapper 'Value:null') return None so
    raw payloads never leak into the UI.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return _unwrap_value(raw.get("value") or raw.get("text") or raw.get("answer"))
    s = str(raw).strip()
    if not s or s.lower() in ("none", "null", "value:null", "{}", '{"value":null}', "{'value': none}"):
        return None
    if s.startswith("{"):
        import json as _json, ast as _ast
        for _parse in (_json.loads, _ast.literal_eval):
            try:
                obj = _parse(s)
                if isinstance(obj, dict):
                    return _unwrap_value(obj.get("value") or obj.get("text") or obj.get("answer"))
            except Exception:
                pass
    return s

# ── Classification labels (same as notebooks/03_idp_pipeline.py) ──────────────

CLASSIFICATION_LABELS = json.dumps({
    "supplier_contract":     "A legal agreement between a supplier and purchaser defining SLAs, pricing, temperature requirements, and liability/penalty clauses.",
    "bill_of_lading":        "A shipping document listing shipment details, carrier, trailer, pickup/delivery times, product quantity, and lot numbers.",
    "temperature_log":       "A continuous time-series temperature monitoring log from a refrigerated trailer, showing readings with alarm events.",
    "certificate_of_analysis": "A quality document certifying product specifications, microbiological test results, lot number, and production/expiry dates.",
    "quality_incident_report": "An internal report documenting a quality incident such as a temperature excursion, product defect, or process failure.",
    "recall_notice":         "An official recall notice specifying lot numbers, affected products, distribution scope, and required actions.",
    "email_chain":           "An email thread regarding shipment exceptions, conditional release decisions, or supplier escalations.",
    "supplier_scorecard":    "A periodic supplier performance evaluation covering KPIs like OTD, fill rate, defect rate, and temperature compliance.",
    "inspection_report":     "A receiving inspection report documenting visual checks, temperature probes, and product condition at a DC.",
    "maintenance_report":    "An equipment maintenance report for a trailer or refrigeration unit including failure diagnosis and corrective actions.",
    "delivery_exception":    "A notification about a delivery exception such as a delay or product hold.",
    "carrier_sla":           "A carrier service level agreement defining transport standards, maintenance obligations, and liability terms.",
    "weather_report":        "A weather conditions report for a transit corridor.",
})

EXTRACTION_CONFIGS = {
    "supplier_contract": {
        "schema": {
            "supplier_name": {"type":"string","description":"Legal name of the supplier."},
            "contract_number": {"type":"string","description":"Contract reference number."},
            "temperature_limit_f": {"type":"string","description":"Maximum temperature threshold in °F."},
            "excursion_threshold_min": {"type":"string","description":"Max allowed excursion minutes before liability."},
            "penalty_amount": {"type":"string","description":"Penalty amount for temperature violations."},
        },
        "instructions": "This is a supplier contract. Extract contractual terms.",
    },
    "bill_of_lading": {
        "schema": {
            "shipment_id": {"type":"string","description":"Shipment or BOL number."},
            "lot_number": {"type":"string","description":"Product lot number."},
            "carrier_name": {"type":"string","description":"Carrier/trucking company."},
            "trailer_id": {"type":"string","description":"Trailer identifier."},
            "distribution_center": {"type":"string","description":"Destination DC name."},
            "quantity_cases": {"type":"string","description":"Number of cases shipped."},
        },
        "instructions": "This is a bill of lading. Extract logistics details.",
    },
    "temperature_log": {
        "schema": {
            "trailer_id": {"type":"string","description":"Trailer identifier."},
            "excursion_detected": {"type":"string","description":"YES or NO."},
            "excursion_duration_min": {"type":"string","description":"Duration in minutes."},
            "peak_temperature_f": {"type":"string","description":"Max temperature in °F."},
            "compliance_status": {"type":"string","description":"COMPLIANT or NON-COMPLIANT."},
        },
        "instructions": "This is a temperature monitoring log. Extract excursion details.",
    },
    "quality_incident_report": {
        "schema": {
            "report_number": {"type":"string","description":"QI report number."},
            "shipment_id": {"type":"string","description":"Affected shipment ID."},
            "lot_number": {"type":"string","description":"Affected lot number."},
            "excursion_duration_min": {"type":"string","description":"Excursion duration in minutes."},
            "peak_temperature_f": {"type":"string","description":"Peak temperature °F."},
            "financial_exposure": {"type":"string","description":"Estimated financial exposure."},
            "risk_classification": {"type":"string","description":"Class I, II, or III."},
        },
        "instructions": "This is a quality incident report. Extract incident details.",
    },
    "recall_notice": {
        "schema": {
            "recall_number": {"type":"string","description":"Recall reference number."},
            "lot_number": {"type":"string","description":"Recalled lot number."},
            "product_name": {"type":"string","description":"Recalled product name."},
            "recall_class": {"type":"string","description":"Class I, II, or III."},
            "num_restaurants_affected": {"type":"string","description":"Number of restaurants affected."},
            "estimated_financial_impact": {"type":"string","description":"Estimated financial impact."},
            "affected_menu_items": {"type":"string","description":"Comma-separated affected menu items."},
        },
        "instructions": "This is a recall notice. Extract recall scope and impact.",
    },
    "weather_report": {
        "schema": {
            "report_date":        {"type":"string","description":"Date of the weather report."},
            "transit_route":      {"type":"string","description":"Transit corridor or route covered by the report."},
            "weather_conditions": {"type":"string","description":"Summary of weather conditions (e.g. clear, fog, storm)."},
            "temperature_range":  {"type":"string","description":"Ambient temperature range along the route."},
            "weather_events":     {"type":"string","description":"Specific weather events recorded (e.g. ice, freezing rain, blizzard). 'None' if clear."},
            "weather_contributed_to_incident": {"type":"string","description":"YES, NO, or POSSIBLE — whether weather contributed to any supply chain incident."},
            "risk_level":         {"type":"string","description":"Overall transit risk level: LOW, MEDIUM, or HIGH."},
        },
        "instructions": "This is a weather conditions report for a transit corridor. Extract weather and risk details.",
    },
    "carrier_sla": {
        "schema": {
            "carrier_name":         {"type":"string","description":"Name of the carrier or logistics provider."},
            "sla_version":          {"type":"string","description":"SLA document version or reference number."},
            "temperature_range_f":  {"type":"string","description":"Required temperature range in °F."},
            "response_time_hours":  {"type":"string","description":"Required response time for excursions (hours)."},
            "penalty_clause":       {"type":"string","description":"Penalty clause for SLA breaches."},
            "effective_date":       {"type":"string","description":"SLA effective date."},
        },
        "instructions": "This is a carrier service level agreement. Extract key SLA terms and obligations.",
    },
    "certificate_of_analysis": {
        "schema": {
            "lot_number":      {"type":"string","description":"Product lot number."},
            "product_name":    {"type":"string","description":"Product name."},
            "test_date":       {"type":"string","description":"Date of analysis."},
            "pass_fail":       {"type":"string","description":"Overall pass/fail result."},
            "pathogen_result": {"type":"string","description":"Pathogen test result (e.g. Negative, Detected)."},
            "ph_level":        {"type":"string","description":"pH level if present."},
            "moisture_pct":    {"type":"string","description":"Moisture percentage if present."},
        },
        "instructions": "This is a certificate of analysis / quality test report. Extract test results and compliance status.",
    },
    "inspection_report": {
        "schema": {
            "facility_name":    {"type":"string","description":"Name of the inspected facility or DC."},
            "inspection_date":  {"type":"string","description":"Date of inspection."},
            "inspector_name":   {"type":"string","description":"Name of inspector."},
            "overall_score":    {"type":"string","description":"Inspection score or rating."},
            "critical_findings":{"type":"string","description":"Critical findings or violations noted."},
            "corrective_actions":{"type":"string","description":"Required corrective actions."},
            "pass_fail":        {"type":"string","description":"Pass or fail outcome."},
        },
        "instructions": "This is a facility or DC inspection report. Extract findings, score, and required actions.",
    },
    "delivery_exception": {
        "schema": {
            "shipment_id":      {"type":"string","description":"Shipment reference number."},
            "exception_type":   {"type":"string","description":"Type of exception (e.g. late delivery, temperature breach, damage)."},
            "exception_date":   {"type":"string","description":"Date the exception occurred."},
            "root_cause":       {"type":"string","description":"Root cause of the exception."},
            "financial_impact": {"type":"string","description":"Estimated financial impact."},
            "resolution_status":{"type":"string","description":"Current resolution status."},
        },
        "instructions": "This is a delivery exception report. Extract the exception type, root cause, and resolution.",
    },
    "maintenance_report": {
        "schema": {
            "asset_id":         {"type":"string","description":"Asset or equipment identifier (trailer, truck, etc)."},
            "maintenance_date": {"type":"string","description":"Date of maintenance."},
            "maintenance_type": {"type":"string","description":"Type of maintenance (preventive, corrective, emergency)."},
            "issues_found":     {"type":"string","description":"Issues or faults found."},
            "repairs_made":     {"type":"string","description":"Repairs or actions taken."},
            "next_service_date":{"type":"string","description":"Next scheduled service date."},
            "technician":       {"type":"string","description":"Technician name or ID."},
        },
        "instructions": "This is an equipment maintenance report. Extract asset info, issues found, and repairs made.",
    },
    "supplier_scorecard": {
        "schema": {
            "supplier_name":        {"type":"string","description":"Supplier name."},
            "scorecard_period":     {"type":"string","description":"Period covered by the scorecard (e.g. Q1 2024)."},
            "overall_score":        {"type":"string","description":"Overall supplier score or rating."},
            "on_time_delivery_pct": {"type":"string","description":"On-time delivery percentage."},
            "quality_score":        {"type":"string","description":"Quality score or defect rate."},
            "compliance_rating":    {"type":"string","description":"Regulatory compliance rating."},
            "risk_level":           {"type":"string","description":"Supplier risk level: LOW, MEDIUM, or HIGH."},
        },
        "instructions": "This is a supplier performance scorecard. Extract scores, KPIs, and risk ratings.",
    },
    "email_chain": {
        "schema": {
            "participants":     {"type":"string","description":"Key participants in the email chain."},
            "subject":          {"type":"string","description":"Email subject or main topic."},
            "date_range":       {"type":"string","description":"Date range of the email chain."},
            "key_decisions":    {"type":"string","description":"Key decisions or agreements reached."},
            "action_items":     {"type":"string","description":"Action items or follow-ups required."},
            "risk_signals":     {"type":"string","description":"Any risk signals, disputes, or compliance concerns raised."},
        },
        "instructions": "This is an email chain or correspondence. Extract participants, key decisions, and action items.",
    },
}

# Default extraction for unknown doc types
DEFAULT_SCHEMA = {
    "document_subject": {"type":"string","description":"The primary subject or topic of this document."},
    "key_entities": {"type":"string","description":"Key named entities: companies, people, locations, dates."},
    "key_facts": {"type":"string","description":"Most important facts or findings in the document."},
    "risk_indicators": {"type":"string","description":"Any risk signals, violations, or compliance issues mentioned."},
}


# ── Routes ───────────────────────────────────────────────────────────────────


@router.post("/agent-query")
async def agent_query(req: AgentQueryRequest, domain_id: str = "supply_chain"):
    """
    Multi-domain AI agent query.
    - Supply chain: uses UC Function toolkit + VS (full agent executor)
    - All other domains: uses direct LLM + VS document context (same path as copilot-query)
    """
    try:
        from databricks_langchain import ChatDatabricks
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"LLM library not available: {e}. Ensure databricks-langchain is installed.")

    _domain = _get_domain_schemas(domain_id)
    _raw = _domain["schema_raw"]
    _vec_schema = _domain.get("schema_vec", "vectors")
    _domain_vs_index = f"{CATALOG}.{_vec_schema}.{domain_id}_docs_index"

    _base_prompt = _domain.get("agent_system_prompt") or (
        f"You are the {domain_id.replace('_', ' ').title()} AI assistant. "
        "You answer questions by synthesizing information from the provided document context. "
        "Always cite the source document IDs. Be specific. Think step by step."
    )
    if req.incident_ref:
        _base_prompt += f"\n\nACTIVE CONTEXT: {req.incident_ref}. Focus answers on this context when relevant."

    # ── Compliance Due Diligence: four-agent tool-calling agent ──────────────
    if domain_id == CDD_DOMAIN_ID:
        return _cdd_agent_query(req, domain_id, _domain, _base_prompt, _domain_vs_index)

    # ── Supply chain: full UC function agent ─────────────────────────────────
    if domain_id == "supply_chain":
        try:
            from langchain.agents import AgentExecutor, create_tool_calling_agent
            from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
            from langchain_community.tools.databricks import UCFunctionToolkit

            _agt = _domain["schema_agt"]
            uc_toolkit = UCFunctionToolkit(catalog=CATALOG, schema=_agt)
            uc_tools = uc_toolkit.get_tools()

            vs_tool_available = False
            try:
                from databricks.vector_search.client import VectorSearchClient
                from langchain_core.tools import tool
                vsc = VectorSearchClient()
                vsc.get_index(VS_ENDPOINT, _domain_vs_index)  # validate

                @tool
                def search_documents(query: str, doc_type_filter: str = None) -> str:
                    """Search supply chain documents semantically using Vector Search."""
                    index = vsc.get_index(VS_ENDPOINT, _domain_vs_index)
                    results = index.similarity_search(
                        query_text=query,
                        columns=["chunk_id", "doc_id", "doc_type", "chunk_to_retrieve"],
                        filters={"doc_type": doc_type_filter} if doc_type_filter else None,
                        num_results=5,
                    )
                    data = results.get("result", {}).get("data_array", [])
                    if not data:
                        return "No relevant documents found."
                    return "\n\n---\n\n".join(
                        f"[Source: {r[1]} | Type: {r[2]}]\n{r[3]}"
                        for r in data if len(r) > 3
                    )

                uc_tools = uc_tools + [search_documents]
                vs_tool_available = True
            except Exception:
                pass

            prompt = ChatPromptTemplate.from_messages([
                ("system", _base_prompt),
                MessagesPlaceholder("chat_history", optional=True),
                ("human", "{input}"),
                MessagesPlaceholder("agent_scratchpad"),
            ])
            llm, _used_model = _get_llm(max_tokens=2048)
            agent = create_tool_calling_agent(llm, uc_tools, prompt)
            executor = AgentExecutor(agent=agent, tools=uc_tools, verbose=False, max_iterations=6)
            result = executor.invoke({
                "input": req.question,
                "chat_history": req.chat_history or [],
            })
            return {
                "answer": result.get("output", ""),
                "question": req.question,
                "tools_used": len(uc_tools),
                "vector_search_active": vs_tool_available,
                "model": AGENT_MODEL,
            }
        except Exception as e:
            fallback = _sql_fallback(req.question, "supply_chain")
            return {"answer": fallback, "question": req.question, "fallback": True, "error": str(e)}

    # ── All other domains: direct LLM with document context ──────────────────
    # (Same approach as copilot-query — no UC functions required)
    try:
        context_text = ""
        cited_docs: list = []

        # 1. Try VS search first
        try:
            from databricks.vector_search.client import VectorSearchClient
            vsc = VectorSearchClient()
            index = vsc.get_index(VS_ENDPOINT, _domain_vs_index)
            results = index.similarity_search(
                query_text=req.question,
                columns=["chunk_id", "doc_id", "doc_type", "chunk_to_retrieve"],
                num_results=6,
            )
            data = results.get("result", {}).get("data_array", [])
            if data:
                chunks = []
                for row in data:
                    doc_id = row[1] if len(row) > 1 else "unknown"
                    doc_type = row[2] if len(row) > 2 else ""
                    chunk = row[3] if len(row) > 3 else ""
                    if doc_id not in cited_docs:
                        cited_docs.append(doc_id)
                    chunks.append(f"[Source: {doc_id} | Type: {doc_type}]\n{chunk}")
                context_text = "\n\n---\n\n".join(chunks)
        except Exception:
            pass

        # 2. SQL fallback for document context if VS unavailable
        if not context_text:
            try:
                fallback_rows = run_sql(f"""
                    SELECT doc_id, doc_type,
                           SUBSTRING(CAST(parsed_content AS STRING), 1, 600) AS snippet
                    FROM {CATALOG}.{_raw}.parsed_documents
                    ORDER BY processed_ts DESC NULLS LAST
                    LIMIT 8
                """, timeout_secs=20) or []
                if fallback_rows:
                    cited_docs = [r["doc_id"] for r in fallback_rows]
                    context_text = "\n\n---\n\n".join(
                        f"[Source: {r['doc_id']} | Type: {r.get('doc_type','')}]\n{r.get('snippet','')}"
                        for r in fallback_rows
                    )
            except Exception:
                pass

        # 3. Build the human message with context
        human_content = req.question
        if context_text:
            human_content = (
                f"Use the following document excerpts as your primary source material:\n\n"
                f"{context_text}\n\n---\n\nQuestion: {req.question}"
            )

        # 4. Include chat history in the system prompt context if provided
        chat_ctx = ""
        if req.chat_history:
            history_lines = []
            for m in req.chat_history[-6:]:  # last 6 turns
                role = m.get("role", "user")
                content = m.get("content", "")
                history_lines.append(f"{role.upper()}: {content}")
            chat_ctx = "\n\nPrevious conversation:\n" + "\n".join(history_lines) + "\n"

        llm, _used_model = _get_llm(max_tokens=2048)
        response = llm.invoke([
            SystemMessage(content=_base_prompt + chat_ctx),
            HumanMessage(content=human_content),
        ])

        return {
            "answer": response.content.strip(),
            "question": req.question,
            "tools_used": 0,
            "vector_search_active": bool(context_text),
            "cited_docs": cited_docs,
            "model": AGENT_MODEL,
        }

    except Exception as e:
        return {
            "answer": f"I encountered an error processing your question: {str(e)}. Please try again.",
            "question": req.question,
            "fallback": True,
            "error": str(e),
        }


def _sql_fallback(question: str, domain_id: str = "supply_chain") -> str:
    """Domain-aware SQL fallback when agent isn't deployed or fails."""
    q = question.lower()
    if domain_id == "supply_chain":
        if "restaurant" in q and ("recall" in q or "affected" in q or "received" in q):
            rows = run_sql(f"""
                SELECT r.restaurant_name, r.state, inv.quantity_cases, inv.delivery_date
                FROM {CATALOG}.{SCH_RAW}.inventory_distribution inv
                JOIN {CATALOG}.{SCH_RAW}.restaurants r ON inv.restaurant_id = r.restaurant_id
                WHERE inv.lot_number = 'LOT-PP-240315'
                ORDER BY r.state
            """)
            if rows:
                lines = [f"  • {r['restaurant_name']} ({r['state']}) — {r['quantity_cases']} cases delivered {r['delivery_date']}" for r in rows]
                return f"12 restaurants received product from LOT-PP-240315 (Recall RCL-2024-0012):\n" + "\n".join(lines)
        if "financial" in q or "exposure" in q or "cost" in q:
            return "Estimated total financial exposure: $220,100 net ($224,800 gross)\n• $15,000 contract penalty\n• $24,000 product disposal\n• $3,500 retesting\n• $187,000 lost restaurant revenue\n• -$4,700 carrier offset"
        if "supplier" in q and ("risk" in q or "score" in q or "performance" in q):
            rows = run_sql(f"""
                SELECT supplier_name, risk_score, region
                FROM {CATALOG}.{SCH_RAW}.suppliers
                ORDER BY risk_score ASC LIMIT 5
            """)
            if rows:
                lines = [f"  • {r['supplier_name']}: {r['risk_score']} risk score ({r['region']})" for r in rows]
                return "Suppliers by risk (lowest score = highest risk):\n" + "\n".join(lines)
        return "I can answer supply chain questions about recall events, affected restaurants, financial exposure, supplier risk, and contractual liability. Please rephrase or ensure the agent is deployed."
    else:
        # Generic fallback for all other domains — pull recent parsed doc summaries
        _domain = _get_domain_schemas(domain_id)
        _raw = _domain.get("schema_raw", "raw")
        try:
            rows = run_sql(f"""
                SELECT doc_id, doc_type, SUBSTRING(CAST(parsed_content AS STRING), 1, 300) AS snippet
                FROM {CATALOG}.{_raw}.parsed_documents
                ORDER BY processed_ts DESC NULLS LAST
                LIMIT 5
            """, timeout_secs=20) or []
            if rows:
                lines = [f"  • [{r.get('doc_type','unknown')}] {r.get('doc_id','')}: {r.get('snippet','')[:200]}" for r in rows]
                return f"Here are recent documents from the {domain_id.replace('_',' ')} library:\n" + "\n".join(lines)
        except Exception:
            pass
        return f"I answer questions grounded in the {domain_id.replace('_', ' ')} document library. Please ensure the AI agent is fully deployed and try again."
@router.get("/domain-overview")
async def domain_overview(domain_id: str = "supply_chain"):
    """
    Returns high-level analytics for any domain:
      - document type breakdown
      - entity type distribution
      - recent extracted fields (sample)
      - incident counts
      - top extracted entities
    Used by the Control Tower when the domain is not supply_chain.
    """
    _d = _get_domain_schemas(domain_id)
    _raw = _d["schema_raw"]; _ont = _d["schema_ont"]

    # -- Document type breakdown
    doc_types = []
    try:
        rows = run_sql(f"""
            SELECT doc_type, COUNT(*) AS doc_count
            FROM {CATALOG}.{_raw}.parsed_documents
            GROUP BY doc_type
            ORDER BY doc_count DESC
        """)
        doc_types = [{"doc_type": r["doc_type"] or "unknown", "doc_count": int(r["doc_count"] or 0)} for r in rows]
    except Exception:
        pass

    # -- Total documents processed
    total_docs = sum(d["doc_count"] for d in doc_types)

    # -- Entity type distribution (from ontology)
    entity_types = []
    try:
        rows = run_sql(f"""
            SELECT entity_type, COUNT(*) AS cnt
            FROM {CATALOG}.{_ont}.entities
            GROUP BY entity_type
            ORDER BY cnt DESC
            LIMIT 12
        """)
        entity_types = [{"entity_type": r["entity_type"], "count": int(r["cnt"] or 0)} for r in rows]
    except Exception:
        pass

    total_entities = sum(e["count"] for e in entity_types)

    # -- Relationship count
    total_relationships = 0
    try:
        rows = run_sql(f"SELECT COUNT(*) AS cnt FROM {CATALOG}.{_ont}.relationships")
        if rows: total_relationships = int(rows[0]["cnt"] or 0)
    except Exception:
        pass

    # -- Top extracted fields (recent sample)
    recent_extractions: list[dict] = []
    try:
        rows = run_sql(f"""
            SELECT doc_id, doc_type, field_name, field_value
            FROM {CATALOG}.{_raw}.extracted_fields
            WHERE field_value IS NOT NULL AND field_value != ''
            ORDER BY RAND()
            LIMIT 20
        """)
        recent_extractions = [
            {"doc_id": r["doc_id"], "doc_type": r["doc_type"],
             "field_name": r["field_name"], "field_value": str(r["field_value"])[:120]}
            for r in rows
        ]
    except Exception:
        pass

    # -- Incidents / cases
    incident_counts: dict = {}
    total_incidents = 0
    try:
        rows = run_sql(f"""
            SELECT status, COUNT(*) AS cnt
            FROM {CATALOG}.platform.incidents
            WHERE domain_id = '{domain_id}'
            GROUP BY status
        """)
        incident_counts = {r["status"]: int(r["cnt"] or 0) for r in rows}
        total_incidents = sum(incident_counts.values())
    except Exception:
        pass

    # -- Recent incidents (for listing)
    recent_incidents: list[dict] = []
    try:
        rows = run_sql(f"""
            SELECT incident_id, incident_type, title, status, severity, opened_date
            FROM {CATALOG}.platform.incidents
            WHERE domain_id = '{domain_id}'
            ORDER BY opened_date DESC
            LIMIT 5
        """)
        recent_incidents = [
            {"incident_id": r["incident_id"], "incident_type": r["incident_type"],
             "title": r["title"], "status": r["status"], "severity": r["severity"],
             "opened_date": str(r["opened_date"])}
            for r in rows
        ]
    except Exception:
        pass

    return {
        "domain_id":           domain_id,
        "total_docs":          total_docs,
        "doc_types":           doc_types,
        "total_entities":      total_entities,
        "entity_types":        entity_types,
        "total_relationships": total_relationships,
        "recent_extractions":  recent_extractions,
        "total_incidents":     total_incidents,
        "incident_counts":     incident_counts,
        "recent_incidents":    recent_incidents,
    }


# ── Ontology Graph ─────────────────────────────────────────────────────────────

@router.get("/ontology-graph")
async def ontology_graph(domain_id: str = "supply_chain"):
    """
    Returns graph nodes and edges for the domain ontology visualization.
    Tries to pull live data from the ontology tables; falls back to a hardcoded
    supply_chain graph if the tables are empty.
    """
    # Fixed-position layout (x,y in a 900×500 SVG canvas)
    FALLBACK_NODES = [
        {"id": "tyson",    "label": "Tyson Foods",        "type": "Supplier",       "x": 80,  "y": 160, "risk": "high"},
        {"id": "swift",    "label": "Swift Logistics",    "type": "Carrier",        "x": 80,  "y": 320, "risk": "medium"},
        {"id": "lot",      "label": "LOT-PP-240315",      "type": "Lot",            "x": 280, "y": 160, "risk": "high"},
        {"id": "shp",      "label": "SHP-20240315",       "type": "Shipment",       "x": 280, "y": 320, "risk": "high"},
        {"id": "tr8821",   "label": "Trailer TR-8821",    "type": "Equipment",      "x": 280, "y": 460, "risk": "high"},
        {"id": "qir",      "label": "QIR-2024-0047",      "type": "QualityIncident","x": 500, "y": 240, "risk": "critical"},
        {"id": "rcl",      "label": "RCL-2024-0012",      "type": "RecallEvent",    "x": 500, "y": 400, "risk": "critical"},
        {"id": "atldc",    "label": "Atlanta DC",         "type": "DistributionCenter","x": 700,"y": 160,"risk": "medium"},
        {"id": "rest",     "label": "12 SE Restaurants",  "type": "RestaurantGroup","x": 900, "y": 240, "risk": "high"},
        {"id": "coa",      "label": "LOT Certificate",    "type": "Document",       "x": 700, "y": 380, "risk": "info"},
    ]
    FALLBACK_EDGES = [
        {"source": "tyson",  "target": "lot",   "label": "produces"},
        {"source": "tyson",  "target": "shp",   "label": "ships"},
        {"source": "swift",  "target": "shp",   "label": "transports"},
        {"source": "shp",    "target": "lot",   "label": "contains"},
        {"source": "tr8821", "target": "shp",   "label": "used_in"},
        {"source": "shp",    "target": "qir",   "label": "triggered"},
        {"source": "qir",    "target": "rcl",   "label": "escalated_to"},
        {"source": "lot",    "target": "atldc", "label": "received_at"},
        {"source": "atldc",  "target": "rest",  "label": "distributed_to"},
        {"source": "coa",    "target": "lot",   "label": "certifies"},
        {"source": "rcl",    "target": "rest",  "label": "impacts"},
    ]

    try:
        import math
        _ont_graph = _get_domain_schemas(domain_id)["schema_ont"]

        # Pull ALL entities (no hard cap — up to 200 is fine for a graph)
        raw_entities = run_sql(f"""
            SELECT entity_id, entity_type,
                   COALESCE(display_name, entity_id) AS label
            FROM {CATALOG}.{_ont_graph}.entities
            LIMIT 200
        """)
        raw_rels = run_sql(f"""
            SELECT subject_id, predicate AS relationship_type, object_id AS target_id
            FROM {CATALOG}.{_ont_graph}.relationships
            LIMIT 300
        """)

        if raw_entities:
            RISK_MAP = {
                "Supplier": "high", "RecallEvent": "critical", "QualityIncident": "critical",
                "Shipment": "high", "Lot": "high", "TemperatureExcursion": "critical",
                "Carrier": "medium", "DistributionCenter": "medium", "Equipment": "medium",
                "Document": "info", "Restaurant": "high", "Product": "info", "Contract": "medium",
            }

            # Known fixed positions for the primary incident entities
            FIXED_POS: dict = {
                "SUPP-001": (80, 120), "CAR-001": (80, 300),
                "LOT-PP-240315": (280, 120), "SHP-20240315": (280, 280),
                "TE-20240315-001": (460, 200), "QIR-2024-0047": (460, 340),
                "RCL-2024-0012": (640, 200), "DC-001": (640, 360),
                "CONTRACT-MSA-2024-TF-001": (80, 450), "PRD-001": (280, 440),
            }

            # Separate restaurants so they collapse into one group node
            restaurants = [e for e in raw_entities if e["entity_type"] == "Restaurant"]
            rest_ids    = {e["entity_id"] for e in restaurants}
            non_rest    = [e for e in raw_entities if e["entity_id"] not in rest_ids]

            nodes: list = []
            positioned_ids: set = set()

            # 1. Place entities that have a known fixed position
            for e in non_rest:
                pos = FIXED_POS.get(e["entity_id"])
                if pos:
                    nodes.append({
                        "id":   e["entity_id"],
                        "label": e.get("label") or e["entity_id"],
                        "type": e["entity_type"],
                        "x": pos[0], "y": pos[1],
                        "risk": RISK_MAP.get(e["entity_type"], "info"),
                    })
                    positioned_ids.add(e["entity_id"])

            # 2. Auto-layout all remaining (unknown) entities in a grid below the fixed band
            unpositioned = [e for e in non_rest if e["entity_id"] not in positioned_ids]
            if unpositioned:
                cols = max(1, min(6, len(unpositioned)))
                col_w, row_h = 150, 90
                grid_x0, grid_y0 = 60, 540
                for i, e in enumerate(unpositioned):
                    col = i % cols
                    row = i // cols
                    nodes.append({
                        "id":   e["entity_id"],
                        "label": e.get("label") or e["entity_id"],
                        "type": e["entity_type"],
                        "x": grid_x0 + col * col_w,
                        "y": grid_y0 + row * row_h,
                        "risk": RISK_MAP.get(e["entity_type"], "info"),
                    })

            # 3. Collapse all restaurants into one representative node
            if restaurants:
                nodes.append({
                    "id":    "RESTAURANTS",
                    "label": f"{len(restaurants)} Restaurants",
                    "type":  "RestaurantGroup",
                    "x":     860, "y": 250,
                    "risk":  "high",
                })

            # 4. Build deduplicated edge list; remap restaurant IDs to the group node
            valid_ids = {n["id"] for n in nodes}
            edges: list = []
            seen: set = set()
            for r in raw_rels:
                src = r["subject_id"]
                tgt = r.get("target_id") or r.get("object_id") or ""
                rel = r.get("relationship_type") or r.get("predicate") or ""
                if tgt in rest_ids:
                    tgt = "RESTAURANTS"
                if src in rest_ids:
                    src = "RESTAURANTS"
                # Only include edges where both endpoints are visible nodes
                if src not in valid_ids or tgt not in valid_ids:
                    continue
                key = (src, rel, tgt)
                if key in seen:
                    continue
                seen.add(key)
                edges.append({"source": src, "target": tgt, "label": rel})

            return {"nodes": nodes, "edges": edges, "source": "live"}
    except Exception:
        pass

    return {"nodes": FALLBACK_NODES, "edges": FALLBACK_EDGES, "source": "fallback"}


# ── Document Library ────────────────────────────────────────────────────────────

DOC_TYPE_LABELS: dict = {
    "supplier_contract":      "Supplier Contract",
    "bill_of_lading":         "Bill of Lading",
    "temperature_log":        "Temperature Log",
    "certificate_of_analysis":"Certificate of Analysis",
    "quality_incident_report":"Quality Incident Report",
    "recall_notice":          "Recall Notice",
    "email_chain":            "Email Chain",
    "supplier_scorecard":     "Supplier Scorecard",
    "inspection_report":      "Inspection Report",
    "maintenance_report":     "Maintenance Report",
    "delivery_exception":     "Delivery Exception",
    "carrier_sla":            "Carrier SLA",
    "weather_report":         "Weather Report",
}

PROCESS_DOCS_JOB_NAME = "DocIntelligence — Process New Documents"
FULL_PIPELINE_JOB_NAME = "DocIntelligence — Full Pipeline"

# Known job IDs as a hard fallback when name-based search is unavailable
# (e.g. service principal lacks jobs:list permission).  Updated by create_domain_job().
_KNOWN_JOB_IDS: dict[str, int] = {
    "supply_chain":             1095463829768201,   # DocIntelligence — Process New Documents
    "compliance":               1096897875306787,   # DocIntelligence — Compliance Pipeline
    "compliance_due_diligence": 872826521276390,    # DocIntelligence — Compliance Due Diligence Pipeline
}

# Genie space ids per domain — powers the Copilot "Data Questions" (aggregate SQL) mode.
_GENIE_SPACE_IDS: dict[str, str] = {
    "compliance_due_diligence": "01f17d61d9051dcdb0c80dd20b1f9aa8",
}

def _find_job_id(name_fragment: str) -> int | None:
    """Find the first job whose name contains name_fragment (case-insensitive substring)."""
    try:
        w = WorkspaceClient()
        fragment_lower = name_fragment.lower()
        for j in w.jobs.list():
            if j.settings and fragment_lower in (j.settings.name or "").lower():
                return j.job_id
    except Exception as e:
        print(f"[pipeline] job lookup error: {e}")
    return None


def _resolve_pipeline_job(domain_id: str, domain_cfg: dict) -> tuple[int, str]:
    """
    Return (job_id, job_name) for the given domain.

    Lookup order:
      1. analytics_config.pipeline_job_id  (stored per-domain)
      2. _KNOWN_JOB_IDS dict               (hard-coded fallback)
      3. Name search via jobs.list()
    """
    # 1. Stored job_id in domain analytics_config
    try:
        ac = domain_cfg.get("analytics_config") or {}
        if isinstance(ac, str):
            import json as _j; ac = _j.loads(ac)
        stored = ac.get("pipeline_job_id")
        if stored:
            return int(stored), f"DocIntelligence — {domain_id} Pipeline"
    except Exception:
        pass

    # 2. Hard-coded fallback
    if domain_id in _KNOWN_JOB_IDS:
        return _KNOWN_JOB_IDS[domain_id], PROCESS_DOCS_JOB_NAME

    # 3. Name-based search (may fail if SP lacks jobs:list)
    jid = _find_job_id(PROCESS_DOCS_JOB_NAME)
    if jid:
        return jid, PROCESS_DOCS_JOB_NAME
    jid = _find_job_id(FULL_PIPELINE_JOB_NAME)
    if jid:
        return jid, FULL_PIPELINE_JOB_NAME

    raise HTTPException(
        status_code=404,
        detail=(
            f"No pipeline job found for domain '{domain_id}'. "
            "Run 'python3 scripts/create_domain_job.py {domain_id}' to create one, "
            "or grant the app service principal CAN_VIEW on the pipeline jobs."
        )
    )


@router.post("/trigger-pipeline")
async def trigger_pipeline(
    domain_id:      str  = "supply_chain",
    volume_path:    str  = "",
    mode:           str  = "batch",
    batch_size:     int  = 999,
    doc_types:      str  = "",
    skip_no_schema: bool = True,
    schema_mode:    str  = "hybrid",   # "configured" | "hybrid" | "ai_infer"
    schedule_cron:  str  = "",
    job_name:       str  = "",
):
    """
    Trigger the IDP pipeline for a domain.
    All processing parameters are forwarded as job_parameters so the pipeline
    notebook (03_idp_pipeline.py) receives them via dbutils.widgets.get().
    Returns run_id, run_url, job_name so the UI can show tracking info immediately.
    """
    try:
        w = WorkspaceClient()
        _d = _get_domain_schemas(domain_id)
        job_id, resolved_job_name = _resolve_pipeline_job(domain_id, _d)
        if not job_name:
            job_name = resolved_job_name

        # Validate + normalise schema_mode
        valid_modes = {"configured", "hybrid", "ai_infer"}
        if schema_mode not in valid_modes:
            schema_mode = "hybrid"
        # Derive skip_no_schema from schema_mode for backward-compat with older notebooks
        effective_skip = (schema_mode == "configured")

        # Forward all processing parameters so notebook widgets pick them up
        job_parameters: dict = {
            "domain_id":      domain_id,
            "volume_path":    volume_path or "",
            "mode":           mode,
            "batch_size":     str(batch_size),
            "doc_types":      doc_types or "",
            "skip_no_schema": str(effective_skip).lower(),
            "schema_mode":    schema_mode,
        }

        run = w.jobs.run_now(
            job_id=job_id,
            job_parameters=job_parameters,
        )
        run_id = run.run_id

        # Fetch run details to get the run page URL
        run_url = None
        try:
            import time as _t
            _t.sleep(1)  # brief wait for run to register
            run_detail = w.jobs.get_run(run_id=run_id)
            run_url = run_detail.run_page_url
        except Exception:
            pass

        # Enumerate tasks expected for this job
        expected_tasks = []
        try:
            job_detail = w.jobs.get(job_id=job_id)
            expected_tasks = [
                TASK_LABELS.get(t.task_key, t.task_key)
                for t in (job_detail.settings.tasks or [])
            ]
        except Exception:
            pass

        return {
            "success":        True,
            "run_id":         run_id,
            "run_url":        run_url,
            "job_id":         job_id,
            "job_name":       job_name,
            "domain_id":      domain_id,
            "expected_tasks": expected_tasks,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Human-friendly labels for each pipeline task key
TASK_LABELS = {
    "platform_setup":   "Platform Setup",
    "setup":            "Provision Schema & Volume",
    "synthetic_corpus": "Generate Synthetic Corpus",
    "structured_tables":"Build Structured Tables",
    "generate_pdfs":    "Generate PDF Documents",
    "workflow_prepare": "Prepare Pipeline",
    "workflow_parse":   "Parse Documents (AI)",
    "workflow_extract": "Extract Document Content",
    "idp_pipeline":     "Classify & Extract Fields",
    "ontology_mapping": "Build Knowledge Graph",
    "vector_search":    "Index for Semantic Search",
    "agent":            "Register AI Agent",
    "demo_scenario":    "Demo Scenario Validation",
}

def _run_state_simple(state) -> str:
    if not state:
        return "unknown"
    lc = state.life_cycle_state.value if state.life_cycle_state else ""
    rs = state.result_state.value if state.result_state else ""
    if lc in ("RUNNING", "PENDING"):
        return "running"
    if rs == "SUCCESS":
        return "succeeded"
    if rs in ("FAILED", "TIMEDOUT", "CANCELED", "INTERNAL_ERROR"):
        return "failed"
    if lc in ("BLOCKED", "SKIPPED"):
        return "skipped"
    return lc.lower()


# ── Job schedule management ───────────────────────────────────────────────────

class JobScheduleRequest(BaseModel):
    domain_id:        str
    cron_expression:  Optional[str] = None   # None / "" = remove schedule
    timezone_id:      Optional[str] = "UTC"
    use_notifications: Optional[bool] = False  # for workflow_parse task


@router.get("/job-schedule")
async def get_job_schedule(domain_id: str = "supply_chain"):
    """Return the current trigger schedule for the domain pipeline job."""
    try:
        w = WorkspaceClient()
        _d = _get_domain_schemas(domain_id)
        job_id, job_name = _resolve_pipeline_job(domain_id, _d)
        job = w.jobs.get(job_id=job_id)
        sched = job.settings and job.settings.schedule
        # Also read use_notifications from workflow_parse task
        use_notifications = False
        for t in (job.settings.tasks or []):
            if t.task_key == "workflow_parse" and t.notebook_task:
                bp = t.notebook_task.base_parameters or {}
                use_notifications = str(bp.get("use_notifications", "false")).lower() == "true"
                break
        if sched and sched.quartz_cron_expression:
            return {
                "has_schedule":      True,
                "cron_expression":   sched.quartz_cron_expression,
                "timezone_id":       getattr(sched, "timezone_id", None) or "UTC",
                "use_notifications": use_notifications,
                "job_id":            job_id,
                "job_name":          job_name,
            }
        return {
            "has_schedule":      False,
            "cron_expression":   None,
            "timezone_id":       "UTC",
            "use_notifications": use_notifications,
            "job_id":            job_id,
            "job_name":          job_name,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/job-schedule")
async def update_job_schedule(req: JobScheduleRequest):
    """
    Set or remove the cron trigger schedule on the domain pipeline job.
    Also updates use_notifications on the workflow_parse task.
    """
    try:
        w = WorkspaceClient()
        _d = _get_domain_schemas(req.domain_id)
        job_id, job_name = _resolve_pipeline_job(req.domain_id, _d)
        job = w.jobs.get(job_id=job_id)
        settings = job.settings

        # Update schedule
        from databricks.sdk.service.jobs import CronSchedule, PauseStatus, JobSettings
        new_cron = (req.cron_expression or "").strip()
        if new_cron:
            settings.schedule = CronSchedule(
                quartz_cron_expression=new_cron,
                timezone_id=req.timezone_id or "UTC",
                pause_status=PauseStatus.UNPAUSED,
            )
        else:
            settings.schedule = None

        # Update use_notifications on workflow_parse task
        for t in (settings.tasks or []):
            if t.task_key == "workflow_parse" and t.notebook_task:
                bp = dict(t.notebook_task.base_parameters or {})
                bp["use_notifications"] = "true" if req.use_notifications else "false"
                t.notebook_task.base_parameters = bp
                break

        w.jobs.reset(job_id=job_id, new_settings=settings)

        return {
            "success":           True,
            "job_id":            job_id,
            "job_name":          job_name,
            "cron_expression":   new_cron or None,
            "timezone_id":       req.timezone_id or "UTC",
            "use_notifications": req.use_notifications,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Document search ───────────────────────────────────────────────────────────

@router.get("/search-docs")
async def search_docs(
    domain_id: str = "supply_chain",
    q: str = "",
    mode: str = "keyword",   # "keyword" | "semantic"
    limit: int = 20,
):
    """
    Search parsed documents for a domain.
    - keyword: SQL ILIKE on raw_text and filename — always available
    - semantic: Vector Search similarity_search on document_chunks — requires VS index
    Returns a uniform list of { doc_id, filename, doc_type, snippet, score? }
    """
    q = q.strip()
    if not q:
        return {"results": [], "mode": mode, "total": 0}

    try:
        _d = _get_domain_schemas(domain_id)
        _raw = _d["schema_raw"]
        _vec = _d.get("schema_vec", "vectors")
        results: list = []

        if mode == "semantic":
            try:
                from databricks.vector_search.client import VectorSearchClient
                vsc = VectorSearchClient()
                vs_index_name = f"{CATALOG}.{_vec}.{domain_id}_docs_index"
                index = vsc.get_index(VS_ENDPOINT, vs_index_name)
                vs_res = index.similarity_search(
                    query_text=q,
                    columns=["chunk_id", "doc_id", "doc_type", "chunk_to_retrieve"],
                    num_results=limit,
                )
                data = vs_res.get("result", {}).get("data_array", [])
                # Map chunk rows back to filenames via a batch SQL join
                doc_ids = list({row[1] for row in data if len(row) > 1})
                filenames: dict = {}
                if doc_ids:
                    id_list = ", ".join(f"'{d}'" for d in doc_ids)
                    fn_rows = run_sql(
                        f"SELECT doc_id, filename, doc_type FROM {CATALOG}.{_raw}.parsed_documents "
                        f"WHERE doc_id IN ({id_list})"
                    ) or []
                    filenames = {r["doc_id"]: r for r in fn_rows}
                for row in data:
                    if len(row) < 4:
                        continue
                    doc_id = row[1]
                    doc_type = row[2] or ""
                    snippet = (row[3] or "")[:300]
                    fn_info = filenames.get(doc_id, {})
                    results.append({
                        "doc_id":   doc_id,
                        "filename": fn_info.get("filename", doc_id),
                        "doc_type": fn_info.get("doc_type", doc_type),
                        "snippet":  snippet,
                        "score":    None,
                    })
            except Exception as vs_err:
                # Fall back to keyword on VS failure
                mode = "keyword_fallback"
                results = []

        if mode in ("keyword", "keyword_fallback"):
            like = f"%{q.lower()}%"
            # Domain isolation comes from the schema (e.g. jai_docintel.compliance or .raw),
            # not from a domain_id column — so no WHERE domain_id filter is needed.
            rows = run_sql(f"""
                SELECT doc_id, filename, doc_type,
                       LEFT(raw_text, 300) AS snippet
                FROM {CATALOG}.{_raw}.parsed_documents
                WHERE LOWER(raw_text) LIKE '{like}'
                   OR LOWER(filename) LIKE '{like}'
                ORDER BY processed_ts DESC
                LIMIT {int(limit)}
            """) or []
            results = [
                {
                    "doc_id":   r["doc_id"],
                    "filename": r["filename"],
                    "doc_type": r["doc_type"] or "",
                    "snippet":  r["snippet"] or "",
                    "score":    None,
                }
                for r in rows
            ]

        return {"results": results, "mode": mode, "total": len(results), "query": q}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Processing configuration & file tracking ─────────────────────────────────

_proc_cfg_checked = False

def _ensure_proc_cfg_table():
    """Ensure platform.processing_configs table exists."""
    global _proc_cfg_checked
    if _proc_cfg_checked:
        return
    try:
        run_sql(f"""
            CREATE TABLE IF NOT EXISTS {CATALOG}.platform.processing_configs (
                domain_id        STRING NOT NULL,
                volume_path      STRING,
                doc_types        STRING,    -- JSON array of doc type strings to process
                job_name         STRING,
                schedule_cron    STRING,    -- cron expression, e.g. "0 2 * * *"
                skip_no_schema   BOOLEAN,
                updated_at       TIMESTAMP
            ) USING DELTA
        """, timeout_secs=30)
    except Exception as e:
        print(f"[proc_cfg_table] {e}")
    _proc_cfg_checked = True


_proc_log_checked = False

def _ensure_proc_log_table():
    """Ensure platform.file_processing_log table exists."""
    global _proc_log_checked
    if _proc_log_checked:
        return
    try:
        run_sql(f"""
            CREATE TABLE IF NOT EXISTS {CATALOG}.platform.file_processing_log (
                file_path        STRING NOT NULL,
                file_name        STRING,
                domain_id        STRING,
                doc_type         STRING,
                status           STRING,   -- pending / processing / success / failed / skipped
                processed_at     TIMESTAMP,
                job_run_id       BIGINT,
                records_written  INT,
                error_message    STRING,
                file_size_bytes  BIGINT,
                pipeline_version STRING
            ) USING DELTA
        """, timeout_secs=30)
    except Exception as e:
        print(f"[proc_log_table] {e}")
    _proc_log_checked = True


class ProcessingConfigRequest(BaseModel):
    domain_id: str
    volume_path: Optional[str] = None
    doc_types: Optional[str] = None       # JSON array
    job_name: Optional[str] = None
    schedule_cron: Optional[str] = None
    skip_no_schema: bool = True


@router.get("/processing-config")
async def get_processing_config(domain_id: str = "supply_chain"):
    """Return saved processing configuration for a domain."""
    _ensure_proc_cfg_table()
    try:
        rows = run_sql(f"""
            SELECT volume_path, doc_types, job_name, schedule_cron, skip_no_schema, updated_at
            FROM {CATALOG}.platform.processing_configs
            WHERE domain_id = '{domain_id}'
            LIMIT 1
        """, timeout_secs=20)
        if rows:
            r = rows[0]
            return {"found": True, "domain_id": domain_id, **r}
        return {"found": False, "domain_id": domain_id}
    except Exception as e:
        return {"found": False, "domain_id": domain_id, "error": str(e)}


@router.post("/processing-config")
async def save_processing_config(req: ProcessingConfigRequest):
    """Upsert processing configuration for a domain."""
    _ensure_proc_cfg_table()
    try:
        dom  = req.domain_id.replace("'", "\\'")
        vp   = (req.volume_path or "").replace("'", "\\'")
        dt   = (req.doc_types or "[]").replace("'", "\\'")
        jn   = (req.job_name or "").replace("'", "\\'")
        sc   = (req.schedule_cron or "").replace("'", "\\'")
        skip = "true" if req.skip_no_schema else "false"

        run_sql(f"""
            MERGE INTO {CATALOG}.platform.processing_configs AS tgt
            USING (SELECT
                '{dom}'  AS domain_id,
                '{vp}'   AS volume_path,
                '{dt}'   AS doc_types,
                '{jn}'   AS job_name,
                '{sc}'   AS schedule_cron,
                {skip}   AS skip_no_schema,
                current_timestamp() AS updated_at
            ) AS src ON tgt.domain_id = src.domain_id
            WHEN MATCHED THEN UPDATE SET
                tgt.volume_path   = src.volume_path,
                tgt.doc_types     = src.doc_types,
                tgt.job_name      = src.job_name,
                tgt.schedule_cron = src.schedule_cron,
                tgt.skip_no_schema = src.skip_no_schema,
                tgt.updated_at    = src.updated_at
            WHEN NOT MATCHED THEN INSERT *
        """, timeout_secs=30)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/processing-log")
async def get_processing_log(domain_id: str = "supply_chain", limit: int = 200):
    """
    Return processing log stats + recent records for a domain.
    Includes:
     - summary counts (total, success, failed, skipped, pending)
     - per-doc-type breakdown
     - last N processed records
    """
    _ensure_proc_log_table()
    try:
        # Summary stats
        stats_rows = run_sql(f"""
            SELECT
                COUNT(*)                                              AS total_files,
                SUM(CASE WHEN status='success'    THEN 1 ELSE 0 END) AS success_count,
                SUM(CASE WHEN status='failed'     THEN 1 ELSE 0 END) AS failed_count,
                SUM(CASE WHEN status='skipped'    THEN 1 ELSE 0 END) AS skipped_count,
                SUM(CASE WHEN status='processing' THEN 1 ELSE 0 END) AS in_progress_count,
                MAX(processed_at)                                     AS last_processed_at
            FROM {CATALOG}.platform.file_processing_log
            WHERE domain_id = '{domain_id}'
        """, timeout_secs=20) or []
        stats = stats_rows[0] if stats_rows else {}

        # By doc type
        by_type = run_sql(f"""
            SELECT doc_type,
                   COUNT(*) AS count,
                   SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success,
                   SUM(CASE WHEN status='failed'  THEN 1 ELSE 0 END) AS failed
            FROM {CATALOG}.platform.file_processing_log
            WHERE domain_id = '{domain_id}'
            GROUP BY doc_type
            ORDER BY count DESC
        """, timeout_secs=20) or []

        # Recent records
        recent = run_sql(f"""
            SELECT file_name, doc_type, status, processed_at, records_written, error_message, job_run_id
            FROM {CATALOG}.platform.file_processing_log
            WHERE domain_id = '{domain_id}'
            ORDER BY processed_at DESC
            LIMIT {min(limit, 500)}
        """, timeout_secs=20) or []

        return {
            "stats": stats,
            "by_doc_type": by_type,
            "recent": recent,
            "domain_id": domain_id,
        }
    except Exception as e:
        return {"stats": {}, "by_doc_type": [], "recent": [], "error": str(e)}


@router.get("/unmatched-docs")
async def get_unmatched_docs(domain_id: str = "supply_chain", limit: int = 200):
    """
    Returns documents that were parsed but had no extraction schema configured.
    These appear in parsed_documents with a doc_type that is either null or not in
    the configured doc_type_schemas for this domain.

    This helps users know which files need schema setup before they can be fully extracted.
    """
    _d = _get_domain_schemas(domain_id)
    raw = _d["schema_raw"]

    try:
        # 1. Get all configured doc types from the global schema library
        configured_types_rows = run_sql(f"""
            SELECT doc_type FROM {CATALOG}.platform.doc_type_schemas
        """, timeout_secs=20) or []
        configured_types = {r["doc_type"] for r in configured_types_rows if r.get("doc_type")}

        # 2. Also get doc types from this domain's config
        try:
            domain_cfg_rows = run_sql(f"""
                SELECT classification_labels FROM {CATALOG}.platform.domain_configs
                WHERE domain_id = '{domain_id}' LIMIT 1
            """, timeout_secs=20) or []
            if domain_cfg_rows and domain_cfg_rows[0].get("classification_labels"):
                import json as _json
                labels = _json.loads(domain_cfg_rows[0]["classification_labels"])
                if isinstance(labels, list):
                    configured_types.update(labels)
                elif isinstance(labels, dict):
                    configured_types.update(labels.keys())
        except Exception:
            pass

        # 3. Query parsed_documents for files not matching any configured type
        unmatched_rows = []
        try:
            where_clauses = []
            if configured_types:
                types_sql = ", ".join(f"'{t}'" for t in configured_types)
                where_clause = f"(doc_type IS NULL OR doc_type = '' OR doc_type NOT IN ({types_sql}))"
            else:
                where_clause = "(doc_type IS NULL OR doc_type = '')"

            unmatched_rows = run_sql(f"""
                SELECT
                    doc_id,
                    filename,
                    doc_type,
                    processed_ts,
                    CASE
                        WHEN doc_type IS NULL OR doc_type = '' THEN 'Not classified'
                        ELSE CONCAT('Type "', doc_type, '" — no schema configured')
                    END AS reason
                FROM {CATALOG}.{raw}.parsed_documents
                WHERE {where_clause}
                ORDER BY processed_ts DESC
                LIMIT {min(limit, 500)}
            """, timeout_secs=30) or []
        except Exception as qe:
            return {"unmatched": [], "total": 0, "configured_types": sorted(configured_types), "error": str(qe)}

        return {
            "unmatched": unmatched_rows,
            "total": len(unmatched_rows),
            "configured_types": sorted(configured_types),
            "domain_id": domain_id,
        }

    except Exception as e:
        return {"unmatched": [], "total": 0, "configured_types": [], "error": str(e)}


@router.get("/pipeline-status")
async def pipeline_status(domain_id: str = "supply_chain"):
    """
    Returns rich status for the most recent pipeline run:
    - Overall status + timing
    - Per-task breakdown with status and duration
    - Table stats (docs, entities, chunks, fields)
    - Last 5 runs summary
    """
    _d = _get_domain_schemas(domain_id)
    _raw = _d["schema_raw"]; _ont = _d["schema_ont"]; _vec = _d["schema_vec"]

    try:
        w = WorkspaceClient()

        # Find latest run across both jobs
        latest_run = None
        latest_job_id = None
        latest_start = 0
        recent_runs_list = []

        # Resolve ONLY the domain-specific job for status — do not mix in shared jobs,
        # which would pollute the status with runs from other domains.
        candidate_job_ids: list[tuple[int, str]] = []
        job_schedule_text: str | None = None
        job_schedule_cron: str | None = None
        job_schedule_tz:   str = "UTC"
        try:
            _da = _get_domain_schemas(domain_id)
            j_id, j_name = _resolve_pipeline_job(domain_id, _da)
            candidate_job_ids.append((j_id, j_name))
            # Fetch the actual job schedule so the UI can show accurate info
            try:
                job_detail = w.jobs.get(job_id=j_id)
                sched = job_detail.settings and job_detail.settings.schedule
                if sched and sched.quartz_cron_expression:
                    tz = getattr(sched, "timezone_id", None) or "UTC"
                    job_schedule_text = f"Scheduled · cron: {sched.quartz_cron_expression} ({tz})"
                    job_schedule_cron = sched.quartz_cron_expression
                    job_schedule_tz   = tz
            except Exception:
                pass
        except Exception:
            pass

        for (job_id, job_name) in candidate_job_ids:
            try:
                runs = list(w.jobs.list_runs(job_id=job_id, limit=5))
                for r in runs:
                    recent_runs_list.append((r, job_id, job_name))
                if runs and (runs[0].start_time or 0) > latest_start:
                    latest_run = runs[0]
                    latest_job_id = job_id
                    latest_start = runs[0].start_time or 0
            except Exception:
                pass

        if not latest_run:
            # Still return table stats even if no runs found
            stats = _pipeline_table_stats(CATALOG, _raw, _ont, _vec)
            return {"status": "never_run", "message": "No pipeline runs found", "stats": stats}

        # Get full run detail (tasks) for the latest run
        run_detail = w.jobs.get_run(run_id=latest_run.run_id)
        tasks_out = []
        for t in (run_detail.tasks or []):
            ts = t.state
            task_simple = _run_state_simple(ts)
            dur_ms = None
            if t.start_time and t.end_time:
                dur_ms = t.end_time - t.start_time
            elif t.start_time and task_simple == "running":
                import time as _time
                dur_ms = int(_time.time() * 1000) - t.start_time

            error_msg = None
            if ts and ts.state_message:
                error_msg = ts.state_message[:300]

            tasks_out.append({
                "task_key":   t.task_key,
                "label":      TASK_LABELS.get(t.task_key, t.task_key),
                "status":     task_simple,
                "start_time_ms": t.start_time,
                "end_time_ms":   t.end_time,
                "duration_ms":   dur_ms,
                "run_url":    t.run_page_url,
                "error":      error_msg,
            })

        # Sort by start time
        tasks_out.sort(key=lambda x: x.get("start_time_ms") or 0)

        # Overall status
        overall_state = run_detail.state or latest_run.state
        overall_simple = _run_state_simple(overall_state)

        # Duration
        total_dur_ms = None
        if latest_run.start_time and latest_run.end_time:
            total_dur_ms = latest_run.end_time - latest_run.start_time

        # Recent runs summary (last 5 across both jobs)
        recent_runs_list.sort(key=lambda x: x[0].start_time or 0, reverse=True)
        recent_runs_out = []
        for (r, jid, jname) in recent_runs_list[:5]:
            rs2 = _run_state_simple(r.state)
            dur2 = None
            if r.start_time and r.end_time:
                dur2 = r.end_time - r.start_time
            recent_runs_out.append({
                "run_id":         r.run_id,
                "job_name":       jname,
                "status":         rs2,
                "start_time_ms":  r.start_time,
                "end_time_ms":    r.end_time,
                "duration_ms":    dur2,
                "run_url":        r.run_page_url,
            })

        # Table stats
        stats = _pipeline_table_stats(CATALOG, _raw, _ont, _vec)

        # Unprocessed doc count (quick, best-effort)
        # Compare by BASE name (no extension) so doc.txt is not counted as new
        # when doc.pdf has already been processed, and vice-versa.
        new_docs_count = 0
        try:
            import os as _os
            _vol = _d.get("volume_docs", "documents")
            volume_path = f"/Volumes/{CATALOG}/{_raw}/{_vol}"
            all_vol_files = [fi.name for fi in w.files.list_directory_contents(volume_path)
                             if fi.name and (fi.name.endswith(".pdf") or fi.name.endswith(".txt"))]
            processed_bases = {
                _os.path.splitext(r["doc_id"])[0]
                for r in (run_sql(f"SELECT doc_id FROM {CATALOG}.{_raw}.parsed_documents") or [])
            }
            new_docs_count = len([
                f for f in all_vol_files
                if _os.path.splitext(f)[0] not in processed_bases
            ])
        except Exception:
            pass

        return {
            "status":            overall_simple,
            "run_id":            latest_run.run_id,
            "run_url":           latest_run.run_page_url,
            "start_time_ms":     latest_run.start_time,
            "end_time_ms":       latest_run.end_time,
            "duration_ms":       total_dur_ms,
            "tasks":             tasks_out,
            "stats":             stats,
            "recent_runs":       recent_runs_out,
            "new_docs_count":    new_docs_count,
            "job_schedule":      job_schedule_text,
            "job_schedule_cron": job_schedule_cron,
            "job_schedule_tz":   job_schedule_tz,
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "stats": {}}


def _pipeline_table_stats(catalog: str, raw: str, ont: str, vec: str) -> dict:
    """Query live row counts from key pipeline tables."""
    stats = {}
    queries = {
        "docs_parsed":       f"SELECT COUNT(*) AS n FROM {catalog}.{raw}.parsed_documents",
        "fields_extracted":  f"SELECT COUNT(*) AS n FROM {catalog}.{raw}.extracted_fields",
        "entities_created":  f"SELECT COUNT(*) AS n FROM {catalog}.{ont}.entities",
        "relationships":     f"SELECT COUNT(*) AS n FROM {catalog}.{ont}.relationships",
        "chunks_indexed":    f"SELECT COUNT(*) AS n FROM {catalog}.{vec}.document_chunks",
    }
    for key, sql in queries.items():
        try:
            rows = run_sql(sql, timeout_secs=15)
            stats[key] = int(rows[0]["n"]) if rows else 0
        except Exception:
            stats[key] = None   # table may not exist yet
    return stats


@router.get("/document-library")
async def document_library(domain_id: str = "supply_chain", filter: str = "", limit: int = 1000, offset: int = 0):
    """
    Returns all processed documents from jai_docintel.raw.parsed_documents
    with metadata and a short text preview.
    Each doc carries its project tags (project_tags[] + universal).
    Optional `filter`: 'project:<id>' | 'universal' | 'unassigned'.
    """
    _d = _get_domain_schemas(domain_id)
    _raw = _d["schema_raw"]; _ont = _d["schema_ont"]
    try:
        docs = run_sql(f"""
            SELECT
                doc_id,
                filename,
                COALESCE(doc_type, 'unknown') AS doc_type,
                CAST(processed_ts AS STRING) AS processed_ts,
                LENGTH(raw_text)              AS char_count,
                ROUND(LENGTH(raw_text) / 5.0) AS est_word_count,
                LEFT(raw_text, 500)           AS text_preview
            FROM {CATALOG}.{_raw}.parsed_documents
            ORDER BY processed_ts DESC
            LIMIT 2000
        """)

        if docs:
            doc_ids_sql = ", ".join(f"'{d['doc_id']}'" for d in docs)
            fields_raw = run_sql(f"""
                SELECT doc_id, field_name, field_value
                FROM {CATALOG}.{_raw}.extracted_fields
                WHERE doc_id IN ({doc_ids_sql})
                  AND field_value IS NOT NULL
                ORDER BY doc_id, field_name
            """)
            fields_map: dict = {}
            for row in fields_raw:
                fid = row["doc_id"]
                if fid not in fields_map:
                    fields_map[fid] = {}
                fields_map[fid][row["field_name"]] = row["field_value"]

            entity_counts_raw = run_sql(f"""
                SELECT source AS doc_id, COUNT(*) AS entity_count
                FROM {CATALOG}.{_ont}.entities
                WHERE source IN ({doc_ids_sql})
                GROUP BY source
            """)
            entity_count_map = {r["doc_id"]: r["entity_count"] for r in (entity_counts_raw or [])}

            for d in docs:
                d["extracted_fields"] = fields_map.get(d["doc_id"], {})
                d["entity_count"]     = entity_count_map.get(d["doc_id"], 0)
                d["doc_type_label"]   = DOC_TYPE_LABELS.get(d["doc_type"], d["doc_type"].replace("_", " ").title())

        # Attach project tags (bootstrapped from derived) + apply optional filter.
        docs = docs or []
        _f = (filter or "").strip().lower()
        _pid_filter = filter.split(":", 1)[1].strip() if _f.startswith("project:") else None
        # Reject unsupported filters rather than silently returning everything.
        if _f and _f not in ("universal", "unassigned") and not (_f.startswith("project:") and _pid_filter):
            raise HTTPException(status_code=400, detail=f"Unsupported filter '{filter}'. Use universal | unassigned | project:<id>.")
        try:
            _bootstrap_project_tags(domain_id)
            _tbd = _tags_by_doc(domain_id, strict=bool(_f))   # strict => surface errors when filtering
            for d in docs:
                t = _tbd.get(d["doc_id"], {"projects": [], "universal": False})
                d["project_tags"] = t["projects"]
                d["universal"]    = t["universal"]
        except HTTPException:
            raise
        except Exception:
            # Best-effort for the UNFILTERED library, but an explicit filter must
            # never be silently ignored (would return wrong results).
            if _f:
                raise HTTPException(status_code=500, detail="Failed to load project tags for filtering.")
            for d in docs:
                d.setdefault("project_tags", []); d.setdefault("universal", False)

        if _f == "universal":
            docs = [d for d in docs if d.get("universal")]
        elif _f == "unassigned":
            docs = [d for d in docs if not d.get("universal") and not d.get("project_tags")]
        elif _f.startswith("project:"):
            _pid = filter.split(":", 1)[1].strip()
            docs = [d for d in docs if d.get("universal") or _pid in (d.get("project_tags") or [])]

        # Paginate the FILTERED set (total reflects the filter). Fetch-then-slice is
        # correct for the current corpus; true SQL-side pagination is future work once
        # the corpus is very large.
        _lim = max(1, min(int(limit or 1000), 200))
        _off = max(0, int(offset or 0))
        total = len(docs)
        page = docs[_off:_off + _lim]
        return {"documents": page, "total": total, "offset": _off, "limit": _lim}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Document ↔ Project tagging  (platform.document_project_tags, M:N + Universal)
# ═══════════════════════════════════════════════════════════════════════════════
_dpt_checked = False

def _ensure_document_project_tags_table():
    global _dpt_checked
    if _dpt_checked:
        return
    try:
        run_sql(f"""
            CREATE TABLE IF NOT EXISTS {CATALOG}.platform.document_project_tags (
                domain_id  STRING,
                doc_id     STRING,
                project_id STRING,
                scope      STRING,   -- 'project' | 'universal'
                source     STRING,   -- 'derived' | 'manual'
                tagged_by  STRING,
                tagged_at  TIMESTAMP
            ) USING DELTA
        """, timeout_secs=30)
        _dpt_checked = True
    except Exception:
        pass

def _bootstrap_project_tags(domain_id: str):
    """Seed derived (doc, project) tags from extracted store_number/project_id — ONCE per
    domain. After the first seed, manual add/delete edits are authoritative and we never
    re-derive, so a user-deleted tag stays deleted (bootstrap is a no-op on later reads)."""
    _ensure_document_project_tags_table()
    _did = (domain_id or "").replace("'", "''")
    try:
        seeded = run_sql(
            f"SELECT 1 FROM {CATALOG}.platform.document_project_tags WHERE domain_id='{_did}' AND scope='marker' LIMIT 1",
            timeout_secs=15) or []
        if seeded:
            return   # seed-complete marker present — never re-derive (deletes persist)
    except Exception:
        return
    _raw = _get_domain_schemas(domain_id)["schema_raw"]
    try:
        run_sql(f"""
            INSERT INTO {CATALOG}.platform.document_project_tags
            SELECT '{_did}', m.doc_id, trim(m.project_id), 'project', 'derived', 'system', current_timestamp()
            FROM (
                SELECT doc_id,
                       COALESCE(
                         MAX(CASE WHEN field_name='store_number' THEN {_parse_val_sql("field_value")} END),
                         MAX(CASE WHEN field_name='project_id'   THEN {_parse_val_sql("field_value")} END)
                       ) AS project_id
                FROM {CATALOG}.{_raw}.extracted_fields
                GROUP BY doc_id
            ) m
            WHERE m.project_id IS NOT NULL AND trim(m.project_id) <> ''
              AND NOT EXISTS (
                SELECT 1 FROM {CATALOG}.platform.document_project_tags t
                WHERE t.domain_id='{_did}' AND t.doc_id=m.doc_id
                  AND t.scope='project' AND t.project_id=trim(m.project_id)
              )
        """, timeout_secs=40)
        # persist a seed-complete marker so we never re-derive for this domain
        run_sql(f"INSERT INTO {CATALOG}.platform.document_project_tags VALUES "
                f"('{_did}','__seeded__',NULL,'marker','system','system',current_timestamp())", timeout_secs=15)
    except Exception:
        pass

def _tags_by_doc(domain_id: str, strict: bool = False) -> dict:
    _ensure_document_project_tags_table()
    _did = (domain_id or "").replace("'", "''")
    out: dict = {}
    try:
        rows = run_sql(f"""
            SELECT doc_id, project_id, scope FROM {CATALOG}.platform.document_project_tags
            WHERE domain_id = '{_did}'
        """, timeout_secs=30) or []
        for r in rows:
            did = r.get("doc_id")
            if not did or r.get("scope") == "marker":
                continue
            e = out.setdefault(did, {"projects": [], "universal": False})
            if r.get("scope") == "universal":
                e["universal"] = True
            elif r.get("project_id") and r["project_id"] not in e["projects"]:
                e["projects"].append(r["project_id"])
    except Exception:
        if strict:      # explicit filter must not be silently mis-answered
            raise
    return out

def _project_doc_ids(domain_id: str, project_id: str) -> set:
    """Doc ids tagged to a project (project tags ∪ universal). Used by Phase 2 grounding."""
    _bootstrap_project_tags(domain_id)   # ensure derived tags exist (no-op after first seed)
    _did = (domain_id or "").replace("'", "''")
    _pid = (project_id or "").replace("'", "''")
    try:
        rows = run_sql(f"""
            SELECT DISTINCT doc_id FROM {CATALOG}.platform.document_project_tags
            WHERE domain_id='{_did}' AND (scope='universal' OR project_id='{_pid}')
        """, timeout_secs=30) or []
        return {r["doc_id"] for r in rows if r.get("doc_id")}
    except Exception:
        return set()


class DocTagRequest(BaseModel):
    domain_id: str = "compliance_due_diligence"
    doc_id: str
    project_id: Optional[str] = None
    universal: bool = False

class DocTagBulkRequest(BaseModel):
    domain_id: str = "compliance_due_diligence"
    doc_ids: List[str]
    project_id: Optional[str] = None
    universal: bool = False
    op: str = "add"

def _tag_where(req, doc_lit: str) -> str:
    if req.universal:
        return f"scope='universal'"
    _pid = (req.project_id or "").strip().replace("'", "''")
    return f"scope='project' AND project_id='{_pid}'"

@router.get("/document-tags")
async def get_document_tags(domain_id: str = "compliance_due_diligence"):
    _bootstrap_project_tags(domain_id)
    tbd = _tags_by_doc(domain_id)
    projects = sorted({p for v in tbd.values() for p in v["projects"]})
    return {"tags_by_doc": tbd, "projects": projects}

@router.post("/document-tags")
async def add_document_tag(req: DocTagRequest):
    if not req.universal and not (req.project_id or "").strip():
        raise HTTPException(status_code=400, detail="project_id or universal required")
    _ensure_document_project_tags_table()
    _did = req.domain_id.replace("'", "''"); _doc = req.doc_id.replace("'", "''")
    scope = "universal" if req.universal else "project"
    _pid = "NULL" if req.universal else "'" + (req.project_id or "").strip().replace("'", "''") + "'"
    try:
        run_sql(f"DELETE FROM {CATALOG}.platform.document_project_tags WHERE domain_id='{_did}' AND doc_id='{_doc}' AND {_tag_where(req, _doc)}", timeout_secs=30)
        run_sql(f"INSERT INTO {CATALOG}.platform.document_project_tags VALUES ('{_did}','{_doc}',{_pid},'{scope}','manual','user',current_timestamp())", timeout_secs=30)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/document-tags")
async def delete_document_tag(req: DocTagRequest):
    if not req.universal and not (req.project_id or "").strip():
        raise HTTPException(status_code=400, detail="project_id or universal required")
    _ensure_document_project_tags_table()
    _did = req.domain_id.replace("'", "''"); _doc = req.doc_id.replace("'", "''")
    try:
        run_sql(f"DELETE FROM {CATALOG}.platform.document_project_tags WHERE domain_id='{_did}' AND doc_id='{_doc}' AND {_tag_where(req, _doc)}", timeout_secs=30)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/document-tags/bulk")
async def bulk_document_tags(req: DocTagBulkRequest):
    if req.op not in ("add", "delete", "remove"):
        raise HTTPException(status_code=400, detail="op must be 'add' or 'delete'")
    if not req.universal and not (req.project_id or "").strip():
        raise HTTPException(status_code=400, detail="project_id or universal required")
    _is_add = req.op == "add"
    _ensure_document_project_tags_table()
    _did = req.domain_id.replace("'", "''")
    scope = "universal" if req.universal else "project"
    _pid = "NULL" if req.universal else "'" + (req.project_id or "").strip().replace("'", "''") + "'"
    n = 0
    for doc in req.doc_ids:
        _doc = (doc or "").replace("'", "''")
        if not _doc:
            continue
        try:
            run_sql(f"DELETE FROM {CATALOG}.platform.document_project_tags WHERE domain_id='{_did}' AND doc_id='{_doc}' AND {_tag_where(req, _doc)}", timeout_secs=30)
            if _is_add:
                run_sql(f"INSERT INTO {CATALOG}.platform.document_project_tags VALUES ('{_did}','{_doc}',{_pid},'{scope}','manual','user',current_timestamp())", timeout_secs=30)
            n += 1
        except Exception:
            pass
    return {"ok": True, "count": n}


@router.get("/docs-by-type")
async def docs_by_type(domain_id: str = "supply_chain", doc_types: str = ""):
    """
    Returns parsed documents grouped by doc_type for the given domain.
    If doc_types is provided (comma-separated), only those types are returned.
    Returns: { "by_type": { "<doc_type>": [ {doc_id, filename, doc_type, processed_ts}, ... ] } }
    """
    _d = _get_domain_schemas(domain_id)
    _raw = _d["schema_raw"]
    type_filter = ""
    if doc_types.strip():
        types = [t.strip() for t in doc_types.split(",") if t.strip()]
        if types:
            quoted = ", ".join(f"'{t}'" for t in types)
            type_filter = f"WHERE COALESCE(doc_type,'unknown') IN ({quoted})"
    try:
        rows = run_sql(f"""
            SELECT
                doc_id,
                COALESCE(filename, doc_id) AS filename,
                COALESCE(doc_type, 'unknown') AS doc_type,
                CAST(processed_ts AS STRING) AS processed_ts
            FROM {CATALOG}.{_raw}.parsed_documents
            {type_filter}
            ORDER BY processed_ts DESC NULLS LAST
            LIMIT 500
        """) or []
        by_type: dict = {}
        for r in rows:
            dt = r.get("doc_type", "unknown")
            if dt not in by_type:
                by_type[dt] = []
            by_type[dt].append({
                "doc_id":       r.get("doc_id", ""),
                "filename":     r.get("filename", r.get("doc_id", "")),
                "doc_type":     dt,
                "processed_ts": r.get("processed_ts", ""),
            })
        return {"by_type": by_type}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gmail-search")
async def gmail_search(q: str = "", max_results: int = 5):
    """
    Search Gmail via the Databricks-managed Gmail MCP server.
    Returns matching thread summaries (subject, sender, snippet, date, thread_id).
    The MCP server is read-only — it supports search/read but not send.
    """
    import re as _re
    import requests as _req
    if not q.strip():
        return {"threads": [], "total": 0}
    try:
        _host = os.getenv("DATABRICKS_HOST", "").rstrip("/")
        if not _host:
            return {"threads": [], "total": 0, "error": "DATABRICKS_HOST not set"}

        # Extract workspace/org ID from hostname  (adb-XXXXXXXXXX.0.azuredatabricks.net)
        _m = _re.search(r"adb-(\d+)\.", _host)
        _org = _m.group(1) if _m else ""
        _mcp_url = f"{_host}/ai-gateway/mcp-services/system.ai.gmail" + (f"?o={_org}" if _org else "")

        # Auth via SDK  (OAuth M2M in app context; PAT in local dev)
        _w  = WorkspaceClient()
        _hdr = {
            **_w.config.authenticate(),
            "Content-Type": "application/json",
            "Accept":       "application/json, text/event-stream",
        }

        # ── 1. initialize session ────────────────────────────────────────────
        _req.post(_mcp_url, json={
            "jsonrpc": "2.0", "method": "initialize", "id": 0,
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "docintel", "version": "1.0"}},
        }, headers=_hdr, timeout=10)

        # ── 2. search threads ────────────────────────────────────────────────
        _resp = _req.post(_mcp_url, json={
            "jsonrpc": "2.0", "method": "tools/call", "id": 1,
            "params": {
                "name": "gmail_search_threads",
                "arguments": {"query": q, "max_results": max_results},
            },
        }, headers=_hdr, timeout=15)

        if not _resp.ok:
            return {"threads": [], "total": 0, "error": f"MCP {_resp.status_code}"}

        _data    = _resp.json()
        _content = _data.get("result", {}).get("content", [])
        _text    = next((c.get("text","") for c in _content if c.get("type")=="text"), "")

        # ── 3. parse the returned text/JSON ──────────────────────────────────
        threads = []
        try:
            import json as _json
            _parsed = _json.loads(_text)
            _items  = _parsed if isinstance(_parsed, list) else _parsed.get("threads", [])
            for t in _items:
                threads.append({
                    "thread_id": t.get("id") or t.get("thread_id", ""),
                    "subject":   t.get("subject", "(no subject)"),
                    "from":      t.get("from", ""),
                    "snippet":   t.get("snippet", "")[:200],
                    "date":      t.get("date", ""),
                    "unread":    t.get("unread", False),
                })
        except Exception:
            # MCP returned plain text — wrap it as a single result
            if _text.strip():
                threads.append({"thread_id": "", "subject": "Search results", "snippet": _text[:300], "from": "", "date": ""})

        return {"threads": threads, "total": len(threads), "query": q}

    except Exception as _e:
        return {"threads": [], "total": 0, "error": str(_e)}


@router.get("/document-detail")
async def document_detail(doc_id: str, domain_id: str = "supply_chain"):
    """
    Returns full detail for one document: metadata, full text, extracted fields,
    related ontology entities, and relationships involving those entities.
    """
    safe_id = doc_id.replace("'", "''")

    _d2 = _get_domain_schemas(domain_id)
    _raw2 = _d2["schema_raw"]; _ont2 = _d2["schema_ont"]
    docs = run_sql(f"""
        SELECT
            doc_id, filename, doc_type,
            CAST(processed_ts AS STRING) AS processed_ts,
            LENGTH(raw_text)             AS char_count,
            ROUND(LENGTH(raw_text)/5.0)  AS est_word_count,
            raw_text
        FROM {CATALOG}.{_raw2}.parsed_documents
        WHERE doc_id = '{safe_id}'
        LIMIT 1
    """)
    if not docs:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")

    doc = docs[0]
    doc["doc_type_label"] = DOC_TYPE_LABELS.get(doc["doc_type"], doc["doc_type"].replace("_", " ").title())

    fields_raw = run_sql(f"""
        SELECT field_name, field_value
        FROM {CATALOG}.{_raw2}.extracted_fields
        WHERE doc_id = '{safe_id}'
          AND field_value IS NOT NULL
        ORDER BY field_name
    """)
    doc["extracted_fields"] = {r["field_name"]: r["field_value"] for r in (fields_raw or [])}

    entities = run_sql(f"""
        SELECT entity_id, entity_type,
               COALESCE(display_name, entity_id) AS display_name,
               attributes
        FROM {CATALOG}.{_ont2}.entities
        WHERE source LIKE '%{safe_id}%'
        LIMIT 30
    """)
    doc["related_entities"] = entities or []

    return doc


# ── Action Log ─────────────────────────────────────────────────────────────────

def _ensure_action_log_table(table_name: str):
    """Create the action log table if it doesn't exist."""
    try:
        run_sql(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                action_id     STRING NOT NULL,
                logged_at     TIMESTAMP NOT NULL,
                action_type   STRING NOT NULL,
                description   STRING,
                priority      STRING,
                incident_ref  STRING,
                logged_by     STRING,
                status        STRING
            )
            USING DELTA
            TBLPROPERTIES ('delta.enableChangeDataFeed' = 'false')
        """, timeout_secs=30)
    except Exception:
        pass


@router.post("/log-action")
async def log_action(req: LogActionRequest, domain_id: str = "supply_chain"):
    """Appends a new action to the action log Delta table."""
    _agt_schema = _get_domain_schemas(domain_id)["schema_agt"]
    action_log_table = f"{CATALOG}.{_agt_schema}.action_log"
    _ensure_action_log_table(action_log_table)
    import uuid
    from datetime import datetime, timezone

    action_id = str(uuid.uuid4())[:8].upper()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    desc = req.description.replace("'", "''")
    logged_by = req.logged_by.replace("'", "''")
    incident = req.incident_ref.replace("'", "''")

    run_sql(f"""
        INSERT INTO {action_log_table}
        (action_id, logged_at, action_type, description, priority, incident_ref, logged_by, status)
        VALUES ('{action_id}', TIMESTAMP '{ts}', '{req.action_type}', '{desc}',
                '{req.priority}', '{incident}', '{logged_by}', 'OPEN')
    """, timeout_secs=30)

    return {"action_id": action_id, "logged_at": ts, "status": "OPEN"}


@router.get("/action-log")
async def get_action_log(incident_ref: str = None, limit: int = 50, domain_id: str = "supply_chain"):
    """Returns the action log. Filters by incident_ref when provided; otherwise returns all domain actions."""
    _agt_schema = _get_domain_schemas(domain_id)["schema_agt"]
    _tbl = f"{CATALOG}.{_agt_schema}.action_log"
    _ensure_action_log_table(_tbl)
    where_clause = f"WHERE incident_ref = '{incident_ref}'" if incident_ref else ""
    rows = run_sql(f"""
        SELECT action_id, logged_at, action_type, description,
               priority, incident_ref, logged_by, status
        FROM {_tbl}
        {where_clause}
        ORDER BY logged_at DESC
        LIMIT {limit}
    """, timeout_secs=30)
    return {"incident_ref": incident_ref, "actions": rows or [], "total": len(rows or [])}


@router.get("/action-report")
async def action_report(incident_ref: str = "RCL-2024-0012", domain_id: str = "supply_chain"):
    """
    Generates a markdown-formatted incident action report.
    Returns the report text plus a summary of actions by type and priority.
    """
    _agt_schema = _get_domain_schemas(domain_id)["schema_agt"]
    _tbl = f"{CATALOG}.{_agt_schema}.action_log"
    _ensure_action_log_table(_tbl)
    try:
        rows = run_sql(f"""
            SELECT action_id, logged_at, action_type, description,
                   priority, logged_by, status
            FROM {_tbl}
            WHERE incident_ref = '{incident_ref}'
            ORDER BY logged_at ASC
        """, timeout_secs=30) or []
    except Exception:
        rows = []   # table not yet materialized for this domain — treat as no actions

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# Incident Action Report",
        f"**Incident:** {incident_ref}",
        f"**Generated:** {now}",
        f"**Total Actions:** {len(rows)}",
        "",
        "---",
        "",
    ]

    if not rows:
        lines.append("_No actions have been logged for this incident yet._")
    else:
        # Group by priority
        by_prio = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}
        for r in rows:
            p = (r.get("priority") or "MEDIUM").upper()
            by_prio.setdefault(p, []).append(r)

        for prio in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            actions = by_prio.get(prio, [])
            if not actions:
                continue
            lines.append(f"## {prio} Priority ({len(actions)} actions)")
            for a in actions:
                ts = str(a.get("logged_at", ""))[:16]
                lines.append(f"- **[{ts}]** `{a['action_type']}` — {a['description']}")
                lines.append(f"  _(logged by {a.get('logged_by','?')} · status: {a.get('status','OPEN')})_")
            lines.append("")

    # Summary stats
    types = {}
    for r in rows:
        t = r.get("action_type", "OTHER")
        types[t] = types.get(t, 0) + 1

    return {
        "incident_ref": incident_ref,
        "generated_at": now,
        "total_actions": len(rows),
        "report_markdown": "\n".join(lines),
        "summary_by_type": types,
    }


# ── Incident Registry ─────────────────────────────────────────────────────────

SCHEMA_PLATFORM = "platform"

@router.get("/incidents")
async def list_incidents(domain_id: str = "supply_chain"):
    """Return all incidents for a domain, newest first."""
    rows = run_sql(f"""
        SELECT incident_id, domain_id, incident_type, title, description,
               status, severity, primary_entity, primary_entity_label,
               CAST(opened_date AS STRING)  AS opened_date,
               CAST(closed_date AS STRING)  AS closed_date,
               assigned_to, financial_exposure_usd,
               affected_count, affected_label,
               CAST(created_at AS STRING)   AS created_at
        FROM {CATALOG}.{SCHEMA_PLATFORM}.incidents
        WHERE domain_id = '{domain_id}'
        ORDER BY opened_date DESC
    """, timeout_secs=30)
    return {"domain_id": domain_id, "incidents": rows, "total": len(rows)}


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str, domain_id: str = "supply_chain"):
    """Return a single incident with its linked documents."""
    rows = run_sql(f"""
        SELECT incident_id, domain_id, incident_type, title, description,
               status, severity, primary_entity, primary_entity_label,
               CAST(opened_date AS STRING)  AS opened_date,
               CAST(closed_date AS STRING)  AS closed_date,
               assigned_to, financial_exposure_usd,
               affected_count, affected_label,
               CAST(created_at AS STRING)   AS created_at
        FROM {CATALOG}.{SCHEMA_PLATFORM}.incidents
        WHERE incident_id = '{incident_id}' AND domain_id = '{domain_id}'
        LIMIT 1
    """, timeout_secs=30)
    if not rows:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    _d = _get_domain_schemas(domain_id)
    _raw = _d["schema_raw"]
    docs = run_sql(f"""
        SELECT
            id.document_path,
            id.document_name,
            CAST(id.linked_at AS STRING) AS linked_at,
            id.linked_by,
            COALESCE(pd.doc_type, 'unknown')       AS doc_type,
            COALESCE(pd.doc_type, 'unknown')       AS doc_type_label,
            LEFT(pd.raw_text, 300)                 AS text_preview,
            LENGTH(pd.raw_text)                    AS char_count,
            ROUND(LENGTH(pd.raw_text) / 5.0)       AS est_word_count
        FROM {CATALOG}.{SCHEMA_PLATFORM}.incident_documents id
        LEFT JOIN {CATALOG}.{_raw}.parsed_documents pd
            ON pd.filename = id.document_name
            OR pd.doc_id   = id.document_path
        WHERE id.incident_id = '{incident_id}'
        ORDER BY id.linked_at DESC
    """, timeout_secs=30)

    # Normalize field names for frontend
    for d in (docs or []):
        d["filename"] = d.get("document_name") or d.get("document_path", "").split("/")[-1]
        d["doc_id"]   = d.get("document_path", "")

    return {**rows[0], "linked_documents": docs or []}


class LinkDocRequest(BaseModel):
    document_path: str
    document_name: Optional[str] = None
    linked_by: str = "user"


@router.get("/doc-incidents")
async def get_doc_incidents(doc_id: str, domain_id: str = "supply_chain"):
    """
    Returns all incidents that a document is currently linked to,
    plus suggestions for other incidents it may be relevant to.
    """
    _d = _get_domain_schemas(domain_id)
    _raw = _d["schema_raw"]

    # Get doc metadata
    doc_rows = run_sql(f"""
        SELECT doc_id, filename, doc_type, LEFT(raw_text, 400) AS text_preview
        FROM {CATALOG}.{_raw}.parsed_documents
        WHERE doc_id = '{doc_id.replace("'","''")}' OR filename = '{doc_id.replace("'","''")}'
        LIMIT 1
    """, timeout_secs=30)
    if not doc_rows:
        raise HTTPException(status_code=404, detail="Document not found")
    doc = doc_rows[0]

    # Already linked incidents
    linked_rows = run_sql(f"""
        SELECT id.incident_id, i.incident_type, i.title, i.severity, i.status,
               CAST(id.linked_at AS STRING) AS linked_at
        FROM {CATALOG}.{SCHEMA_PLATFORM}.incident_documents id
        JOIN {CATALOG}.{SCHEMA_PLATFORM}.incidents i
            ON i.incident_id = id.incident_id
        WHERE (id.document_name = '{doc_id.replace("'","''")}' OR id.document_path = '{doc_id.replace("'","''")}')
          AND i.domain_id = '{domain_id}'
    """, timeout_secs=30) or []

    # Suggested incidents (by type affinity)
    doc_type = doc.get("doc_type", "unknown")
    all_incidents = run_sql(f"""
        SELECT incident_id, incident_type, title, severity, status
        FROM {CATALOG}.{SCHEMA_PLATFORM}.incidents
        WHERE domain_id = '{domain_id}'
    """, timeout_secs=30) or []

    linked_ids = {r["incident_id"] for r in linked_rows}
    suggestions = []
    for inc in all_incidents:
        if inc["incident_id"] in linked_ids:
            continue
        priority_types = _INCIDENT_DOC_AFFINITY.get(inc.get("incident_type", ""), [])
        if doc_type in priority_types:
            suggestions.append({
                **inc,
                "relevance_note": f"This doc type ({doc_type.replace('_',' ')}) is relevant to {inc['incident_type'].replace('_',' ')} incidents"
            })

    return {
        "doc_id":            doc.get("doc_id"),
        "filename":          doc.get("filename"),
        "doc_type":          doc_type,
        "linked_incidents":  linked_rows,
        "suggested_incidents": suggestions,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Copilot Studio  — prompt management, gap analysis, and structured queries
# ═══════════════════════════════════════════════════════════════════════════════

class CopilotPromptSaveRequest(BaseModel):
    domain_id: str
    prompt: str

class CopilotAnalyzeRequest(BaseModel):
    domain_id: str
    prompt: str

class CopilotQueryRequest(BaseModel):
    domain_id: str
    query: str
    prompt_override: Optional[str] = None


class GenieQueryRequest(BaseModel):
    domain_id: str
    query: str
    conversation_id: Optional[str] = None


@router.get("/genie-space")
async def get_genie_space(domain_id: str = "compliance_due_diligence"):
    """Whether a Genie 'Data Questions' space is configured for this domain (UI gate)."""
    sid = _GENIE_SPACE_IDS.get(domain_id)
    return {"domain_id": domain_id, "enabled": bool(sid), "space_id": sid}


@router.post("/genie-query")
async def genie_query(req: GenieQueryRequest):
    """
    Answer an aggregate / structured "Data Question" via the domain's Genie space
    (Genie Conversation API). Complements /copilot-query (LLM + Vector Search over
    document text) for questions Genie answers better with governed SQL.
    """
    space_id = _GENIE_SPACE_IDS.get(req.domain_id)
    if not space_id:
        raise HTTPException(
            status_code=404,
            detail=f"No Genie space configured for domain '{req.domain_id}'.",
        )
    try:
        w = WorkspaceClient()
        if req.conversation_id:
            msg = w.genie.create_message_and_wait(space_id, req.conversation_id, req.query)
        else:
            msg = w.genie.start_conversation_and_wait(space_id, req.query)

        answer_text = None
        sql = None
        columns = None
        data = None
        for a in (msg.attachments or []):
            if getattr(a, "text", None) and a.text and a.text.content:
                answer_text = a.text.content
            if getattr(a, "query", None) and a.query:
                sql = a.query.query
                # Best-effort: pull the result rows so the UI can render a table.
                try:
                    res = w.genie.get_message_query_result(space_id, msg.conversation_id, msg.id)
                    sr = getattr(res, "statement_response", None)
                    if sr and sr.result and sr.result.data_array is not None:
                        data = sr.result.data_array
                        if sr.manifest and sr.manifest.schema and sr.manifest.schema.columns:
                            columns = [c.name for c in sr.manifest.schema.columns]
                except Exception:
                    pass

        return {
            "domain_id":       req.domain_id,
            "conversation_id": msg.conversation_id,
            "message_id":      msg.id,
            "answer":          answer_text,
            "sql":             sql,
            "columns":         columns,
            "data":            data,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/copilot-prompt")
async def get_copilot_prompt(domain_id: str = "compliance"):
    """Return the saved guiding prompt for a domain (or null if not yet set)."""
    try:
        rows = run_sql(f"""
            SELECT agent_system_prompt, updated_at
            FROM {CATALOG}.platform.domain_configs
            WHERE domain_id = '{domain_id}'
            LIMIT 1
        """, timeout_secs=30)
        if rows and rows[0].get("agent_system_prompt"):
            return {
                "prompt": rows[0]["agent_system_prompt"],
                "saved_at": rows[0].get("updated_at"),
            }
        return {"prompt": None, "saved_at": None}
    except Exception as e:
        return {"prompt": None, "saved_at": None, "error": str(e)}


@router.post("/copilot-prompt")
async def save_copilot_prompt(req: CopilotPromptSaveRequest):
    """Persist the user's guiding prompt into platform.domain_configs."""
    if len(req.prompt or "") > 2500:
        raise HTTPException(status_code=400, detail="Copilot prompt exceeds the 2500-character limit.")
    try:
        escaped = req.prompt.replace("'", "''")
        run_sql(f"""
            UPDATE {CATALOG}.platform.domain_configs
            SET agent_system_prompt = '{escaped}',
                updated_at = current_timestamp()
            WHERE domain_id = '{req.domain_id}'
        """, timeout_secs=30)
        # Invalidate in-process cache so next agent-query picks up new prompt
        with _domain_cache_lock:
            _domain_cache.pop(req.domain_id, None)
        return {"saved": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/copilot-analyze")
async def copilot_analyze(req: CopilotAnalyzeRequest):
    """
    Gap analysis: given the user's pasted guiding prompt, ask the LLM what
    document types / data it would need, then compare against what is actually
    present in parsed_documents for the domain.
    """
    try:
        from databricks_langchain import ChatDatabricks
        from langchain_core.messages import HumanMessage, SystemMessage

        # Step 1 — ask LLM what document types the prompt requires
        llm, _ = _get_llm(max_tokens=1024)
        meta_prompt = (
            "You are a document-intelligence data architect. "
            "Read the system instructions below and identify, as a flat JSON array of strings, "
            "every distinct DOCUMENT TYPE that an AI using these instructions would need access to "
            "in order to answer the kinds of questions described. "
            "Return ONLY a JSON array, no prose. Example: [\"inspection_report\",\"permit_application\"]"
        )
        resp = llm.invoke([
            SystemMessage(content=meta_prompt),
            HumanMessage(content=req.prompt),
        ])
        raw = resp.content.strip()
        # Extract JSON array from response (may be wrapped in markdown)
        import re as _re
        arr_match = _re.search(r'\[.*?\]', raw, _re.DOTALL)
        required_types: list = []
        if arr_match:
            try:
                required_types = json.loads(arr_match.group(0))
            except Exception:
                pass
        if not required_types:
            # Fallback: treat comma-separated tokens
            required_types = [t.strip().strip('"').replace(" ", "_").lower() for t in raw.strip("[]").split(",") if t.strip()]

        # Step 2 — query what's actually in parsed_documents for the domain
        _domain = _get_domain_schemas(req.domain_id)
        _raw = _domain["schema_raw"]
        available_rows = run_sql(f"""
            SELECT doc_type, COUNT(*) AS cnt
            FROM {CATALOG}.{_raw}.parsed_documents
            WHERE doc_type IS NOT NULL
            GROUP BY doc_type
            ORDER BY cnt DESC
        """, timeout_secs=30) or []

        available: dict = {r["doc_type"]: int(r["cnt"]) for r in available_rows}
        total_docs = sum(available.values())

        # Step 3 — match required vs available (fuzzy: substring / token overlap)
        gaps = []
        covered = {}
        for req_type in required_types:
            req_norm = req_type.lower().replace(" ", "_").replace("-", "_")
            matched_key = None
            for avail_key in available:
                avail_norm = avail_key.lower().replace(" ", "_").replace("-", "_")
                if req_norm in avail_norm or avail_norm in req_norm:
                    matched_key = avail_key
                    break
            if matched_key:
                covered[req_type] = available[matched_key]
            else:
                gaps.append(req_type)

        coverage_pct = round(len(covered) / len(required_types) * 100) if required_types else 100
        ready = len(gaps) == 0

        gap_message = (
            f"All {len(required_types)} required document type(s) are represented in the library. Ready to proceed."
            if ready else
            f"{len(gaps)} document type(s) referenced in your instructions are not yet available: "
            + ", ".join(f'"{g}"' for g in gaps)
            + ". Upload them via the Document Library and re-run the pipeline."
        )

        return {
            "required": required_types,
            "available": available,
            "covered": covered,
            "gaps": gaps,
            "total_docs": total_docs,
            "coverage_pct": coverage_pct,
            "ready_to_proceed": ready,
            "message": gap_message,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Domain Schema Setup ───────────────────────────────────────────────────────

class DomainSchemaRequest(BaseModel):
    domain_id: str
    classification_labels: Optional[str] = None   # JSON array of doc type strings
    extraction_schemas: Optional[str] = None       # JSON object: {doc_type: {fields:[{name,desc,example}]}}
    parse_instructions: Optional[str] = None       # Free-text LLM guidance for parsing
    volume_path: Optional[str] = None              # Full /Volumes/catalog/schema/volume_name override

# Track if we've already ensured the parse_instructions column exists
_parse_instr_col_checked: bool = False
_volume_path_col_checked: bool = False

def _ensure_schema_columns():
    """Add parse_instructions and volume_path columns to domain_configs if they don't exist yet."""
    global _parse_instr_col_checked, _volume_path_col_checked
    if not _parse_instr_col_checked:
        try:
            run_sql(
                f"ALTER TABLE {CATALOG}.platform.domain_configs ADD COLUMN IF NOT EXISTS parse_instructions STRING",
                timeout_secs=30,
            )
        except Exception:
            pass
        _parse_instr_col_checked = True
    if not _volume_path_col_checked:
        try:
            run_sql(
                f"ALTER TABLE {CATALOG}.platform.domain_configs ADD COLUMN IF NOT EXISTS volume_path STRING",
                timeout_secs=30,
            )
        except Exception:
            pass
        _volume_path_col_checked = True

# Keep old name as alias for backwards compat
def _ensure_parse_instructions_column():
    _ensure_schema_columns()


def _domain_volume_path(domain_id: str, volume_path_override: str | None = None) -> str:
    """
    Resolve the /Volumes path for a domain.
    Priority: explicit override > saved volume_path in domain_configs > constructed default.
    """
    if volume_path_override:
        return volume_path_override.rstrip("/")
    _d = _get_domain_schemas(domain_id)
    saved = _d.get("volume_path")
    if saved:
        return saved.rstrip("/")
    _raw = _d["schema_raw"]
    _vol = _d.get("volume_docs", "documents")
    return f"/Volumes/{CATALOG}/{_raw}/{_vol}"


@router.get("/list-volumes")
async def list_uc_volumes(catalog_filter: str = ""):
    """
    List Unity Catalog volumes accessible to the app's service principal.
    Uses information_schema.volumes (SQL) for reliability; falls back to SDK REST calls.
    Returns {volumes: [...], total: int, method: str, error?: str}.
    """
    import traceback as _tb

    results = []
    method  = "unknown"
    error_detail = None

    # ── Strategy 1: SHOW SCHEMAS + SHOW VOLUMES per schema (most reliable) ────
    try:
        target_cats: list[str] = [c.strip() for c in catalog_filter.split(",") if c.strip()] if catalog_filter else [CATALOG]
        sql_results = []
        for cat in target_cats:
            # List schemas in this catalog
            schemas_in_cat: list[str] = []
            try:
                schema_rows = run_sql(f"SHOW SCHEMAS IN {cat}", timeout_secs=10) or []
                for r in schema_rows:
                    sname = r.get("databaseName") or r.get("namespace") or r.get("schema_name") or (list(r.values())[0] if r else "")
                    if sname and not str(sname).startswith("information_schema"):
                        schemas_in_cat.append(str(sname))
            except Exception as se:
                error_detail = f"SHOW SCHEMAS failed for {cat}: {se}"

            # For each schema, list volumes
            for sname in schemas_in_cat:
                try:
                    vol_rows = run_sql(f"SHOW VOLUMES IN {cat}.{sname}", timeout_secs=10) or []
                    for r in vol_rows:
                        # column could be volume_name or name depending on DBR version
                        vname = r.get("volume_name") or r.get("name") or (list(r.values())[0] if r else "")
                        if vname:
                            sql_results.append({
                                "catalog":     cat,
                                "schema":      sname,
                                "name":        str(vname),
                                "full_path":   f"/Volumes/{cat}/{sname}/{vname}",
                                "label":       f"{cat}.{sname}.{vname}",
                                "volume_type": r.get("volume_type", "MANAGED"),
                            })
                except Exception:
                    pass  # schema may not have volumes

        if sql_results:
            results = sorted(sql_results, key=lambda x: x["label"])
            method  = "SHOW VOLUMES"

    except Exception as e:
        error_detail = f"SHOW VOLUMES strategy failed: {e}"

    # ── Strategy 1b: information_schema fallback ──────────────────────────────
    if not results:
        try:
            target_cats2 = [c.strip() for c in catalog_filter.split(",") if c.strip()] if catalog_filter else [CATALOG]
            info_results = []
            for cat in target_cats2:
                try:
                    rows = run_sql(f"""
                        SELECT catalog_name, schema_name, volume_name, volume_type
                        FROM {cat}.information_schema.volumes
                        ORDER BY schema_name, volume_name
                    """, timeout_secs=15) or []
                    for r in rows:
                        c = r.get("catalog_name") or cat
                        s = r.get("schema_name",  "")
                        v = r.get("volume_name",  "")
                        if v:
                            info_results.append({
                                "catalog":     c,
                                "schema":      s,
                                "name":        v,
                                "full_path":   f"/Volumes/{c}/{s}/{v}",
                                "label":       f"{c}.{s}.{v}",
                                "volume_type": r.get("volume_type", "MANAGED"),
                            })
                except Exception:
                    pass
            if info_results:
                results = sorted(info_results, key=lambda x: x["label"])
                method  = "information_schema"
        except Exception as e:
            error_detail = f"{error_detail or ''} | information_schema failed: {e}"

    # ── Strategy 2: system.information_schema across all catalogs ─────────────
    if not results:
        try:
            rows = run_sql("""
                SELECT catalog_name, schema_name, volume_name, volume_type
                FROM system.information_schema.volumes
                ORDER BY catalog_name, schema_name, volume_name
            """, timeout_secs=20) or []
            for r in rows:
                c = r.get("catalog_name", "")
                s = r.get("schema_name",  "")
                v = r.get("volume_name",  "")
                if v:
                    results.append({
                        "catalog":     c,
                        "schema":      s,
                        "name":        v,
                        "full_path":   f"/Volumes/{c}/{s}/{v}",
                        "label":       f"{c}.{s}.{v}",
                        "volume_type": r.get("volume_type", "MANAGED"),
                    })
            if results:
                method = "system.information_schema"
        except Exception as e:
            error_detail = f"{error_detail or ''} | system.information_schema failed: {e}"

    # ── Strategy 3: SDK REST calls (last resort) ──────────────────────────────
    if not results:
        try:
            w = WorkspaceClient()
            target_cats = [c.strip() for c in catalog_filter.split(",") if c.strip()] if catalog_filter else [CATALOG]
            # Also try to discover additional catalogs
            try:
                for ci in w.catalogs.list():
                    if ci.name and ci.name not in target_cats:
                        target_cats.append(ci.name)
                        if len(target_cats) >= 10:
                            break
            except Exception:
                pass

            sdk_errors = []
            for cat in target_cats:
                try:
                    for sch in w.schemas.list(catalog_name=cat):
                        if not sch.name:
                            continue
                        try:
                            for vol in w.volumes.list(catalog_name=cat, schema_name=sch.name):
                                if vol.name:
                                    results.append({
                                        "catalog":     cat,
                                        "schema":      sch.name,
                                        "name":        vol.name,
                                        "full_path":   f"/Volumes/{cat}/{sch.name}/{vol.name}",
                                        "label":       f"{cat}.{sch.name}.{vol.name}",
                                        "volume_type": str(getattr(vol, "volume_type", "MANAGED")),
                                    })
                        except Exception as ve:
                            sdk_errors.append(f"{cat}.{sch.name}: {ve}")
                except Exception as se:
                    sdk_errors.append(f"catalog {cat}: {se}")

            if results:
                method = "sdk"
            elif sdk_errors:
                error_detail = f"{error_detail or ''} | SDK errors: {'; '.join(sdk_errors[:5])}"

        except Exception as e:
            error_detail = f"{error_detail or ''} | SDK strategy failed: {_tb.format_exc(limit=3)}"

    results.sort(key=lambda v: v["label"])
    response: dict = {"volumes": results, "total": len(results), "method": method}
    if error_detail:
        response["debug_error"] = error_detail.strip(" |")
    return response


@router.get("/volume-files")
async def list_volume_files(domain_id: str = "supply_chain", volume_path: str = ""):
    """
    List PDF/TXT files in the domain's UC Volume.
    If volume_path is provided it overrides the domain's saved/default volume.
    """
    try:
        vpath = _domain_volume_path(domain_id, volume_path or None)
        w = WorkspaceClient()
        files = []
        try:
            for fi in w.files.list_directory_contents(vpath):
                if fi.name and (fi.name.lower().endswith(".pdf") or fi.name.lower().endswith(".txt")):
                    files.append({
                        "name": fi.name,
                        "path": f"{vpath}/{fi.name}",
                        "size_bytes": fi.file_size or 0,
                        "modified": str(fi.last_modified) if fi.last_modified else None,
                    })
        except Exception as e:
            return {
                "domain_id": domain_id,
                "volume_path": vpath,
                "files": [],
                "message": f"Could not list volume: {e}",
            }

        files.sort(key=lambda f: f.get("modified") or "", reverse=True)
        return {
            "domain_id": domain_id,
            "volume_path": vpath,
            "files": files,
            "total": len(files),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Global Document-Type Schema Library ──────────────────────────────────────
#
# Stores extraction schemas PER DOCUMENT TYPE (not per domain).
# Allows reuse across all subject areas: once a "purchase_order" schema is
# created for Supply Chain it is available for any other domain too.
#
# Table: {CATALOG}.platform.doc_type_schemas
#   doc_type          STRING  PRIMARY KEY (normalized snake_case)
#   display_name      STRING
#   description       STRING
#   extraction_schema STRING  JSON array [{name, description, example}]
#   parse_instructions STRING
#   sample_file_path  STRING
#   created_by_domain STRING
#   updated_at        TIMESTAMP

_doc_type_table_checked: bool = False

def _ensure_doc_type_table():
    global _doc_type_table_checked
    if _doc_type_table_checked:
        return
    try:
        run_sql(f"""
            CREATE TABLE IF NOT EXISTS {CATALOG}.platform.doc_type_schemas (
                doc_type              STRING NOT NULL,
                display_name          STRING,
                description           STRING,
                extraction_schema     STRING,
                parse_instructions    STRING,
                sample_file_path      STRING,
                volume_path           STRING,
                classification_examples STRING,
                created_by_domain     STRING,
                updated_at            TIMESTAMP
            ) USING DELTA
        """, timeout_secs=30)
    except Exception as e:
        print(f"[doc_type_table] create warning: {e}")
    # Lazily add new columns if table pre-existed
    for col, dtype in [("volume_path", "STRING"), ("classification_examples", "STRING")]:
        try:
            run_sql(f"ALTER TABLE {CATALOG}.platform.doc_type_schemas ADD COLUMN IF NOT EXISTS {col} {dtype}", timeout_secs=20)
        except Exception:
            pass
    _doc_type_table_checked = True


class DocTypeSchemaRequest(BaseModel):
    doc_type: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    extraction_schema: Optional[str] = None           # JSON array [{name, description, example}]
    parse_instructions: Optional[str] = None
    sample_file_path: Optional[str] = None
    volume_path: Optional[str] = None                 # per-doc-type volume
    classification_examples: Optional[str] = None     # JSON array of example strings
    domain_id: Optional[str] = None                   # for provenance


@router.get("/schema-presets")
async def get_schema_presets():
    """
    Returns named field-extraction preset schemas that users can load into
    the Schema Setup wizard with one click, rather than building from scratch.
    """
    presets = {
        "compliance_standard": {
            "display_name": "Compliance Standard Fields",
            "description": "Core extraction fields for any compliance document — inspections, permits, violations, correspondence, regulatory changes.",
            "fields": [
                {"name": "jurisdiction",          "description": "State, county, or city this document applies to",              "example": "Georgia"},
                {"name": "statute_number",        "description": "CFR section, state code, or rule number cited",                "example": "40 CFR § 280.20"},
                {"name": "enforcement_authority", "description": "Agency or authority responsible for enforcement",              "example": "EPA Region IV"},
                {"name": "effective_date",        "description": "Date this regulation or requirement takes effect",             "example": "2025-06-01"},
                {"name": "deadline",              "description": "Response or corrective action deadline",                       "example": "2025-04-11"},
                {"name": "assigned_owner",        "description": "Person or role responsible for this item",                     "example": "District Manager"},
                {"name": "risk_level",            "description": "Severity: CRITICAL, HIGH, MEDIUM, or LOW",                   "example": "HIGH"},
                {"name": "change_type",           "description": "Type of regulatory change: AMENDED, NEW REQUIREMENT, REPEALED", "example": "AMENDED"},
                {"name": "confidence_level",      "description": "Source reliability: HIGH, MEDIUM, or LOW",                   "example": "HIGH"},
            ],
        },
        "supply_chain_standard": {
            "display_name": "Supply Chain Standard Fields",
            "description": "Core extraction fields for supply chain documents — contracts, shipments, quality reports.",
            "fields": [
                {"name": "supplier_name",     "description": "Name of the supplier or vendor",                    "example": "Tyson Foods Inc."},
                {"name": "shipment_id",       "description": "Shipment, lot, or PO number",                       "example": "SHP-20240315"},
                {"name": "delivery_date",     "description": "Scheduled or actual delivery date",                 "example": "2024-03-15"},
                {"name": "temperature_max",   "description": "Maximum temperature recorded during transit",        "example": "48°F"},
                {"name": "sla_status",        "description": "Whether SLA requirements were met: PASS or FAIL",   "example": "FAIL"},
                {"name": "penalty_amount",    "description": "Financial penalty amount if applicable",            "example": "$12,500"},
                {"name": "corrective_action", "description": "Required corrective action or resolution",          "example": "Replace refrigeration unit"},
                {"name": "risk_level",        "description": "Risk assessment: CRITICAL, HIGH, MEDIUM, or LOW",   "example": "HIGH"},
            ],
        },
    }
    return {"presets": presets}


@router.get("/doc-type-schemas")
async def list_doc_type_schemas():
    """
    Return all document type schemas from the global library.
    Each entry: {doc_type, display_name, description, extraction_schema, parse_instructions, updated_at}
    """
    _ensure_doc_type_table()
    try:
        rows = run_sql(f"""
            SELECT doc_type, display_name, description,
                   extraction_schema, parse_instructions,
                   created_by_domain, updated_at
            FROM {CATALOG}.platform.doc_type_schemas
            ORDER BY doc_type
        """, timeout_secs=30)
        return {"schemas": rows or [], "total": len(rows or [])}
    except Exception as e:
        return {"schemas": [], "total": 0, "error": str(e)}


@router.get("/doc-type-schema")
async def get_doc_type_schema_by_type(doc_type: str):
    """Return schema for a specific document type, or null if not found."""
    _ensure_doc_type_table()
    try:
        rows = run_sql(f"""
            SELECT doc_type, display_name, description,
                   extraction_schema, parse_instructions,
                   sample_file_path, created_by_domain, updated_at
            FROM {CATALOG}.platform.doc_type_schemas
            WHERE doc_type = '{doc_type.lower().replace(" ", "_")}'
            LIMIT 1
        """, timeout_secs=30)
        if not rows:
            return {"found": False, "doc_type": doc_type}
        r = rows[0]
        return {"found": True, **r}
    except Exception as e:
        return {"found": False, "doc_type": doc_type, "error": str(e)}


@router.post("/doc-type-schema")
async def save_doc_type_schema(req: DocTypeSchemaRequest):
    """
    Insert or update a document type schema in the global library.
    Uses MERGE to upsert by doc_type.
    """
    _ensure_doc_type_table()
    try:
        import json as _json
        dt = req.doc_type.strip().lower().replace(" ", "_")
        display = req.display_name or dt.replace("_", " ").title()
        desc   = (req.description or "").replace("'", "\\'")
        es     = (req.extraction_schema or "").replace("'", "\\'")
        pi     = (req.parse_instructions or "").replace("'", "\\'")
        sfp    = (req.sample_file_path or "").replace("'", "\\'")
        vp     = (req.volume_path or "").replace("'", "\\'")
        ce     = (req.classification_examples or "").replace("'", "\\'")
        domain = (req.domain_id or "unknown").replace("'", "\\'")
        display_esc = display.replace("'", "\\'")
        dt_esc = dt.replace("'", "\\'")

        run_sql(f"""
            MERGE INTO {CATALOG}.platform.doc_type_schemas AS tgt
            USING (SELECT
                '{dt_esc}'       AS doc_type,
                '{display_esc}'  AS display_name,
                '{desc}'         AS description,
                '{es}'           AS extraction_schema,
                '{pi}'           AS parse_instructions,
                '{sfp}'          AS sample_file_path,
                '{vp}'           AS volume_path,
                '{ce}'           AS classification_examples,
                '{domain}'       AS created_by_domain,
                current_timestamp() AS updated_at
            ) AS src
            ON tgt.doc_type = src.doc_type
            WHEN MATCHED THEN UPDATE SET
                tgt.display_name              = src.display_name,
                tgt.description               = src.description,
                tgt.extraction_schema         = CASE WHEN src.extraction_schema != '' THEN src.extraction_schema ELSE tgt.extraction_schema END,
                tgt.parse_instructions        = CASE WHEN src.parse_instructions != '' THEN src.parse_instructions ELSE tgt.parse_instructions END,
                tgt.sample_file_path          = CASE WHEN src.sample_file_path != '' THEN src.sample_file_path ELSE tgt.sample_file_path END,
                tgt.volume_path               = CASE WHEN src.volume_path != '' THEN src.volume_path ELSE tgt.volume_path END,
                tgt.classification_examples   = CASE WHEN src.classification_examples != '' THEN src.classification_examples ELSE tgt.classification_examples END,
                tgt.updated_at                = src.updated_at
            WHEN NOT MATCHED THEN INSERT *
        """, timeout_secs=30)

        # Also invalidate domain cache so the domain picks up the new type
        with _domain_cache_lock:
            _domain_cache.pop(req.domain_id or "", None)

        return {"ok": True, "doc_type": dt, "display_name": display}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/generate-parse-hints")
async def generate_parse_hints(doc_type: str, domain_id: str = "supply_chain"):
    """
    Generate parse instruction hints for a doc type using the LLM.
    Returns a suggested parse_instructions template and a guidance blurb.
    """
    try:
        llm, model = _get_llm(max_tokens=800)
        from langchain_core.messages import HumanMessage, SystemMessage
        dt_label = doc_type.replace("_", " ").title()
        prompt = (
            f"You are a document-intelligence expert helping a business analyst configure "
            f"an AI parser for '{dt_label}' documents.\n\n"
            f"Write concise parse instructions (3-6 bullet points) telling the LLM what to focus on "
            f"when parsing this document type. Then provide 2-3 example instruction phrases.\n\n"
            f"Format your response as:\n"
            f"INSTRUCTIONS:\n"
            f"- <bullet 1>\n"
            f"- <bullet 2>\n"
            f"...\n\n"
            f"EXAMPLES:\n"
            f"- \"<example phrase 1>\"\n"
            f"- \"<example phrase 2>\"\n"
        )
        resp = llm.invoke([
            SystemMessage(content="You are a precise technical writer. Be concise and practical."),
            HumanMessage(content=prompt),
        ])
        raw = resp.content.strip()

        # Parse into instructions and examples sections
        instructions_text = ""
        examples_text = ""
        if "EXAMPLES:" in raw:
            parts = raw.split("EXAMPLES:", 1)
            instructions_text = parts[0].replace("INSTRUCTIONS:", "").strip()
            examples_text = parts[1].strip()
        else:
            instructions_text = raw.replace("INSTRUCTIONS:", "").strip()

        # Build the full suggested template
        template = (
            f"# Parse Instructions for {dt_label}\n\n"
            f"Goal: Extract structured information from {dt_label} documents accurately.\n\n"
            f"{instructions_text}\n\n"
            f"General rules:\n"
            f"- Extract values exactly as they appear; do not infer or fabricate values\n"
            f"- Normalize dates to YYYY-MM-DD where possible\n"
            f"- Return null (not empty string) for fields genuinely absent from the document\n"
            f"- Monetary amounts: extract numeric value only, note currency separately\n"
        )
        if examples_text:
            template += f"\nExample guidance phrases:\n{examples_text}"

        return {
            "doc_type": doc_type,
            "suggested_instructions": template,
            "examples_section": examples_text,
            "model": model,
        }
    except Exception as e:
        # Return a static template on LLM failure
        dt_label = doc_type.replace("_", " ").title()
        return {
            "doc_type": doc_type,
            "suggested_instructions": (
                f"# Parse Instructions for {dt_label}\n\n"
                f"Goal: Extract structured information from {dt_label} documents.\n\n"
                f"- Focus on identifying all key fields listed in the extraction schema\n"
                f"- Extract values exactly as they appear in the document\n"
                f"- For dates, normalize to YYYY-MM-DD format\n"
                f"- Return null for fields genuinely absent from the document\n"
                f"- Monetary values: extract numeric amount, note currency separately\n\n"
                f"Example guidance:\n"
                f'- "Look for the document number near the header, typically labeled as ID or Reference"\n'
                f'- "Dates may appear in multiple formats — extract the primary/first occurrence"\n'
            ),
            "error": str(e),
        }


@router.get("/generate-classification-examples")
async def generate_classification_examples(doc_type: str, domain_id: str = "supply_chain"):
    """
    Generate 3 classification example sentences for a doc type using the LLM.
    These are passed to ai_classify() to sharpen edge-case detection.
    """
    try:
        llm, model = _get_llm(max_tokens=400)
        from langchain_core.messages import HumanMessage, SystemMessage
        dt_label = doc_type.replace("_", " ").title()
        prompt = (
            f"Write exactly 3 short example sentences that describe what a '{dt_label}' "
            f"document looks like. Each sentence should capture a different scenario or variation "
            f"a classifier might encounter. Keep each under 25 words.\n\n"
            f"Respond with ONLY a JSON array of 3 strings, no other text:\n"
            f'["example 1", "example 2", "example 3"]'
        )
        resp = llm.invoke([
            SystemMessage(content="You produce only valid JSON. No markdown, no explanation."),
            HumanMessage(content=prompt),
        ])
        raw = resp.content.strip()
        parsed = _robust_json_loads(raw)
        examples = parsed if isinstance(parsed, list) else list(parsed.values())
        if not examples:
            raise ValueError("empty result")
        return {"doc_type": doc_type, "examples": [str(e) for e in examples[:3]], "model": model}
    except Exception as e:
        dt_label = doc_type.replace("_", " ").title()
        return {
            "doc_type": doc_type,
            "examples": [
                f"This document is a {dt_label} containing structured data.",
                f"A {dt_label} record with dates, identifiers, and party information.",
                f"Scanned {dt_label} form with field labels and handwritten or printed values.",
            ],
            "error": str(e),
        }


class AnalyzeUploadedFileRequest(BaseModel):
    doc_type: str = ""
    file_name: str = ""
    file_content_b64: str = ""       # base64-encoded file bytes
    file_mime: str = "application/pdf"
    domain_id: str = "supply_chain"
    extraction_schema: Optional[str] = None   # JSON [{name, description, example}]
    parse_instructions: Optional[str] = None


@router.post("/analyze-uploaded-file")
async def analyze_uploaded_file(req: AnalyzeUploadedFileRequest):
    """
    Accept a base64-encoded file (PDF or TXT), extract its text, run AI schema analysis,
    and return suggested extraction fields — same structure as domain-schema-preview.
    This allows users to upload a sample document directly without needing a UC volume.
    """
    try:
        import base64 as _b64
        from langchain_core.messages import HumanMessage, SystemMessage

        # Decode file
        file_bytes = _b64.b64decode(req.file_content_b64)
        doc_text = ""

        if req.file_mime == "application/pdf" or req.file_name.lower().endswith(".pdf"):
            try:
                import io as _io
                import PyPDF2
                reader = PyPDF2.PdfReader(_io.BytesIO(file_bytes))
                pages = [p.extract_text() or "" for p in reader.pages]
                doc_text = "\n".join(pages)[:12000]
            except Exception as pe:
                doc_text = f"[PDF extraction failed: {pe}]"
        else:
            doc_text = file_bytes.decode("utf-8", errors="replace")[:12000]

        # Sanitize: remove control characters and characters that can break prompt f-strings
        import re as _re
        doc_text = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', ' ', doc_text)  # strip ctrl chars
        # Replace lone { and } with unicode lookalikes so the f-string doesn't misinterpret them
        doc_text_safe = doc_text.replace("{", "｛").replace("}", "｝").replace("\\", "/")

        if not doc_text.strip():
            return {
                "ok": False,
                "error": "Could not extract text from the uploaded file. Ensure it is a text-based PDF or plain TXT.",
                "predicted_doc_type": req.doc_type or "unknown",
                "extracted_fields": {},
                "suggested_new_fields": [],
                "parse_flags": [],
                "data_quality_notes": [],
            }

        # Build current schema context
        current_fields_desc = ""
        if req.extraction_schema:
            try:
                import json as _json
                flds = _json.loads(req.extraction_schema)
                current_fields_desc = "\n".join(
                    f"  - {f.get('name','?')}: {f.get('description','')}" for f in flds
                )
            except Exception:
                pass

        dt_hint = req.doc_type.replace("_", " ").title() if req.doc_type else "unknown"

        prompt = f"""You are a document intelligence analyst examining a sample document.

Document type hint: {dt_hint}
Filename: {req.file_name}

{f"Existing extraction fields already configured:{chr(10)}{current_fields_desc}" if current_fields_desc else "No extraction fields configured yet — discover them from scratch."}

DOCUMENT TEXT (first ~3000 chars):
{doc_text_safe[:3000]}

Analyze this document and return a JSON object with these keys:
{{
  "predicted_doc_type": "snake_case_type",
  "extracted_fields": {{"field_name": "extracted_value_from_sample", ...}},
  "suggested_new_fields": [
    {{"name": "field_name", "description": "what this field means", "example_value": "example from the doc"}}
  ],
  "parse_flags": ["any warnings, e.g. scanned/low-quality, tables, multi-language"],
  "data_quality_notes": ["observations about data quality or layout complexity"]
}}

Focus on fields actually present in this document. Return ONLY the JSON object."""

        llm, model = _get_llm(max_tokens=1500)
        resp = llm.invoke([
            SystemMessage(content="You are a precise document analyst. Always respond with valid JSON only — no markdown, no explanations, no comments."),
            HumanMessage(content=prompt),
        ])
        raw = resp.content.strip()
        parsed = _robust_json_loads(raw)

        return {
            "ok": True,
            "predicted_doc_type": parsed.get("predicted_doc_type", req.doc_type or "unknown"),
            "extracted_fields": parsed.get("extracted_fields", {}),
            "suggested_new_fields": parsed.get("suggested_new_fields", []),
            "parse_flags": parsed.get("parse_flags", []),
            "data_quality_notes": parsed.get("data_quality_notes", []),
            "model": model,
            "text_length": len(doc_text),
        }
    except Exception as e:
        import traceback
        return {
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc()[-500:],
            "predicted_doc_type": req.doc_type or "unknown",
            "extracted_fields": {},
            "suggested_new_fields": [],
            "parse_flags": [],
            "data_quality_notes": [],
        }


@router.get("/domain-schema")
async def get_domain_schema(domain_id: str = "supply_chain"):
    """
    Return the current domain schema config: classification labels,
    extraction schemas, parse instructions, and volume_path override.
    """
    _ensure_schema_columns()
    try:
        rows = run_sql(f"""
            SELECT classification_labels, extraction_schemas, parse_instructions,
                   volume_path, updated_at
            FROM {CATALOG}.platform.domain_configs
            WHERE domain_id = '{domain_id}'
            LIMIT 1
        """, timeout_secs=30)
        if not rows:
            return {
                "domain_id": domain_id,
                "classification_labels": None,
                "extraction_schemas": None,
                "parse_instructions": None,
                "volume_path": None,
                "saved_at": None,
            }
        r = rows[0]
        return {
            "domain_id": domain_id,
            "classification_labels": r.get("classification_labels"),
            "extraction_schemas": r.get("extraction_schemas"),
            "parse_instructions": r.get("parse_instructions"),
            "volume_path": r.get("volume_path"),
            "saved_at": r.get("updated_at"),
        }
    except Exception as e:
        # Fallback: column may not exist yet — retry without volume_path
        try:
            rows = run_sql(f"""
                SELECT classification_labels, extraction_schemas, parse_instructions, updated_at
                FROM {CATALOG}.platform.domain_configs
                WHERE domain_id = '{domain_id}'
                LIMIT 1
            """, timeout_secs=30)
            if not rows:
                return {"domain_id": domain_id, "classification_labels": None,
                        "extraction_schemas": None, "parse_instructions": None,
                        "volume_path": None, "saved_at": None}
            r = rows[0]
            return {"domain_id": domain_id,
                    "classification_labels": r.get("classification_labels"),
                    "extraction_schemas": r.get("extraction_schemas"),
                    "parse_instructions": r.get("parse_instructions"),
                    "volume_path": None, "saved_at": r.get("updated_at")}
        except Exception as e2:
            raise HTTPException(status_code=500, detail=str(e2))


@router.post("/domain-schema")
async def save_domain_schema(req: DomainSchemaRequest):
    """
    Persist domain schema config (classification labels, extraction schemas,
    parse instructions, volume_path) into platform.domain_configs.
    Invalidates the in-process domain cache so the next pipeline run picks
    up the new config immediately.
    """
    _ensure_schema_columns()
    try:
        set_clauses = ["updated_at = current_timestamp()"]

        if req.classification_labels is not None:
            esc = req.classification_labels.replace("'", "''")
            set_clauses.append(f"classification_labels = '{esc}'")

        if req.extraction_schemas is not None:
            esc = req.extraction_schemas.replace("'", "''")
            set_clauses.append(f"extraction_schemas = '{esc}'")

        if req.parse_instructions is not None:
            esc = req.parse_instructions.replace("'", "''")
            set_clauses.append(f"parse_instructions = '{esc}'")

        if req.volume_path is not None:
            esc = req.volume_path.strip().rstrip("/").replace("'", "''")
            set_clauses.append(f"volume_path = '{esc}'")

        if len(set_clauses) == 1:
            return {"saved": True, "message": "Nothing to update"}

        run_sql(f"""
            UPDATE {CATALOG}.platform.domain_configs
            SET {', '.join(set_clauses)}
            WHERE domain_id = '{req.domain_id}'
        """, timeout_secs=30)

        # Invalidate in-process cache so pipeline picks up new config
        with _domain_cache_lock:
            _domain_cache.pop(req.domain_id, None)

        return {"saved": True, "domain_id": req.domain_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/domain-schema-preview")
async def domain_schema_preview(req: dict):
    """
    Test the current schema config against a specific file in the UC Volume or a recently-parsed doc.

    Request body:
      domain_id             - required
      file_name             - optional: filename in the UC Volume to test against (PDF or TXT)
      classification_labels - optional: override labels to test (not yet saved)
      extraction_schemas    - optional: override schemas to test (not yet saved)
      parse_instructions    - optional: override parse instructions to test (not yet saved)

    Returns:
      preview               - human-readable formatted text summary
      doc_id                - document tested
      predicted_doc_type    - the classified label
      extracted_fields      - dict of {field_name: extracted_value} from the schema
      suggested_new_fields  - list of {name, description, example_value} for additional fields
      parse_flags           - list of any threshold/rule violations found
    """
    import re as _re
    import json as _json
    try:
        domain_id = req.get("domain_id", "supply_chain")

        # Lazy import — isolates mcp/langchain compatibility errors to this endpoint only
        try:
            from databricks_langchain import ChatDatabricks
            from langchain_core.messages import HumanMessage, SystemMessage
        except ImportError as ie:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"LLM client import failed: {ie}. "
                    "This is usually a package version conflict (mcp). "
                    "Check requirements.txt and ensure mcp>=1.0.0,<1.9.0 is installed."
                ),
            )

        _domain = _get_domain_schemas(domain_id)
        _raw    = _domain["schema_raw"]

        labels_raw  = req.get("classification_labels")  or _domain.get("classification_labels") or "[]"
        schemas_raw = req.get("extraction_schemas")     or _domain.get("extraction_schemas")    or "[]"
        parse_instr = req.get("parse_instructions")     or _domain.get("parse_instructions")    or ""

        doc_content = ""
        doc_id      = "sample"
        is_pdf      = False

        # Resolve volume path: request override > saved > default
        vol_path_base = _domain_volume_path(domain_id, req.get("volume_path"))

        # ── Option 1: specific file from UC Volume ────────────────────────────
        file_name = req.get("file_name")
        if file_name:
            try:
                volume_path = f"{vol_path_base}/{file_name}"
                w = WorkspaceClient()
                file_bytes = w.files.download(volume_path).contents.read(12000)
                doc_id = file_name
                is_pdf = file_name.lower().endswith(".pdf")

                if is_pdf:
                    # Extract text from PDF using PyPDF2
                    import io
                    try:
                        import PyPDF2
                        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
                        pages_text = []
                        for i, page in enumerate(pdf_reader.pages):
                            if i >= 6:          # cap at 6 pages for preview
                                break
                            t = page.extract_text() or ""
                            if t.strip():
                                pages_text.append(f"[Page {i+1}]\n{t}")
                        doc_content = "\n\n".join(pages_text)[:4000]
                    except Exception as pdf_err:
                        # Fall back to raw bytes as Latin-1 text
                        doc_content = file_bytes.decode("latin-1", errors="replace")[:4000]
                else:
                    doc_content = file_bytes.decode("utf-8", errors="replace")[:4000]

            except Exception as fe:
                return {
                    "preview": f"Could not read file '{file_name}' from volume: {fe}",
                    "doc_id": file_name,
                    "predicted_doc_type": None,
                    "extracted_fields": {},
                    "suggested_new_fields": [],
                    "parse_flags": [],
                }

        # ── Option 2: most recently parsed document ───────────────────────────
        if not doc_content:
            rows = run_sql(f"""
                SELECT doc_id, doc_type, SUBSTRING(CAST(parsed_content AS STRING), 1, 3000) AS content
                FROM {CATALOG}.{_raw}.parsed_documents
                ORDER BY processed_ts DESC NULLS LAST
                LIMIT 1
            """, timeout_secs=20) or []
            if rows:
                doc  = rows[0]
                doc_content = doc.get("content", "")
                doc_id      = doc.get("doc_id", "unknown")

        if not doc_content:
            return {
                "preview": "No sample data found. Upload a document to the volume first, or run the pipeline at least once.",
                "doc_id": None,
                "predicted_doc_type": None,
                "extracted_fields": {},
                "suggested_new_fields": [],
                "parse_flags": [],
            }

        # ── Build structured prompt ───────────────────────────────────────────
        prompt = f"""You are a document intelligence schema validator analyzing a {domain_id.replace('_',' ').title()} document.

DOCUMENT: {doc_id}{"  [PDF — text extracted]" if is_pdf else "  [TXT]"}

DOCUMENT CONTENT:
{doc_content}

---
CLASSIFICATION LABELS: {labels_raw}
EXTRACTION SCHEMA (per doc type): {schemas_raw}
{f"PARSE INSTRUCTIONS: {parse_instr}" if parse_instr else ""}
---

Respond ONLY with valid JSON — no markdown fences, no prose before or after — in this exact structure:
{{
  "predicted_doc_type": "<the single best-matching label from the classification list>",
  "prediction_reason": "<one sentence explaining why>",
  "extracted_fields": {{
    "<field_name>": "<actual value found in the document, or null if not present>"
  }},
  "suggested_new_fields": [
    {{
      "name": "<snake_case_field_name>",
      "description": "<what this field captures>",
      "example_value": "<the actual value from this document>"
    }}
  ],
  "parse_flags": ["<any threshold exceedance, missing required field, or rule violation>"],
  "data_quality_notes": "<brief note about gaps or ambiguities in this document>"
}}

Rules:
- extracted_fields must use the field names from the EXTRACTION SCHEMA for the predicted doc type.
- suggested_new_fields should propose 5-8 additional fields not in the current schema that would be valuable for this doc type. Base them on what you actually see in the document.
- All values must come from the document — never invent values.
- Return null (JSON null, not the string "null") for fields genuinely not found."""

        llm, _ = _get_llm(max_tokens=2000)
        response = llm.invoke([
            SystemMessage(content="You are a precise document schema validator. Return only valid JSON — no markdown, no prose."),
            HumanMessage(content=prompt),
        ])

        raw_text = response.content.strip()

        # ── Parse JSON from response ──────────────────────────────────────────
        structured = {}
        try:
            # Strip any accidental markdown fences
            clean = _re.sub(r'^```(?:json)?\s*', '', raw_text, flags=_re.MULTILINE)
            clean = _re.sub(r'\s*```\s*$', '', clean, flags=_re.MULTILINE)
            structured = _json.loads(clean.strip())
        except Exception:
            # If JSON parse fails, return raw text as preview only
            return {
                "preview": raw_text,
                "doc_id": doc_id,
                "predicted_doc_type": None,
                "extracted_fields": {},
                "suggested_new_fields": [],
                "parse_flags": [],
                "parse_error": "LLM did not return valid JSON — see preview text.",
            }

        # ── Build human-readable preview from structured data ─────────────────
        dt   = structured.get("predicted_doc_type", "unknown")
        ef   = structured.get("extracted_fields", {}) or {}
        snf  = structured.get("suggested_new_fields", []) or []
        pf   = structured.get("parse_flags", []) or []
        dqn  = structured.get("data_quality_notes", "")
        reason = structured.get("prediction_reason", "")

        lines = [
            f"📋 Document Type: {dt}",
            f"   Reason: {reason}",
            "",
            "📊 Extracted Fields:",
        ]
        for k, v in ef.items():
            lines.append(f"   {k}: {v}")
        if not ef:
            lines.append("   (no extraction schema configured for this doc type yet)")

        if snf:
            lines.append("")
            lines.append("💡 Suggested New Fields:")
            for f_item in snf:
                n = f_item.get("name", "")
                d = f_item.get("description", "")
                ex = f_item.get("example_value", "")
                ex_hint = ('  →  "' + ex + '"') if ex else ''
                lines.append(f"   + {n}: {d}{ex_hint}")

        if pf:
            lines.append("")
            lines.append("⚠️  Parse Flags:")
            for flag in pf:
                lines.append(f"   • {flag}")

        if dqn:
            lines.append("")
            lines.append(f"📝 Data Quality: {dqn}")

        return {
            "preview": "\n".join(lines),
            "doc_id": doc_id,
            "predicted_doc_type": dt,
            "extracted_fields": ef,
            "suggested_new_fields": snf,
            "parse_flags": pf,
            "data_quality_notes": dqn,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _parse_copilot_sections(text: str) -> dict:
    """
    Split LLM response into Compliance Map Copilot sections.
    Handles both '## Facts' heading style and 'Facts:' inline style.
    Returns a dict with keys: facts, interpretations, sources, risks,
    open_questions, next_steps.  Missing sections are empty strings.
    """
    import re as _re
    section_map = {
        "facts":           _re.compile(r'(?:^|\n)(?:#{1,3}\s*)?Facts\s*[:：\n]', _re.IGNORECASE),
        "interpretations": _re.compile(r'(?:^|\n)(?:#{1,3}\s*)?Interpretations?\s*[:：\n]', _re.IGNORECASE),
        "sources":         _re.compile(r'(?:^|\n)(?:#{1,3}\s*)?Sources?\s*[:：\n]', _re.IGNORECASE),
        "risks":           _re.compile(r'(?:^|\n)(?:#{1,3}\s*)?Risks?\s*[:：\n]', _re.IGNORECASE),
        "open_questions":  _re.compile(r'(?:^|\n)(?:#{1,3}\s*)?Open\s+Questions?\s*[:：\n]', _re.IGNORECASE),
        "next_steps":      _re.compile(r'(?:^|\n)(?:#{1,3}\s*)?(?:Recommended\s+)?Next\s+Steps?\s*[:：\n]', _re.IGNORECASE),
    }
    order = ["facts", "interpretations", "sources", "risks", "open_questions", "next_steps"]

    # Find positions of each section header
    positions = {}
    for key, pattern in section_map.items():
        m = pattern.search(text)
        if m:
            positions[key] = m.end()

    if not positions:
        return {k: "" for k in order}

    sorted_keys = sorted(positions, key=lambda k: positions[k])
    result = {}
    for i, key in enumerate(sorted_keys):
        start = positions[key]
        if i + 1 < len(sorted_keys):
            next_key = sorted_keys[i + 1]
            next_m = section_map[next_key].search(text, start)
            end = next_m.start() if next_m else len(text)
        else:
            end = len(text)
        result[key] = text[start:end].strip()

    for key in order:
        result.setdefault(key, "")
    return result


@router.post("/copilot-query")
async def copilot_query(req: CopilotQueryRequest):
    """
    Run a question through the Compliance Map Copilot.
    Uses saved guiding prompt (or override), retrieves relevant doc context via
    vector search, calls FMAPI LLM, and returns structured sections.
    """
    try:
        from databricks_langchain import ChatDatabricks
        from langchain_core.messages import HumanMessage, SystemMessage

        # Load saved prompt (or use override)
        system_prompt = req.prompt_override
        if not system_prompt:
            rows = run_sql(f"""
                SELECT agent_system_prompt FROM {CATALOG}.platform.domain_configs
                WHERE domain_id = '{req.domain_id}' LIMIT 1
            """, timeout_secs=20)
            if rows and rows[0].get("agent_system_prompt"):
                system_prompt = rows[0]["agent_system_prompt"]

        if not system_prompt:
            system_prompt = (
                f"You are an AI compliance intelligence assistant for the {req.domain_id} domain. "
                "Answer questions based on the provided document context. "
                "Separate every response into: Facts, Interpretations, Sources, Risks, Open Questions, Recommended Next Steps."
            )

        # Ensure the response-format instruction always includes Interpretations
        format_instruction = (
            "\n\nAlways structure EVERY response with EXACTLY these section headers in this order:\n"
            "Facts:\n"
            "Interpretations:\n"
            "Sources:\n"
            "Risks:\n"
            "Open Questions:\n"
            "Recommended Next Steps:\n\n"
            "Under Facts: state only verifiable information grounded in provided documents or cited regulatory sources.\n"
            "Under Interpretations: explain how the facts apply to the situation — distinguish your analysis from the raw facts.\n"
            "Under Sources: cite every document, statute, or regulation referenced.\n"
        )
        if "Interpretations" not in system_prompt:
            system_prompt += format_instruction

        # Per-fact source citation (ALWAYS applied) so the UI can align a source link
        # to each fact. Each Facts line must end with the source filename in square
        # brackets, copied from the [Source: <filename>] tags in the provided context.
        system_prompt += (
            "\n\nFACTS FORMATTING (mandatory): Under the Facts section, put each fact on its own "
            "line starting with '- ', and END EACH LINE with the single most relevant source "
            "document filename in square brackets, copied exactly from the [Source: <filename>] "
            "tags provided — e.g. '- Alcohol license required; lead time ~60 days. "
            "[dallas_alcohol_permit.pdf]'. If a fact has no supporting document, end it with "
            "'[no source]'. Do not put filenames anywhere except in these brackets."
        )

        # Retrieve relevant doc context via Vector Search (best-effort)
        context_text = ""
        cited_docs: list = []
        try:
            from databricks.vector_search.client import VectorSearchClient
            _domain = _get_domain_schemas(req.domain_id)
            _vec = _domain["schema_vec"]
            domain_index = f"{CATALOG}.{_vec}.{req.domain_id}_docs_index"
            vsc = VectorSearchClient()
            index = vsc.get_index(VS_ENDPOINT, domain_index)
            results = index.similarity_search(
                query_text=req.query,
                columns=["chunk_id", "doc_id", "doc_type", "chunk_to_retrieve"],
                num_results=6,
            )
            data = results.get("result", {}).get("data_array", [])
            if data:
                chunks = []
                for row in data:
                    doc_id = row[1] if len(row) > 1 else "unknown"
                    doc_type = row[2] if len(row) > 2 else ""
                    chunk = row[3] if len(row) > 3 else ""
                    if doc_id not in cited_docs:
                        cited_docs.append(doc_id)
                    chunks.append(f"[Source: {doc_id} | Type: {doc_type}]\n{chunk}")
                context_text = "\n\n---\n\n".join(chunks)
        except Exception as vs_err:
            # Fall back: pull recent parsed doc text snippets from SQL
            try:
                _domain = _get_domain_schemas(req.domain_id)
                _raw = _domain["schema_raw"]
                fallback_rows = run_sql(f"""
                    SELECT doc_id, doc_type,
                           SUBSTRING(CAST(parsed_content AS STRING), 1, 500) AS snippet
                    FROM {CATALOG}.{_raw}.parsed_documents
                    ORDER BY processed_ts DESC NULLS LAST
                    LIMIT 8
                """, timeout_secs=20) or []
                if fallback_rows:
                    cited_docs = [r["doc_id"] for r in fallback_rows]
                    context_text = "\n\n---\n\n".join(
                        f"[Source: {r['doc_id']} | Type: {r.get('doc_type','')}]\n{r.get('snippet','')}"
                        for r in fallback_rows
                    )
            except Exception:
                pass

        human_content = req.query
        if context_text:
            human_content = (
                f"Use the following document excerpts as your primary source material:\n\n"
                f"{context_text}\n\n"
                f"---\n\nQuestion: {req.query}"
            )

        llm, _ = _get_llm(max_tokens=2048)
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_content),
        ])
        raw_answer = response.content.strip()

        sections = _parse_copilot_sections(raw_answer)
        attorney_review = "attorney review recommended" in raw_answer.lower()

        # Derive confidence and source_tier from whether we had VS results
        import re as _re
        confidence_match = _re.search(r'Confidence\s*[:：]\s*(HIGH|MEDIUM|LOW|UNABLE[_\s]TO[_\s]VERIFY)', raw_answer, _re.IGNORECASE)
        if confidence_match:
            confidence = confidence_match.group(1).upper().replace(" ", "_")
        elif cited_docs and context_text:
            confidence = "HIGH" if len(cited_docs) >= 3 else "MEDIUM"
        else:
            confidence = "LOW"

        if context_text and cited_docs:
            # Determine tier from doc IDs — if any come from VS they're user docs
            source_tier = "user_docs"
        elif context_text:
            source_tier = "regulatory"
        else:
            source_tier = "inferred"

        return {
            "sections": sections,
            "attorney_review": attorney_review,
            "cited_docs": cited_docs,
            "raw_answer": raw_answer,
            "query": req.query,
            "confidence": confidence,
            "source_tier": source_tier,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Clean Processing State ────────────────────────────────────────────────────

@router.post("/clean-processing-state")
async def clean_processing_state(domain_id: str = "supply_chain", delete_job_runs: bool = True):
    """
    Deletes all processed document data for the given domain so the pipeline
    can start from a clean state.

    DELETES: parsed_documents, extracted_fields, document_chunks, entities,
             relationships, file_processing_log rows, and job run history.
    PRESERVES: doc_type_schemas, domain_configs, processing_configs,
               copilot_prompts, action_log, and job definitions.
    """
    _d = _get_domain_schemas(domain_id)
    raw = _d["schema_raw"]
    ont = _d.get("schema_ont", "ontology")

    results: dict = {"deleted": [], "errors": [], "job_runs_deleted": 0}

    tables_to_clear = [
        (f"{CATALOG}.{raw}.parsed_documents",  f"DELETE FROM {CATALOG}.{raw}.parsed_documents"),
        (f"{CATALOG}.{raw}.extracted_fields",  f"DELETE FROM {CATALOG}.{raw}.extracted_fields"),
        (f"{CATALOG}.{raw}.document_chunks",   f"DELETE FROM {CATALOG}.{raw}.document_chunks"),
        (f"{CATALOG}.{ont}.entities",          f"DELETE FROM {CATALOG}.{ont}.entities"),
        (f"{CATALOG}.{ont}.relationships",     f"DELETE FROM {CATALOG}.{ont}.relationships"),
    ]

    for label, sql in tables_to_clear:
        try:
            run_sql(sql)
            results["deleted"].append(label)
        except Exception as exc:
            err = str(exc)
            if "TABLE_OR_VIEW_NOT_FOUND" in err or "does not exist" in err.lower():
                results["deleted"].append(f"{label} (skipped — not found)")
            else:
                results["errors"].append(f"{label}: {err}")

    # file_processing_log — domain-scoped
    try:
        run_sql(f"DELETE FROM {CATALOG}.platform.file_processing_log WHERE domain_id = '{domain_id}'")
        results["deleted"].append(f"{CATALOG}.platform.file_processing_log (domain={domain_id})")
    except Exception as exc:
        err = str(exc)
        if "TABLE_OR_VIEW_NOT_FOUND" in err or "does not exist" in err.lower():
            results["deleted"].append("platform.file_processing_log (skipped — not found)")
        else:
            results["errors"].append(f"file_processing_log: {err}")

    # Job run history
    if delete_job_runs:
        try:
            w = _get_ws_client()
            j_id, j_name = _resolve_pipeline_job(domain_id, _d)
            deleted_runs = 0
            for run in w.jobs.list_runs(job_id=j_id, limit=100):
                try:
                    w.jobs.delete_run(run_id=run.run_id)
                    deleted_runs += 1
                except Exception:
                    pass
            results["job_runs_deleted"] = deleted_runs
            results["deleted"].append(f"Job '{j_name}' — {deleted_runs} run(s) deleted")
        except Exception as exc:
            results["errors"].append(f"job_runs: {str(exc)}")

    return {
        "status": "ok" if not results["errors"] else "partial",
        "domain_id": domain_id,
        "deleted": results["deleted"],
        "errors": results["errors"],
        "job_runs_deleted": results["job_runs_deleted"],
    }

# ── Correspondence Digest ─────────────────────────────────────────────────────

@router.get("/correspondence-digest")
async def correspondence_digest(domain_id: str = "supply_chain"):
    """
    Returns a structured digest of correspondence and action items extracted
    from email threads, regulatory correspondence, and violation notices.

    Each row includes: doc_id, filename, doc_type, jurisdiction, assigned_owner,
    deadline, risk_level, statute_number, status (derived from deadline vs today).
    """
    _d = _get_domain_schemas(domain_id)
    raw = _d["schema_raw"]
    try:
        import datetime as _dt
        today_str = _dt.date.today().isoformat()

        rows = run_sql(f"""
            SELECT
                ef.doc_id,
                COALESCE(pd.filename, ef.doc_id)   AS filename,
                COALESCE(pd.doc_type, 'unknown')   AS doc_type,
                MAX(CASE WHEN ef.field_name = 'jurisdiction'     THEN ef.field_value END) AS jurisdiction,
                MAX(CASE WHEN ef.field_name = 'assigned_owner'   THEN ef.field_value END) AS assigned_owner,
                MAX(CASE WHEN ef.field_name = 'deadline'         THEN ef.field_value END) AS deadline,
                MAX(CASE WHEN ef.field_name = 'risk_level'       THEN ef.field_value END) AS risk_level,
                MAX(CASE WHEN ef.field_name = 'statute_number'   THEN ef.field_value END) AS statute_number,
                CAST(pd.processed_ts AS STRING)    AS processed_ts
            FROM {CATALOG}.{raw}.extracted_fields ef
            JOIN {CATALOG}.{raw}.parsed_documents pd ON pd.doc_id = ef.doc_id
            WHERE pd.doc_type IN ('email_thread', 'regulatory_correspondence',
                                  'violation_notice', 'corrective_action_plan',
                                  'inspection_report', 'regulatory_change')
            GROUP BY ef.doc_id, pd.filename, pd.doc_type, pd.processed_ts
            ORDER BY deadline ASC NULLS LAST
            LIMIT 200
        """) or []

        # Clean raw field values (unwrap {"value":...}) and derive status from deadline
        _RISK_LEVELS = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
        for row in rows:
            for _f in ("jurisdiction", "assigned_owner", "deadline", "statute_number"):
                row[_f] = _unwrap_value(row.get(_f))
            _rl = _unwrap_value(row.get("risk_level"))
            _rl = _rl.strip().upper() if _rl else None
            row["risk_level"] = _rl if _rl in _RISK_LEVELS else None
            dl = row.get("deadline") or ""
            if not dl:
                row["status"] = "NO_DEADLINE"
            else:
                try:
                    import re as _re
                    # Extract YYYY-MM-DD from various formats
                    m = _re.search(r'(\d{4}-\d{2}-\d{2})', dl)
                    if m:
                        dl_date = _dt.date.fromisoformat(m.group(1))
                        days_left = (dl_date - _dt.date.today()).days
                        if days_left < 0:
                            row["status"] = "OVERDUE"
                        elif days_left <= 7:
                            row["status"] = "DUE_SOON"
                        else:
                            row["status"] = "OPEN"
                    else:
                        row["status"] = "OPEN"
                except Exception:
                    row["status"] = "OPEN"

        return {"items": rows, "total": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Jurisdiction Compliance Map ───────────────────────────────────────────────

@router.get("/jurisdiction-map")
async def jurisdiction_map(domain_id: str = "supply_chain"):
    """
    Jurisdiction × requirement/license-type coverage matrix. Shows, per municipality,
    which license/requirement types have been researched/covered vs. gaps.

    Real cells come from parsed docs (extracted municipality + doc_type) and the
    document_sources provenance table.  For the store-development demo the grid is
    then completed with a deterministic synthetic overlay so the matrix reads as a
    real coverage picture (covered / in-progress / gap) across the demo regions.
    """
    _d = _get_domain_schemas(domain_id)
    raw = _d["schema_raw"]

    # Non-CDD domains keep the ORIGINAL generic jurisdiction × doc_type matrix.
    # The demo coverage-matrix overlay below is specific to compliance_due_diligence.
    if domain_id != "compliance_due_diligence":
        try:
            rows = run_sql(f"""
                SELECT
                    ef.doc_id,
                    COALESCE(pd.filename, ef.doc_id)          AS filename,
                    COALESCE(pd.doc_type, 'unknown')          AS doc_type,
                    MAX(CASE WHEN ef.field_name = 'jurisdiction'     THEN ef.field_value END) AS jurisdiction,
                    MAX(CASE WHEN ef.field_name = 'risk_level'       THEN ef.field_value END) AS risk_level,
                    MAX(CASE WHEN ef.field_name = 'deadline'         THEN ef.field_value END) AS deadline,
                    MAX(CASE WHEN ef.field_name = 'statute_number'   THEN ef.field_value END) AS statute_number,
                    MAX(CASE WHEN ef.field_name = 'enforcement_authority' THEN ef.field_value END) AS enforcement_authority
                FROM {CATALOG}.{raw}.extracted_fields ef
                JOIN {CATALOG}.{raw}.parsed_documents pd ON pd.doc_id = ef.doc_id
                GROUP BY ef.doc_id, pd.filename, pd.doc_type
            """) or []
            matrix: dict = {}
            jurisdictions: set = set()
            topics: set = set()
            for row in rows:
                j = (row.get("jurisdiction") or "").strip()
                t = (row.get("doc_type") or "unknown").strip()
                if not j or j.lower() in ("", "none", "null", "n/a"):
                    continue
                jurisdictions.add(j); topics.add(t)
                matrix.setdefault(j, {})
                cell = matrix[j].setdefault(t, {"count": 0, "risk_levels": [], "has_open": False, "docs": []})
                cell["count"] += 1
                rl = (row.get("risk_level") or "").upper()
                if rl:
                    cell["risk_levels"].append(rl)
                if rl in ("CRITICAL", "HIGH"):
                    cell["has_open"] = True
                cell["docs"].append({
                    "doc_id": row.get("doc_id", ""), "filename": row.get("filename", ""),
                    "risk_level": rl, "statute_number": row.get("statute_number", ""),
                    "enforcement_authority": row.get("enforcement_authority", ""),
                })
            total_cells = sum(len(v) for v in matrix.values())
            cells_with_issues = sum(1 for j in matrix for t in matrix[j] if matrix[j][t]["has_open"])
            return {
                "jurisdictions": sorted(jurisdictions),
                "topics": sorted(topics),
                "matrix": matrix,
                "total_docs_with_jurisdiction": len(rows),
                "total_cells": total_cells,
                "cells_with_issues": cells_with_issues,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── compliance_due_diligence coverage matrix (demo) ──────────────────────
    # requirement/license topics that make up a coverage matrix (not correspondence)
    REQUIREMENT_TOPICS = [
        "alcohol_license", "tobacco_license", "business_license",
        "zoning_document", "permit", "municipal_requirement",
    ]
    try:
        # 1. Real coverage from extracted fields (municipality/county, JSON-parsed) + doc_type
        rows = run_sql(f"""
            SELECT
                ef.doc_id,
                COALESCE(pd.filename, ef.doc_id)          AS filename,
                COALESCE(pd.doc_type, 'unknown')          AS doc_type,
                MAX(CASE WHEN ef.field_name = 'municipality' THEN CASE WHEN CAST(ef.field_value AS STRING) LIKE '{{%' THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') ELSE CAST(ef.field_value AS STRING) END END) AS municipality,
                MAX(CASE WHEN ef.field_name = 'county'       THEN CASE WHEN CAST(ef.field_value AS STRING) LIKE '{{%' THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') ELSE CAST(ef.field_value AS STRING) END END) AS county,
                MAX(CASE WHEN ef.field_name = 'risk_level'   THEN CASE WHEN CAST(ef.field_value AS STRING) LIKE '{{%' THEN GET_JSON_OBJECT(CAST(ef.field_value AS STRING),'$.value') ELSE CAST(ef.field_value AS STRING) END END) AS risk_level
            FROM {CATALOG}.{raw}.extracted_fields ef
            JOIN {CATALOG}.{raw}.parsed_documents pd ON pd.doc_id = ef.doc_id
            GROUP BY ef.doc_id, pd.filename, pd.doc_type
        """) or []

        # 2. Provenance coverage (multi-format municipal docs)
        prov = []
        try:
            prov = run_sql(f"""
                SELECT filename, jurisdiction, doc_type, source_url FROM {CATALOG}.{raw}.document_sources
            """) or []
        except Exception:
            prov = []

        matrix: dict = {}
        jurisdictions: set = set()
        topics: set = set()

        def _cell(j, t):
            jurisdictions.add(j); topics.add(t)
            matrix.setdefault(j, {})
            return matrix[j].setdefault(t, {"count": 0, "risk_levels": [], "has_open": False,
                                            "status": "gap", "synthetic": False, "docs": []})

        # Canonical demo jurisdictions — collapse label variants (city/county/state) into one.
        def _norm_juris(muni, county):
            v = (muni or county or "").strip()
            if not v or v.lower() in ("none", "null", "n/a") or v.startswith("{"):
                return ""
            lo = v.lower()
            if "tampa" in lo or "hillsborough" in lo:
                return "Tampa / Hillsborough Co., FL"
            if "dallas" in lo:
                return "Dallas, TX"
            if "atlanta" in lo or "fulton" in lo:
                return "Atlanta / Fulton Co., GA"
            return ""  # outside the demo-region scope

        for row in rows:
            t = (row.get("doc_type") or "unknown").strip()
            j = _norm_juris(row.get("municipality"), row.get("county"))
            if not j:
                continue
            cell = _cell(j, t)
            cell["count"] += 1
            cell["status"] = "covered"
            rl = (row.get("risk_level") or "").upper()
            if rl:
                cell["risk_levels"].append(rl)
            if rl in ("CRITICAL", "HIGH"):
                cell["has_open"] = True
                cell["status"] = "issues"
            cell["docs"].append({
                "doc_id": row.get("doc_id", ""), "filename": row.get("filename", ""),
                "risk_level": rl, "statute_number": "", "enforcement_authority": "",
            })

        for row in prov:
            j = _norm_juris(row.get("jurisdiction"), "")
            t = (row.get("doc_type") or "unknown").strip()
            if not j:
                continue
            fn = row.get("filename", "")
            cell = _cell(j, t)
            if fn and any(d.get("filename") == fn for d in cell["docs"]):
                continue  # same doc already counted from extracted rows — avoid double-count
            cell["count"] += 1
            cell["status"] = "covered" if not cell["has_open"] else "issues"
            # For these multi-format docs the doc_id equals the filename, so the
            # source chip in the UI can open the document.
            _fn = row.get("filename") or ""
            cell["docs"].append({"doc_id": _fn, "filename": _fn,
                                 "risk_level": "", "statute_number": "", "enforcement_authority": "",
                                 "source_url": row.get("source_url")})

        # 3. Demo synthetic overlay — complete the grid across demo regions × requirement topics
        DEMO_JURISDICTIONS = ["Tampa / Hillsborough Co., FL", "Dallas, TX", "Atlanta / Fulton Co., GA"]
        for j in list(jurisdictions) + DEMO_JURISDICTIONS:
            jurisdictions.add(j)
        for t in REQUIREMENT_TOPICS:
            topics.add(t)
        # deterministic in-progress/gap fill so the matrix is complete and realistic
        import hashlib
        for j in sorted(jurisdictions):
            for t in REQUIREMENT_TOPICS:
                existing = matrix.get(j, {}).get(t)
                if existing and existing["count"] > 0:
                    continue
                h = int(hashlib.md5(f"{j}:{t}".encode()).hexdigest(), 16) % 10
                cell = _cell(j, t)
                if h < 6:
                    cell["status"] = "covered"; cell["synthetic"] = True; cell["count"] = 1
                elif h < 8:
                    cell["status"] = "in_progress"; cell["synthetic"] = True
                else:
                    cell["status"] = "gap"; cell["synthetic"] = True

        total_cells = sum(len(v) for v in matrix.values())
        cells_with_issues = sum(1 for j in matrix for t in matrix[j] if matrix[j][t]["has_open"])
        cells_gap = sum(1 for j in matrix for t in matrix[j] if matrix[j][t]["status"] == "gap")
        show_topics = [t for t in REQUIREMENT_TOPICS if t in topics]
        return {
            "jurisdictions": sorted(jurisdictions),
            "topics": show_topics,
            "matrix": matrix,
            "total_docs_with_jurisdiction": len(rows),
            "total_cells": total_cells,
            "cells_with_issues": cells_with_issues,
            "cells_gap": cells_gap,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Attorney Review Queue ─────────────────────────────────────────────────────

_attorney_queue_checked: bool = False

def _ensure_attorney_queue_table():
    global _attorney_queue_checked
    if _attorney_queue_checked:
        return
    try:
        run_sql(f"""
            CREATE TABLE IF NOT EXISTS {CATALOG}.platform.attorney_review_queue (
                id            STRING NOT NULL,
                domain_id     STRING,
                query         STRING,
                response_summary STRING,
                flagged_reason   STRING,
                flagged_at    TIMESTAMP,
                status        STRING,
                reviewed_by   STRING,
                reviewed_at   TIMESTAMP
            ) USING DELTA
        """, timeout_secs=30)
        _attorney_queue_checked = True
    except Exception:
        _attorney_queue_checked = True  # don't keep retrying on persistent failures


class AttorneyQueueLogRequest(BaseModel):
    domain_id: str
    query: str
    response_summary: Optional[str] = None
    flagged_reason: Optional[str] = None


class AttorneyQueueUpdateRequest(BaseModel):
    status: str        # PENDING | CLEARED | ESCALATED
    reviewed_by: Optional[str] = None


@router.get("/attorney-review-queue")
async def get_attorney_review_queue(domain_id: str = "supply_chain"):
    _ensure_attorney_queue_table()
    try:
        rows = run_sql(f"""
            SELECT id, domain_id, query, response_summary, flagged_reason,
                   CAST(flagged_at AS STRING) AS flagged_at,
                   status, reviewed_by,
                   CAST(reviewed_at AS STRING) AS reviewed_at
            FROM {CATALOG}.platform.attorney_review_queue
            WHERE domain_id = '{domain_id}'
            ORDER BY flagged_at DESC
            LIMIT 200
        """) or []
        pending = sum(1 for r in rows if r.get("status") == "PENDING")
        # Check when the table was last populated
        meta = run_sql(f"""
            SELECT CAST(MAX(flagged_at) AS STRING) AS last_populated,
                   COUNT(*) AS total_ever
            FROM {CATALOG}.platform.attorney_review_queue
        """, timeout_secs=20) or []
        last_pop = meta[0].get("last_populated") if meta else None
        return {
            "items": rows,
            "total": len(rows),
            "pending_count": pending,
            "table_exists": True,
            "last_populated": last_pop,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/attorney-review-queue")
async def log_attorney_review(req: AttorneyQueueLogRequest):
    _ensure_attorney_queue_table()
    try:
        import uuid as _uuid
        item_id = str(_uuid.uuid4())
        query_esc   = req.query[:500].replace("'", "\\'")
        summary_esc = (req.response_summary or "")[:1000].replace("'", "\\'")
        reason_esc  = (req.flagged_reason or "Attorney review flagged by AI")[:500].replace("'", "\\'")
        domain_esc  = req.domain_id.replace("'", "\\'")
        run_sql(f"""
            INSERT INTO {CATALOG}.platform.attorney_review_queue
                (id, domain_id, query, response_summary, flagged_reason, flagged_at, status)
            VALUES
                ('{item_id}', '{domain_esc}', '{query_esc}', '{summary_esc}',
                 '{reason_esc}', current_timestamp(), 'PENDING')
        """, timeout_secs=20)
        return {"ok": True, "id": item_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/attorney-review-queue/{item_id}")
async def update_attorney_review(item_id: str, req: AttorneyQueueUpdateRequest):
    _ensure_attorney_queue_table()
    try:
        valid_statuses = {"PENDING", "CLEARED", "ESCALATED"}
        status = req.status.upper()
        if status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status: {req.status}")
        reviewer_esc = (req.reviewed_by or "").replace("'", "\\'")
        run_sql(f"""
            UPDATE {CATALOG}.platform.attorney_review_queue
            SET status = '{status}',
                reviewed_by = CASE WHEN '{reviewer_esc}' != '' THEN '{reviewer_esc}' ELSE reviewed_by END,
                reviewed_at = current_timestamp()
            WHERE id = '{item_id}'
        """, timeout_secs=20)
        return {"ok": True, "id": item_id, "status": status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Escalation Rules Engine ───────────────────────────────────────────────────
# Deterministic rules that turn document/answer signals into escalations. This is
# the DECISION maker for escalation (replacing the previous LLM-substring
# "attorney review recommended" heuristic). An LLM hint, if any, is just one
# optional signal in the context. Backward compatible: with no context signals,
# no rule fires, so existing callers behave exactly as before.

from datetime import date as _date

_escalation_rules_checked = False

# rule_id, rule_type, params, target
_DEFAULT_ESCALATION_RULES = [
    ("low_confidence_default",    "low_confidence",     {"threshold": 0.85}, "attorney_review"),
    ("deadline_risk_default",     "deadline_risk",      {},                  "priority_bump"),
    ("requirement_change_default","requirement_change", {},                  "attorney_review"),
    ("high_value_default",        "high_value",         {},                  "priority_bump"),
]


def _ensure_escalation_rules_table():
    global _escalation_rules_checked
    if _escalation_rules_checked:
        return
    try:
        run_sql(f"""
            CREATE TABLE IF NOT EXISTS {CATALOG}.platform.escalation_rules (
                rule_id    STRING NOT NULL,
                domain_id  STRING,           -- '' or NULL = applies to all domains
                rule_type  STRING,           -- low_confidence | deadline_risk | requirement_change | high_value
                params     STRING,           -- JSON
                target     STRING,           -- attorney_review | priority_bump | notify
                active     BOOLEAN,           -- always written explicitly on insert
                created_at TIMESTAMP
            ) USING DELTA
        """, timeout_secs=30)
        existing = run_sql(
            f"SELECT COUNT(*) AS c FROM {CATALOG}.platform.escalation_rules", timeout_secs=20) or []
        if existing and int(existing[0].get("c", 0) or 0) == 0:
            for rid, rtype, params, target in _DEFAULT_ESCALATION_RULES:
                p = json.dumps(params).replace("'", "\\'")
                run_sql(f"""
                    INSERT INTO {CATALOG}.platform.escalation_rules
                        (rule_id, domain_id, rule_type, params, target, active, created_at)
                    VALUES ('{rid}', '', '{rtype}', '{p}', '{target}', true, current_timestamp())
                """, timeout_secs=20)
        _escalation_rules_checked = True
    except Exception:
        _escalation_rules_checked = True  # don't keep retrying on persistent failures


def _load_escalation_rules(domain_id: str) -> list:
    """Active rules for a domain (plus global rules with empty domain_id)."""
    _ensure_escalation_rules_table()
    dom = (domain_id or "").replace("'", "\\'")
    try:
        rows = run_sql(f"""
            SELECT rule_id, domain_id, rule_type, params, target, active
            FROM {CATALOG}.platform.escalation_rules
            WHERE active = true
              AND (domain_id = '' OR domain_id IS NULL OR domain_id = '{dom}')
        """, timeout_secs=20) or []
        for r in rows:
            try:
                r["params"] = json.loads(r.get("params") or "{}")
            except Exception:
                r["params"] = {}
        return rows
    except Exception:
        # In-memory defaults if the table is unreachable
        return [{"rule_id": rid, "domain_id": "", "rule_type": rtype,
                 "params": params, "target": target, "active": True}
                for rid, rtype, params, target in _DEFAULT_ESCALATION_RULES]


def _apply_escalation_rule(rule: dict, context: dict, today=None):
    """Pure, deterministic evaluation of one rule against a context dict.
    Returns a trigger dict when the rule fires, else None. Unit-testable."""
    today  = today or _date.today()
    rtype  = rule.get("rule_type")
    params = rule.get("params") or {}
    rid    = rule.get("rule_id")
    target = rule.get("target")

    if rtype == "low_confidence":
        conf = context.get("confidence")
        thr  = float(params.get("threshold", 0.85))
        if conf is not None and float(conf) < thr:
            return {"rule_id": rid, "rule_type": rtype, "target": target,
                    "reason": f"Confidence {float(conf):.2f} below threshold {thr:.2f}"}

    elif rtype == "deadline_risk":
        lead      = context.get("license_lead_time_days")
        open_date = context.get("expected_open_date")
        if lead is not None and open_date:
            try:
                od         = _date.fromisoformat(str(open_date)[:10])
                days_until = (od - today).days
                if int(lead) > days_until:
                    return {"rule_id": rid, "rule_type": rtype, "target": target,
                            "reason": (f"License lead time {int(lead)}d exceeds "
                                       f"{days_until}d until open date {od.isoformat()}")}
            except Exception:
                return None

    elif rtype == "requirement_change":
        if context.get("requirement_change"):
            return {"rule_id": rid, "rule_type": rtype, "target": target,
                    "reason": context.get("change_summary")
                              or "Regulatory requirement changed vs prior decision"}

    elif rtype == "high_value":
        if context.get("high_value"):
            return {"rule_id": rid, "rule_type": rtype, "target": target,
                    "reason": "High-value / strategic project"}

    return None


def evaluate_escalations(domain_id: str, context: dict) -> list:
    """Deterministically evaluate all active rules for a domain against a context.
    Returns the list of triggered rule dicts (empty when nothing fires)."""
    triggered = []
    for rule in _load_escalation_rules(domain_id):
        hit = _apply_escalation_rule(rule, context or {})
        if hit:
            triggered.append(hit)
    return triggered


def _queue_attorney_review(domain_id: str, query: str, summary: str, reason: str):
    """Insert a PENDING row into the attorney review queue. Returns id or None."""
    _ensure_attorney_queue_table()
    try:
        import uuid as _uuid
        item_id = str(_uuid.uuid4())
        q = (query or "")[:500].replace("'", "\\'")
        s = (summary or "")[:1000].replace("'", "\\'")
        r = (reason or "")[:500].replace("'", "\\'")
        d = (domain_id or "").replace("'", "\\'")
        run_sql(f"""
            INSERT INTO {CATALOG}.platform.attorney_review_queue
                (id, domain_id, query, response_summary, flagged_reason, flagged_at, status)
            VALUES ('{item_id}', '{d}', '{q}', '{s}', '{r}', current_timestamp(), 'PENDING')
        """, timeout_secs=20)
        return item_id
    except Exception:
        return None


class EscalationRuleUpsertRequest(BaseModel):
    rule_id:   str
    domain_id: str  = ""          # '' = all domains
    rule_type: str                # low_confidence | deadline_risk | requirement_change | high_value
    params:    dict = {}
    target:    str  = "attorney_review"
    active:    bool = True


class EscalationEvaluateRequest(BaseModel):
    domain_id:     str  = "supply_chain"
    context:       dict = {}
    apply_actions: bool = False   # if True, queue attorney reviews for triggered rules
    query:         str  = ""      # optional label for the queued review


@router.get("/escalation-rules")
async def get_escalation_rules(domain_id: str = ""):
    rules = _load_escalation_rules(domain_id)
    return {"rules": rules, "total": len(rules)}


@router.post("/escalation-rules")
async def upsert_escalation_rule(req: EscalationRuleUpsertRequest):
    _ensure_escalation_rules_table()
    try:
        rid    = req.rule_id.replace("'", "\\'")
        dom    = (req.domain_id or "").replace("'", "\\'")
        rtype  = req.rule_type.replace("'", "\\'")
        target = req.target.replace("'", "\\'")
        p      = json.dumps(req.params or {}).replace("'", "\\'")
        run_sql(f"DELETE FROM {CATALOG}.platform.escalation_rules WHERE rule_id = '{rid}'",
                timeout_secs=20)
        run_sql(f"""
            INSERT INTO {CATALOG}.platform.escalation_rules
                (rule_id, domain_id, rule_type, params, target, active, created_at)
            VALUES ('{rid}', '{dom}', '{rtype}', '{p}', '{target}',
                    {str(bool(req.active)).lower()}, current_timestamp())
        """, timeout_secs=20)
        return {"ok": True, "rule_id": req.rule_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/escalation-evaluate")
async def escalation_evaluate(req: EscalationEvaluateRequest):
    """Deterministically evaluate escalation rules for a context (used by
    action-create and change-detection). Optionally queues attorney reviews."""
    triggered = evaluate_escalations(req.domain_id, req.context or {})
    queued = []
    if req.apply_actions:
        for t in triggered:
            if t.get("target") == "attorney_review":
                qid = _queue_attorney_review(
                    req.domain_id, req.query or "escalation", "",
                    t.get("reason") or t.get("rule_type"))
                if qid:
                    queued.append(qid)
    return {"triggered": triggered, "queued_reviews": queued, "domain_id": req.domain_id}


# ── Regulatory Changes Feed ───────────────────────────────────────────────────

@router.get("/regulatory-changes")
async def regulatory_changes(domain_id: str = "supply_chain"):
    """
    Returns regulatory change documents (doc_type = 'regulatory_change') for
    the domain, enriched with extracted structured fields.
    Sorted by effective_date ascending (most imminent first).
    """
    _d = _get_domain_schemas(domain_id)
    raw = _d["schema_raw"]
    try:
        rows = run_sql(f"""
            SELECT
                ef.doc_id,
                COALESCE(pd.filename, ef.doc_id)   AS filename,
                CAST(pd.processed_ts AS STRING)    AS processed_ts,
                MAX(CASE WHEN ef.field_name = 'change_type'          THEN ef.field_value END) AS change_type,
                MAX(CASE WHEN ef.field_name = 'effective_date'       THEN ef.field_value END) AS effective_date,
                MAX(CASE WHEN ef.field_name = 'jurisdiction'         THEN ef.field_value END) AS jurisdiction,
                MAX(CASE WHEN ef.field_name = 'statute_number'       THEN ef.field_value END) AS statute_number,
                MAX(CASE WHEN ef.field_name = 'enforcement_authority' THEN ef.field_value END) AS enforcement_authority,
                MAX(CASE WHEN ef.field_name = 'risk_level'           THEN ef.field_value END) AS risk_level,
                MAX(CASE WHEN ef.field_name = 'confidence_level'     THEN ef.field_value END) AS confidence_level
            FROM {CATALOG}.{raw}.extracted_fields ef
            JOIN {CATALOG}.{raw}.parsed_documents pd ON pd.doc_id = ef.doc_id
            WHERE pd.doc_type = 'regulatory_change'
            GROUP BY ef.doc_id, pd.filename, pd.processed_ts
            ORDER BY effective_date ASC NULLS LAST
            LIMIT 100
        """) or []

        # Annotate with days_until for UI urgency coloring
        import datetime as _dt
        import re as _re
        for row in rows:
            ed = row.get("effective_date") or ""
            m = _re.search(r'(\d{4}-\d{2}-\d{2})', ed)
            if m:
                try:
                    days = (_dt.date.fromisoformat(m.group(1)) - _dt.date.today()).days
                    row["days_until"] = days
                except Exception:
                    row["days_until"] = None
            else:
                row["days_until"] = None

        # Attach the authoritative municipal/gov source URL (provenance) — best-effort.
        # document_sources only exists for compliance_due_diligence, so guard by domain.
        if domain_id == "compliance_due_diligence":
            try:
                src = run_sql(f"SELECT filename, source_url FROM {CATALOG}.{raw}.document_sources", timeout_secs=15) or []
                url_map = {s["filename"]: s.get("source_url") for s in src if s.get("filename")}
                for row in rows:
                    row["source_url"] = url_map.get(row.get("filename"))
            except Exception:
                for row in rows:
                    row.setdefault("source_url", None)
        else:
            for row in rows:
                row.setdefault("source_url", None)

        return {"changes": rows, "total": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _parse_val_sql(col: str) -> str:
    """SQL snippet: JSON-parse a field_value ({"value":..}) else raw string."""
    c = f"CAST({col} AS STRING)"
    return f"CASE WHEN {c} LIKE '{{%' THEN GET_JSON_OBJECT({c},'$.value') ELSE {c} END"


@router.get("/compliance-tracker")
async def compliance_tracker(domain_id: str = "compliance_due_diligence"):
    """
    Shared compliance tracker (the "Smartsheet replacement"): one row per
    feasibility project/store — municipality, request type, status/owner/due
    (from action_master), last response, and whether a regulatory change was
    detected for that municipality.
    """
    if domain_id != "compliance_due_diligence":
        raise HTTPException(status_code=404, detail="Compliance tracker is available only for compliance_due_diligence.")
    _d = _get_domain_schemas(domain_id)
    raw = _d["schema_raw"]
    try:
        pv_store = _parse_val_sql("CASE WHEN field_name='store_number' THEN field_value END")
        pv_proj  = _parse_val_sql("CASE WHEN field_name='project_id' THEN field_value END")
        pv_muni  = _parse_val_sql("CASE WHEN field_name='municipality' THEN field_value END")
        pv_cnty  = _parse_val_sql("CASE WHEN field_name='county' THEN field_value END")
        pv_state = _parse_val_sql("CASE WHEN field_name='state' THEN field_value END")
        pv_rtype = _parse_val_sql("CASE WHEN field_name='request_type' THEN field_value END")
        pv_reqty = _parse_val_sql("CASE WHEN field_name='requirement_type' THEN field_value END")
        pv_resp  = _parse_val_sql("CASE WHEN field_name='responder' THEN field_value END")
        pv_rdate = _parse_val_sql("CASE WHEN field_name='response_date' THEN field_value END")
        pv_lead  = _parse_val_sql("CASE WHEN field_name='lead_time' THEN field_value END")
        rows = run_sql(f"""
            WITH ef AS (
                SELECT doc_id,
                    MAX({pv_store}) AS store_number,
                    MAX({pv_proj})  AS project_id,
                    MAX({pv_muni})  AS municipality,
                    MAX({pv_cnty})  AS county,
                    MAX({pv_state}) AS state,
                    MAX({pv_rtype}) AS request_type,
                    MAX({pv_reqty}) AS requirement_type,
                    MAX({pv_resp})  AS responder,
                    MAX({pv_rdate}) AS response_date,
                    MAX({pv_lead})  AS lead_time
                FROM {CATALOG}.{raw}.extracted_fields GROUP BY doc_id
            )
            SELECT pd.doc_id, pd.filename, pd.doc_type,
                   ef.store_number, ef.project_id, ef.municipality, ef.county, ef.state,
                   ef.request_type, ef.requirement_type, ef.responder, ef.response_date, ef.lead_time
            FROM {CATALOG}.{raw}.parsed_documents pd
            JOIN ef ON pd.doc_id = ef.doc_id
            WHERE pd.doc_type IN ('feasibility_request','historical_response')
        """, timeout_secs=40) or []

        # municipalities with a detected regulatory change
        changed = set()
        try:
            crows = run_sql(f"""
                SELECT DISTINCT {_parse_val_sql("ef.field_value")} AS muni
                FROM {CATALOG}.{raw}.extracted_fields ef
                JOIN {CATALOG}.{raw}.parsed_documents pd ON pd.doc_id = ef.doc_id
                WHERE pd.doc_type = 'regulatory_change' AND ef.field_name IN ('municipality','jurisdiction')
            """, timeout_secs=20) or []
            changed = {(_c.get("muni") or "").strip().lower() for _c in crows if _c.get("muni")}
        except Exception:
            pass

        # action_master rows (status/owner/due) keyed by doc_id
        act_by_doc: dict = {}
        try:
            arows = run_sql(f"""
                SELECT source_doc_ids, status, owner, due_date
                FROM {CATALOG}.platform.action_master
                WHERE domain_id = '{domain_id}'
            """, timeout_secs=20) or []
            for a in arows:
                for did in str(a.get("source_doc_ids") or "").replace("[","").replace("]","").replace('"',"").split(","):
                    did = did.strip()
                    if did:
                        act_by_doc[did] = a
        except Exception:
            pass

        # Build tracker rows, keyed by (project/store + municipality)
        tracker: dict = {}
        for r in rows:
            proj = (r.get("store_number") or r.get("project_id") or "").strip()
            muni = (r.get("municipality") or r.get("county") or "").strip()   # fall back to county
            if not proj and not muni:
                continue
            key = f"{proj}|{muni}".lower()
            row = tracker.get(key)
            if not row:
                _st = (r.get("state") or "").strip()
                muni_disp = f"{muni}, {_st}" if (muni and _st) else (muni or "—")
                _ml = muni.lower()
                changed_hit = bool(_ml) and any(c and (c in _ml or _ml in c) for c in changed)
                row = {
                    "project": proj or "—",
                    "municipality": muni_disp,
                    "request_type": None, "status": "Open", "owner": None, "due_date": None,
                    "last_response": None, "change_detected": changed_hit,
                    "doc_id": r.get("doc_id"), "filename": r.get("filename"),
                }
                tracker[key] = row
            rt = r.get("request_type") or r.get("requirement_type")
            if rt and not row["request_type"]:
                row["request_type"] = rt
            if r.get("doc_type") == "feasibility_request":
                row["doc_id"] = r.get("doc_id"); row["filename"] = r.get("filename")
            if r.get("doc_type") == "historical_response" and (r.get("responder") or r.get("response_date")):
                lr = " · ".join([x for x in [r.get("responder"), r.get("response_date")] if x])
                if lr:
                    row["last_response"] = lr
            a = act_by_doc.get(r.get("doc_id"))
            if a:
                row["status"] = a.get("status") or row["status"]
                row["owner"]  = a.get("owner") or row["owner"]
                row["due_date"] = str(a.get("due_date")) if a.get("due_date") else row["due_date"]

        out = sorted(tracker.values(), key=lambda x: (not x["change_detected"], x["project"]))
        return {"rows": out, "total": len(out),
                "changed_count": sum(1 for x in out if x["change_detected"])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class DraftReplyRequest(BaseModel):
    domain_id: str = "compliance_due_diligence"
    doc_id: str


@router.post("/generate-draft-reply")
async def generate_draft_reply(req: DraftReplyRequest):
    """
    Generate a ready-to-send draft email reply to a feasibility request, grounded
    in the municipality's requirements (Vector Search + extracted fields) and any
    prior response. Returns {draft, sources}.
    """
    if req.domain_id != "compliance_due_diligence":
        raise HTTPException(status_code=404, detail="Draft reply is available only for compliance_due_diligence.")
    _d = _get_domain_schemas(req.domain_id)
    raw = _d["schema_raw"]; vec = _d["schema_vec"]
    _doc_id = (req.doc_id or "").replace("'", "''")   # escape for the SQL literal below
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        # 1. The request text
        rows = run_sql(f"""
            SELECT SUBSTRING(CAST(parsed_content AS STRING), 1, 4000) AS body, filename, doc_type
            FROM {CATALOG}.{raw}.parsed_documents WHERE doc_id = '{_doc_id}' LIMIT 1
        """, timeout_secs=20) or []
        if not rows:
            raise HTTPException(status_code=404, detail=f"Document '{req.doc_id}' not found.")
        request_text = rows[0].get("body") or ""

        # 2. Retrieve municipality requirements via Vector Search (best-effort)
        context_text = ""; sources: list = []
        try:
            from databricks.vector_search.client import VectorSearchClient
            vsc = VectorSearchClient()
            index = vsc.get_index(VS_ENDPOINT, f"{CATALOG}.{vec}.{req.domain_id}_docs_index")
            res = index.similarity_search(
                query_text=request_text[:800],
                columns=["doc_id", "doc_type", "chunk_to_retrieve"], num_results=6)
            for r in res.get("result", {}).get("data_array", []):
                did = r[0] if len(r) > 0 else ""
                context_text += f"\n\n[{r[1] if len(r)>1 else ''} · {did}]\n{r[2] if len(r)>2 else ''}"
                if did and did not in [s['doc_id'] for s in sources]:
                    sources.append({"doc_id": did, "filename": did})
        except Exception:
            pass

        # 2b. Deterministic SQL grounding — pull THIS municipality's requirement/license/
        #     change docs directly (filenames encode the city), so the draft is grounded
        #     and cited even when Vector Search misses on this small corpus.
        try:
            mrow = run_sql(f"""
                SELECT {_parse_val_sql("field_value")} AS v
                FROM {CATALOG}.{raw}.extracted_fields
                WHERE doc_id = '{_doc_id}' AND field_name = 'municipality' LIMIT 1
            """, timeout_secs=15) or []
            muni = ((mrow[0].get("v") if mrow else "") or "").lower()
            token = next((t for t in ["dallas", "hillsborough", "tampa", "atlanta", "fulton"] if t in muni), "")
            if token:
                docs = run_sql(f"""
                    SELECT DISTINCT pd.doc_id, pd.filename, pd.doc_type,
                           SUBSTRING(CAST(pd.parsed_content AS STRING), 1, 700) AS body
                    FROM {CATALOG}.{raw}.parsed_documents pd
                    WHERE pd.doc_type IN ('municipal_requirement','alcohol_license','tobacco_license',
                          'business_license','zoning_document','regulatory_change','permit','historical_response')
                      AND LOWER(pd.filename) LIKE '%{token}%'
                    LIMIT 6
                """, timeout_secs=20) or []
                for d in docs:
                    fn = d.get("filename", "")
                    context_text += f"\n\n[{d.get('doc_type','')} · {fn}]\n{d.get('body','')}"
                    if fn and fn not in [s["filename"] for s in sources]:
                        sources.append({"doc_id": d.get("doc_id", ""), "filename": fn})
        except Exception:
            pass

        # 2c. Project-scoped grounding (Phase 2) — the CURATED docs tagged to this
        #     request's project (∪ Universal), so the reply uses exactly the docs the
        #     team associated with the project (not just filename heuristics).
        try:
            _didq = req.domain_id.replace("'", "''")
            _prow = run_sql(f"""
                SELECT to_json(sort_array(collect_set(project_id))) AS projects
                FROM {CATALOG}.platform.document_project_tags
                WHERE domain_id='{_didq}' AND doc_id='{_doc_id}'
                  AND scope='project' AND project_id IS NOT NULL
            """, timeout_secs=15) or []
            import json as _jt2
            try:
                _projs = [str(x) for x in _jt2.loads((_prow[0].get("projects") if _prow else None) or "[]")]
            except Exception:
                _projs = []
            if _projs:
                # union the curated docs across ALL of the request's projects (∪ Universal)
                _pset: set = set()
                for _proj in _projs:
                    _pset.update(_project_doc_ids(req.domain_id, _proj))
                _pdocs = sorted(d for d in _pset if d and d != req.doc_id)   # deterministic
                _plabel = "/".join(_projs)
                if _pdocs:
                    _in = ", ".join("'" + str(d).replace("'", "''") + "'" for d in _pdocs[:8])
                    for d in (run_sql(f"""
                        SELECT DISTINCT pd.doc_id, pd.filename, pd.doc_type,
                               SUBSTRING(CAST(pd.parsed_content AS STRING), 1, 700) AS body
                        FROM {CATALOG}.{raw}.parsed_documents pd
                        WHERE pd.doc_id IN ({_in}) LIMIT 8
                    """, timeout_secs=20) or []):
                        fn = d.get("filename", "")
                        context_text += f"\n\n[project {_plabel} · {d.get('doc_type','')} · {fn}]\n{d.get('body','')}"
                        if fn and fn not in [s["filename"] for s in sources]:
                            sources.append({"doc_id": d.get("doc_id", ""), "filename": fn})
        except Exception:
            pass

        # 3. Attach source URLs (provenance)
        try:
            src = run_sql(f"SELECT filename, source_url FROM {CATALOG}.{raw}.document_sources", timeout_secs=15) or []
            umap = {s["filename"]: s.get("source_url") for s in src if s.get("filename")}
            for s in sources:
                s["source_url"] = umap.get(s["filename"])
        except Exception:
            pass

        # 4. Draft the reply
        llm, _m = _get_llm(max_tokens=1400)
        system = (
            "You are a store-development compliance analyst. Draft a professional, ready-to-send "
            "EMAIL REPLY to the feasibility/due-diligence request below. Answer the specific questions "
            "(alcohol/tobacco/business licensing, zoning, distance restrictions, lead times) using ONLY "
            "the provided requirement excerpts; where the excerpts are silent, say what still needs to be "
            "confirmed. Keep it concise and business-appropriate: greeting, a short summary answer, a "
            "bulleted requirements/next-steps list with lead times, and a sign-off. End with a 'Sources:' "
            "line listing the document names used. Do not invent regulations."
        )
        human = f"FEASIBILITY REQUEST:\n{request_text}\n\nREQUIREMENT EXCERPTS:{context_text or ' (none retrieved)'}"
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
        return {"draft": resp.content.strip(), "sources": sources, "doc_id": req.doc_id}
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# Compliance Due Diligence (Store Development) — agent tools + change detection
# ═══════════════════════════════════════════════════════════════════════════════
#
# domain_id = "compliance_due_diligence" is DISTINCT from the operational
# "compliance" (RaceTrac) domain. Everything below is additive and gated on this
# domain_id, so supply_chain / compliance behavior is untouched.
#
# The four "agents" from the flagship build are exposed as LangChain tools that
# agent_query consumes for this domain:
#   1. Intake    — classify a feasibility request  (ai_classify + ai_extract)
#   2. Research  — municipality requirements/licenses (Vector Search + DEFINES edges)
#   3. History   — "have we handled this municipality before?" (VS + prior Responses)
#   4. Action    — create/track an action (reuses lifecycle + escalation engine)
#   + Change detection — detect_regulatory_change(municipality, requirement_type)

CDD_DOMAIN_ID = "compliance_due_diligence"


def _sql_lit(s, max_len: int = 8000) -> str:
    """Escape + cap a value for safe inline use in a single-quoted SQL literal."""
    return str(s or "")[:max_len].replace("\\", "\\\\").replace("'", "\\'")


def _unwrap_expr(col: str = "field_value") -> str:
    """SQL expression that unwraps a `{"value": X}` ai_extract wrapper to a plain
    string (mirrors the pattern used by the UC-function tools in 06_agent.py)."""
    return (
        f"CASE WHEN {col} LIKE '{{\"value\":%' "
        f"THEN GET_JSON_OBJECT(CAST({col} AS STRING), '$.value') "
        f"ELSE CAST({col} AS STRING) END"
    )


def _cdd_classification_labels(domain_cfg: dict) -> list:
    """Return the classification label list for the domain (dict keys or list)."""
    raw = domain_cfg.get("classification_labels")
    labels: list = []
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                labels = list(parsed.keys())
            elif isinstance(parsed, list):
                labels = [str(x) for x in parsed]
        except Exception:
            labels = []
    if not labels:
        labels = [
            "feasibility_request", "municipal_requirement", "alcohol_license",
            "tobacco_license", "business_license", "zoning_document", "permit",
            "historical_response", "regulatory_change", "consultant_correspondence",
        ]
    return labels


# ── Agent Tool 1: Intake ──────────────────────────────────────────────────────
def _cdd_intake(domain_id: str, request_text: str) -> dict:
    """Classify a feasibility request and pull the key structured fields.
    Reuses Databricks ai_classify (label routing) + ai_extract (field lift)."""
    dom = _get_domain_schemas(domain_id)
    labels = _cdd_classification_labels(dom)
    txt = _sql_lit(request_text, 6000)
    labels_arr = ", ".join(f"'{_sql_lit(l, 120)}'" for l in labels)
    fields = ["request_type", "project_id", "store_number", "municipality",
              "state", "county", "priority", "requester"]
    fields_arr = ", ".join(f"'{f}'" for f in fields)
    try:
        rows = run_sql(f"""
            SELECT
                ai_classify('{txt}', ARRAY({labels_arr}))                    AS doc_class,
                to_json(ai_extract('{txt}', ARRAY({fields_arr})))            AS extracted
        """, timeout_secs=60) or []
    except Exception as e:
        return {"ok": False, "error": str(e), "request_type": None}
    if not rows:
        return {"ok": False, "error": "no result", "request_type": None}
    doc_class = rows[0].get("doc_class")
    extracted = {}
    try:
        raw = rows[0].get("extracted") or "{}"
        parsed = json.loads(raw)
        for k, v in (parsed.items() if isinstance(parsed, dict) else []):
            extracted[k] = _unwrap_value(v)
    except Exception:
        pass
    return {
        "ok": True,
        "document_class": doc_class,
        "request_type": extracted.get("request_type") or doc_class,
        "project": extracted.get("project_id") or extracted.get("store_number"),
        "store_number": extracted.get("store_number"),
        "municipality": extracted.get("municipality"),
        "state": extracted.get("state"),
        "county": extracted.get("county"),
        "priority": (extracted.get("priority") or "MEDIUM"),
        "requester": extracted.get("requester"),
    }


def _cdd_vs_search(vs_index: str, query: str, doc_type_filter=None, k: int = 6):
    """Vector Search helper → (context_text, cited_docs)."""
    try:
        from databricks.vector_search.client import VectorSearchClient
        vsc = VectorSearchClient()
        index = vsc.get_index(VS_ENDPOINT, vs_index)
        results = index.similarity_search(
            query_text=query,
            columns=["chunk_id", "doc_id", "doc_type", "chunk_to_retrieve"],
            filters={"doc_type": doc_type_filter} if doc_type_filter else None,
            num_results=k,
        )
        data = results.get("result", {}).get("data_array", [])
        cited, chunks = [], []
        for r in data:
            if len(r) < 4:
                continue
            doc_id = r[1]
            if doc_id not in cited:
                cited.append(doc_id)
            chunks.append(f"[Source: {r[1]} | Type: {r[2]}]\n{r[3]}")
        return "\n\n---\n\n".join(chunks), cited
    except Exception:
        return "", []


# ── Agent Tool 2: Research ────────────────────────────────────────────────────
def _cdd_research(domain_id: str, municipality: str, requirement_type: str = "",
                  vs_index: str = None) -> dict:
    """Retrieve municipality requirements/licenses via Vector Search over the
    domain index, enriched with the ontology `Municipality DEFINES ...` edges."""
    dom = _get_domain_schemas(domain_id)
    raw = dom["schema_raw"]
    ont = dom.get("schema_ont") or raw
    vs_index = vs_index or f"{CATALOG}.{dom.get('schema_vec', 'vectors')}.{domain_id}_docs_index"
    query = f"requirements and licenses to open a store in {municipality} {requirement_type}".strip()
    context_text, cited = _cdd_vs_search(vs_index, query)

    # Ontology: Municipality DEFINES requirement/license edges
    defines: list = []
    try:
        muni = _sql_lit(municipality, 200)
        defines = run_sql(f"""
            SELECT r.predicate, e.entity_type AS object_type,
                   e.display_name, e.attributes
            FROM {CATALOG}.{ont}.relationships r
            JOIN {CATALOG}.{ont}.entities e ON e.entity_id = r.object_id
            WHERE r.predicate = 'DEFINES'
              AND (LOWER(r.subject_id)   LIKE LOWER('%{muni}%')
                OR LOWER(COALESCE(e.display_name,'')) LIKE LOWER('%{muni}%'))
            LIMIT 25
        """, timeout_secs=30) or []
    except Exception:
        defines = []

    # Structured requirement/license fields from extracted_fields as a fallback
    reqs: list = []
    try:
        muni = _sql_lit(municipality, 200)
        uw = _unwrap_expr("ef.field_value")
        reqs = run_sql(f"""
            WITH d AS (
              SELECT ef.doc_id, pd.doc_type,
                MAX(CASE WHEN ef.field_name='municipality'      THEN {uw} END) AS municipality,
                MAX(CASE WHEN ef.field_name='requirement_type'  THEN {uw} END) AS requirement_type,
                MAX(CASE WHEN ef.field_name='license_type'      THEN {uw} END) AS license_type,
                MAX(CASE WHEN ef.field_name='authority'         THEN {uw} END) AS authority,
                MAX(CASE WHEN ef.field_name='issuing_authority' THEN {uw} END) AS issuing_authority,
                MAX(CASE WHEN ef.field_name='lead_time'         THEN {uw} END) AS lead_time,
                MAX(CASE WHEN ef.field_name='effective_date'    THEN {uw} END) AS effective_date
              FROM {CATALOG}.{raw}.extracted_fields ef
              JOIN {CATALOG}.{raw}.parsed_documents pd ON pd.doc_id = ef.doc_id
              GROUP BY ef.doc_id, pd.doc_type
            )
            SELECT * FROM d
            WHERE LOWER(COALESCE(municipality,'')) LIKE LOWER('%{muni}%')
            ORDER BY effective_date DESC NULLS LAST
            LIMIT 25
        """, timeout_secs=30) or []
    except Exception:
        reqs = []

    return {
        "ok": True, "municipality": municipality, "requirement_type": requirement_type,
        "context": context_text, "cited_docs": cited,
        "defines_edges": defines, "requirements": reqs,
    }


# ── Agent Tool 3: Historical Knowledge ────────────────────────────────────────
def _cdd_history(domain_id: str, municipality: str, vs_index: str = None) -> dict:
    """"Have we handled this municipality before?" — VS over prior responses plus
    `Response`/`HAS_HISTORY_OF` edges, returning cited prior answers with dates."""
    dom = _get_domain_schemas(domain_id)
    raw = dom["schema_raw"]
    ont = dom.get("schema_ont") or raw
    vs_index = vs_index or f"{CATALOG}.{dom.get('schema_vec', 'vectors')}.{domain_id}_docs_index"
    query = f"prior feasibility response history for {municipality}"
    context_text, cited = _cdd_vs_search(vs_index, query, doc_type_filter="historical_response")
    if not context_text:  # fall back to an unfiltered search
        context_text, cited = _cdd_vs_search(vs_index, query)

    priors: list = []
    try:
        muni = _sql_lit(municipality, 200)
        uw = _unwrap_expr("ef.field_value")
        priors = run_sql(f"""
            WITH d AS (
              SELECT ef.doc_id, pd.doc_type,
                MAX(CASE WHEN ef.field_name='municipality'  THEN {uw} END) AS municipality,
                MAX(CASE WHEN ef.field_name='responder'     THEN {uw} END) AS responder,
                MAX(CASE WHEN ef.field_name='response_date' THEN {uw} END) AS response_date,
                MAX(CASE WHEN ef.field_name='request_type'  THEN {uw} END) AS request_type
              FROM {CATALOG}.{raw}.extracted_fields ef
              JOIN {CATALOG}.{raw}.parsed_documents pd ON pd.doc_id = ef.doc_id
              WHERE pd.doc_type IN ('historical_response','consultant_correspondence')
              GROUP BY ef.doc_id, pd.doc_type
            )
            SELECT * FROM d
            WHERE LOWER(COALESCE(municipality,'')) LIKE LOWER('%{muni}%')
            ORDER BY response_date DESC NULLS LAST
            LIMIT 25
        """, timeout_secs=30) or []
    except Exception:
        priors = []

    has_history = bool(priors) or bool(context_text)
    return {
        "ok": True, "municipality": municipality, "has_history": has_history,
        "prior_responses": priors, "context": context_text, "cited_docs": cited,
    }


# ── Agent Tool 4: Action (reuses lifecycle + escalation engine) ───────────────
def _cdd_action(domain_id: str, description: str, action_type: str = "FEASIBILITY_FOLLOWUP",
                priority: str = "MEDIUM", source_doc_ids=None,
                requirement_change: bool = None, high_value: bool = None,
                license_lead_time_days: int = None, expected_open_date: str = None,
                logged_by: str = "cdd_agent") -> dict:
    """Create + track an action. Reuses _create_action_master_core, so the Phase-1
    escalation engine (evaluate_escalations) runs identically."""
    docs = source_doc_ids or []
    if isinstance(docs, str):
        docs = [docs]
    req = ActionMasterCreateRequest(
        domain_id=domain_id, action_type=action_type, description=description,
        priority=priority, logged_by=logged_by,
        source_doc_ids=json.dumps(docs),
        requirement_change=requirement_change, high_value=high_value,
        license_lead_time_days=license_lead_time_days,
        expected_open_date=expected_open_date,
    )
    return _create_action_master_core(req)


# ── Change detection ──────────────────────────────────────────────────────────
def _ensure_regulatory_change_history_table():
    """Gold persistence for detected regulatory changes (new table, not a dup)."""
    try:
        run_sql(f"""
            CREATE TABLE IF NOT EXISTS {CATALOG}.platform.regulatory_change_history (
                change_id               STRING NOT NULL,
                domain_id               STRING,
                municipality            STRING,
                requirement_type        STRING,
                previous_doc_id         STRING,
                previous_effective_date STRING,
                previous_summary        STRING,
                new_doc_id              STRING,
                new_effective_date      STRING,
                new_summary             STRING,
                affected_projects       STRING,   -- JSON array
                impact                  STRING,
                escalated               BOOLEAN,
                action_id               STRING,
                detected_at             TIMESTAMP
            ) USING DELTA
        """, timeout_secs=30)
    except Exception as e:
        print(f"[cdd] ensure regulatory_change_history failed: {e}")


def detect_regulatory_change(municipality: str, requirement_type: str = "",
                             domain_id: str = CDD_DOMAIN_ID,
                             persist: bool = True) -> dict:
    """Compare the latest ingested requirement for a municipality/requirement_type
    against the prior effective_date version. On a material change emit a
    structured REGULATORY CHANGE DETECTED result, fire the escalation engine
    (requirement_change) → escalated action, and persist to the Gold history."""
    dom = _get_domain_schemas(domain_id)
    raw = dom["schema_raw"]
    uw = _unwrap_expr("ef.field_value")
    muni = _sql_lit(municipality, 200)
    rt = _sql_lit(requirement_type, 200)
    rt_pred = (
        f"AND (LOWER(COALESCE(requirement_type,'')) LIKE LOWER('%{rt}%') "
        f"OR LOWER(COALESCE(license_type,'')) LIKE LOWER('%{rt}%'))"
    ) if requirement_type else ""

    try:
        versions = run_sql(f"""
            WITH d AS (
              SELECT ef.doc_id, pd.doc_type,
                MAX(CASE WHEN ef.field_name='municipality'      THEN {uw} END) AS municipality,
                MAX(CASE WHEN ef.field_name='requirement_type'  THEN {uw} END) AS requirement_type,
                MAX(CASE WHEN ef.field_name='license_type'      THEN {uw} END) AS license_type,
                MAX(CASE WHEN ef.field_name='authority'         THEN {uw} END) AS authority,
                MAX(CASE WHEN ef.field_name='issuing_authority' THEN {uw} END) AS issuing_authority,
                MAX(CASE WHEN ef.field_name='effective_date'    THEN {uw} END) AS effective_date,
                MAX(CASE WHEN ef.field_name='requirement'       THEN {uw} END) AS requirement,
                MAX(CASE WHEN ef.field_name='lead_time'         THEN {uw} END) AS lead_time
              FROM {CATALOG}.{raw}.extracted_fields ef
              JOIN {CATALOG}.{raw}.parsed_documents pd ON pd.doc_id = ef.doc_id
              GROUP BY ef.doc_id, pd.doc_type
            )
            SELECT * FROM d
            WHERE LOWER(COALESCE(municipality,'')) LIKE LOWER('%{muni}%')
            {rt_pred}
            ORDER BY effective_date DESC NULLS LAST
            LIMIT 5
        """, timeout_secs=45) or []
    except Exception as e:
        return {"ok": False, "detected": False, "error": str(e),
                "municipality": municipality, "requirement_type": requirement_type}

    if len(versions) < 2:
        return {"ok": True, "detected": False, "municipality": municipality,
                "requirement_type": requirement_type, "versions_found": len(versions),
                "message": "Not enough versions to compare."}

    latest, prior = versions[0], versions[1]

    def _sig(v: dict) -> str:
        return " | ".join(str(v.get(f) or "") for f in
                          ("requirement_type", "license_type", "authority",
                           "issuing_authority", "requirement", "lead_time"))

    material = (_sig(latest) != _sig(prior)) or \
               ((latest.get("effective_date") or "") != (prior.get("effective_date") or ""))
    if not material:
        return {"ok": True, "detected": False, "municipality": municipality,
                "requirement_type": requirement_type,
                "message": "Latest version matches prior — no material change."}

    # Affected projects for this municipality
    affected: list = []
    try:
        affected_rows = run_sql(f"""
            WITH d AS (
              SELECT ef.doc_id,
                MAX(CASE WHEN ef.field_name='municipality'  THEN {uw} END) AS municipality,
                MAX(CASE WHEN ef.field_name='project_id'    THEN {uw} END) AS project_id,
                MAX(CASE WHEN ef.field_name='store_number'  THEN {uw} END) AS store_number
              FROM {CATALOG}.{raw}.extracted_fields ef
              GROUP BY ef.doc_id
            )
            SELECT DISTINCT COALESCE(project_id, store_number) AS project
            FROM d
            WHERE LOWER(COALESCE(municipality,'')) LIKE LOWER('%{muni}%')
              AND COALESCE(project_id, store_number) IS NOT NULL
            LIMIT 50
        """, timeout_secs=30) or []
        affected = [r["project"] for r in affected_rows if r.get("project")]
    except Exception:
        affected = []

    prev_sum = f"{prior.get('requirement_type') or prior.get('license_type') or ''}: " \
               f"{prior.get('requirement') or prior.get('authority') or ''} " \
               f"(eff {prior.get('effective_date') or 'n/a'})"
    new_sum = f"{latest.get('requirement_type') or latest.get('license_type') or ''}: " \
              f"{latest.get('requirement') or latest.get('authority') or ''} " \
              f"(eff {latest.get('effective_date') or 'n/a'})"
    change_summary = (
        f"Regulatory change in {municipality} "
        f"({requirement_type or latest.get('requirement_type') or latest.get('license_type') or 'requirement'}): "
        f"'{prev_sum.strip()}' → '{new_sum.strip()}'"
    )
    impact = (f"{len(affected)} project(s) affected: {', '.join(affected)}"
              if affected else "No active projects currently linked to this municipality.")

    # Fire escalation engine → escalated action (reuses Phase-1 engine)
    escalations, action_id, escalated = [], None, False
    try:
        result = _cdd_action(
            domain_id=domain_id,
            action_type="REGULATORY_CHANGE_REVIEW",
            description=change_summary + " | " + impact,
            priority="HIGH",
            source_doc_ids=[latest.get("doc_id"), prior.get("doc_id")],
            requirement_change=True,
        )
        action_id = result.get("action_id")
        escalations = result.get("escalations", [])
        escalated = bool(result.get("attorney_review")) or bool(escalations)
    except Exception as e:
        print(f"[cdd] change-detection escalation failed: {e}")

    if persist:
        _ensure_regulatory_change_history_table()
        try:
            import uuid as _uuid
            cid = str(_uuid.uuid4())
            run_sql(f"""
                INSERT INTO {CATALOG}.platform.regulatory_change_history
                    (change_id, domain_id, municipality, requirement_type,
                     previous_doc_id, previous_effective_date, previous_summary,
                     new_doc_id, new_effective_date, new_summary,
                     affected_projects, impact, escalated, action_id, detected_at)
                VALUES ('{cid}', '{_sql_lit(domain_id,100)}', '{_sql_lit(municipality,200)}',
                        '{_sql_lit(requirement_type or latest.get('requirement_type') or '',200)}',
                        '{_sql_lit(prior.get('doc_id'),300)}', '{_sql_lit(prior.get('effective_date'),50)}',
                        '{_sql_lit(prev_sum,2000)}',
                        '{_sql_lit(latest.get('doc_id'),300)}', '{_sql_lit(latest.get('effective_date'),50)}',
                        '{_sql_lit(new_sum,2000)}',
                        '{_sql_lit(json.dumps(affected),4000)}', '{_sql_lit(impact,2000)}',
                        {str(bool(escalated)).lower()}, '{_sql_lit(action_id or '',100)}',
                        current_timestamp())
            """, timeout_secs=30)
        except Exception as e:
            print(f"[cdd] persist regulatory_change_history failed: {e}")

    return {
        "ok": True, "detected": True, "municipality": municipality,
        "requirement_type": requirement_type or latest.get("requirement_type"),
        "previous": prior, "new": latest,
        "affected_projects": affected, "impact": impact,
        "change_summary": change_summary,
        "escalations": escalations, "escalated": escalated, "action_id": action_id,
        "banner": "REGULATORY CHANGE DETECTED",
    }


class RegulatoryChangeDetectRequest(BaseModel):
    municipality:     str
    requirement_type: str  = ""
    domain_id:        str  = CDD_DOMAIN_ID
    persist:          bool = True


@router.post("/regulatory-change/detect")
async def regulatory_change_detect(req: RegulatoryChangeDetectRequest):
    """Detect a material regulatory change for a municipality/requirement_type,
    escalate via the Phase-1 engine, and persist to the Gold history table."""
    return detect_regulatory_change(
        req.municipality, req.requirement_type, req.domain_id, req.persist)


@router.get("/regulatory-change/history")
async def regulatory_change_history(domain_id: str = CDD_DOMAIN_ID, limit: int = 100):
    """Return persisted regulatory change history (Gold) for the domain."""
    _ensure_regulatory_change_history_table()
    try:
        rows = run_sql(f"""
            SELECT change_id, domain_id, municipality, requirement_type,
                   previous_doc_id, previous_effective_date, previous_summary,
                   new_doc_id, new_effective_date, new_summary,
                   affected_projects, impact, escalated, action_id,
                   CAST(detected_at AS STRING) AS detected_at
            FROM {CATALOG}.platform.regulatory_change_history
            WHERE domain_id = '{_sql_lit(domain_id,100)}'
            ORDER BY detected_at DESC
            LIMIT {int(limit)}
        """, timeout_secs=30) or []
        for r in rows:
            try:
                r["affected_projects"] = json.loads(r.get("affected_projects") or "[]")
            except Exception:
                r["affected_projects"] = []
        return {"changes": rows, "total": len(rows), "domain_id": domain_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── The CDD agent: four tools orchestrated inside the existing agent_query ─────
def _cdd_agent_query(req, domain_id: str, domain_cfg: dict,
                     base_prompt: str, vs_index: str) -> dict:
    """Build a tool-calling agent whose tools ARE the four CDD 'agents'
    (Intake / Research / History / Action) plus change detection. Falls back to
    a direct-LLM answer over document context if the agent stack is unavailable."""
    try:
        from langchain.agents import AgentExecutor, create_tool_calling_agent
        from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
        from langchain_core.tools import tool

        @tool
        def intake_request(request_text: str) -> str:
            """Classify a feasibility/store-development request and extract its
            request_type, project/store, municipality, state and priority."""
            return json.dumps(_cdd_intake(domain_id, request_text))

        @tool
        def research_municipality(municipality: str, requirement_type: str = "") -> str:
            """Retrieve the regulatory requirements and licenses for a municipality
            (e.g. Tampa FL, Dallas TX). Uses Vector Search over the domain document
            index plus the ontology 'Municipality DEFINES' edges. Cite doc IDs."""
            return json.dumps(_cdd_research(domain_id, municipality, requirement_type, vs_index))

        @tool
        def municipality_history(municipality: str) -> str:
            """Answer 'have we handled this municipality before?'. Returns prior
            responses/correspondence with their dates and cited document IDs."""
            return json.dumps(_cdd_history(domain_id, municipality, vs_index))

        @tool
        def create_tracked_action(description: str, action_type: str = "FEASIBILITY_FOLLOWUP",
                                  priority: str = "MEDIUM") -> str:
            """Create and track an action in the platform action register. Runs the
            escalation engine automatically. Use to log follow-ups or open items."""
            return json.dumps(_cdd_action(domain_id, description, action_type, priority))

        @tool
        def detect_change(municipality: str, requirement_type: str = "") -> str:
            """Detect whether a municipality's regulatory requirement changed vs its
            prior effective-dated version. Emits REGULATORY CHANGE DETECTED and
            escalates when material."""
            return json.dumps(detect_regulatory_change(municipality, requirement_type, domain_id))

        tools = [intake_request, research_municipality, municipality_history,
                 create_tracked_action, detect_change]

        prompt = ChatPromptTemplate.from_messages([
            ("system", base_prompt),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ])
        llm, _used_model = _get_llm(max_tokens=2048)
        agent = create_tool_calling_agent(llm, tools, prompt)
        executor = AgentExecutor(agent=agent, tools=tools, verbose=False, max_iterations=8)
        result = executor.invoke({
            "input": req.question,
            "chat_history": req.chat_history or [],
        })
        return {
            "answer": result.get("output", ""),
            "question": req.question,
            "tools_used": len(tools),
            "vector_search_active": True,
            "model": AGENT_MODEL,
            "domain_id": domain_id,
        }
    except Exception as e:
        # Graceful fallback: direct LLM over VS/SQL document context
        context_text, cited = _cdd_vs_search(vs_index, req.question)
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            human = req.question
            if context_text:
                human = (f"Use these document excerpts as your primary source:\n\n"
                         f"{context_text}\n\n---\n\nQuestion: {req.question}")
            llm, _used_model = _get_llm(max_tokens=2048)
            resp = llm.invoke([SystemMessage(content=base_prompt),
                               HumanMessage(content=human)])
            return {"answer": resp.content.strip(), "question": req.question,
                    "tools_used": 0, "vector_search_active": bool(context_text),
                    "cited_docs": cited, "fallback": True, "error": str(e),
                    "domain_id": domain_id}
        except Exception as e2:
            return {"answer": f"I encountered an error: {e2}", "question": req.question,
                    "fallback": True, "error": str(e2), "domain_id": domain_id}


# ═══════════════════════════════════════════════════════════════════════════════
# FMAPI Model Configuration
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/model-config")
async def get_model_config():
    """
    Returns the current FMAPI / Foundation Model endpoint configuration.
    agent_model is resolved live from serving endpoints (with fallback chain).
    embed_model and setup_model are static per the notebook/backend source.
    """
    try:
        resolved = _resolve_model()
        # Try to get the list of actually available models from cache
        available = list(_available_models_cache) or []
        return {
            "agent_model":            resolved,
            "agent_model_configured": AGENT_MODEL,
            "embed_model":            "databricks-gte-large-en",
            "setup_model":            "databricks-meta-llama-3-3-70b-instruct",
            "fallback_chain":         list(dict.fromkeys(_MODEL_FALLBACKS)),
            "available_models":       available,
            "resolved_live":          True,
        }
    except Exception as e:
        return {
            "agent_model":            AGENT_MODEL,
            "agent_model_configured": AGENT_MODEL,
            "embed_model":            "databricks-gte-large-en",
            "setup_model":            "databricks-meta-llama-3-3-70b-instruct",
            "fallback_chain":         list(dict.fromkeys(_MODEL_FALLBACKS)),
            "available_models":       [],
            "resolved_live":          False,
            "error":                  str(e),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Copilot Prompt Library  (multi-prompt management per domain)
# ═══════════════════════════════════════════════════════════════════════════════

class CopilotPromptCreateRequest(BaseModel):
    domain_id:   str
    name:        str        # user-given label e.g. "Compliance Review v2"
    prompt_text: str
    created_by:  str = "app_user"

class CopilotPromptUpdateRequest(BaseModel):
    name:        Optional[str] = None
    prompt_text: Optional[str] = None

def _ensure_copilot_prompts_table():
    """Create platform.copilot_prompts if it does not exist."""
    run_sql(f"""
        CREATE TABLE IF NOT EXISTS {CATALOG}.platform.copilot_prompts (
            prompt_id   STRING  NOT NULL,
            domain_id   STRING  NOT NULL,
            name        STRING  NOT NULL,
            prompt_text STRING  NOT NULL,
            is_active   BOOLEAN,
            created_at  TIMESTAMP,
            updated_at  TIMESTAMP,
            created_by  STRING
        )
    """, timeout_secs=30)


@router.get("/copilot-prompts")
async def list_copilot_prompts(domain_id: str = "compliance"):
    """Return all named prompts for a domain, ordered newest first."""
    _ensure_copilot_prompts_table()
    try:
        rows = run_sql(f"""
            SELECT prompt_id, domain_id, name, is_active,
                   LEFT(prompt_text, 200)       AS preview,
                   CAST(created_at AS STRING)   AS created_at,
                   CAST(updated_at AS STRING)   AS updated_at,
                   created_by
            FROM {CATALOG}.platform.copilot_prompts
            WHERE domain_id = '{domain_id}'
            ORDER BY is_active DESC, created_at DESC
        """, timeout_secs=30) or []
        # Also attach the full text for the active prompt
        active = [r for r in rows if r.get("is_active")]
        active_full = None
        if active:
            full = run_sql(f"""
                SELECT prompt_text FROM {CATALOG}.platform.copilot_prompts
                WHERE prompt_id = '{active[0]["prompt_id"]}'
            """, timeout_secs=20) or []
            active_full = full[0]["prompt_text"] if full else None
        return {"prompts": rows, "total": len(rows), "active_prompt_text": active_full}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/copilot-prompts")
async def create_copilot_prompt(req: CopilotPromptCreateRequest):
    """Create a new named prompt for a domain."""
    if len(req.prompt_text or "") > 2500:
        raise HTTPException(status_code=400, detail="Copilot prompt exceeds the 2500-character limit.")
    _ensure_copilot_prompts_table()
    import uuid as _uuid
    try:
        pid   = str(_uuid.uuid4())
        name  = req.name.replace("'", "''")
        text  = req.prompt_text.replace("'", "''")
        by    = req.created_by.replace("'", "''")
        dom   = req.domain_id.replace("'", "''")
        run_sql(f"""
            INSERT INTO {CATALOG}.platform.copilot_prompts
                (prompt_id, domain_id, name, prompt_text, is_active, created_at, updated_at, created_by)
            VALUES ('{pid}', '{dom}', '{name}', '{text}', FALSE,
                    current_timestamp(), current_timestamp(), '{by}')
        """, timeout_secs=30)
        return {"prompt_id": pid, "created": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/copilot-prompts/{prompt_id}/full")
async def get_copilot_prompt_full(prompt_id: str):
    """Return the full text of a single prompt (not truncated)."""
    _ensure_copilot_prompts_table()
    try:
        rows = run_sql(f"""
            SELECT prompt_id, domain_id, name, prompt_text, is_active,
                   CAST(created_at AS STRING) AS created_at
            FROM {CATALOG}.platform.copilot_prompts
            WHERE prompt_id = '{prompt_id}'
            LIMIT 1
        """, timeout_secs=20) or []
        if not rows:
            raise HTTPException(status_code=404, detail="Prompt not found")
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/copilot-prompts/{prompt_id}")
async def update_copilot_prompt(prompt_id: str, req: CopilotPromptUpdateRequest):
    """Edit the name and/or text of an existing prompt."""
    _ensure_copilot_prompts_table()
    try:
        parts = ["updated_at = current_timestamp()"]
        if req.name is not None:
            parts.append(f"name = '{req.name.replace(chr(39), chr(39)*2)}'")
        if req.prompt_text is not None:
            parts.append(f"prompt_text = '{req.prompt_text.replace(chr(39), chr(39)*2)}'")
        if len(parts) == 1:
            return {"updated": False, "reason": "Nothing to update"}
        run_sql(f"""
            UPDATE {CATALOG}.platform.copilot_prompts
            SET {', '.join(parts)}
            WHERE prompt_id = '{prompt_id}'
        """, timeout_secs=30)
        # If this prompt is active, sync to domain_configs
        active_rows = run_sql(f"""
            SELECT domain_id, prompt_text, is_active
            FROM {CATALOG}.platform.copilot_prompts
            WHERE prompt_id = '{prompt_id}'
        """, timeout_secs=20) or []
        if active_rows and active_rows[0].get("is_active") and req.prompt_text:
            esc_p = req.prompt_text.replace("'", "''")
            dom   = active_rows[0]["domain_id"]
            run_sql(f"""
                UPDATE {CATALOG}.platform.domain_configs
                SET agent_system_prompt = '{esc_p}', updated_at = current_timestamp()
                WHERE domain_id = '{dom}'
            """, timeout_secs=30)
            with _domain_cache_lock:
                _domain_cache.pop(dom, None)
        return {"updated": True, "prompt_id": prompt_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/copilot-prompts/{prompt_id}")
async def delete_copilot_prompt(prompt_id: str):
    """Permanently delete a prompt (cannot delete the active prompt)."""
    _ensure_copilot_prompts_table()
    try:
        rows = run_sql(f"""
            SELECT is_active, domain_id FROM {CATALOG}.platform.copilot_prompts
            WHERE prompt_id = '{prompt_id}'
        """, timeout_secs=20) or []
        if not rows:
            raise HTTPException(status_code=404, detail="Prompt not found")
        if rows[0].get("is_active"):
            raise HTTPException(status_code=400, detail="Cannot delete the active prompt. Activate another prompt first.")
        run_sql(f"""
            DELETE FROM {CATALOG}.platform.copilot_prompts WHERE prompt_id = '{prompt_id}'
        """, timeout_secs=30)
        return {"deleted": True, "prompt_id": prompt_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/copilot-prompts/{prompt_id}/activate")
async def activate_copilot_prompt(prompt_id: str):
    """
    Set a prompt as the active guiding principle for its domain.
    Deactivates all other prompts for the same domain and syncs
    the text into domain_configs.agent_system_prompt.
    """
    _ensure_copilot_prompts_table()
    try:
        rows = run_sql(f"""
            SELECT domain_id, prompt_text FROM {CATALOG}.platform.copilot_prompts
            WHERE prompt_id = '{prompt_id}'
        """, timeout_secs=20) or []
        if not rows:
            raise HTTPException(status_code=404, detail="Prompt not found")
        domain_id   = rows[0]["domain_id"]
        prompt_text = rows[0]["prompt_text"]
        # Deactivate all in domain, then activate this one
        run_sql(f"""
            UPDATE {CATALOG}.platform.copilot_prompts
            SET is_active = FALSE
            WHERE domain_id = '{domain_id}'
        """, timeout_secs=30)
        run_sql(f"""
            UPDATE {CATALOG}.platform.copilot_prompts
            SET is_active = TRUE, updated_at = current_timestamp()
            WHERE prompt_id = '{prompt_id}'
        """, timeout_secs=30)
        # Sync to domain_configs.agent_system_prompt
        esc_p = prompt_text.replace("'", "''")
        run_sql(f"""
            UPDATE {CATALOG}.platform.domain_configs
            SET agent_system_prompt = '{esc_p}', updated_at = current_timestamp()
            WHERE domain_id = '{domain_id}'
        """, timeout_secs=30)
        with _domain_cache_lock:
            _domain_cache.pop(domain_id, None)
        return {"activated": True, "prompt_id": prompt_id, "domain_id": domain_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Action Master — full lifecycle tracking
# ═══════════════════════════════════════════════════════════════════════════════

class ActionMasterCreateRequest(BaseModel):
    domain_id:     str  = "supply_chain"
    action_type:   str
    description:   str
    priority:      str  = "MEDIUM"
    incident_ref:  str  = ""
    logged_by:     str  = "app_user"
    source_doc_ids: str = ""   # JSON array string e.g. '["doc1","doc2"]'
    # Optional escalation-context signals, evaluated deterministically on create.
    # Omitted by existing callers → no rule fires → identical behavior.
    confidence:             Optional[float] = None   # e.g. answer/extraction confidence 0..1
    license_lead_time_days: Optional[int]   = None
    expected_open_date:     Optional[str]   = None    # YYYY-MM-DD
    requirement_change:     Optional[bool]  = None
    high_value:             Optional[bool]  = None

class ActionMasterUpdateRequest(BaseModel):
    new_status:          str
    changed_by:          str  = "app_user"
    comments:            str  = ""
    # INITIATED fields
    owner:               Optional[str] = None
    due_date:            Optional[str] = None   # ISO date string YYYY-MM-DD
    # IN_PROGRESS fields
    eta:                 Optional[str] = None
    next_update_date:    Optional[str] = None
    # COMPLETED fields
    verified_by:         Optional[str] = None
    # IGNORED fields
    ignore_reason:       Optional[str] = None
    ignore_by:           Optional[str] = None
    # CANCELLED fields
    cancel_reason:       Optional[str] = None
    cancel_authorized_by: Optional[str] = None


_ACTION_STATUS_FLOW = {
    "OPEN":              ["INITIATED", "IGNORED"],
    "INITIATED":         ["IN_PROGRESS", "CANCELLED"],
    "IN_PROGRESS":       ["PENDING_VERIFICATION", "CANCELLED"],
    "PENDING_VERIFICATION": ["COMPLETED", "IN_PROGRESS"],
    "COMPLETED":         [],     # terminal
    "IGNORED":           [],     # terminal
    "CANCELLED":         [],     # terminal
}


def _ensure_action_master_table():
    """Create platform.action_master if it does not exist."""
    run_sql(f"""
        CREATE TABLE IF NOT EXISTS {CATALOG}.platform.action_master (
            action_id            STRING  NOT NULL,
            domain_id            STRING  NOT NULL,
            action_type          STRING,
            description          STRING,
            priority             STRING,
            source_doc_ids       STRING,
            incident_ref         STRING,
            status               STRING,
            owner                STRING,
            due_date             DATE,
            eta                  DATE,
            next_update_date     DATE,
            completed_date       TIMESTAMP,
            verified_by          STRING,
            ignore_reason        STRING,
            ignore_by            STRING,
            cancel_reason        STRING,
            cancel_authorized_by STRING,
            cancel_date          TIMESTAMP,
            logged_by            STRING,
            created_at           TIMESTAMP,
            updated_at           TIMESTAMP
        )
    """, timeout_secs=30)


def _ensure_action_history_table():
    """Create platform.action_history if it does not exist."""
    run_sql(f"""
        CREATE TABLE IF NOT EXISTS {CATALOG}.platform.action_history (
            history_id    STRING  NOT NULL,
            action_id     STRING  NOT NULL,
            old_status    STRING,
            new_status    STRING,
            changed_by    STRING,
            changed_at    TIMESTAMP,
            comments      STRING,
            metadata_json STRING
        )
    """, timeout_secs=30)


def _write_action_history(action_id: str, old_status: str, new_status: str,
                           changed_by: str, comments: str, meta: dict):
    """Append one history row."""
    import uuid as _uuid
    hid  = str(_uuid.uuid4())
    cb   = changed_by.replace("'", "''")
    cmt  = comments.replace("'", "''")
    meta_json = json.dumps(meta).replace("'", "''")
    try:
        run_sql(f"""
            INSERT INTO {CATALOG}.platform.action_history
                (history_id, action_id, old_status, new_status,
                 changed_by, changed_at, comments, metadata_json)
            VALUES ('{hid}', '{action_id}', '{old_status}', '{new_status}',
                    '{cb}', current_timestamp(), '{cmt}', '{meta_json}')
        """, timeout_secs=30)
    except Exception as e:
        print(f"[action_history] write failed: {e}")


@router.post("/action-master")
async def create_action_master(req: ActionMasterCreateRequest):
    """
    Create a new action in the platform-wide action_master table.
    Also writes the initial OPEN history row.
    """
    return _create_action_master_core(req)


def _create_action_master_core(req: ActionMasterCreateRequest) -> dict:
    """Synchronous core of POST /action-master.

    Extracted verbatim so in-process callers (CDD Action agent tool, regulatory
    change detection) can create+track actions and run the SAME Phase-1
    escalation engine without an HTTP round-trip. Behavior is identical to the
    original route body — no change for supply_chain / compliance callers.
    """
    _ensure_action_master_table()
    _ensure_action_history_table()
    import uuid as _uuid
    from datetime import datetime, timezone
    action_id = "ACT-" + str(_uuid.uuid4())[:8].upper()
    desc   = req.description.replace("'", "''")
    by     = req.logged_by.replace("'", "''")
    inc    = req.incident_ref.replace("'", "''")
    dom    = req.domain_id.replace("'", "''")
    docs   = req.source_doc_ids.replace("'", "''")
    run_sql(f"""
        INSERT INTO {CATALOG}.platform.action_master
            (action_id, domain_id, action_type, description, priority,
             source_doc_ids, incident_ref, status, logged_by, created_at, updated_at)
        VALUES ('{action_id}', '{dom}', '{req.action_type}', '{desc}',
                '{req.priority}', '{docs}', '{inc}', 'OPEN', '{by}',
                current_timestamp(), current_timestamp())
    """, timeout_secs=30)
    _write_action_history(action_id, "", "OPEN", req.logged_by, "Action created", {})

    # ── Deterministic escalation evaluation ──
    context = {
        "confidence":             req.confidence,
        "license_lead_time_days": req.license_lead_time_days,
        "expected_open_date":     req.expected_open_date,
        "requirement_change":     req.requirement_change,
        "high_value":             req.high_value,
    }
    triggered, escalated, bumped = [], False, False
    try:
        triggered = evaluate_escalations(req.domain_id, context)
    except Exception as _e:
        print(f"[escalation] evaluate failed: {_e}")
    for t in triggered:
        tgt = t.get("target")
        if tgt == "attorney_review":
            _queue_attorney_review(
                req.domain_id, req.description,
                f"Action {action_id} ({req.action_type})",
                t.get("reason") or t.get("rule_type"))
            escalated = True
        elif tgt == "priority_bump" and not bumped:
            try:
                run_sql(f"""
                    UPDATE {CATALOG}.platform.action_master
                    SET priority = 'HIGH', updated_at = current_timestamp()
                    WHERE action_id = '{action_id}' AND priority NOT IN ('HIGH','CRITICAL')
                """, timeout_secs=20)
                bumped = True
            except Exception as _e:
                print(f"[escalation] priority bump failed: {_e}")

    return {"action_id": action_id, "status": "OPEN", "created": True,
            "escalations": triggered, "attorney_review": escalated,
            "priority_bumped": bumped}


@router.get("/action-master")
async def list_action_master(
    domain_id:    str  = "supply_chain",
    status:       str  = "",      # empty = active only (excludes COMPLETED/CANCELLED)
    include_all:  bool = False,   # if True, return all statuses
    limit:        int  = 200,
):
    """List actions for a domain. By default excludes COMPLETED and CANCELLED."""
    _ensure_action_master_table()
    try:
        if include_all or status == "ALL":
            where = f"WHERE domain_id = '{domain_id}'"
        elif status:
            where = f"WHERE domain_id = '{domain_id}' AND status = '{status.upper()}'"
        else:
            where = f"WHERE domain_id = '{domain_id}' AND status NOT IN ('COMPLETED','CANCELLED')"
        rows = run_sql(f"""
            SELECT action_id, domain_id, action_type, description, priority,
                   source_doc_ids, incident_ref, status, owner,
                   CAST(due_date AS STRING)          AS due_date,
                   CAST(eta AS STRING)               AS eta,
                   CAST(next_update_date AS STRING)  AS next_update_date,
                   CAST(completed_date AS STRING)    AS completed_date,
                   verified_by, ignore_reason, ignore_by,
                   cancel_reason, cancel_authorized_by,
                   CAST(cancel_date AS STRING)       AS cancel_date,
                   logged_by,
                   CAST(created_at AS STRING)        AS created_at,
                   CAST(updated_at AS STRING)        AS updated_at
            FROM {CATALOG}.platform.action_master
            {where}
            ORDER BY
                CASE priority WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1
                               WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                created_at DESC
            LIMIT {limit}
        """, timeout_secs=30) or []
        return {"actions": rows, "total": len(rows), "domain_id": domain_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/action-master/{action_id}")
async def update_action_master(action_id: str, req: ActionMasterUpdateRequest):
    """
    Transition an action to a new status.
    Validates the transition against the allowed lifecycle.
    Writes an audit row to action_history.
    """
    _ensure_action_master_table()
    _ensure_action_history_table()
    try:
        rows = run_sql(f"""
            SELECT status FROM {CATALOG}.platform.action_master WHERE action_id = '{action_id}'
        """, timeout_secs=20) or []
        if not rows:
            raise HTTPException(status_code=404, detail=f"Action {action_id} not found")
        old_status = rows[0]["status"]
        new_status = req.new_status.upper()
        allowed    = _ACTION_STATUS_FLOW.get(old_status, [])
        if new_status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Transition {old_status}→{new_status} is not allowed. Allowed: {allowed}"
            )
        # Returning an action for rework after a failed review must carry a reason.
        if old_status == "PENDING_VERIFICATION" and new_status == "IN_PROGRESS" and not (req.comments or "").strip():
            raise HTTPException(status_code=400, detail="A reason is required to return an action for rework.")
        # Build SET clause based on new status
        set_parts = [f"status = '{new_status}'", "updated_at = current_timestamp()"]
        meta: dict = {}

        if new_status == "INITIATED":
            if req.owner:
                set_parts.append(f"owner = '{req.owner.replace(chr(39),chr(39)*2)}'")
                meta["owner"] = req.owner
            if req.due_date:
                set_parts.append(f"due_date = DATE '{req.due_date}'")
                meta["due_date"] = req.due_date

        elif new_status == "IN_PROGRESS":
            if req.eta:
                set_parts.append(f"eta = DATE '{req.eta}'")
                meta["eta"] = req.eta
            if req.next_update_date:
                set_parts.append(f"next_update_date = DATE '{req.next_update_date}'")
                meta["next_update_date"] = req.next_update_date

        elif new_status == "COMPLETED":
            set_parts.append("completed_date = current_timestamp()")
            if req.verified_by:
                set_parts.append(f"verified_by = '{req.verified_by.replace(chr(39),chr(39)*2)}'")
                meta["verified_by"] = req.verified_by

        elif new_status == "IGNORED":
            if req.ignore_reason:
                set_parts.append(f"ignore_reason = '{req.ignore_reason.replace(chr(39),chr(39)*2)}'")
                meta["ignore_reason"] = req.ignore_reason
            if req.ignore_by:
                set_parts.append(f"ignore_by = '{req.ignore_by.replace(chr(39),chr(39)*2)}'")
                meta["ignore_by"] = req.ignore_by

        elif new_status == "CANCELLED":
            set_parts.append("cancel_date = current_timestamp()")
            if req.cancel_reason:
                set_parts.append(f"cancel_reason = '{req.cancel_reason.replace(chr(39),chr(39)*2)}'")
                meta["cancel_reason"] = req.cancel_reason
            if req.cancel_authorized_by:
                set_parts.append(f"cancel_authorized_by = '{req.cancel_authorized_by.replace(chr(39),chr(39)*2)}'")
                meta["cancel_authorized_by"] = req.cancel_authorized_by

        run_sql(f"""
            UPDATE {CATALOG}.platform.action_master
            SET {', '.join(set_parts)}
            WHERE action_id = '{action_id}'
        """, timeout_secs=30)
        _write_action_history(action_id, old_status, new_status, req.changed_by, req.comments, meta)
        return {"action_id": action_id, "old_status": old_status, "new_status": new_status, "updated": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/action-master/{action_id}/history")
async def get_action_history(action_id: str):
    """Return the full audit history for a single action."""
    _ensure_action_history_table()
    try:
        rows = run_sql(f"""
            SELECT history_id, action_id, old_status, new_status,
                   changed_by, CAST(changed_at AS STRING) AS changed_at,
                   comments, metadata_json
            FROM {CATALOG}.platform.action_history
            WHERE action_id = '{action_id}'
            ORDER BY changed_at ASC
        """, timeout_secs=30) or []
        return {"action_id": action_id, "history": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/action-reports")
async def get_action_reports(domain_id: str = "supply_chain"):
    """
    Aggregated action reports for a domain:
    - Counts by status and priority
    - Overdue actions (due_date < today and status not terminal)
    - All actions with full history summary
    """
    _ensure_action_master_table()
    _ensure_action_history_table()
    from datetime import date
    _did = (domain_id or "").replace("'", "''")   # escape for the SQL literals below
    try:
        # Aggregate stats
        stats = run_sql(f"""
            SELECT
                status,
                priority,
                COUNT(*) AS cnt
            FROM {CATALOG}.platform.action_master
            WHERE domain_id = '{_did}'
            GROUP BY status, priority
            ORDER BY status, priority
        """, timeout_secs=30) or []

        # Overdue: due_date < today AND status not terminal
        today = date.today().isoformat()
        overdue = run_sql(f"""
            SELECT action_id, action_type, description, priority,
                   CAST(due_date AS STRING) AS due_date, owner, status,
                   CAST(source_doc_ids AS STRING) AS source_doc_ids
            FROM {CATALOG}.platform.action_master
            WHERE domain_id = '{_did}'
              AND due_date < DATE '{today}'
              AND status NOT IN ('COMPLETED','CANCELLED','IGNORED')
            ORDER BY due_date ASC
            LIMIT 50
        """, timeout_secs=30) or []

        # All actions with lifecycle info
        all_actions = run_sql(f"""
            SELECT action_id, action_type, description, priority, status,
                   owner, CAST(due_date AS STRING) AS due_date,
                   CAST(created_at AS STRING) AS created_at,
                   CAST(completed_date AS STRING) AS completed_date,
                   logged_by, incident_ref, verified_by,
                   cancel_reason, ignore_reason,
                   CAST(source_doc_ids AS STRING) AS source_doc_ids,
                   CAST(updated_at AS STRING) AS updated_at
            FROM {CATALOG}.platform.action_master
            WHERE domain_id = '{_did}'
            ORDER BY created_at DESC
            LIMIT 500
        """, timeout_secs=30) or []

        # Build summary counts
        by_status: dict = {}
        by_priority: dict = {}
        for r in stats:
            s = r.get("status","?")
            p = r.get("priority","?")
            _c = int(r.get("cnt") or 0)          # SQL statement API returns counts as strings
            by_status[s]    = by_status.get(s,0) + _c
            by_priority[p]  = by_priority.get(p,0) + _c

        # Attach the owning project to each action from the CURATED doc->project tags
        # (Phase 2) so manual re-tagging in the Library flows through; the tags table is
        # seeded from the same derived store/project id, so behaviour is unchanged by default.
        # A doc may be tagged to MANY projects → collect ALL of them so an action
        # appears under every project its source docs belong to.
        doc_proj: dict = {}
        try:
            _bootstrap_project_tags(domain_id)   # ensure derived tags exist (no-op after first seed)
            _didq = (domain_id or "").replace("'", "''")
            trows = run_sql(f"""
                SELECT doc_id, to_json(sort_array(collect_set(project_id))) AS projects
                FROM {CATALOG}.platform.document_project_tags
                WHERE domain_id='{_didq}' AND scope='project' AND project_id IS NOT NULL
                GROUP BY doc_id
            """, timeout_secs=30) or []
            import json as _jt
            for r in trows:
                try:
                    arr = _jt.loads(r.get("projects") or "[]")   # JSON array — id-safe
                    if arr:
                        doc_proj[r["doc_id"]] = [str(x) for x in arr]
                except Exception:
                    pass
        except Exception:
            doc_proj = {}

        import json as _json
        def _projs_for(src) -> list:
            # source_doc_ids may be a JSON list, a JSON scalar, or a plain/CSV string.
            ids = []
            if isinstance(src, (list, tuple)):
                ids = list(src)
            elif src:
                s = str(src).strip()
                try:
                    parsed = _json.loads(s)
                    ids = parsed if isinstance(parsed, list) else [parsed]
                except Exception:
                    ids = s.strip("[]").replace('"', "").split(",")
            out: list = []
            for did in ids:
                for p in doc_proj.get(str(did).strip(), []):
                    if p not in out:
                        out.append(p)
            return out

        for _r in overdue + all_actions:
            _pj = _projs_for(_r.get("source_doc_ids"))
            _r["projects"] = _pj
            _r["project"]  = _pj[0] if _pj else None   # first, for backward-compat
        projects = sorted({p for _r in all_actions for p in (_r.get("projects") or [])})

        return {
            "domain_id":    domain_id,
            "by_status":    by_status,
            "by_priority":  by_priority,
            "total":        sum(by_status.values()),
            "overdue":      overdue,
            "overdue_count": len(overdue),
            "actions":      all_actions,
            "projects":     projects,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Platform Schema Library — Pre-built doc type schemas derived from the
# docIntel-framework.md action management framework.
# Covers: Compliance, Supply Chain, Legal, Cross-domain, Finance.
# ═══════════════════════════════════════════════════════════════════════════════

_PLATFORM_SCHEMA_LIBRARY = [
    # ── Compliance ────────────────────────────────────────────────────────────
    {
        "doc_type": "health_inspection_report",
        "display_name": "Health Inspection Report",
        "description": "Food safety and health department inspection findings, violations, and corrective action requirements for restaurant or food-service locations.",
        "extraction_schema": json.dumps([
            {"name": "inspection_date",      "description": "Date the inspection was conducted",                          "example": "2024-03-15"},
            {"name": "inspector_name",       "description": "Name or ID of the health inspector",                         "example": "Inspector J. Williams"},
            {"name": "establishment_name",   "description": "Name of the establishment inspected",                       "example": "Store 220 - QuikTrip"},
            {"name": "violation_code",       "description": "Regulatory code number of the violation found",             "example": "FDA 3-501.16(A)"},
            {"name": "violation_description","description": "Full description of the finding or violation",               "example": "Cold holding temperature exceeded allowable limit"},
            {"name": "severity",             "description": "Violation severity: CRITICAL, MAJOR, or MINOR",             "example": "CRITICAL"},
            {"name": "corrective_action",    "description": "Required corrective action or remedy",                      "example": "Discard product, repair refrigeration unit"},
            {"name": "deadline",             "description": "Deadline for corrective action completion",                  "example": "24 hours"},
            {"name": "store_location",       "description": "Store number, address, or location identifier",             "example": "Store 220, Atlanta GA"},
            {"name": "inspection_score",     "description": "Numerical inspection score if assigned",                    "example": "78"},
            {"name": "follow_up_required",   "description": "Whether a follow-up inspection is required: YES or NO",     "example": "YES"},
            {"name": "risk_level",           "description": "Overall risk level: CRITICAL, HIGH, MEDIUM, or LOW",        "example": "CRITICAL"},
        ]),
        "parse_instructions": (
            "Focus on: (1) specific violation codes and their descriptions, "
            "(2) corrective action deadlines (often stated as '24 hours', '30 days', etc.), "
            "(3) severity ratings and whether violations are 'critical' (imminent health risk) or 'non-critical', "
            "(4) inspector details and inspection date, "
            "(5) any scoring or grading. "
            "Extract each finding as a separate record when possible."
        ),
        "classification_examples": (
            "Health inspection report|Food safety violation found|Inspector from health department|"
            "Critical violation cited|Cold holding temperature|Improper food storage|Score: 78|"
            "Corrective action required within 24 hours|Follow-up inspection scheduled"
        ),
        "created_by_domain": "platform",
    },
    {
        "doc_type": "environmental_inspection_report",
        "display_name": "Environmental Inspection Report",
        "description": "EPA, state environmental agency, or underground storage tank (UST) inspection reports documenting environmental compliance status, violations, and remediation requirements.",
        "extraction_schema": json.dumps([
            {"name": "inspection_date",      "description": "Date of the environmental inspection",                      "example": "2024-02-20"},
            {"name": "inspector_agency",     "description": "Regulatory agency conducting the inspection",               "example": "EPA Region IV"},
            {"name": "facility_name",        "description": "Name and address of the inspected facility",                "example": "Store 145, 1234 Highway Blvd"},
            {"name": "regulation_cited",     "description": "Federal or state regulation code cited in the finding",     "example": "EPA UST 40 CFR § 280.20"},
            {"name": "finding_type",         "description": "Type of environmental finding (e.g. UST_FAILURE, SPILL)",   "example": "UST_FAILURE"},
            {"name": "finding_description",  "description": "Detailed description of the environmental finding",         "example": "UST monitoring system failed annual inspection"},
            {"name": "severity",             "description": "Finding severity: CRITICAL, HIGH, MEDIUM, or LOW",          "example": "HIGH"},
            {"name": "corrective_action",    "description": "Required remediation or corrective action",                  "example": "Repair UST monitoring system"},
            {"name": "deadline",             "description": "Regulatory deadline for corrective action",                  "example": "30 days"},
            {"name": "permit_number",        "description": "Environmental permit or facility registration number",       "example": "UST-GA-2024-0145"},
            {"name": "penalty_amount",       "description": "Financial penalty if assessed",                             "example": "$15,000"},
            {"name": "risk_level",           "description": "Risk level: CRITICAL, HIGH, MEDIUM, or LOW",                "example": "HIGH"},
        ]),
        "parse_instructions": (
            "Focus on: (1) specific regulatory citations (CFR sections, state codes), "
            "(2) UST (underground storage tank) monitoring findings, "
            "(3) spill or release findings with volume and location, "
            "(4) corrective action deadlines — EPA regulations frequently specify exact timeframes, "
            "(5) penalty amounts or NOV (Notice of Violation) references."
        ),
        "classification_examples": (
            "Environmental inspection|EPA inspection report|Underground storage tank|UST monitoring|"
            "Notice of violation|Environmental compliance|Corrective action required within 30 days|"
            "Remediation plan|Spill report|40 CFR compliance|State environmental agency"
        ),
        "created_by_domain": "platform",
    },
    {
        "doc_type": "osha_report",
        "display_name": "OSHA Safety Report",
        "description": "OSHA (Occupational Safety and Health Administration) inspection reports, citations, workplace safety violations, and injury/illness records.",
        "extraction_schema": json.dumps([
            {"name": "inspection_date",       "description": "Date of the OSHA inspection or incident",                  "example": "2024-04-10"},
            {"name": "inspection_number",     "description": "OSHA inspection or citation number",                       "example": "OSHA-2024-GA-00145"},
            {"name": "employer_name",         "description": "Name of the employer or establishment inspected",          "example": "QuikTrip Corp - Store 145"},
            {"name": "violation_type",        "description": "OSHA violation type: WILLFUL, SERIOUS, REPEAT, or OTHER",  "example": "SERIOUS"},
            {"name": "standard_cited",        "description": "OSHA standard or CFR section cited",                      "example": "29 CFR 1910.303(b)(1)"},
            {"name": "hazard_description",    "description": "Description of the workplace hazard identified",           "example": "Electrical panels blocked, egress path obstructed"},
            {"name": "penalty_proposed",      "description": "Proposed penalty amount",                                  "example": "$13,653"},
            {"name": "abatement_date",        "description": "Required abatement (correction) deadline",                 "example": "2024-05-01"},
            {"name": "injury_type",           "description": "Type of injury if incident-related",                       "example": "Laceration requiring stitches"},
            {"name": "days_away",             "description": "Number of days away from work if applicable",              "example": "3"},
            {"name": "corrective_action",     "description": "Required corrective action to abate the hazard",           "example": "Clear blocked electrical panels, post egress signage"},
            {"name": "risk_level",            "description": "Risk: CRITICAL, HIGH, MEDIUM, or LOW",                    "example": "HIGH"},
        ]),
        "parse_instructions": (
            "Focus on: (1) OSHA standard numbers cited (29 CFR sections), "
            "(2) classification as Willful/Serious/Repeat/Other-than-Serious, "
            "(3) proposed penalty dollar amounts, "
            "(4) abatement dates (deadlines to fix hazards), "
            "(5) any OSHA 300 log entries for recordable incidents including days away, days restricted."
        ),
        "classification_examples": (
            "OSHA inspection|Occupational safety citation|Workplace safety violation|29 CFR|"
            "Serious violation|Willful citation|Penalty proposed|Abatement date|"
            "OSHA 300 log|Injury and illness|Recordable incident|Lockout tagout"
        ),
        "created_by_domain": "platform",
    },
    {
        "doc_type": "fire_safety_inspection",
        "display_name": "Fire Safety Inspection",
        "description": "Fire marshal or fire department inspection reports documenting fire code compliance, equipment status (extinguishers, sprinklers, exits), and required corrections.",
        "extraction_schema": json.dumps([
            {"name": "inspection_date",       "description": "Date of the fire safety inspection",                       "example": "2024-01-15"},
            {"name": "inspector_name",        "description": "Name of the fire marshal or inspector",                    "example": "Lt. K. Johnson"},
            {"name": "location_name",         "description": "Facility name and address inspected",                     "example": "Store 88, 500 Main St Atlanta"},
            {"name": "finding_description",   "description": "Description of the fire code deficiency found",            "example": "Fire extinguisher not inspected within 12 months"},
            {"name": "fire_code_section",     "description": "Fire code or NFPA section cited",                          "example": "NFPA 10 § 7.3.2"},
            {"name": "equipment_status",      "description": "Status of specific equipment: PASS, FAIL, or N/A",         "example": "FAIL"},
            {"name": "corrective_action",     "description": "Required corrective action",                               "example": "Replace and recertify fire extinguisher immediately"},
            {"name": "deadline",              "description": "Deadline for correction",                                   "example": "Immediate / 24 hours"},
            {"name": "inspection_result",     "description": "Overall result: PASS, FAIL, or CONDITIONAL",               "example": "FAIL"},
            {"name": "follow_up_required",    "description": "Whether a re-inspection is required: YES or NO",           "example": "YES"},
            {"name": "risk_level",            "description": "Risk level: CRITICAL, HIGH, MEDIUM, or LOW",               "example": "CRITICAL"},
        ]),
        "parse_instructions": (
            "Focus on: (1) specific equipment failures — extinguishers, sprinklers, exit signs, smoke detectors, "
            "(2) NFPA or local fire code sections cited, "
            "(3) immediate vs. scheduled correction requirements, "
            "(4) overall pass/fail result and re-inspection requirements, "
            "(5) life-safety vs. administrative deficiencies."
        ),
        "classification_examples": (
            "Fire inspection|Fire marshal inspection|Fire extinguisher|Sprinkler system|Exit sign|"
            "NFPA compliance|Fire code violation|Smoke detector|Emergency lighting|"
            "Certificate of occupancy|Fire safety deficiency|Re-inspection required"
        ),
        "created_by_domain": "platform",
    },
    {
        "doc_type": "permit",
        "display_name": "Operating Permit / License",
        "description": "Government-issued operating permits, environmental permits, business licenses, and regulatory approvals with expiration dates and conditions.",
        "extraction_schema": json.dumps([
            {"name": "permit_number",        "description": "Permit or license number assigned by the authority",        "example": "UST-GA-2024-0145"},
            {"name": "permit_type",          "description": "Type of permit: OPERATING, ENVIRONMENTAL, FOOD_SERVICE, etc.", "example": "ENVIRONMENTAL"},
            {"name": "issuing_authority",    "description": "Agency or authority that issued the permit",                "example": "Georgia EPD"},
            {"name": "holder_name",          "description": "Business or individual the permit is issued to",            "example": "QuikTrip Corp - Store 145"},
            {"name": "issue_date",           "description": "Date the permit was issued or last renewed",                "example": "2024-01-01"},
            {"name": "expiration_date",      "description": "Date the permit expires or must be renewed",                "example": "2025-01-01"},
            {"name": "conditions",           "description": "Key conditions or restrictions attached to the permit",     "example": "Monthly UST monitoring required"},
            {"name": "regulated_activity",   "description": "Activity authorized by the permit",                         "example": "Underground storage of petroleum products"},
            {"name": "location_address",     "description": "Address or facility the permit covers",                    "example": "1234 Highway Blvd, Atlanta GA 30301"},
            {"name": "renewal_status",       "description": "Renewal status: CURRENT, EXPIRED, PENDING, RENEWAL_DUE",   "example": "RENEWAL_DUE"},
            {"name": "risk_level",           "description": "Risk if permit lapses: CRITICAL, HIGH, MEDIUM, or LOW",    "example": "HIGH"},
        ]),
        "parse_instructions": (
            "Focus on: (1) permit/license number and issuing authority, "
            "(2) expiration and renewal dates — these drive action triggers, "
            "(3) specific conditions or restrictions tied to the permit, "
            "(4) regulated activities authorized, "
            "(5) any compliance conditions that must be maintained to keep the permit active."
        ),
        "classification_examples": (
            "Permit issued|License granted|Environmental permit|Operating license|"
            "Expiration date|Renewal required|Permit conditions|Issued by agency|"
            "Certificate of compliance|UST permit|Food service permit|Business license"
        ),
        "created_by_domain": "platform",
    },
    {
        "doc_type": "regulatory_change_notice",
        "display_name": "Regulatory Change Notice",
        "description": "Notifications of new, amended, or repealed regulations from federal, state, or local authorities requiring operational or compliance changes.",
        "extraction_schema": json.dumps([
            {"name": "regulation_name",      "description": "Name or title of the regulation being changed",             "example": "EPA UST Regulation 40 CFR Part 280"},
            {"name": "change_type",          "description": "Type of change: NEW, AMENDED, REPEALED, or CLARIFICATION",  "example": "AMENDED"},
            {"name": "statute_number",       "description": "Statute, CFR section, or rule number",                      "example": "40 CFR § 280.45"},
            {"name": "effective_date",       "description": "Date the change takes effect",                              "example": "2025-06-01"},
            {"name": "compliance_deadline",  "description": "Deadline by which businesses must comply",                  "example": "2025-12-31"},
            {"name": "issuing_authority",    "description": "Federal agency, state, or local authority issuing the change", "example": "U.S. Environmental Protection Agency"},
            {"name": "jurisdiction",         "description": "Geographic jurisdiction: FEDERAL, STATE (specify), or LOCAL", "example": "Federal"},
            {"name": "impact_summary",       "description": "Summary of how this change impacts operations",              "example": "All UST owners must install secondary containment by Dec 2025"},
            {"name": "affected_operations",  "description": "Which operations or locations are affected",                "example": "All stores with underground storage tanks"},
            {"name": "required_action",      "description": "Specific action required to comply",                        "example": "Install secondary containment; update monitoring procedures"},
            {"name": "risk_level",           "description": "Non-compliance risk: CRITICAL, HIGH, MEDIUM, or LOW",       "example": "HIGH"},
        ]),
        "parse_instructions": (
            "Focus on: (1) the exact regulatory citation (CFR, state code), "
            "(2) effective and compliance deadline dates, "
            "(3) distinction between AMENDED vs. NEW requirements, "
            "(4) specific operational changes required (equipment, procedures, reporting), "
            "(5) penalties or consequences for non-compliance."
        ),
        "classification_examples": (
            "Regulatory update|Amended regulation|New requirement|Federal Register|"
            "Compliance deadline|Effective date|CFR amended|Rule change|"
            "Agency notice|Rulemaking|State regulation update|Compliance obligation"
        ),
        "created_by_domain": "platform",
    },
    {
        "doc_type": "audit_finding",
        "display_name": "Audit Finding Report",
        "description": "Internal or external audit reports documenting compliance gaps, operational deficiencies, and recommendations for improvement.",
        "extraction_schema": json.dumps([
            {"name": "audit_date",           "description": "Date the audit was conducted",                              "example": "2024-03-01"},
            {"name": "auditor_name",         "description": "Name of the auditor or audit firm",                         "example": "Ernst & Young LLP"},
            {"name": "audit_type",           "description": "Type of audit: COMPLIANCE, OPERATIONAL, FINANCIAL, SAFETY", "example": "COMPLIANCE"},
            {"name": "finding_id",           "description": "Finding identifier or reference number",                    "example": "AUD-2024-045"},
            {"name": "finding_category",     "description": "Category of finding: CRITICAL, SIGNIFICANT, OBSERVATION",  "example": "SIGNIFICANT"},
            {"name": "finding_description",  "description": "Full description of the audit finding",                     "example": "Lack of documented training records for food safety procedures"},
            {"name": "root_cause",           "description": "Root cause of the finding if identified",                   "example": "No formal onboarding training program"},
            {"name": "recommendation",       "description": "Auditor recommendation to address the finding",            "example": "Implement documented training program with sign-off sheets"},
            {"name": "management_response",  "description": "Management's agreed corrective action",                    "example": "Training program rollout by Q2 2024"},
            {"name": "due_date",             "description": "Target date for resolution",                                "example": "2024-06-30"},
            {"name": "location",             "description": "Location or business unit audited",                         "example": "Southeast Region"},
            {"name": "risk_level",           "description": "Audit risk rating: CRITICAL, HIGH, MEDIUM, or LOW",        "example": "HIGH"},
        ]),
        "parse_instructions": (
            "Focus on: (1) finding category/severity — Critical/Significant/Observation ratings, "
            "(2) root cause analysis when provided, "
            "(3) management response and committed actions with due dates, "
            "(4) repeat findings from prior audits (if noted), "
            "(5) auditor's overall opinion or conclusion."
        ),
        "classification_examples": (
            "Audit report|Internal audit|External audit|Audit finding|Compliance gap|"
            "Management response|Corrective action committed|Auditor recommendation|"
            "Control deficiency|Material weakness|Observation|Audit conclusion"
        ),
        "created_by_domain": "platform",
    },
    # ── Cross-Domain / Operations ─────────────────────────────────────────────
    {
        "doc_type": "corrective_action_plan",
        "display_name": "Corrective Action Plan (CAP)",
        "description": "Formal plans documenting specific corrective actions to address inspection findings, violations, audit deficiencies, or safety incidents.",
        "extraction_schema": json.dumps([
            {"name": "cap_number",           "description": "CAP reference or tracking number",                          "example": "CAP-2024-0088"},
            {"name": "source_finding",       "description": "Finding, inspection, or incident that triggered this CAP",  "example": "Health Inspection Finding HI-2024-220"},
            {"name": "finding_description",  "description": "Description of the issue being corrected",                  "example": "UST monitoring system failure at Store 145"},
            {"name": "corrective_action",    "description": "Specific corrective action to be taken",                    "example": "Repair and recertify UST monitoring equipment"},
            {"name": "root_cause",           "description": "Identified root cause of the finding",                     "example": "Equipment not serviced per annual schedule"},
            {"name": "owner",                "description": "Person or role responsible for implementing the CAP",       "example": "District Facilities Manager"},
            {"name": "start_date",           "description": "Date corrective action implementation begins",              "example": "2024-03-15"},
            {"name": "completion_date",      "description": "Target completion date",                                    "example": "2024-04-15"},
            {"name": "verification_method",  "description": "How completion will be verified",                           "example": "Regulator re-inspection confirmation"},
            {"name": "status",               "description": "Current CAP status: OPEN, IN_PROGRESS, COMPLETED, OVERDUE", "example": "IN_PROGRESS"},
            {"name": "evidence_required",    "description": "Type of evidence needed to close the CAP",                  "example": "Signed maintenance record and re-inspection certificate"},
            {"name": "priority",             "description": "Priority: CRITICAL, HIGH, MEDIUM, or LOW",                 "example": "HIGH"},
        ]),
        "parse_instructions": (
            "Focus on: (1) the specific corrective action steps and responsibilities, "
            "(2) start and completion dates — these create action deadlines, "
            "(3) who is accountable (owner/assignee), "
            "(4) how completion will be verified (evidence requirements), "
            "(5) current status and any escalation triggers."
        ),
        "classification_examples": (
            "Corrective action plan|CAP|Remediation plan|Action plan|"
            "Root cause analysis|Corrective measure|Implementation plan|"
            "Compliance remediation|Owner assigned|Due date|Verification method|"
            "Finding resolution|Action tracking"
        ),
        "created_by_domain": "platform",
    },
    {
        "doc_type": "incident_report",
        "display_name": "Operational Incident Report",
        "description": "Reports of workplace accidents, safety incidents, equipment failures, customer incidents, or near-miss events requiring investigation and corrective action.",
        "extraction_schema": json.dumps([
            {"name": "incident_date",         "description": "Date and time the incident occurred",                      "example": "2024-03-15 14:30"},
            {"name": "incident_type",         "description": "Category: INJURY, PROPERTY_DAMAGE, ENVIRONMENTAL, NEAR_MISS", "example": "INJURY"},
            {"name": "location",              "description": "Location where the incident occurred",                    "example": "Store 145 - Fuel canopy"},
            {"name": "description",           "description": "Full description of what happened",                       "example": "Employee slipped on wet floor near fuel pump"},
            {"name": "persons_involved",      "description": "Names or roles of persons involved",                      "example": "Store associate, customer"},
            {"name": "injury_type",           "description": "Type of injury if applicable",                            "example": "Knee laceration"},
            {"name": "days_away",             "description": "Days away from work if applicable",                        "example": "2"},
            {"name": "root_cause",            "description": "Identified or suspected root cause",                      "example": "No wet floor sign posted after mopping"},
            {"name": "immediate_action",      "description": "Immediate action taken at time of incident",              "example": "First aid administered, area secured"},
            {"name": "corrective_action",     "description": "Corrective action to prevent recurrence",                 "example": "New wet floor sign policy, retraining"},
            {"name": "recordable",            "description": "OSHA recordable: YES or NO",                              "example": "YES"},
            {"name": "risk_level",            "description": "Severity: CRITICAL, HIGH, MEDIUM, or LOW",                "example": "HIGH"},
        ]),
        "parse_instructions": (
            "Focus on: (1) incident date/time and exact location, "
            "(2) type of incident and any injuries (including severity), "
            "(3) root cause determination, "
            "(4) immediate actions taken and planned corrective actions, "
            "(5) OSHA recordability classification."
        ),
        "classification_examples": (
            "Incident report|Safety incident|Workplace accident|Near miss|"
            "Injury report|Property damage|Environmental release|Spill incident|"
            "Root cause analysis|Corrective action required|OSHA recordable|"
            "Workers compensation|First aid|Investigation findings"
        ),
        "created_by_domain": "platform",
    },
    # ── Supply Chain ──────────────────────────────────────────────────────────
    {
        "doc_type": "delivery_manifest",
        "display_name": "Delivery Manifest / Shipment Record",
        "description": "Records of product deliveries including shipment details, lot numbers, temperature logs, quantity received, and delivery confirmation.",
        "extraction_schema": json.dumps([
            {"name": "shipment_id",          "description": "Shipment, PO, or bill of lading number",                   "example": "SHP-20240315-001"},
            {"name": "supplier_name",        "description": "Name of the supplier or carrier",                          "example": "Tyson Foods Inc."},
            {"name": "delivery_date",        "description": "Date and time of delivery",                                "example": "2024-03-15 09:30"},
            {"name": "receiving_location",   "description": "Store or DC receiving the shipment",                       "example": "Store 145, Atlanta GA"},
            {"name": "product_description",  "description": "Description of products delivered",                        "example": "Chicken Breast 8lb bags, Lot #CH-240315"},
            {"name": "lot_number",           "description": "Lot or batch number for traceability",                     "example": "CH-240315-A"},
            {"name": "quantity_received",    "description": "Quantity and unit of product received",                    "example": "48 cases"},
            {"name": "temperature_at_receipt","description": "Temperature measured at time of receipt",                 "example": "38°F"},
            {"name": "temperature_threshold","description": "Required temperature threshold",                            "example": "41°F maximum"},
            {"name": "sla_status",           "description": "SLA compliance: PASS or FAIL",                             "example": "PASS"},
            {"name": "discrepancy",          "description": "Any shortage, damage, or quality issue noted",             "example": "3 cases damaged packaging"},
            {"name": "receiver_name",        "description": "Name of the person who received the delivery",             "example": "J. Smith, Assistant Manager"},
        ]),
        "parse_instructions": (
            "Focus on: (1) shipment and lot number for traceability, "
            "(2) temperature readings at receipt vs. required thresholds, "
            "(3) quantity received vs. ordered discrepancies, "
            "(4) any noted quality issues, damage, or refusals, "
            "(5) receiver signature and timestamp."
        ),
        "classification_examples": (
            "Delivery manifest|Shipment record|Bill of lading|Receiving log|"
            "Temperature at receipt|Lot number|Supplier delivery|"
            "Quantity received|Delivery confirmation|Product received|Driver signature"
        ),
        "created_by_domain": "platform",
    },
    {
        "doc_type": "quality_inspection_report",
        "display_name": "Supplier Quality Inspection",
        "description": "Quality control inspection reports for supplier products including lab test results, sensory evaluations, specification compliance, and pass/fail determinations.",
        "extraction_schema": json.dumps([
            {"name": "inspection_date",      "description": "Date quality inspection was performed",                    "example": "2024-03-16"},
            {"name": "supplier_name",        "description": "Supplier or manufacturer name",                            "example": "Tyson Foods Inc."},
            {"name": "product_name",         "description": "Product name and SKU inspected",                           "example": "Chicken Breast 8lb - SKU 44521"},
            {"name": "lot_number",           "description": "Lot or batch number inspected",                            "example": "CH-240315-A"},
            {"name": "inspection_type",      "description": "Type of inspection: INCOMING, IN_PROCESS, FINAL, or AUDIT", "example": "INCOMING"},
            {"name": "sample_size",          "description": "Number of units sampled",                                  "example": "10 of 48 cases"},
            {"name": "test_parameters",      "description": "Parameters tested (temperature, color, weight, etc.)",     "example": "Temperature, pH, visual inspection"},
            {"name": "test_results",         "description": "Key test results with values",                             "example": "pH: 5.8 (spec 5.5-6.2), Temp: 38°F"},
            {"name": "specification_status", "description": "Meets spec: PASS, FAIL, or CONDITIONAL",                  "example": "PASS"},
            {"name": "defects_found",        "description": "Description of any defects or non-conformances found",     "example": "2 units with damaged packaging"},
            {"name": "disposition",          "description": "Product disposition: ACCEPTED, REJECTED, or HOLD",         "example": "ACCEPTED"},
            {"name": "inspector_name",       "description": "QC inspector name or ID",                                  "example": "QC Inspector R. Torres"},
        ]),
        "parse_instructions": (
            "Focus on: (1) specific test parameters and their measured vs. specification values, "
            "(2) pass/fail determination for each parameter, "
            "(3) sample size and sampling method, "
            "(4) final disposition (accept/reject/hold), "
            "(5) any corrective action or hold requirements."
        ),
        "classification_examples": (
            "Quality inspection|QC report|Incoming inspection|Lab test results|"
            "Specification compliance|Pass/fail|Product inspection|Sample tested|"
            "Non-conformance|Defect found|Product hold|Supplier quality|Certificate of conformance"
        ),
        "created_by_domain": "platform",
    },
    {
        "doc_type": "certificate_of_analysis",
        "display_name": "Certificate of Analysis (COA)",
        "description": "Lab-issued quality certificates confirming that a product lot meets specified quality, safety, and regulatory requirements.",
        "extraction_schema": json.dumps([
            {"name": "coa_number",           "description": "Certificate of Analysis reference number",                 "example": "COA-2024-CH-8821"},
            {"name": "product_name",         "description": "Product name and description",                             "example": "Chicken Breast Fillet - Natural"},
            {"name": "lot_number",           "description": "Production lot or batch number",                           "example": "CH-240315-A"},
            {"name": "manufacturer",         "description": "Manufacturing facility or supplier name",                   "example": "Tyson Foods - Springdale Facility"},
            {"name": "production_date",      "description": "Production or manufacturing date",                         "example": "2024-03-15"},
            {"name": "expiration_date",      "description": "Product expiration or best-by date",                       "example": "2024-04-15"},
            {"name": "test_methods",         "description": "Testing standards or methods used",                         "example": "USDA FSIS, AOAC 2003.02"},
            {"name": "microbial_results",    "description": "Microbial test results (Salmonella, Listeria, E. coli)",    "example": "Salmonella: Negative; E. coli: <10 CFU/g"},
            {"name": "chemical_results",     "description": "Chemical parameter results",                                "example": "Moisture: 72.3% (spec max 75%)"},
            {"name": "conformance_status",   "description": "Overall conformance: PASS, FAIL, or CONDITIONAL",          "example": "PASS"},
            {"name": "certifying_lab",       "description": "Laboratory that performed testing",                         "example": "NSF International - Atlanta Lab"},
            {"name": "certifying_signature", "description": "Name and title of certifying official",                    "example": "Dr. A. Chen, QA Director"},
        ]),
        "parse_instructions": (
            "Focus on: (1) microbial and chemical test results with units and specification limits, "
            "(2) production lot number and expiration date for traceability, "
            "(3) testing methods and standards applied, "
            "(4) overall conformance conclusion, "
            "(5) certifying lab and signatory."
        ),
        "classification_examples": (
            "Certificate of analysis|COA|Lab report|Test results|Lot number|"
            "Salmonella negative|E. coli|Microbial testing|Specification compliance|"
            "Passed testing|Product conforms|Quality certificate|Laboratory results"
        ),
        "created_by_domain": "platform",
    },
    {
        "doc_type": "recall_notice",
        "display_name": "Product Recall Notice",
        "description": "FDA, USDA, or supplier-issued product recall notices requiring identification and removal of affected products from inventory.",
        "extraction_schema": json.dumps([
            {"name": "recall_number",        "description": "Official recall reference number",                          "example": "FSIS-RC-2024-0042"},
            {"name": "issuing_authority",    "description": "Agency or company issuing the recall (FDA, USDA, supplier)", "example": "USDA FSIS"},
            {"name": "recall_class",         "description": "Recall class: CLASS_I (health hazard), CLASS_II, CLASS_III", "example": "CLASS_I"},
            {"name": "product_name",         "description": "Name and description of recalled product",                  "example": "Ready-to-Eat Chicken Salad 8oz"},
            {"name": "brand",                "description": "Brand name on recalled product",                           "example": "Deli Fresh"},
            {"name": "lot_numbers",          "description": "Affected lot/batch numbers",                               "example": "Lots CH-240301 through CH-240315"},
            {"name": "upc_codes",            "description": "Affected UPC or product codes",                            "example": "UPC 0-12345-67890-1"},
            {"name": "reason",               "description": "Reason for recall",                                        "example": "Potential Listeria monocytogenes contamination"},
            {"name": "recall_date",          "description": "Date recall was announced",                                 "example": "2024-03-20"},
            {"name": "affected_states",      "description": "States or regions where product was distributed",           "example": "GA, FL, SC, NC, TN"},
            {"name": "action_required",      "description": "Required action for retailers/consumers",                   "example": "Remove from sale, return to supplier for full credit"},
            {"name": "response_deadline",    "description": "Deadline to complete recall actions",                       "example": "2024-03-21"},
        ]),
        "parse_instructions": (
            "Focus on: (1) recall class — Class I (health hazard) requires immediate action, "
            "(2) exact lot numbers and UPC codes for product identification, "
            "(3) reason for recall (contamination type, allergen, foreign object), "
            "(4) action required and response deadline, "
            "(5) distribution scope (which states/stores are affected)."
        ),
        "classification_examples": (
            "Recall notice|Product recall|FDA recall|USDA recall|Class I recall|"
            "Remove from sale|Lot number recalled|Listeria|Salmonella|E. coli|"
            "Allergen undeclared|Consumer advisory|Voluntary recall|Market withdrawal"
        ),
        "created_by_domain": "platform",
    },
    # ── Legal & Contracts ─────────────────────────────────────────────────────
    {
        "doc_type": "contract",
        "display_name": "Service Contract / Agreement",
        "description": "Formal agreements between parties including service contracts, vendor agreements, supply agreements, and lease agreements with obligations, terms, and renewal dates.",
        "extraction_schema": json.dumps([
            {"name": "contract_number",      "description": "Contract identifier or reference number",                  "example": "CTR-2024-TYSON-001"},
            {"name": "contract_type",        "description": "Type: SERVICE, SUPPLY, LEASE, MAINTENANCE, or MASTER",     "example": "SUPPLY"},
            {"name": "party_1",              "description": "First contracting party (typically the company)",           "example": "QuikTrip Corporation"},
            {"name": "party_2",              "description": "Second contracting party (supplier/vendor/landlord)",       "example": "Tyson Foods Inc."},
            {"name": "effective_date",       "description": "Date the contract becomes effective",                       "example": "2024-01-01"},
            {"name": "expiration_date",      "description": "Contract expiration or end date",                           "example": "2025-12-31"},
            {"name": "renewal_terms",        "description": "Auto-renewal conditions or renewal notice period",          "example": "Auto-renews unless 90-day notice given"},
            {"name": "contract_value",       "description": "Total contract value or annual spend",                     "example": "$2,400,000 annually"},
            {"name": "key_obligations",      "description": "Primary obligations of each party",                         "example": "Supplier: deliver within 48 hours; Buyer: pay net-30"},
            {"name": "sla_terms",            "description": "Service level agreement terms or KPIs",                    "example": "98% on-time delivery; max 2°F temperature variance"},
            {"name": "termination_clause",   "description": "Conditions under which either party may terminate",         "example": "Either party may terminate with 60-day written notice"},
            {"name": "governing_law",        "description": "Governing law or jurisdiction",                             "example": "State of Georgia"},
        ]),
        "parse_instructions": (
            "Focus on: (1) contract parties, effective dates, and expiration/renewal dates, "
            "(2) key obligations and responsibilities for each party, "
            "(3) SLA terms, KPIs, and penalty clauses, "
            "(4) termination and renewal conditions, "
            "(5) governing law and dispute resolution provisions."
        ),
        "classification_examples": (
            "Service agreement|Supply contract|Master agreement|Vendor contract|"
            "Effective date|Expiration|Renewal terms|Terms and conditions|"
            "Party obligations|SLA requirements|Termination clause|Contract value"
        ),
        "created_by_domain": "platform",
    },
    {
        "doc_type": "nda",
        "display_name": "Non-Disclosure Agreement (NDA)",
        "description": "Confidentiality agreements protecting proprietary information shared between parties, including one-way and mutual NDAs.",
        "extraction_schema": json.dumps([
            {"name": "nda_number",           "description": "NDA reference number if assigned",                         "example": "NDA-2024-0088"},
            {"name": "nda_type",             "description": "Type: MUTUAL (both parties) or UNILATERAL (one-way)",       "example": "MUTUAL"},
            {"name": "disclosing_party",     "description": "Party disclosing confidential information",                 "example": "QuikTrip Corporation"},
            {"name": "receiving_party",      "description": "Party receiving and protecting confidential information",    "example": "TechVendor Solutions LLC"},
            {"name": "effective_date",       "description": "Date the NDA takes effect",                                "example": "2024-01-15"},
            {"name": "term_years",           "description": "Duration of the NDA in years",                             "example": "3 years"},
            {"name": "expiration_date",      "description": "NDA expiration date",                                       "example": "2027-01-15"},
            {"name": "confidential_info",    "description": "Types of information covered by the NDA",                  "example": "Trade secrets, pricing, customer lists, technology"},
            {"name": "permitted_disclosure", "description": "Permitted disclosures or exclusions",                       "example": "Publicly available information, required by law"},
            {"name": "penalty_clause",       "description": "Penalties for breach if specified",                         "example": "Injunctive relief; damages"},
            {"name": "governing_law",        "description": "Governing jurisdiction",                                    "example": "State of Georgia"},
        ]),
        "parse_instructions": (
            "Focus on: (1) whether NDA is mutual or one-directional, "
            "(2) specific types of confidential information covered, "
            "(3) term/duration and expiration date, "
            "(4) permitted disclosures and exclusions, "
            "(5) breach consequences and governing law."
        ),
        "classification_examples": (
            "Non-disclosure agreement|NDA|Confidentiality agreement|"
            "Proprietary information|Trade secrets|Mutual NDA|One-way NDA|"
            "Confidential information|Disclosure restrictions|Term of confidentiality"
        ),
        "created_by_domain": "platform",
    },
    {
        "doc_type": "statement_of_work",
        "display_name": "Statement of Work (SOW)",
        "description": "Formal documents defining the scope, deliverables, timeline, and costs for a specific project or service engagement.",
        "extraction_schema": json.dumps([
            {"name": "sow_number",           "description": "SOW reference or project number",                          "example": "SOW-2024-IT-0045"},
            {"name": "project_name",         "description": "Name of the project or engagement",                        "example": "POS System Upgrade Phase 2"},
            {"name": "vendor_name",          "description": "Vendor or service provider name",                          "example": "Oracle Corporation"},
            {"name": "client_name",          "description": "Client or buyer name",                                     "example": "QuikTrip IT Division"},
            {"name": "start_date",           "description": "Project start date",                                        "example": "2024-04-01"},
            {"name": "end_date",             "description": "Project completion date",                                   "example": "2024-09-30"},
            {"name": "deliverables",         "description": "Key deliverables listed in the SOW",                       "example": "System installation, training, 90-day support"},
            {"name": "total_cost",           "description": "Total project cost",                                        "example": "$450,000"},
            {"name": "payment_milestones",   "description": "Payment schedule tied to milestones",                      "example": "30% on start, 40% at mid-point, 30% on completion"},
            {"name": "acceptance_criteria",  "description": "Criteria for accepting deliverables",                      "example": "System live and stable for 30 days"},
            {"name": "change_order_process", "description": "Process for handling scope changes",                        "example": "Written approval required for changes > $10,000"},
        ]),
        "parse_instructions": (
            "Focus on: (1) project scope boundaries — what is and isn't included, "
            "(2) specific deliverables with acceptance criteria, "
            "(3) milestones, timeline, and payment triggers, "
            "(4) change management process, "
            "(5) performance guarantees or SLAs."
        ),
        "classification_examples": (
            "Statement of work|SOW|Project scope|Deliverables|Milestones|"
            "Project timeline|Acceptance criteria|Payment schedule|"
            "Scope of services|Work order|Task order|Professional services"
        ),
        "created_by_domain": "platform",
    },
    {
        "doc_type": "amendment",
        "display_name": "Contract Amendment / Addendum",
        "description": "Formal modifications to existing contracts, NDAs, or agreements that change specific terms, pricing, scope, or duration.",
        "extraction_schema": json.dumps([
            {"name": "amendment_number",     "description": "Amendment or addendum reference number",                   "example": "AMD-CTR-2024-TYSON-001-A1"},
            {"name": "original_contract",    "description": "Reference to the original contract being amended",          "example": "CTR-2024-TYSON-001"},
            {"name": "effective_date",       "description": "Date this amendment takes effect",                          "example": "2024-06-01"},
            {"name": "parties",              "description": "Parties to the amendment",                                  "example": "QuikTrip Corporation and Tyson Foods Inc."},
            {"name": "change_summary",       "description": "Summary of what is being changed",                          "example": "Extends contract term by 12 months; updates pricing schedule"},
            {"name": "original_term",        "description": "Original provision being replaced",                         "example": "Contract expires 2024-12-31"},
            {"name": "new_term",             "description": "New provision replacing the original",                      "example": "Contract now expires 2025-12-31"},
            {"name": "price_change",         "description": "Any pricing change, if applicable",                         "example": "+3.5% annual price increase effective Jan 1"},
            {"name": "reason_for_change",    "description": "Business reason for the amendment",                         "example": "Market conditions; mutual agreement to extend"},
            {"name": "remaining_unchanged",  "description": "Confirmation that all other terms remain unchanged",        "example": "All other terms and conditions remain in full force"},
        ]),
        "parse_instructions": (
            "Focus on: (1) which original contract is being amended and what amendment number this is, "
            "(2) the specific original text being replaced vs. the new replacement text, "
            "(3) effective date of the amendment, "
            "(4) any pricing or scope changes, "
            "(5) confirmation that remaining terms are unchanged."
        ),
        "classification_examples": (
            "Amendment|Contract amendment|Addendum|Modification|Change order|"
            "Amends the agreement|Effective as of|Original contract|"
            "As modified herein|All other terms unchanged|Exhibit amended"
        ),
        "created_by_domain": "platform",
    },
    # ── Cross-Domain / General ────────────────────────────────────────────────
    {
        "doc_type": "correspondence",
        "display_name": "Official Correspondence",
        "description": "Formal letters, notices, and official communications from regulatory agencies, legal counsel, vendors, or customers requiring action or acknowledgement.",
        "extraction_schema": json.dumps([
            {"name": "correspondence_date",  "description": "Date on the letter or communication",                      "example": "2024-03-15"},
            {"name": "sender_name",          "description": "Name and organization of the sender",                      "example": "Georgia EPD - Waste Management Division"},
            {"name": "sender_role",          "description": "Role of the sender (Regulator, Vendor, Customer, Legal)",  "example": "Environmental Regulator"},
            {"name": "recipient_name",       "description": "Name of the recipient",                                    "example": "Compliance Manager, QuikTrip Corp"},
            {"name": "subject",              "description": "Subject line or purpose of the correspondence",             "example": "Notice of Violation - UST Monitoring Failure"},
            {"name": "correspondence_type",  "description": "Type: NOV, DEMAND_LETTER, NOTICE, INQUIRY, APPROVAL",      "example": "NOV"},
            {"name": "key_request",          "description": "Primary action requested from the recipient",               "example": "Submit remediation plan within 30 days"},
            {"name": "deadline",             "description": "Response or action deadline stated in the correspondence",  "example": "April 15, 2024"},
            {"name": "reference_numbers",    "description": "Any permit, case, or reference numbers cited",             "example": "Case No. EPD-2024-WM-0088"},
            {"name": "urgency",              "description": "Urgency level: URGENT, STANDARD, or INFORMATIONAL",        "example": "URGENT"},
            {"name": "response_required",    "description": "Whether a formal response is required: YES or NO",          "example": "YES"},
        ]),
        "parse_instructions": (
            "Focus on: (1) who sent the letter and their authority/role, "
            "(2) specific action or response being requested, "
            "(3) stated deadlines for response or action, "
            "(4) reference to regulatory citations, case numbers, or prior correspondence, "
            "(5) urgency cues (notice of violation, demand letter, legal notice)."
        ),
        "classification_examples": (
            "Official letter|Notice of violation|NOV|Demand letter|Agency notice|"
            "Response required|Action required by|Regulatory correspondence|"
            "Legal notice|Please respond by|In reference to|Pursuant to regulation"
        ),
        "created_by_domain": "platform",
    },
    {
        "doc_type": "invoice",
        "display_name": "Invoice / Billing Document",
        "description": "Supplier or vendor invoices for goods and services delivered, including payment terms, line items, taxes, and due dates.",
        "extraction_schema": json.dumps([
            {"name": "invoice_number",       "description": "Invoice reference number",                                 "example": "INV-2024-TYS-8821"},
            {"name": "invoice_date",         "description": "Date the invoice was issued",                              "example": "2024-03-15"},
            {"name": "vendor_name",          "description": "Vendor or supplier name issuing the invoice",              "example": "Tyson Foods Inc."},
            {"name": "bill_to",              "description": "Entity being billed",                                      "example": "QuikTrip Corporation - Accounts Payable"},
            {"name": "po_number",            "description": "Related purchase order number",                            "example": "PO-2024-031500"},
            {"name": "line_items",           "description": "Summary of products or services billed",                   "example": "Chicken Breast 8lb x 48 cases @ $42.50 = $2,040"},
            {"name": "subtotal",             "description": "Pre-tax subtotal amount",                                  "example": "$8,450.00"},
            {"name": "tax_amount",           "description": "Tax amount if applicable",                                  "example": "$0.00 (food exemption)"},
            {"name": "total_due",            "description": "Total amount due",                                          "example": "$8,450.00"},
            {"name": "payment_terms",        "description": "Payment terms (net-30, net-60, etc.)",                      "example": "Net 30"},
            {"name": "due_date",             "description": "Payment due date",                                          "example": "2024-04-14"},
            {"name": "payment_method",       "description": "Accepted payment methods",                                  "example": "ACH, Check"},
        ]),
        "parse_instructions": (
            "Focus on: (1) invoice number, date, and vendor details, "
            "(2) purchase order cross-reference number, "
            "(3) line items with quantities, unit prices, and totals, "
            "(4) payment terms and exact due date, "
            "(5) any early payment discounts or late payment penalties."
        ),
        "classification_examples": (
            "Invoice|Bill|Billing statement|Amount due|Payment terms|"
            "Net 30|Net 60|Due date|Remit to|Purchase order|"
            "Line items|Total amount|Tax invoice|Please pay by"
        ),
        "created_by_domain": "platform",
    },
]


@router.post("/seed-schema-library")
async def seed_schema_library(overwrite: bool = False):
    """
    Loads all 19 pre-built document type schemas derived from the
    docIntel-framework.md into jai_docintel.platform.doc_type_schemas.

    By default (overwrite=False), only inserts schemas that do not already
    exist — user-customized schemas are never overwritten.

    Pass ?overwrite=true to force-update all schemas (resets any edits).

    Returns: {seeded: N, skipped: N, total: N, doc_types: [...]}
    """
    _ensure_doc_type_table()
    seeded  = []
    skipped = []

    for schema in _PLATFORM_SCHEMA_LIBRARY:
        dt = schema["doc_type"]
        try:
            # Check if this doc_type already exists
            existing = run_sql(f"""
                SELECT doc_type FROM {CATALOG}.platform.doc_type_schemas
                WHERE doc_type = '{dt}'
                LIMIT 1
            """, timeout_secs=15) or []

            if existing and not overwrite:
                skipped.append(dt)
                continue

            # Escape all string values for SQL
            def esc(v: str) -> str:
                return v.replace("'", "''") if v else ""

            display_esc = esc(schema.get("display_name", dt.replace("_"," ").title()))
            desc_esc    = esc(schema.get("description", ""))
            es_esc      = esc(schema.get("extraction_schema", ""))
            pi_esc      = esc(schema.get("parse_instructions", ""))
            ce_esc      = esc(schema.get("classification_examples", ""))
            domain_esc  = esc(schema.get("created_by_domain", "platform"))

            if existing and overwrite:
                run_sql(f"""
                    UPDATE {CATALOG}.platform.doc_type_schemas
                    SET display_name          = '{display_esc}',
                        description           = '{desc_esc}',
                        extraction_schema     = '{es_esc}',
                        parse_instructions    = '{pi_esc}',
                        classification_examples = '{ce_esc}',
                        created_by_domain     = '{domain_esc}',
                        updated_at            = current_timestamp()
                    WHERE doc_type = '{dt}'
                """, timeout_secs=30)
            else:
                run_sql(f"""
                    INSERT INTO {CATALOG}.platform.doc_type_schemas
                        (doc_type, display_name, description, extraction_schema,
                         parse_instructions, classification_examples,
                         created_by_domain, updated_at)
                    VALUES ('{dt}', '{display_esc}', '{desc_esc}', '{es_esc}',
                            '{pi_esc}', '{ce_esc}', '{domain_esc}',
                            current_timestamp())
                """, timeout_secs=30)
            seeded.append(dt)
        except Exception as e:
            print(f"[seed_schema] Failed for {dt}: {e}")
            skipped.append(f"{dt} (ERROR: {str(e)[:100]})")

    return {
        "seeded":    len(seeded),
        "skipped":   len(skipped),
        "total":     len(_PLATFORM_SCHEMA_LIBRARY),
        "doc_types_seeded":  seeded,
        "doc_types_skipped": skipped,
    }
