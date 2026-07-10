# Component 3 — Action Management Framework (reuse-aware)

> **Status: IMPLEMENTED in Phase 1.** `platform.escalation_rules` + a deterministic
> `evaluate_escalations()` / `_apply_escalation_rule()` are in `app/backend/docintel_routes.py`,
> wired into `POST /action-master` (optional context signals) and exposed via
> `GET/POST /escalation-rules` and `POST /escalation-evaluate` (for change-detection).

## Goal
Add a **deterministic escalation rules engine** to the existing action framework. Do **not** create a new `platform.actions` table.

## What already exists — DO NOT rebuild
- `platform.action_master` + `platform.action_history` with a lifecycle state machine `_ACTION_STATUS_FLOW` (`app/backend/docintel_routes.py` ~4332): `OPEN → INITIATED → IN_PROGRESS → PENDING_VERIFICATION → COMPLETED`, plus `IGNORED`/`CANCELLED`. Stage fields: `owner, due_date, eta, verified_by, ignore_reason, cancel_reason`.
- Endpoints: `POST/GET /api/docintel/action-master`, `PATCH /action-master/{id}` (validates transitions, writes audit rows), `GET /action-master/{id}/history`, `GET /action-reports`.
- `platform.attorney_review_queue` (statuses `PENDING | CLEARED | ESCALATED`) + a HIGH/MEDIUM/LOW confidence signal and `attorney_review` flag.
- Frontend: Action Center + Action Reports in `app/frontend/src/app/supply-chain/page.tsx` (the `actions` tab).

Map the doc's requested tables onto these: `actions`→`action_master`, `action_history`→`action_history`, `action_assignments`/`action_evidence`→columns/history rows on the existing tables (add only if a real need emerges). `action_escalations` is the genuine gap below.

## Gap to fill
1. **`platform.escalation_rules`** (new config table): `rule_id, domain_id (nullable=all), rule_type, params JSON, target (attorney_review|priority_bump|notify), active`. Seed rule types:
   - `low_confidence` — extraction/answer confidence `< threshold` (default 0.85).
   - `deadline_risk` — license/permit `lead_time` + today `>` `expected_open_date`.
   - `requirement_change` — a change-detection event fired for the entity.
   - `high_value` — project flagged strategic/high-value.
2. **Deterministic evaluator** `evaluate_escalations(action|entity, context) -> [triggered_rules]`, invoked when actions are created and when change detection fires. On trigger: set `attorney_review`, insert into `attorney_review_queue` (reason = rule id + explanation), optionally bump priority. Replace the current substring-driven escalation with this rules pass (keep the LLM hint as one optional input, not the decision).
3. Expose `GET /api/docintel/escalation-rules` (+ optional CRUD) so the UI can show/edit rules.

## Deliverables
- DDL + seed for `platform.escalation_rules`.
- `evaluate_escalations()` in `docintel_routes.py`, wired into action-create + change-detection.
- New endpoint(s) for rules.

## Acceptance criteria
- Creating an action with confidence `0.7` auto-lands in `attorney_review_queue` via `low_confidence`, with a traceable reason.
- A license lead-time exceeding `expected_open_date` triggers `deadline_risk` deterministically (no LLM).
- Existing action lifecycle/endpoints/tests for supply_chain + compliance unaffected.

## Constraints
Extend `action_master`/`attorney_review_queue`; do not replace them. Rules must be pure/deterministic and unit-testable.
