---
title: Access Kit × 360 — W5 Action Owner Audit
slug: access-kit-w5-action-owner-survey
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: "0.1.0"
---

# Access Kit × 360 — W5 Action Owner Audit

**Decision: no Access Kit write or action operation is declared.** The Access Kit
stays read-only for governed 360 data. The existing `continuations create`
operation is a principal-scoped durable resource write, not an action with an
external effect, and it does not count toward W5.

**Status.** All five gaps below are closed in the owner (see "Fixed in the owner").
No Access Kit action operation is declared, and none is needed to close W5: the
precondition work was in the owner, and adding an operation is a separate,
opt-in decision.

**Audit depth.** Line numbers in the table cite the code as it was at commit
`98f7e2f9c`, before the fixes below. This audit read the suggestion lifecycle end to end with file and
line citations: `lifecycle.py`, `service.py`, `repository.py`, `dispatcher.py`,
`policy.py`, `routes.py`, and `adapters/notification_adapter.py` under
`services/api/intelligence/suggestions/`. It read test names only, not test bodies.
Nothing here was run against a live tenant.

## Candidate: the suggestion lifecycle

`services/api/intelligence/suggestions/` is the strongest existing owner. It is a
tenant-scoped state machine with a policy decision, an audit trail, and a
notification hand-off. Citations are `file:line` inside that directory.

| W5 precondition | Finding | Status |
|---|---|---|
| Authenticated principal and tenant binding | Create rejects a `tenant_id` that differs from the caller (`service.py:63`, `routes.py:142`). Every read and transition goes through `get_or_fail(id, tenant_id)`, which returns not-found for another tenant (`repository.py:38-50`). | Met |
| Reviewer identity is the authenticated principal | `approve`, `reject`, and `suppress` use `body.actor_id or tenant_context.user_id` (`service.py:194`, `:221`, `:241`). A caller with `write` can record any `actor_id` as `reviewed_by` (`lifecycle.py:191-194`). | **Fixed:** reviewer is always the authenticated principal; `body.actor_id` is ignored |
| Rights and consent from the real owner | Policy only appends the string obligation `verify_consent_before_delivery` for marketing and identity classes (`policy.py:161-166`). No code calls a consent or rights owner. | **Gap: obligation is recorded, never checked** |
| Durable policy decision and approval chain | The decision is stored on the record (`service.py:124`). `requires_approval` blocks the `suggested → approved` shortcut (`lifecycle.py:131-139`). Approve needs `write` (`routes.py:172`); execute needs `admin` (`routes.py:211`). | Met for approval; see expiry |
| Expiry | `expires_at` is stored (`service.py:126`) and `EXPIRED` is a legal target (`lifecycle.py:57`), but nothing sets `EXPIRED` and approve never compares `expires_at` to the clock (`service.py:176-208`). | **Fixed:** approve, execute, and deliver check `expires_at`, move the suggestion to `EXPIRED`, and refuse |
| Atomic, idempotent create with a semantic fingerprint | `create_suggestion` always mints a new UUID (`service.py:82`) and inserts (`repository.py:30-32`). No idempotency key, no fingerprint. `find_by_source_ref` exists (`repository.py:114`) but is a 200-row scan used only by the recommendation adapter. | **Fixed:** optional `idempotency_key` plus a content fingerprint, scoped to tenant and principal; same key and content replays, same key and different content is a 409 |
| Atomic state transitions | `apply_transition` reads, validates, then calls `repo.transition`, which re-reads and checks `from_status` before `update` (`lifecycle.py:176-214`, `repository.py:145-154`). The check and the write are separate calls, not a compare-and-set. | **Fixed:** `repo.transition` is a compare-and-set on status and revision (`replace_if_matches`); the loser gets a conflict |
| Sequential double-approval | A second approve sees `APPROVED`, which is not `review_required` or `suggested`, and raises (`service.py:184-188`). | Met sequentially only |
| Owner-produced receipt and readback | Approval hands off to delivery and the suggestion stays `APPROVED` until a delivery worker confirms a provider receipt (`service.py:199-207`, `adapters/notification_adapter.py:91-94`). A hand-off failure is logged and the approval stands (`service.py:206-207`). | Met for notify-only delivery |
| Execution gate | Execute needs `APPROVED`, `execution_eligible`, and the `AETHER_SUGGESTIONS_EXECUTION_ENABLED` flag, which defaults to disabled (`service.py:257-265`). Only the recommendation source can run the legacy executor (`dispatcher.py:36-38`, `:54-55`). | Met; off by default |
| Dispatch failure handling | A non-validation error moves the suggestion to `FAILED` with an audit event; if that also fails the original record is returned unchanged (`dispatcher.py:113-130`). `FAILED` can go back to `review_required` (`lifecycle.py:100-103`). | Partly met |
| Replay and retry | Dispatch is a no-op for `EXECUTED`, `DELIVERED`, and `CLOSED` (`dispatcher.py:29-33`, `:78-80`). | Met for dispatch only |
| Compensation through authorized owners | No compensate, undo, or rollback code exists in the directory. `reversible` is a score input, not a mechanism (`service.py:118`). | **Gap: none** |

Tests exist for lifecycle, dispatcher, policy, repository, routes, service,
outcome, and tenant isolation (`services/api/tests/unit/test_suggestion_*.py`).
By test name, the only replay or idempotency cases are dispatcher no-ops
(`test_suggestion_dispatcher.py:216-246`) and recommendation find-or-create
(`test_suggestion_recommendation_adapter.py:188`). No test name covers expiry
enforcement, concurrent approval, create replay, or an `actor_id` override.

## Fixed in the owner

- `service.py`: reviewer from the principal; `_expire_if_due` on approve, execute,
  and deliver; deterministic suggestion ID and fingerprint for keyed creates.
- `repository.py`: `create_if_absent` and a compare-and-set `transition`. The
  `patch` that `apply_transition` always built (`reviewed_by`, `reviewed_at`,
  `closed_at`, `ooda_phase`) was never persisted before; it is now.
- `lifecycle.py`: `approved → expired` is a legal transition.
- `models.py`: `expires_at` must parse as an ISO 8601 timestamp.
- Tests: `test_suggestion_w5_owner_gaps.py` runs against the real in-memory
  repository (reviewer override, expiry, replay, conflict, principal scoping,
  concurrent creates, concurrent approvals).

## Consent, effect state, and compensation (fixed)

- `consent.py`: a suggestion has an `audience` (`tenant_staff` by default, or
  `end_user`). End-user suggestions must name a `consent_subject_id` and are
  delivered only when `shared.privacy.consent_enforcement.check_consent` (the
  consent owner) reports a grant for the purpose mapped from the suggestion class
  (`marketing` for campaign, retargeting, and notification; `personalization` for
  identity). A missing subject, no record, or a failed lookup is a denial.
- Enforcement points: `dispatcher.dispatch` (approval hand-off and execute) and
  `service.deliver_suggestion`. A denial leaves the status unchanged, writes a
  `delivery_blocked_consent` audit event, and sets `effect_state` to
  `blocked_consent`.
- `effect_state` records what is known about the effect: `pending_receipt` after a
  delivery hand-off, `confirmed` when delivery is recorded, `unverified` after the
  legacy executor reports success, `failed`, `blocked_consent`, and
  `compensation_requested`. A request alone never reads as success.
- Compensation: `POST /v1/suggestions/{id}/compensate` (admin) on an executed,
  delivered, or failed suggestion records who asked and why, sets
  `effect_state`, and emits `suggestion.compensation_requested` for the owner of
  the affected system. It does not reverse anything itself, and a replay is a
  no-op.

## Conclusion

The lifecycle is a sound base for a human-reviewed, notify-only flow. It is not
yet ready to back an Access Kit write operation. The original five owner-side
gaps were, in the owner and not in the adapter:

1. Take the reviewer from the authenticated principal; ignore `body.actor_id`
   unless the caller is a verified operator.
2. Enforce `expires_at` on approve, execute, and deliver, and add the transition
   to `EXPIRED`.
3. Add an idempotency key plus a semantic fingerprint scoped to tenant and
   principal on create.
4. Make `repo.transition` a compare-and-set on `from_status`.
5. Call the real consent or rights owner for classes that carry
   `verify_consent_before_delivery`, and add a compensation path or an explicit
   "effect unverified" state.

Then prove a full lifecycle through the direct API with double-approval, expiry,
replay, and partial-failure tests. Only then add one opt-in Access Kit operation,
with negative proof that read-only delegated tokens cannot call it.

Declaring an Access Kit action operation remains a separate decision. It would
still need the lifecycle proven through the direct API on a live tenant (W3) and
negative proof that read-only delegated tokens cannot call it.

A recorded request alone is not success; completion needs an owner-produced
receipt or an explicit "effect unverified" state.
