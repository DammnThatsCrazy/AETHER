---
title: Access Kit × 360 — W5 Action Owner Survey
slug: access-kit-w5-action-owner-survey
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: "0.1.0"
---

# Access Kit × 360 — W5 Action Owner Survey

**Decision: no Access Kit write or action operation is declared.** The Access Kit
stays read-only for governed 360 data. The existing `continuations create`
operation is a principal-scoped durable resource write, not an action with an
external effect, and it does not count toward W5.

**Survey depth.** This was a shallow code survey (file names, enums, route lists,
test names). Items marked unknown were not read. It is not a W5 precondition audit
with file and line citations. The audit agent that was to produce one was stopped
by an API rate limit before it wrote anything.

## Candidate: the suggestion lifecycle

`services/api/intelligence/suggestions/` is the strongest existing owner found. It
is a tenant-scoped, approval-gated state machine with a policy decision, expiry,
audit events, an outcome record, and routes for approve, reject, suppress,
execute, deliver, and outcome.

| W5 precondition | Observed | Status |
|---|---|---|
| Authenticated principal and tenant binding | `test_suggestion_tenant_isolation.py` exists | Partly met; route auth not read |
| Rights and consent from the real owner | Not seen in the service or models | Unknown |
| Durable policy decision and approval chain, with expiry | `SuggestionPolicyDecision`, `requires_approval`, `expires_at`, and `approve`/`reject` routes exist | Partly met |
| Atomic cross-instance idempotent create with semantic fingerprint | No idempotency or fingerprint code matched in `service.py` | Not seen |
| Durable state machine | `SuggestionStatus` runs detected → … → executing → executed → delivered → measured → closed, plus expired and failed | Met on paper; transition atomicity unread |
| Owner-produced receipt, readback, and effect vs request | A code comment says a suggestion stays `APPROVED` until the delivery worker confirms a provider receipt; `SuggestionOutcome` exists | Partly met |
| Compensation through authorized owners | No compensate or rollback code matched | Not seen |
| Replay, retry, denial, expiry, double-approval, and partial-failure tests | Lifecycle, dispatcher, policy, and outcome test files exist; contents unread | Unknown |

## What must be true before any write operation is declared

1. Read the suggestion service and repository end to end, then re-run this table
   with file and line citations.
2. Close the gaps found: an idempotency key with a semantic fingerprint scoped to
   principal and tenant, a rights and consent check against the real owner, and a
   compensation path.
3. Prove a full lifecycle through the direct API, with double-approval, expiry,
   replay, and partial-failure tests.
4. Only then add one explicitly declared, opt-in Access Kit operation, with
   negative proof that read-only delegated tokens cannot call it.

A recorded request alone is not success; completion needs an owner-produced
receipt or an explicit "effect unverified" state.
