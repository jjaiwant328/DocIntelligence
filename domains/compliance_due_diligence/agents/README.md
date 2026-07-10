# agents/

The four capabilities, realized for the MVP as tools orchestrated by the existing `agent_query`
(`app/backend/docintel_routes.py`); graduate to a served Supervisor per
`claude_prompts/06_agent_framework.md` in Phase 3.

1. **Intake** — classify a feasibility request → `{request_type, project/store, municipality, priority}`.
2. **Research** — municipal requirements & licenses via Vector Search + `Municipality DEFINES` edges.
3. **Historical Knowledge** — prior responses for a municipality via `HAS_HISTORY_OF` / VS.
4. **Action** — create/track tasks via `POST /action-master` (+ escalation engine).
