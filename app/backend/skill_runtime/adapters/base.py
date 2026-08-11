"""Adapter base + the execution Context (injectable seams for offline tests)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Context:
    """Callable seams a skill may use. Live build wires these to docintel_routes;
    tests pass fakes."""
    run_sql: Optional[Callable[[str], list]] = None            # (sql) -> list[dict]
    vs_search: Optional[Callable[..., list]] = None            # (query, schema_vec, k, doc_type) -> list[dict]
    chat_completion: Optional[Callable[[str], str]] = None     # (prompt) -> str (model text)
    resolve_model: Optional[Callable[[], str]] = None          # () -> model name
    internal: dict = field(default_factory=dict)               # name -> callable(inputs, ctx) -> (outputs, evidence)


class Adapter:
    def execute(self, contract, inputs: dict, ctx: Context):
        """Return (outputs: dict, evidence: list[Evidence])."""
        raise NotImplementedError
