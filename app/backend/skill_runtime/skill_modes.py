"""Classify how each skill can be invoked, so the UI only offers valid actions.

Not every skill runs on a document. Given a skill's contract, decide:
  - runnable_on_docs: its required inputs can be satisfied from selected parsed
    documents (text-ish inputs) plus caller/domain-filled inputs.
  - manual_inputs: required inputs the user must supply directly (e.g. a search
    `query`, a `question`) — these are prompted before running.
  - blocked_reason: if a required input can be met neither from docs nor by a
    simple manual value (it must come from an upstream workflow step), the skill
    is not runnable standalone and we say why.

Kept deliberately in the runtime package (not the route) so it is unit-testable
offline and shared by /skills enrichment and /skill-invoke validation."""
from __future__ import annotations

# Inputs that a selected set of documents can fill (see doc_inputs._TEXT_KEYS).
DOC_TEXT_INPUTS = {"text", "context", "current", "previous", "conclusion"}
# Inputs the route fills from domain config / the run itself.
CALLER_FILLED = {"schema_vec", "domain", "project"}
# Required inputs a user can reasonably type in a small form before running.
# name -> {label, kind, placeholder}
MANUAL_INPUTS = {
    "query":        {"label": "Search phrase", "kind": "text",
                     "placeholder": "e.g. alcohol license renewal"},
    "question":     {"label": "Question", "kind": "text",
                     "placeholder": "Ask a question to answer from evidence"},
    "labels":       {"label": "Candidate labels (comma-separated)", "kind": "list",
                     "placeholder": "license, permit, correspondence"},
    "entity_types": {"label": "Entity types (comma-separated)", "kind": "list",
                     "placeholder": "person, org, address, date"},
    "doc_type":     {"label": "Restrict to doc type (optional)", "kind": "text",
                     "placeholder": "license_alcohol"},
}
# Inputs that can only come from an upstream workflow step's output — a skill
# that requires one of these cannot be run standalone on documents.
UPSTREAM_ONLY = {
    "gaps", "assessments", "findings", "risk", "recommendation",
    "proposed_actions", "action_id", "assigned_to", "work_object_id",
    "finding_type", "changes", "events", "requirements", "candidate_requirements",
    "affected_entities", "evidence", "resolution", "reason",
}


def classify_skill(contract) -> dict:
    """Return {runnable_on_docs, manual_inputs, blocked_reason, needs_docs}.

    manual_inputs is a list of {name, label, kind, placeholder, required}.
    """
    inputs = contract.inputs or {}
    required = [k for k, v in inputs.items() if (v or {}).get("required")]

    needs_docs = any(k in DOC_TEXT_INPUTS for k in required)
    manual: list = []
    blocked: list = []

    for name in required:
        if name in DOC_TEXT_INPUTS or name in CALLER_FILLED:
            continue
        if name in MANUAL_INPUTS:
            manual.append({"name": name, "required": True, **MANUAL_INPUTS[name]})
        elif name in UPSTREAM_ONLY:
            blocked.append(name)
        else:
            # unknown required input we can't source → treat as blocked so we
            # never silently run with a fabricated value
            blocked.append(name)

    # optional inputs that we know how to prompt for (nice-to-have, not required)
    for name, spec in inputs.items():
        if (spec or {}).get("required"):
            continue
        if name in MANUAL_INPUTS and name not in {m["name"] for m in manual}:
            manual.append({"name": name, "required": False, **MANUAL_INPUTS[name]})

    blocked_reason = ""
    runnable = not blocked
    if blocked:
        blocked_reason = (
            "needs " + ", ".join(sorted(set(blocked)))
            + " — produced by an earlier workflow step, so run this inside a workflow")

    return {
        "runnable_on_docs": runnable and needs_docs,
        "runnable": runnable,
        "needs_docs": needs_docs,
        "manual_inputs": manual,
        "blocked_reason": blocked_reason,
    }
