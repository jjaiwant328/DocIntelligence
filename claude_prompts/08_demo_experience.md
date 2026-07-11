# Component 8 — Demo Experience Layer (reuse-aware)

## Goal
Make the store-development story shine in the **existing** UI. Most views are inherited automatically via `?domain_id=`; add only the change-detection and escalation surfaces.

## What already exists — DO NOT rebuild
- Next.js app (`app/frontend/src/app/*`), domain-switching via `DomainContext` + `?domain_id=`; tabs: Document Intelligence (`document-intelligence/page.tsx`), Document Library, Control Tower (`supply-chain/page.tsx` — generic: Overview / Knowledge Graph / Action Center / Compliance Map / Copilot Studio), AI Agent (`agent/page.tsx`), global ⌘K Document Search.
- New-domain setup wizard (`app/setup/page.tsx` → `/api/platform/setup/*`).
- Action Center / Reports, Copilot Studio, Knowledge Graph views already render any domain's data.

Once `compliance_due_diligence` is active, all of the above light up for it with **no new UI**.

## Gap to fill
1. **Verify** every tab renders correctly for `domain_id=compliance_due_diligence` (icons, labels, suggested questions, entity graph, actions).
2. **Change-Detection view** — surface `regulatory_change_history` / `REGULATORY CHANGE DETECTED` results (affected project, previous vs new requirement, impact) — ideally a sub-view under Control Tower → Compliance Map (Regulatory Pulse) or Copilot.
3. **Escalation view** — show `platform.escalation_rules` and the `attorney_review_queue` entries with their triggering rule (extends the existing Legal Queue sub-view).
4. **Demo script** — a runnable Tampa feasibility walkthrough (`domains/compliance_due_diligence/DEMO.md`): upload feasibility email → classify → research → recall prior Tampa project → detect Dallas change → create tracked action.
5. **Genie space (optional enhancement — same app, no new app).** Create one Genie space scoped to the `compliance_due_diligence` schema + `platform.action_master` to answer structured/aggregate questions the agent handles poorly (e.g. "how many open Tampa feasibility requests?", "which municipalities changed requirements this quarter?"). Surface it inside the existing Copilot/Ask tab (e.g. a "Data Questions" mode) via the Genie Conversation API — do **not** stand up a separate application. Skip if the agent already answers these well enough for the demo.

## Deliverables
- UI verification report for the new domain.
- Change-detection + escalation sub-views (reuse existing components/patterns).
- `domains/compliance_due_diligence/DEMO.md`.

## Acceptance criteria
- All tabs work for the new domain with correct data.
- A regulatory change renders in the Change-Detection view and its escalated action appears in Action Center + Legal Queue.
- The demo script runs start-to-finish in the deployed app.

## Constraints
Reuse existing components and the `?domain_id=` pattern. Additive views only; don't fork per-domain pages.

## Fine-tuning (round 2 — user feedback 2026-07-11)
6. **Genie "Data Questions" mode** in Copilot Studio → Ask: toggle between Documents (`/copilot-query`) and Data Questions (`/genie-query`); gate the toggle on `GET /genie-space`. Backend already built (space `01f17d61d9051dcdb0c80dd20b1f9aa8`).
7. **Knowledge Graph:**
   - Fix the shading: unselected entities render in an odd shaded value — correct the dim/opacity logic.
   - Entity List tab: add a filter + search box.
   - Graph View tab: move the entity-type filter to the top.
   - Remove the **Send email** action (duplicates **Request Action**).
8. **Compliance Map → Coverage Matrix** is empty: define what it demonstrates (jurisdiction × requirement/license-type coverage — which municipalities have which requirements researched/covered vs gaps), generate good synthetic data in line with the store-development use case, and render it.
9. **Action Digest (Compliance Map):** keep the per-doc links but **summarize the actions** and add a review link per action.
10. **Regulatory Pulse:** add a **summary**, **effective dates**, and **what action is required by when** for each change.
11. **Global — key/value display:** wherever extracted key/value pairs are shown (e.g. `field_value` = `{"value":...,"confidence":...}`), parse and show **only the value** for a cleaner read.
12. **Navigation:** review all navigation — especially **Back** — and ensure it is correct/smooth (URL sync, tab/sub-tab restore).
13. **Setup & Readiness compliance prompt editor:** it becomes read-only after save, shows only a small portion of the saved prompt, and doesn't scroll. Make it re-editable, show the full prompt, and make it scrollable.
