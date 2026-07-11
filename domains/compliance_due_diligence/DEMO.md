# Compliance Due Diligence — Demo Script (Tampa feasibility walkthrough)

A ~10‑minute, start‑to‑finish story for the **store‑development / feasibility** use case,
run entirely in the deployed DocIntelligence app with `?domain=compliance_due_diligence`.

> **Persona:** Connie, who coordinates feasibility/due‑diligence responses for new store
> parcels. Today she does this by hand across email threads and an outside consultant.
> This demo shows the same work as a governed, searchable, agent‑assisted workflow.

## 0. Setup (once)
- App: `https://docintel-supply-chain-4101016551133680.0.azure.databricksapps.com`
- Switch domain to **Compliance Due Diligence** (top‑level subject selector → the URL becomes `?domain=compliance_due_diligence`).
- Data is already provisioned: catalog `jai_docintel`, schema `compliance_due_diligence`,
  volume `documents`, VS index `compliance_due_diligence_docs_index`, pipeline job
  `872826521276390`. Regions in the corpus: **Tampa/Hillsborough FL, Dallas TX, Atlanta/Fulton GA**.

## 1. Ingest — "the inbox is now a pipeline"
1. Open **Document Intelligence**. Note the corpus is mixed‑format: feasibility **emails**
   (`.eml`), municode **web pages** (`.html`), city **ordinances** (`.docx`/PDF), plus
   licenses and municipal requirements (`.txt`). All flow through one parse pipeline.
2. (Optional) Upload a new feasibility email or drop a file in the volume and trigger the
   pipeline (**Pipeline Status** shows the 7 tasks: prepare → parse → extract → idp →
   ontology → vector_search → agent).

## 2. Classify + extract — "pre‑sorted, structured"
1. Open **Document Library** → filter to the Tampa parcel (SD‑2024‑201).
2. Show that each doc is auto‑classified (`feasibility_request`, `alcohol_license`,
   `municipal_requirement`, `zoning_document`, …) and key fields are extracted
   (municipality, license type, authority, lead time, effective date).

## 3. Agent — "answer the feasibility questions"
Open **AI Agent** and ask, in order:
1. *"Classify and summarize the latest Tampa feasibility request."* → intake tool
   (`cdd_classify_request`) + summary.
2. *"What are the alcohol license requirements for Hillsborough County?"* → research tool
   (`cdd_get_municipality_requirements`) returns distance rules (500 ft schools / 250 ft
   churches), C‑1/C‑2 permitting, tobacco permit.
3. *"Have we researched Tampa before? What did we say last time?"* → historical‑knowledge
   tool surfaces the prior SD‑2024‑201 response.

## 4. Change detection — "the rules changed" (the money moment)
1. Ask the agent: *"Has anything changed for Dallas alcohol licensing?"* — or open
   **Control Tower → Compliance Map → Regulatory Pulse**.
2. The **Dallas alcohol v2024 → v2025** pair is detected: the school‑distance requirement
   dropped from **1,000 ft → 300 ft** and waivers moved from Council to administrative.
   The affected project(s) and previous‑vs‑new requirement are shown, sourced to the
   ordinance (`dallas_alcohol_ordinance_2025.docx`, provenance in `document_sources`).

## 5. Escalation → tracked action — "so nothing falls through"
1. When a regulatory change or high‑risk answer triggers a rule, it escalates to the
   **Legal Queue** (Control Tower → Copilot Studio → Legal Queue / `attorney_review_queue`).
2. Show the queued item with its triggering escalation rule, and the tracked action in the
   **Action Center**.

## 6. Data questions — Genie (aggregate/structured)
In **Copilot Studio → Data Questions** (Genie space scoped to the CDD schema + action
master), ask:
- *"How many open feasibility requests are there by municipality?"*
- *"Which municipalities changed requirements this year?"*
Genie returns SQL‑backed answers over the same governed tables (no hallucinated law).

## Reset between runs
Re‑run pipeline job `872826521276390` (its `workflow_prepare` task cleans tables and
checkpoints, then rebuilds from the volume). `notebooks/09_source_ingest` (`mode=simulate`)
re‑creates the multi‑format municipal sources if needed.

---
### Talk track — the three pains this addresses (from the discovery call)
1. **Email‑heavy, manual sorting** → auto‑parse/classify/extract into a governed store.
2. **Repeated research + changing laws** → historical recall + automatic regulatory‑change
   detection, sourced to real municipal documents.
3. **Nothing tracked / deadlines missed** → escalations, Legal Queue, and an action tracker.
