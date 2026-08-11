"""UC-function adapter. Wraps existing SQL-backed capabilities.

For `find_supporting_evidence` (implementation `_vs_search`) it calls the injected
`ctx.vs_search` seam (the existing ai_similarity retrieval) and normalizes rows to
Evidence. Other uc_function skills call a UC SQL function via ctx.run_sql.
"""
from __future__ import annotations

from .base import Adapter, Context
from ..models import Evidence, SkillError


class UCFunctionAdapter(Adapter):
    def execute(self, contract, inputs: dict, ctx: Context):
        impl = contract.implementation
        if impl == "_vs_search":
            if ctx.vs_search is None:
                raise SkillError("vs_search seam not configured")
            rows = ctx.vs_search(
                inputs["query"], inputs["schema_vec"],
                inputs.get("k", 6), inputs.get("doc_type"),
            ) or []
            evidence = [
                Evidence(
                    document_id=str(r.get("doc_id", r.get("chunk_id", ""))),
                    locator=str(r.get("chunk_id", "")),
                    source_text=str(r.get("chunk_to_retrieve", "")),
                    method="ai_similarity",
                )
                for r in rows
            ]
            return {"evidence": [e.to_dict() for e in evidence]}, evidence

        # Generic UC function call: SELECT * FROM impl(<args>)
        if ctx.run_sql is None:
            raise SkillError("run_sql seam not configured")
        args = ", ".join(_lit(v) for v in inputs.values())
        rows = ctx.run_sql(f"SELECT * FROM {impl}({args})") or []
        return {"rows": rows}, []


def _lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"
