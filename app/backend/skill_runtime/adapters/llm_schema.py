"""LLM-with-schema adapter. Renders the skill's prompt file with the inputs,
calls ctx.chat_completion, parses JSON constrained to the contract's outputs,
and lifts any returned evidence to Evidence objects. Never fabricates: if the
model returns status 'insufficient_evidence' that is a first-class result."""
from __future__ import annotations

import json
import os
import re

from .base import Adapter, Context
from ..models import Evidence, SkillError

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LLMSchemaAdapter(Adapter):
    def execute(self, contract, inputs: dict, ctx: Context):
        if ctx.chat_completion is None:
            raise SkillError("chat_completion seam not configured")
        prompt = self._render(contract.implementation, inputs)
        raw = ctx.chat_completion(prompt)
        data = _extract_json(raw)
        if data is None:
            snippet = (raw or "").strip().replace("\n", " ")[:180] or "(empty response)"
            raise SkillError(f"{contract.id}: model did not return JSON — got: {snippet}")
        evidence = [_coerce_evidence(e) for e in (data.get("evidence") or [])]
        # keep evidence in outputs as dicts too (schema declares it)
        if "evidence" in contract.outputs:
            data["evidence"] = [e.to_dict() for e in evidence]
        return data, evidence

    def _render(self, impl: str, inputs: dict) -> str:
        path = impl if os.path.isabs(impl) else os.path.join(_HERE, impl)
        with open(path) as f:
            tmpl = f.read()
        out = tmpl
        for k, v in inputs.items():
            out = out.replace("{" + k + "}", _fmt(v))
        # blank any unfilled placeholders
        out = re.sub(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", "", out)
        return out


def _coerce_evidence(e):
    """Normalize a model-returned evidence item to an Evidence object.

    The model may return a dict (mapped by keyword), a plain string (treated as
    source_text), or an already-constructed Evidence. Unknown dict keys are
    dropped so a stray field can't crash construction."""
    if isinstance(e, Evidence):
        return e
    if isinstance(e, str):
        return Evidence(document_id="", source_text=e)
    if isinstance(e, dict):
        allowed = {"document_id", "locator", "source_text", "confidence", "method"}
        kwargs = {k: v for k, v in e.items() if k in allowed}
        kwargs.setdefault("document_id", "")
        return Evidence(**kwargs)
    return Evidence(document_id="", source_text=str(e))


def _fmt(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _extract_json(text: str):
    if not text:
        return None
    # strip code fences
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # find first {...} block
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
