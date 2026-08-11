"""Intent router — the agent's ONLY job in the deterministic architecture
(ADR-003). The LLM interprets a natural-language question into a structured
intent; it does NOT decide business logic or tool order. The workflow engine and
skills own all orchestration.

Three intents:
  - workflow_run:  run a template (e.g. due_diligence) for a project
  - skill_invoke:  invoke one named skill directly
  - conversational: no deterministic action — answer from retrieved context

Consequential actions (workflow steps that create actions, or create_action
itself) are flagged so the caller can require explicit confirmation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

# Skills that have side effects and therefore require confirmation before running.
CONSEQUENTIAL_SKILLS = {"create_action", "assign_action", "escalate_action",
                        "close_action"}


@dataclass
class Intent:
    kind: str                      # workflow_run | skill_invoke | conversational
    template: Optional[str] = None
    skill: Optional[str] = None
    project: Optional[str] = None
    params: dict = field(default_factory=dict)
    requires_confirmation: bool = False
    raw: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "template": self.template, "skill": self.skill,
                "project": self.project, "params": self.params,
                "requires_confirmation": self.requires_confirmation}


_PROMPT = """You are an intent router for a document-intelligence assistant.
Classify the user's request into ONE structured intent. Do not answer the
question or decide any steps — only classify.

Available templates: {templates}
Available skills: {skills}

User request: {question}

Return ONLY JSON:
{{"kind": "workflow_run|skill_invoke|conversational",
  "template": "<template id or null>",
  "skill": "<skill id or null>",
  "project": "<project/case name if the user named one, else null>",
  "confirm_action": <true if the user is asking to CREATE/ASSIGN/ESCALATE/CLOSE actions>}}

Rules:
- "run due diligence / assess / review <project>" => workflow_run, template due_diligence.
- "create the actions / log the actions" => skill_invoke, skill create_action, confirm_action true.
- Anything conversational or a plain question => conversational.
"""


def classify(question: str, chat_completion, templates: list, skills: list) -> Intent:
    """Use the LLM to classify intent. `chat_completion(prompt)->str` is injected."""
    prompt = (_PROMPT
              .replace("{templates}", ", ".join(templates))
              .replace("{skills}", ", ".join(skills))
              .replace("{question}", question))
    raw = chat_completion(prompt) or ""
    data = _extract_json(raw) or {}
    kind = data.get("kind", "conversational")
    if kind not in ("workflow_run", "skill_invoke", "conversational"):
        kind = "conversational"
    skill = data.get("skill")
    confirm = bool(data.get("confirm_action")) or (skill in CONSEQUENTIAL_SKILLS)
    return Intent(
        kind=kind,
        template=data.get("template") if kind == "workflow_run" else None,
        skill=skill if kind == "skill_invoke" else None,
        project=data.get("project"),
        requires_confirmation=confirm and kind != "conversational",
        raw=raw,
    )


def _extract_json(text: str):
    if not text:
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
