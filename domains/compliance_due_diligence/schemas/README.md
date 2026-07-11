# schemas/ — Compliance Due Diligence

Extraction schemas and classification labels for the `compliance_due_diligence` domain.

## Files

| File | Purpose |
|---|---|
| `classification_labels.json` | The 10 doc-type labels and their natural-language descriptions used by `ai_classify`. |
| `extraction_schemas.json` | Per-label extraction schemas in the platform shape `{doc_type: {schema: {field: {type, description}}, instructions}}`. |

## Doc types

| Label | Extracts |
|---|---|
| `feasibility_request` | project_id, store_number, address, market, state, municipality, county, request_type, requester, priority, source_document |
| `municipal_requirement` | project_id, store_number, municipality, county, state, requirement_type, authority, effective_date, lead_time, source_document |
| `alcohol_license` | store_number, address, municipality, state, license_type, issuing_authority, effective_date, expiration_date, renewal_period, lead_time, source_document |
| `tobacco_license` | store_number, address, municipality, state, license_type, issuing_authority, effective_date, expiration_date, renewal_period, lead_time, source_document |
| `business_license` | store_number, address, municipality, county, state, license_type, issuing_authority, effective_date, expiration_date, renewal_period, lead_time, source_document |
| `zoning_document` | project_id, store_number, address, municipality, county, state, requirement_type, authority, effective_date, lead_time, source_document |
| `permit` | project_id, store_number, address, municipality, state, requirement_type, issuing_authority, effective_date, expiration_date, lead_time, source_document |
| `historical_response` | project_id, store_number, municipality, state, request_type, responder, response_date, requester, source_document |
| `regulatory_change` | municipality, county, state, requirement_type, authority, effective_date, source_document |
| `consultant_correspondence` | project_id, store_number, municipality, state, requester, responder, request_type, response_date, source_document |

## How it is consumed

`scripts/setup_compliance_due_diligence.py` serialises these schemas into the
`platform.domain_configs.extraction_schemas` column (JSON string).
The pipeline notebook `03_idp_pipeline.py` reads them from there at runtime — no code change needed.
