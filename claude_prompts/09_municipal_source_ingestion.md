# Component 9 — Municipal / Government Source Ingestion (reuse-aware)

## Goal
Feed the `compliance_due_diligence` demo with **real municipal/government source documents**, narrowed to the demo regions, and make the whole corpus (emails + office docs + web pages + PDFs) parseable and searchable through the **existing** pipeline. Runs **before** Prompt 08 so its data is available for the demo.

## Scope guardrails (agreed 2026-07-10)
- **Demo regions ONLY** (curated allowlist): Tampa / Hillsborough County **FL**, Dallas **TX**, Atlanta / Fulton County **GA**.
- **Demo-relevant doc types ONLY**: alcohol / tobacco / business licensing, zoning, municipal codes (municode), and regulatory changes. No open-web crawling.
- Respectful fetching: obey robots.txt / rate limits / ToS; prefer official bulk downloads / APIs where offered. Every fetch requires the jurisdiction to be on the allowlist.

## What already exists — DO NOT rebuild
- Volume `/Volumes/jai_docintel/compliance_due_diligence/documents/` + full pipeline job `872826521276390` (parse → extract → idp → ontology → vector_search → agent).
- Parse notebook `app/unstructured_workflow/src/transformations/01_parse_documents.py`: **PDF/image branch** (`ai_parse_document`) and **TXT branch** (synthetic VARIANT via `named_struct → to_json → parse_json`). Downstream `02_extract_document_content.py` consumes the VARIANT — no change needed if new formats emit the same shape.
- Corpus generator `notebooks/01_synthetic_corpus_store_dev.py` (writes files straight into the volume via `write_doc`).
- Domain config `scripts/setup_compliance_due_diligence.py` + `domains/compliance_due_diligence/*`.

## Gap to fill
1. **New file-type parse branches** in `01_parse_documents.py`, each mirroring the TXT branch's synthetic-VARIANT pattern and writing `path, parsed, parsed_at` into `parsed_documents_raw` with its own per-format checkpoint:
   - `.eml` — parse MIME, extract subject + body (+ note attachments) → text.
   - `.html` — strip tags to readable text (municode / .gov pages).
   - `.docx` — binary; read via `binaryFile` + a docx text extractor (or `ai_parse_document` if it supports docx).
   - Confirm `.eml` is genuinely ingested (today it is NOT — only `*.txt` and `*.{pdf,jpg,jpeg,png}` are globbed).
2. **Synthetic test files** of `.eml` / `.docx` / `.html` for the demo regions (simulating a municode ordinance page, a `.gov` PDF/HTML ordinance, a feasibility email thread) so the corpus exercises every branch end-to-end.
3. **Source-ingestion connector** (`notebooks/09_source_ingest.py` or a job task): given the jurisdiction allowlist, fetch demo-relevant PDFs/HTML into the volume with **provenance metadata** (`source_url`, `jurisdiction`, `retrieved_at`, `effective_date`). Fetching is gated to the allowlist; dry-run/manifest mode by default.
4. **Provenance propagation** — carry `source_url` / `jurisdiction` / `effective_date` through extraction so the agent can cite the authoritative source and `detect_regulatory_change` can diff year-over-year ordinance versions.
5. **Region config knob** — add a `regions` / jurisdiction allowlist to the domain config (none exists today).

## Deliverables
- `.eml/.docx/.html` parse branches (backward-compatible; existing PDF/TXT untouched).
- Synthetic multi-format test files for the demo regions.
- Source-ingestion connector + provenance metadata.
- Region/jurisdiction allowlist in domain config.

## Acceptance criteria
- Dropping a `.eml`, `.docx`, and `.html` file into the volume → each is parsed into `parsed_documents_raw`, flows through classify/extract/ontology/chunk, and is retrievable via the VS index.
- Ingested municipal docs carry provenance (`source_url`, `jurisdiction`).
- A year-over-year ordinance pair (e.g. Dallas alcohol) triggers `detect_regulatory_change`.
- Full pipeline run stays green; existing PDF/TXT ingestion unaffected.

## Constraints
Reuse the existing parse/pipeline/VS/agent. Additive branches only — do not alter the PDF/TXT paths or downstream VARIANT contract. Fetching restricted to the demo-region allowlist.
