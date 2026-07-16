# Compliance Due Diligence — End-to-End Demo (Dallas Store 5202)

A ~10-minute, single-project walkthrough of the store-development compliance workflow,
run entirely in the deployed Control Tower. It follows the real arc from the discovery
call: **inbound feasibility email → triage → research → recall prior work → detect a
regulatory change → track the work → send a grounded reply.**

> **Persona:** Connie, who coordinates feasibility/due-diligence for new store parcels.
> Today this is email-heavy and manual across an outside consultant. This demo shows the
> same work as a governed, agent-assisted, single-project workspace.
>
> **Why Store 5202 (Dallas):** it's the one project with the complete arc already in the
> data — an inbound feasibility email, a prior response, **and** the Dallas alcohol
> **v2024 → v2025** regulatory change (the "the rules changed, re-research" moment).

## Setup (once)
- App: `https://docintel-supply-chain-4101016551133680.0.azure.databricksapps.com`
- Top-level subject selector → **Compliance Due Diligence** (`?domain=compliance_due_diligence`).
- Data is provisioned & processed: schema `jai_docintel.compliance_due_diligence`, volume
  `documents`, VS index `compliance_due_diligence_docs_index` (READY), pipeline job
  `872826521276390`. Chunks are `ai_prep_search` context-enriched; retrieval is hybrid.

---

## The flow — 7 steps, one project

### 1. Pick the project (single-project focus)
In the Control Tower header, **"Working on project ▾" → Store 5202 (Dallas, TX)**.
Everything below now scopes to 5202. (Switching warns if you have unsaved edits.)

### 2. Overview — "what do I act on today?"
- **🎯 Today's Priorities**: the ranked act-today queue — the **overdue Dallas alcohol
  escalation** sits on top; the License-Filing action is awaiting review.
- **🧭 Lifecycle timeline**: NPUC → **Feasibility Request (Jul 8 2024)** → **Response
  (Dec 10 2024)** → **⚑ Regulatory Change Detected**. The change node links to Regulatory
  Pulse; the others open their source doc.

### 3. 📨 Inbox — "the email inbox, now triaged"
The inbound **feasibility email for 5202** shows auto-parsed sender / subject / date,
**Dallas** + **5202** badges, a `feasibility_request` classification, and per-row
**Open · ✉️ Draft Reply · 📁 Project**. This is the scene the demo is named for.

### 4. 🧠 Copilot Studio → Ask — "research, grounded"
- (First, **Setup & Readiness** shows the guiding prompt that drives the agent + the
  recommended actions — the prompt *is* the driver.)
- Ask: **"What are the alcohol license requirements for Dallas, and have we researched
  this location before?"** → grounded answer citing the Dallas requirement docs + the
  **prior 5202 response** (historical recall), with a clickable **🔗 municipal source**.
  Reinforces *"don't make it up."*

### 5. 🗺 Compliance Map → Regulatory Pulse — "the rules changed" (the money moment)
The **Dallas alcohol v2024 → v2025** change is detected: school-distance requirement
dropped **1,000 ft → 300 ft**, waivers moved Council → administrative. Shows a **summary,
effective date, and action-required-by**, sourced to `dallas_alcohol_ordinance_2025.docx`.

### 6. ⚡ Action Center — "turn it into tracked work"
Scoped to 5202. **Recommended actions** (generated from the Copilot prompt, per category:
Feasibility Response / License Filing / Research / Escalation):
1. **Add to tracker** on a recommendation → it appears in the **Active Action Tracker**
   (no refresh) with owner/due/lifecycle. The button flips to **✓ Added to tracker**.
2. **Advance the lifecycle** (Initiated → In Progress → Pending Verification → Completed);
   each transition is logged in **History**. A failed review is **"Return for rework"**
   with a required reason.
3. **📎 Attach for review** — attach an existing doc or upload a new one; it's linked to
   the action, tagged to 5202, and logged. Shown under "Documents for review."
4. The **regulatory-change escalation** appears in **Copilot Studio → Legal Queue**.
- **Action Reports** always shows the status/priority rollup + history (incl. deleted).

### 7. ✉️ Draft Reply → Send (demo) — "fire back a grounded answer"
From the Inbox or Tracker, **✉️ Draft Reply** generates a ready-to-send email **grounded
in 5202's curated docs ∪ Universal** (cites the Dallas requirements, the change, the prior
response, the ordinance, the municode doc). **📤 Send (demo)** wraps it in RaceTrac
letterhead and logs it to the sent log — **it never actually emails**.

**Throughout:** the **📋 Tracker** is the shared project ledger (the Smartsheet
replacement) — Project · Municipality · Request · Status · Owner · Due · Last Response ·
⚑ Change. It's the "where does everything stand" backdrop, referenced across the flow.

---

## Optional closers (not core to the single-project walk)
- **🕸 Knowledge Graph → Focus project = 5202** — *verify the right documents are attached
  to this project* (its docs, municipality, licenses, prior response light up; unassigned
  docs are dimmed). Use it as a "trust the inputs" check, not a general graph explore.
- **Copilot Studio → Data Questions (Genie)** — aggregate/portfolio questions
  ("how many open feasibility requests by municipality?", "which municipalities changed
  requirements this year?"). A closing flourish, since the walk is single-project.

## Trimmed for this demo (deliberately not shown)
- **Coverage Matrix** (jurisdiction × topic) — a portfolio view whose projected/synthetic
  cells distract at the single-project altitude; hidden for CDD.

## Reset between runs
Re-run pipeline job `872826521276390` (its `workflow_prepare` cleans + rebuilds from the
volume). Seeded demo state (actions, history, tags) lives in `platform.*` and persists.
