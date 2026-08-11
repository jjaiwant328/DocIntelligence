# Component 6 — AI Agent Framework (reuse-aware) — PHASE 3

## Goal
Graduate from the single in-process agent to a **configurable Supervisor + specialized-agent** pattern, reusing existing wiring. MVP realizes the "4 agents" as tools (see Prompt 04); this component makes them first-class, optionally served.

## What already exists — DO NOT rebuild
- Single LangChain agent: `create_tool_calling_agent` + `AgentExecutor(max_iterations=6)` in `docintel_routes.py:agent_query` (~478); model fallback `_resolve_model` (~51, chain `databricks-claude-sonnet-4-5 → haiku → gpt-5 → opus`); VS `search_documents` tool.
- Copilot single-LLM path `copilot-query` (~3529) with forced structured sections + citations.
- UC-function tools registered in `notebooks/06_agent.py` (supply_chain bespoke; generic `get_entity_documents`, `get_extracted_fields_for_doc`).
- An MLflow pyfunc agent (`DocIntelChatModel`) is registered in nb 06 but **not** currently served/called by the app.

## Gap to fill
1. **Config-driven agent registry** in `platform.domain_configs` (e.g. `agents_config` JSON): per-domain list of `{name, role, system_prompt, tools[], knowledge_sources[]}` and a `supervisor` spec.
2. **Supervisor orchestration**: a router that dispatches a query to specialized agents (e.g. compliance: Municipality/Research, Historical Response, Action) and composes results. Start as an in-process orchestrator over the existing tools; graduate to deployed Mosaic AI / model-serving endpoints only if the demo needs true multi-endpoint separation.
3. Keep `agent_query`'s response contract (`answer, tools_used, vector_search_active, cited_docs, model`) so the frontend is unchanged.

## Deliverables
- `agents_config` on `domain_configs` + loader.
- Supervisor orchestrator + specialized-agent definitions (config-first).
- Optional: served endpoints per agent (only if warranted).

## Acceptance criteria
- Compliance Due Diligence answers a multi-part question by invoking ≥2 specialized agents and citing sources.
- Supply chain + single-agent path still work via the same endpoint contract.

## Constraints
Reuse `agent_query`, `_resolve_model`, UC tools, and Vector Search. Config over code. Backward compatible.
