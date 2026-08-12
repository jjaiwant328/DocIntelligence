"""Map a set of parsed documents to a skill's declared inputs, so the UI can
apply a skill to the corpus without the user hand-writing JSON.

Pure logic (no DB): given a SkillContract and document rows (each a dict with at
least doc_id, doc_type, and text), fill the contract's required inputs. Text-ish
inputs get concatenated document text; a `query` input defaults to doc types;
`schema_vec` is filled by the caller (route) since it is domain-derived.
"""
from __future__ import annotations

from typing import Optional

from .models import InputError

# Contract input names that should receive concatenated document text.
_TEXT_KEYS = {"text", "context", "current", "previous", "conclusion"}
# Inputs the caller fills from domain config, not from docs.
_CALLER_FILLED = {"schema_vec"}


def _doc_text(row: dict) -> str:
    return str(row.get("text") or row.get("content")
               or row.get("chunk_to_retrieve") or "").strip()


def map_docs_to_inputs(contract, doc_rows: list,
                       base_inputs: Optional[dict] = None) -> dict:
    """Return an inputs dict for `contract` built from `doc_rows`.

    Raises InputError if there are no documents but the skill needs document text.
    `base_inputs` (e.g. schema_vec, project) are merged in and take precedence.
    """
    base_inputs = dict(base_inputs or {})
    rows = doc_rows or []
    joined = "\n\n---\n\n".join(t for t in (_doc_text(r) for r in rows) if t)
    doc_types = sorted({str(r.get("doc_type")) for r in rows if r.get("doc_type")})
    doc_ids = [str(r.get("doc_id")) for r in rows if r.get("doc_id")]

    out: dict = {}
    needs_text = False
    for name, spec in (contract.inputs or {}).items():
        spec = spec or {}
        if name in base_inputs:
            out[name] = base_inputs[name]
            continue
        if name in _CALLER_FILLED:
            continue  # caller supplies (or leaves for route default)
        if name in _TEXT_KEYS:
            needs_text = True
            out[name] = joined
        elif name == "query":
            out[name] = " ".join(doc_types) or base_inputs.get("project", "")
        elif name == "doc_ids":
            out[name] = doc_ids
        # other required inputs (arrays like evidence/gaps) are produced by
        # upstream steps in a workflow; for a single-skill invoke they stay unset
        # and the contract's validate_inputs will surface a clear error.

    # merge any remaining base inputs (project, etc.)
    for k, v in base_inputs.items():
        out.setdefault(k, v)

    if needs_text and not joined:
        raise InputError(
            f"{contract.id}: needs document text but no parsed documents were selected")
    return out
