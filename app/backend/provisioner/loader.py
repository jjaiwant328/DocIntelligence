"""Load blueprint YAML specs and resolve their $blueprint.* references.

A blueprint's starter_workflow steps may reference the blueprint's own
reconciliation spec via $blueprint.<path> (e.g. $blueprint.reconciliation.checks).
We resolve those to literal values when seeding the template, so the stored
template is self-contained and the engine needs no new ref type.
"""
from __future__ import annotations

import copy
import os
from typing import Any, Optional

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
BLUEPRINTS_DIR = os.path.join(_HERE, "blueprints")


def list_blueprints() -> list[dict]:
    out = []
    for fn in sorted(os.listdir(BLUEPRINTS_DIR)):
        if not fn.endswith(".yaml"):
            continue
        bp = _read(os.path.join(BLUEPRINTS_DIR, fn))
        if bp:
            out.append({"id": bp.get("id", fn[:-5]),
                        "name": bp.get("name", bp.get("id", fn[:-5])),
                        "description": (bp.get("description") or "").strip()})
    return out


def load_blueprint(blueprint_id: str) -> Optional[dict]:
    path = os.path.join(BLUEPRINTS_DIR, f"{blueprint_id}.yaml")
    if not os.path.exists(path):
        return None
    return _read(path)


def resolve_blueprint_refs(obj: Any, blueprint: dict) -> Any:
    """Recursively replace '$blueprint.a.b' strings with blueprint['a']['b']."""
    if isinstance(obj, str) and obj.startswith("$blueprint."):
        cur: Any = blueprint
        for part in obj[len("$blueprint."):].split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return copy.deepcopy(cur)
    if isinstance(obj, dict):
        return {k: resolve_blueprint_refs(v, blueprint) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_blueprint_refs(v, blueprint) for v in obj]
    return obj


def _read(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}
