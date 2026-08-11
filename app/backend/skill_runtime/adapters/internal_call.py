"""Internal-call adapter. Resolves the implementation name to a registered
Python callable in ctx.internal. The callable owns its own side effects
(e.g. writing DRAFT actions to platform.action_master)."""
from __future__ import annotations

from .base import Adapter, Context
from ..models import Evidence, SkillError


class InternalCallAdapter(Adapter):
    def execute(self, contract, inputs: dict, ctx: Context):
        fn = ctx.internal.get(contract.implementation)
        if fn is None:
            raise SkillError(
                f"internal callable '{contract.implementation}' not registered")
        result = fn(inputs, ctx)
        # callable may return (outputs, evidence) or just outputs
        if isinstance(result, tuple) and len(result) == 2:
            outputs, evidence = result
        else:
            outputs, evidence = result, []
        evidence = [e if isinstance(e, Evidence) else Evidence(**e)
                    for e in (evidence or [])]
        return outputs or {}, evidence
