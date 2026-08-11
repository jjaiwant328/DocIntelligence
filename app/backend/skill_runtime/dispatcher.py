"""Dispatcher — the single skill-invocation surface. Enforces the envelope:
validate input -> execute adapter -> validate output -> attach evidence -> log ->
return. Never raises for skill failures; returns SkillResult(status="error")."""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from .adapters import DEFAULT_ADAPTERS
from .adapters.base import Context
from .executions import ExecutionLogger, ExecutionRecord, now_iso
from .models import SkillResult, SkillError, InputError, OutputError


def _digest(inputs: dict) -> str:
    try:
        return hashlib.sha256(
            json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()[:16]
    except Exception:
        return ""


class Dispatcher:
    def __init__(self, registry, ctx: Context, adapters: Optional[dict] = None,
                 logger: Optional[ExecutionLogger] = None):
        self.registry = registry
        self.ctx = ctx
        self.adapters = adapters or DEFAULT_ADAPTERS
        self.logger = logger or ExecutionLogger()

    def invoke(self, skill_id: str, inputs: dict, wf_ctx: Optional[dict] = None) -> SkillResult:
        wf_ctx = wf_ctx or {}
        start = now_iso()
        rec = ExecutionRecord(
            skill_id=skill_id, start_time=start,
            workflow_id=wf_ctx.get("workflow_id", ""),
            workflow_version=wf_ctx.get("workflow_version", ""),
            work_object_id=wf_ctx.get("work_object_id", ""),
            inputs_digest=_digest(inputs),
        )
        try:
            contract = self.registry.get(skill_id)
            rec.skill_version = contract.version
            adapter = self.adapters.get(contract.adapter)
            if adapter is None:
                raise SkillError(f"no adapter '{contract.adapter}' for '{skill_id}'")

            contract.validate_inputs(inputs)
            outputs, evidence = adapter.execute(contract, inputs, self.ctx)
            contract.validate_outputs(outputs)

            status = outputs.get("status", "ok")
            if (contract.evidence_requirements == "required"
                    and not evidence and status not in ("insufficient_evidence",)):
                # required-evidence skill produced none: not an error, but flag
                status = outputs.get("status", "ok")

            result = SkillResult(status=status, outputs=outputs, evidence=evidence)
            rec.status = status
            rec.evidence_count = len(evidence)
            rec.model = (self.ctx.resolve_model() if (contract.adapter == "llm_schema"
                         and self.ctx.resolve_model) else None)
            return result
        except (InputError, OutputError, SkillError) as e:
            rec.status = "error"
            rec.error = str(e)
            return SkillResult(status="error", error=str(e))
        except Exception as e:  # unexpected — still return structured error
            rec.status = "error"
            rec.error = f"{type(e).__name__}: {e}"
            return SkillResult(status="error", error=rec.error)
        finally:
            rec.end_time = now_iso()
            self.logger.log(rec)
