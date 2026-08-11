"""Core dataclasses + exceptions for the skill runtime.

Thin projections over existing platform data (ADR-006). No per-vertical classes.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


class SkillError(Exception):
    """Base class for skill runtime errors."""


class InputError(SkillError):
    """Raised when a skill's inputs fail contract validation."""


class OutputError(SkillError):
    """Raised when a skill's outputs fail contract validation."""


class ContractError(SkillError):
    """Raised when a registry/contract is malformed."""


@dataclass
class Evidence:
    """Provenance for an AI-derived conclusion (guardrail 14)."""
    document_id: str
    locator: str = ""          # page/section/chunk id where available
    source_text: str = ""      # source text or retrieval reference
    confidence: Optional[float] = None
    method: str = ""           # extraction/retrieval/reasoning method

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SkillResult:
    """Structured result of a single skill invocation."""
    status: str                       # e.g. "ok", "insufficient_evidence", "error"
    outputs: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)  # list[Evidence]
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "outputs": self.outputs,
            "evidence": [e.to_dict() if isinstance(e, Evidence) else e
                         for e in self.evidence],
            "error": self.error,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkObject:
    """Generic work object (case/review/investigation/...). ADR-006."""
    id: str
    type: str                          # case | review | investigation | project | request | monitoring_event
    title: str
    domain: str
    status: str = "open"
    owner: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    documents: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [e.to_dict() if isinstance(e, Evidence) else e
                         for e in self.evidence]
        return d


_ALLOWED_ADAPTERS = {"uc_function", "internal_call", "llm_schema"}
_ALLOWED_TYPES = {"string", "number", "integer", "boolean", "array", "object", "enum"}


@dataclass
class SkillContract:
    """Parsed skill contract (docs Phase 2 / spec §4)."""
    id: str
    version: str
    category: str
    adapter: str
    implementation: str
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    required_capabilities: list = field(default_factory=list)
    ontology_dependencies: list = field(default_factory=list)
    evidence_requirements: str = "optional"   # required | optional
    side_effects: dict = field(default_factory=dict)
    test_method: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    # --- validation --------------------------------------------------------
    def _check_field(self, name: str, spec: dict, value: Any, kind: str) -> None:
        t = spec.get("type")
        if t and t not in _ALLOWED_TYPES:
            raise ContractError(f"{self.id}: {kind} '{name}' has unknown type '{t}'")
        if t == "enum":
            allowed = spec.get("values") or []
            if value not in allowed:
                raise (InputError if kind == "input" else OutputError)(
                    f"{self.id}: {kind} '{name}'={value!r} not in {allowed}")
            return
        pytypes = {
            "string": str, "number": (int, float), "integer": int,
            "boolean": bool, "array": list, "object": dict,
        }
        expected = pytypes.get(t)
        if expected is not None and value is not None and not isinstance(value, expected):
            raise (InputError if kind == "input" else OutputError)(
                f"{self.id}: {kind} '{name}' expected {t}, got {type(value).__name__}")

    def validate_inputs(self, data: dict) -> None:
        if not isinstance(data, dict):
            raise InputError(f"{self.id}: inputs must be a dict")
        for name, spec in self.inputs.items():
            spec = spec or {}
            if spec.get("required") and name not in data:
                raise InputError(f"{self.id}: missing required input '{name}'")
            if name in data:
                self._check_field(name, spec, data[name], "input")

    def validate_outputs(self, data: dict) -> None:
        if not isinstance(data, dict):
            raise OutputError(f"{self.id}: outputs must be a dict")
        for name, spec in self.outputs.items():
            spec = spec or {}
            if name in data:
                self._check_field(name, spec, data[name], "output")

    def creates_actions(self) -> bool:
        return bool(self.side_effects.get("creates_actions"))
