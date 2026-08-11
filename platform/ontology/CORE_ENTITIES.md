# Core Entity Vocabulary & Config-Driven Ontology

The ontology builder (`notebooks/04_ontology_mapping.py`) is **config-driven** for all
non-`supply_chain` domains. A domain declares its entity model in
`platform.domain_configs.analytics_config` (JSON), under an `ontology_config` key —
**no schema change** is needed (a new column would break the positional INSERT in
`app/backend/platform_routes.py:create_domain`).

## `ontology_config` shape

```json
{
  "ontology_config": {
    "field_entity_map": {
      "store_number":     ["Project",              "PROJ"],
      "municipality":     ["Municipality",         "MUNI"],
      "requirement_type": ["RegulatoryRequirement","REQ"],
      "license_type":     ["License",              "LIC"],
      "responder":        ["Response",             "RESP"]
    },
    "relationship_rules": [
      {"subject_field": "store_number", "predicate": "LOCATED_IN",  "object_field": "municipality"},
      {"subject_field": "municipality", "predicate": "DEFINES",     "object_field": "requirement_type"},
      {"subject_field": "requirement_type", "predicate": "REQUIRES","object_field": "license_type"}
    ]
  }
}
```

- **`field_entity_map`**: extracted field name → `[entity_type, id_prefix]`. Merged on top of
  `DEFAULT_FIELD_ENTITY_MAP`, so a domain only declares what it adds/overrides.
- **`relationship_rules`**: field-based edges built between entities extracted from the **same
  document**. Both fields must appear in `field_entity_map` (or the default) and be present on the doc.

## Reusable core entity types (shared prefixes)

Domains should map their fields onto these where they fit, extending only when needed:

| Core entity | Typical prefix | Example domain use |
|---|---|---|
| Organization | `ORG` | Supplier, Vendor, Municipality authority |
| Person | `PERS` | Inspector, Requester, Responder |
| Location | `LOC` | Store, Project site, Facility |
| Document | `DOC` | Every parsed document (auto) |
| Event | `EVT` | Inspection, Excursion, RecallEvent |
| Asset | `AST` | Trailer, Equipment |
| Risk | `RSK` | Violation, TemperatureExcursion |
| Requirement | `REQ` | RegulatoryRequirement, License prerequisite |
| Action | `ACT` | Tracked action (see `platform.action_master`) |

## Backward compatibility

- `supply_chain` uses a bespoke hand-authored branch and is untouched.
- `compliance` has no `ontology_config` → falls back to `DEFAULT_FIELD_ENTITY_MAP` → identical
  entities/relationships as before.
- `relationship_rules` absent → the rules pass is a no-op.
