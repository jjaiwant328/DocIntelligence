# prompts/ — Compliance Due Diligence

Prompt artifacts for the `compliance_due_diligence` domain.

## Files

| File | Stored in | Purpose |
|---|---|---|
| `agent_system_prompt.md` | `platform.domain_configs.agent_system_prompt` | LangChain system message for `agent_query` — compliance-teammate persona. |
| `suggested_questions.json` | `platform.domain_configs.suggested_questions` | Four canned questions surfaced in the UI chat input. |

## Agent persona summary

The agent follows a **Classify → Research → Recall Prior → Detect Change → Create/Track Actions**
workflow. It always cites sources, flags LOW CONFIDENCE when uncertain, and distinguishes OPEN
from SATISFIED requirements.

## Suggested questions

1. What are the requirements to open this store?
2. Have we answered this municipality before?
3. What changed since the last feasibility request for `<municipality>`?
4. What actions remain open for `<project>`?
