# ontology/

`ontology_config` overlay for this domain — consumed by the config-driven builder in
`notebooks/04_ontology_mapping.py` (see `claude_prompts/02_ontology_framework.md`).

- `field_entity_map`: e.g. `store_number→(Project,PROJ)`, `municipality→(Municipality,MUNI)`,
  `requirement_type→(RegulatoryRequirement,REQ)`, `license_type→(License,LIC)`,
  `responder→(Response,RESP)`.
- `relationship_rules`: `Project LOCATED_IN Municipality`, `Municipality DEFINES RegulatoryRequirement`,
  `RegulatoryRequirement REQUIRES License`, `FeasibilityRequest GENERATES Action`,
  `Response ANSWERS FeasibilityRequest`, `Response SUPPORTED_BY Document`,
  `Project HAS_HISTORY_OF Response`.
