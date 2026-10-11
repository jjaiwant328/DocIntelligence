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
            evidence = [_row_to_evidence(r) for r in rows]
            return {"evidence": [e.to_dict() for e in evidence]}, evidence

        # Generic UC function call: SELECT * FROM impl(<args>)
        if ctx.run_sql is None:
            raise SkillError("run_sql seam not configured")
        args = ", ".join(_lit(v) for v in inputs.values())
        rows = ctx.run_sql(f"SELECT * FROM {impl}({args})") or []
        return {"rows": rows}, []


def _row_to_evidence(r) -> Evidence:
    """Normalize a vs_search row to Evidence. `_vs_search` returns rows as LISTS
    `[chunk_id, doc_id, doc_type, chunk_to_retrieve]`; tolerate dict rows too."""
    if isinstance(r, (list, tuple)):
        chunk_id = r[0] if len(r) > 0 else ""
        doc_id = r[1] if len(r) > 1 else ""
        text = r[3] if len(r) > 3 else ""
        return Evidence(document_id=str(doc_id or chunk_id or ""),
                        locator=str(chunk_id or ""),
                        source_text=str(text or ""), method="ai_similarity")
    # dict row
    return Evidence(document_id=str(r.get("doc_id", r.get("chunk_id", ""))),
                    locator=str(r.get("chunk_id", "")),
                    source_text=str(r.get("chunk_to_retrieve", "")),
                    method="ai_similarity")


def _lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"
