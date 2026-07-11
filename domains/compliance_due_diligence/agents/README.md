# agents/ — Compliance Due Diligence

Four agent capabilities for the `compliance_due_diligence` domain, wired as tools into the
existing LangChain `AgentExecutor` in `docintel_routes.py` / `notebooks/06_agent.py`.

## Tool summary

| Tool | Function name | Core reuse |
|---|---|---|
| **Intake** | `classify_feasibility_request` | `ai_classify` UC function + LLM extractor |
| **Research** | `research_municipal_requirements` | Vector Search index + ontology graph edges |
| **Historical Knowledge** | `recall_prior_responses` | Vector Search (historical_response) + `HAS_HISTORY_OF` edges |
| **Action** | `create_or_track_action` | `platform.action_master` + escalation engine |

See `tool_definitions.md` for full input/output contracts.

## Integration point

In `notebooks/06_agent.py`, these tools are added in the `else` branch (generic domains):

```python
if domain_id == "supply_chain":
    tools = [...supply_chain bespoke tools...]
else:
    tools = build_generic_tools(domain_id, domain_config)
    if domain_id == "compliance_due_diligence":
        tools += build_compliance_due_diligence_tools(domain_id, w, schema)
```

Graduate to a served Supervisor agent per `claude_prompts/06_agent_framework.md` in Phase 3.
