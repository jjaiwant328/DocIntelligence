"""Registry + contract loader. Validates on load; never executes code from YAML."""
from __future__ import annotations

import os
from typing import Optional

import yaml

from .models import SkillContract, ContractError, _ALLOWED_ADAPTERS

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REGISTRY = os.path.join(_HERE, "registry.yaml")
CONTRACTS_DIR = os.path.join(_HERE, "contracts")


class Registry:
    def __init__(self, entries: list, contracts: dict):
        self._entries = entries          # list of registry dict rows
        self._contracts = contracts      # skill_id -> SkillContract

    def list(self, enabled_only: bool = False) -> list:
        rows = [e for e in self._entries if (e.get("enabled") or not enabled_only)]
        return rows

    def enabled_ids(self) -> list:
        return [e["id"] for e in self._entries if e.get("enabled")]

    def get(self, skill_id: str) -> SkillContract:
        if skill_id not in self._contracts:
            raise ContractError(f"no contract loaded for skill '{skill_id}'")
        return self._contracts[skill_id]

    def validate(self) -> list:
        """Return a list of human-readable errors ([] == valid)."""
        errors = []
        seen = set()
        for e in self._entries:
            sid = e.get("id")
            if not sid:
                errors.append("registry row missing id")
                continue
            if sid in seen:
                errors.append(f"duplicate skill id '{sid}'")
            seen.add(sid)
            if not e.get("enabled"):
                continue
            c = self._contracts.get(sid)
            if c is None:
                errors.append(f"enabled skill '{sid}' has no contract file")
                continue
            if c.adapter not in _ALLOWED_ADAPTERS:
                errors.append(f"skill '{sid}' has unknown adapter '{c.adapter}'")
            if c.adapter == "llm_schema":
                pth = os.path.join(_HERE, c.implementation)
                if not os.path.exists(pth):
                    errors.append(f"skill '{sid}' prompt file missing: {c.implementation}")
        return errors


def _contract_from_dict(d: dict) -> SkillContract:
    return SkillContract(
        id=d["id"], version=str(d.get("version", "1.0")),
        category=d.get("category", ""), adapter=d["adapter"],
        implementation=d["implementation"],
        inputs=d.get("inputs", {}) or {}, outputs=d.get("outputs", {}) or {},
        required_capabilities=d.get("required_capabilities", []) or [],
        ontology_dependencies=d.get("ontology_dependencies", []) or [],
        evidence_requirements=d.get("evidence_requirements", "optional"),
        side_effects=d.get("side_effects", {}) or {},
        test_method=d.get("test_method", ""),
    )


def load_registry(path: Optional[str] = None,
                  contracts_dir: Optional[str] = None) -> Registry:
    path = path or DEFAULT_REGISTRY
    contracts_dir = contracts_dir or CONTRACTS_DIR
    with open(path) as f:
        reg = yaml.safe_load(f) or {}
    entries = reg.get("skills", [])
    contracts = {}
    for e in entries:
        if not e.get("enabled"):
            continue
        cpath = os.path.join(contracts_dir, f"{e['id']}.yaml")
        if not os.path.exists(cpath):
            continue  # validate() will surface this
        with open(cpath) as cf:
            contracts[e["id"]] = _contract_from_dict(yaml.safe_load(cf))
    return Registry(entries, contracts)
