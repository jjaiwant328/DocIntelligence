"""Deterministic workflow engine.

Runs a template's steps in order. Each step's inputs are resolved from an
`inputs_map` referencing $input.*, $domain.*, $docs.*, $steps.<id>.<key>, or a
literal. Supports bounded retries, halt-on-failure with partial history, and ONE
human approval gate before the step named in `approval_before`."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATES_DIR = os.path.join(_HERE, "templates")


def _walk(node, keys):
    """Walk nested dict keys (for $steps.<id>.<k>.<k2>...). Returns None if any
    level is missing or not a dict."""
    for k in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(k)
    return node


class ParamError(ValueError):
    """A declared run-time parameter is missing (required) or the wrong type."""


def _coerce_one(typ: str, val, spec: dict, name: str):
    if typ == "number":
        try:
            f = float(val)
            return int(f) if f.is_integer() else f
        except (TypeError, ValueError):
            raise ParamError(f"parameter '{name}' must be a number")
    if typ == "boolean":
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("1", "true", "yes", "on")
    if typ == "choice":
        opts = [str(o) for o in (spec.get("options") or [])]
        if opts and str(val) not in opts:
            raise ParamError(f"parameter '{name}' must be one of {opts}")
        return val
    if typ == "list":
        if isinstance(val, list):
            return val
        return [x.strip() for x in str(val).split(",") if x.strip()]
    return str(val)   # string, date → kept as string (ISO for date)


def coerce_params(declared: Optional[list], supplied: Optional[dict]) -> dict:
    """Validate + coerce run-time params ($param.*) against a template's `inputs`
    declaration: apply defaults, coerce types, enforce required + choice. Raises
    ParamError on a missing-required or ill-typed value."""
    supplied = supplied or {}
    out: dict = {}
    for spec in (declared or []):
        name = spec.get("name")
        if not name:
            continue
        typ = (spec.get("type") or "string").lower()
        provided = name in supplied and supplied[name] not in (None, "")
        if not provided:
            if spec.get("default") is not None:
                out[name] = spec["default"]
            elif spec.get("required"):
                raise ParamError(f"missing required parameter: '{name}'")
            else:
                out[name] = None
            continue
        out[name] = _coerce_one(typ, supplied[name], spec, name)
    return out


def _build_doc_context(docs: list) -> dict:
    """Collapse the workflow's document set into resolvable values.

    Mirrors doc_inputs.map_docs_to_inputs so a doc-consuming step gets the same
    concatenated text whether run standalone or inside a workflow."""
    rows = docs or []
    def _text(r):
        return str(r.get("text") or r.get("content")
                   or r.get("chunk_to_retrieve") or "").strip()
    joined = "\n\n---\n\n".join(t for t in (_text(r) for r in rows) if t)
    doc_types = sorted({str(r.get("doc_type")) for r in rows if r.get("doc_type")})
    doc_ids = [str(r.get("doc_id")) for r in rows if r.get("doc_id")]
    # Per-document structured list so cross-referencing skills (reconcile) can see
    # each document's type + text separately, not just the joined blob.
    items = [{"doc_id": str(r.get("doc_id") or ""),
              "doc_type": str(r.get("doc_type") or ""),
              "text": _text(r)} for r in rows if _text(r)]
    return {
        "text": joined, "context": joined,
        "current": joined, "previous": joined, "conclusion": joined,
        "doc_types": doc_types, "doc_ids": doc_ids, "items": items,
        "query": " ".join(doc_types),
    }


@dataclass
class StepRecord:
    id: str
    skill: str
    status: str
    outputs: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    error: Optional[str] = None
    attempts: int = 1

    def to_dict(self) -> dict:
        return {
            "id": self.id, "skill": self.skill, "status": self.status,
            "outputs": self.outputs,
            "evidence": [e.to_dict() if hasattr(e, "to_dict") else e
                         for e in self.evidence],
            "error": self.error, "attempts": self.attempts,
        }


@dataclass
class WorkflowRun:
    template_id: str
    template_version: str
    domain: str
    status: str                       # completed | pending_approval | failed
    steps: list = field(default_factory=list)      # list[StepRecord]
    work_object_id: str = ""
    halted_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "template_version": self.template_version,
            "domain": self.domain, "status": self.status,
            "work_object_id": self.work_object_id, "halted_at": self.halted_at,
            "steps": [s.to_dict() for s in self.steps],
        }


class WorkflowEngine:
    def __init__(self, dispatcher, templates_dir: Optional[str] = None,
                 domain_loader=None, default_retries: int = 1,
                 template_loader=None):
        self.dispatcher = dispatcher
        self.templates_dir = templates_dir or DEFAULT_TEMPLATES_DIR
        self.domain_loader = domain_loader   # callable(domain_id) -> DomainConfig
        self.default_retries = default_retries
        # optional callable(domain_id, template_id) -> template dict | None.
        # Checked BEFORE the YAML files (DB-first), so user-saved templates win.
        self.template_loader = template_loader

    def _load_template(self, template_id: str, domain: Optional[str] = None) -> dict:
        if self.template_loader and domain:
            try:
                db = self.template_loader(domain, template_id)
                if db:
                    return db
            except Exception as e:
                print(f"[engine] template_loader failed for {template_id}: {e}")
        with open(os.path.join(self.templates_dir, f"{template_id}.yaml")) as f:
            return yaml.safe_load(f)

    def run(self, template_id: str, domain: str, inputs: dict,
            docs: Optional[list] = None, params: Optional[dict] = None) -> WorkflowRun:
        """Run a template. `docs` is the workflow's document set (list of rows with
        doc_id/doc_type/text); doc-consuming steps resolve their text from it via
        `$docs.*` references emitted by autowire. `params` are the declared run-time
        inputs (the template's `inputs:` block), referenced by steps as `$param.*`."""
        tmpl = self._load_template(template_id, domain)
        # Coerce/validate declared run-time params (raises ParamError on bad input).
        params = coerce_params(tmpl.get("inputs"), params)
        domain_cfg = self.domain_loader(domain) if self.domain_loader else None
        doc_ctx = _build_doc_context(docs or [])
        run = WorkflowRun(template_id=tmpl["id"],
                          template_version=str(tmpl.get("version", "1.0")),
                          domain=domain, status="completed")
        approval_before = tmpl.get("approval_before")
        approved = bool(inputs.get("approve"))
        step_outputs: dict = {}
        wf_ctx = {"workflow_id": tmpl["id"],
                  "workflow_version": str(tmpl.get("version", "1.0"))}

        for step in tmpl["steps"]:
            sid, skill = step["id"], step["skill"]

            # human approval gate
            if approval_before and skill == approval_before and not approved:
                run.status = "pending_approval"
                run.halted_at = sid
                return run

            resolved = self._resolve_inputs(step.get("inputs_map", {}),
                                            inputs, domain_cfg, step_outputs,
                                            doc_ctx, params)
            rec = self._run_step(sid, skill, resolved, wf_ctx)
            run.steps.append(rec)

            if rec.status == "error":
                run.status = "failed"
                run.halted_at = sid
                return run

            step_outputs[sid] = rec.outputs
            if skill == "create_work_object":
                run.work_object_id = rec.outputs.get("work_object_id", "")
                wf_ctx["work_object_id"] = run.work_object_id

        return run

    def _run_step(self, sid, skill, resolved, wf_ctx) -> StepRecord:
        attempts = 0
        last = None
        for attempts in range(1, self.default_retries + 2):  # 1 try + retries
            result = self.dispatcher.invoke(skill, resolved, wf_ctx=wf_ctx)
            last = result
            if result.status != "error":
                break
        return StepRecord(id=sid, skill=skill, status=last.status,
                          outputs=last.outputs, evidence=last.evidence,
                          error=last.error, attempts=attempts)

    def _resolve_inputs(self, inputs_map, inputs, domain_cfg, step_outputs,
                        doc_ctx=None, params=None) -> dict:
        out = {}
        for key, ref in inputs_map.items():
            out[key] = self._resolve_ref(ref, inputs, domain_cfg, step_outputs,
                                         doc_ctx, params)
        return out

    def _resolve_ref(self, ref, inputs, domain_cfg, step_outputs, doc_ctx=None,
                     params=None):
        if not isinstance(ref, str) or not ref.startswith("$"):
            return ref  # literal
        parts = ref[1:].split(".")
        root = parts[0]
        if root == "input":
            return inputs.get(parts[1]) if len(parts) > 1 else None
        if root == "param":
            # $param.<name> — a declared run-time input (the template's inputs block)
            return (params or {}).get(parts[1]) if len(parts) > 1 else None
        if root == "domain":
            if domain_cfg is None:
                return None
            return getattr(domain_cfg, parts[1], None) if len(parts) > 1 else None
        if root == "docs":
            # $docs.text | $docs.doc_types | $docs.doc_ids — the workflow's corpus
            return (doc_ctx or {}).get(parts[1]) if len(parts) > 1 else None
        if root == "steps":
            # $steps.<id> or $steps.<id>.<key>[.<subkey>...] — walk nested dicts
            if len(parts) == 2:
                return step_outputs.get(parts[1])
            return _walk(step_outputs.get(parts[1]), parts[2:])
        return None
