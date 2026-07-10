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
