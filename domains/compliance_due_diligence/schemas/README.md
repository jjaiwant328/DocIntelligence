# schemas/

Per-doc-type extraction schemas for `compliance_due_diligence`, in the platform shape
`{doc_type: {schema: {field: {type, description}}, instructions}}`.

Doc types: `feasibility_request`, `municipal_requirement`, `alcohol_license`, `tobacco_license`,
`business_license`, `zoning_document`, `permit`, `historical_response`, `regulatory_change`,
`consultant_correspondence`.

Populated by `claude_prompts/04_compliance_due_diligence_domain.md` (written into the
`platform.domain_configs.extraction_schemas` row by `scripts/setup_compliance_due_diligence.py`).
