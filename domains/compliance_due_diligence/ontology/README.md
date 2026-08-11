# ontology/ — Compliance Due Diligence

Config-driven ontology overlay for `compliance_due_diligence`, consumed by
`notebooks/04_ontology_mapping.py` via the `ontology_config` key in
`platform.domain_configs.analytics_config`.

## Entity types

| Entity | Prefix | Fields that map to it |
|---|---|---|
| `Project` | `PROJ` | `store_number`, `project_id` |
| `FeasibilityRequest` | `FREQ` | `requester` |
| `Municipality` | `MUNI` | `municipality` |
| `RegulatoryRequirement` | `REQ` | `requirement_type` |
| `License` | `LIC` | `license_type` |
| `Response` | `RESP` | `responder` |
| `Action` | `ACT` | (populated by action_master lifecycle) |
| `Document` | `DOC` | (auto — every parsed document) |

## Relationship rules (field-based)

| Subject field | Predicate | Object field | Rationale |
|---|---|---|---|
| `store_number` | `LOCATED_IN` | `municipality` | A project site is in a municipality |
| `municipality` | `DEFINES` | `requirement_type` | Municipalities impose regulatory requirements |
| `requirement_type` | `REQUIRES` | `license_type` | Requirements necessitate specific license types |
| `responder` | `ANSWERS` | `requester` | Response answers a FeasibilityRequest (co-occurrence) |
| `store_number` | `HAS_HISTORY_OF` | `responder` | Project has a history of responses (co-occurrence) |

## File

`ontology_config.json` — the `ontology_config` dict written into `analytics_config` by the
setup script. The builder merges this on top of `DEFAULT_FIELD_ENTITY_MAP`; no schema change
to `domain_configs` is required.
