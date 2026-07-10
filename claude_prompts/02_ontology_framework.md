# Component 2 — Enterprise Ontology Framework (reuse-aware)

## Goal
Make the **existing** ontology builder config-driven so new domains can declare their entity/relationship model without editing notebook code. Do **not** invent a new ontology store.

## What already exists — DO NOT rebuild
- Tables `{schema}.entities` (`entity_id, entity_type, canonical_id, attributes` JSON, `source, display_name`), `{schema}.relationships` (`subject_id, predicate, object_id, reference_id, confidence` DOUBLE, `source_doc`), `{schema}.entity_aliases` — built by `notebooks/04_ontology_mapping.py`.
- These already support entities, relationships, attributes, source lineage, and confidence — everything Component 2 asks for.
- `platform.domain_configs.entity_types` (JSON array) already carries each domain's declared entity types (read but **not enforced** today).
- Generic builder path (`notebooks/04_ontology_mapping.py`, ~line 264): `FIELD_ENTITY_MAP` maps extracted field names → `(entity_type, id_prefix)`, mints entities from `extracted_fields`, adds a `Document` entity per doc, and builds generic edges (`EXTRACTED_FROM`, `COVERS`, `INSPECTED`, `ASSOCIATED_WITH`).

## Gap to fill
1. **Externalize `FIELD_ENTITY_MAP` into config.** Read the field→entity mapping and the relationship rules from `platform.domain_configs` (extend the schema, e.g. an `ontology_config` JSON: `{ "field_entity_map": {"store_number":["Project","PROJ"], ...}, "relationship_rules": [{"subject_field":..., "predicate":..., "object_field":...}] }`). Fall back to the current hardcoded map when absent (backward compatible).
2. **Define a reusable core-entity vocabulary** (prefixes) shared across domains: Organization, Person, Location, Document, Event, Asset, Risk, Requirement, Action. Domains extend, never fork.
3. Keep the `supply_chain` bespoke branch untouched; only generalize the generic (`else`) branch.

## Deliverables
- Edited `notebooks/04_ontology_mapping.py`: config-driven `FIELD_ENTITY_MAP` + relationship rules, with hardcoded fallback.
- `platform/ontology/CORE_ENTITIES.md` documenting the shared vocabulary + prefix conventions.
- (If needed) an additive `ontology_config` column/key on `platform.domain_configs` — additive DDL only.

## Acceptance criteria
- Re-run `04_ontology_mapping.py` for `supply_chain` and `compliance`: entity/relationship counts unchanged (regression guard).
- A new domain can produce Project/Municipality/Requirement/License entities **purely from its `domain_configs` row**, no notebook edits.

## Constraints
Additive, backward-compatible, config-first. Do not rename existing tables/columns or change the supply_chain graph.
