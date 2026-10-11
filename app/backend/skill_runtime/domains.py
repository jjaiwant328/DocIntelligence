"""Domain configuration loader. Domains configure semantics only (ADR-004);
they never reimplement the platform. `requirements` is flattened to a single
candidate list the Due-Diligence template feeds to extract_requirements."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import yaml

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DOMAINS_DIR = os.path.join(_HERE, "domains")


@dataclass
class DomainConfig:
    """A use case's config. Since P4 the use_case_id IS the project id and the
    Lakehouse schema — there is no more overlay→platform id indirection, so `id`
    is the single canonical identifier (was: id + platform_domain_id + schema_vec)."""
    id: str
    name: str
    ontology_entities: list = field(default_factory=list)
    requirements: list = field(default_factory=list)
    requirements_by_group: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def load_domain(domain_id: str, domains_dir: Optional[str] = None) -> DomainConfig:
    base = os.path.join(domains_dir or DEFAULT_DOMAINS_DIR, domain_id)
    if not os.path.isdir(base):
        # A blueprint-provisioned use case has no on-disk domain dir (it wasn't
        # bundled at build time). Fall back to a minimal config keyed by the id —
        # this is what makes "build a use case on the fly" runnable through the
        # engine with no redeploy.
        return DomainConfig(id=domain_id, name=domain_id)
    dom = _read(os.path.join(base, "domain.yaml"))
    ont = _read(os.path.join(base, "ontology.yaml"))
    req = _read(os.path.join(base, "requirements.yaml"))
    flat = []
    for group in (req or {}).values():
        for r in (group or []):
            if r not in flat:
                flat.append(r)
    return DomainConfig(
        id=dom.get("id", domain_id),
        name=dom.get("name", domain_id),
        ontology_entities=(ont or {}).get("entities", []),
        requirements=flat,
        requirements_by_group=req or {},
    )


def _read(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}
