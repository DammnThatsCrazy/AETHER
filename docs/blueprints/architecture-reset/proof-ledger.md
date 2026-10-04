---
title: Aether Architecture Reset Proof Ledger
slug: blueprints/architecture-reset/proof-ledger
section: blueprints
visibility: I
audience: [architect, dev-senior, ops, security]
status: experimental
since_version: 0.1.0
---

# Architecture reset proof ledger

**Baseline:** `Development` commit `17503aef9fa3a9515a029471796f1ee3510a5b2c`.
This ledger starts with no baseline or target runtime proof. Repo paths and
tests in the authority maps are candidate evidence, not completed proof.

For each row, record a command or procedure, commit, environment, fixture or
tenant, result, evidence location, owner, and recovery/rollback. Keep local,
hosted PR, staging, provider-backed, and release evidence separate. A failed
or unavailable result stays visible.

| Proof path | Baseline at reset start | New-path evidence required | Status |
| --- | --- | --- | --- |
| Tenant provision, auth, roles, and billing/pilot access | Not replayed for this reset | Scoped tenant creation, authorized/denied reads, entitlement and billing fail-closed states | Pending |
| Source connect, credential, consent/rights, and health | Not replayed | Source-specific connection and data-rights admission, honest waiting/degraded/revoked states | Pending |
| SDK/provider/import event acceptance | Not replayed | Tenant/source-scoped idempotent acceptance, duplicate/corrupt rejection, source identity preserved | Pending |
| Raw evidence and replay identity | Not replayed | Durable evidence, provenance, version, event/ingestion time, retention and replay key | Pending |
| Normalization and classification | Not replayed | Canonical typed fact; source versus campaign distinct; missing/empty/zero and late-event semantics | Pending |
| Identity/entity decision | Not replayed | Merge, no-merge, review, cross-namespace collision, correction and audit evidence | Pending |
| Governed graph mutation/query | Not replayed | `MutationIntent` gateway, tenant isolation, idempotency, partial failure and history/diff | Pending |
| Journey, touchpoint, attribution, and value | Not replayed | Versioned computation with evidence, time window, correction, and distinct attribution credit | Pending |
| Profile, Journey, Graph, Lens, and Value views | Not replayed | Populated, empty, loading, error, partial/stale, denied, and explanation states | Pending |
| Governed action and measured outcome | Not replayed | Eligibility, confirmation/approval, audit, receipt, outcome and failure recovery | Pending |
| Quarantine, dead letter, replay, and backfill | Not replayed | Authorized tenant-scoped repair from retained evidence with before/after diff | Pending |
| Bronze/Silver rollback, source-tag audit, and evidence lifecycle | Not replayed; code review found hard-delete-by-tag paths without tenant predicates and a 10,000-row query cap | Same-tag cross-tenant isolation, exact affected-row accounting, actor/reason/correlation record, authorized audit scoping, and explicit erasure behavior | High-priority gap; correction and focused adversarial tests pending |
| Operator diagnosis and runbook | Not replayed | Kyber source/event/identity/graph/billing/readiness inspection without alternate write authority | Pending |
| Staging deploy, wake, smoke, and sleep | No verified snapshot recorded for this reset | Immutable release, plan/policy review, awake lease, smoke, rollback, and sleep evidence | Pending |
| Design-partner source proof | None recorded for this reset | One permitted real source and tenant traverses the proof path with recoverable failures | Pending |
| Normal PR authority | Not run during accumulation | `verification / disposition` terminal result after `ready_for_review` | Pending |
| Release claim | Not requested or run | Canonical release gate and `scripts/production_status.py` scorecard plus live operational evidence | Pending |

## Recorded local baseline evidence

| Date | Revision and environment | Command | Result | What it establishes | What remains unproved |
| --- | --- | --- | --- | --- | --- |
| 2026-10-04 | `Development` `17503aef9fa3a9515a029471796f1ee3510a5b2c`, detached local baseline checkout, project virtual environment | `PYTHONPATH=services/backend /Users/osazehunt/AETHER/.venv/bin/python -m pytest tests/unit/observation/test_golden_cross_path_fixture.py -q` | 1 passed in 2.84s | The existing fixture observes one SDK batch event, its Bronze replay, and the legacy event-alias path on the canonical bus with original event time and no second Bronze row on replay. | This uses local in-memory stores and a fake producer. It does not exercise a real provider, Silver/identity/graph, persistent retry, tenant authorization, staging, or a deployed UI. |
| 2026-10-04 | Same detached baseline and interpreter | `PYTHONPATH=services/backend /Users/osazehunt/AETHER/.venv/bin/python -m pytest services/backend/tests/identity/test_late_binding_end_to_end_proof.py services/backend/tests/ingestion/test_bronze_hash_chain.py -q` | 7 passed in 14.69s | Focused identity continuity and Bronze chain behavior pass at the baseline commit. | The tests do not join a real provider delivery to a customer-visible graph view. |
| 2026-10-04 | Same detached baseline and interpreter | `PYTHONPATH=services/backend /Users/osazehunt/AETHER/.venv/bin/python -m pytest tests/unit/graph_gateway/test_mutation_gateway.py -q` | 18 passed in 14.47s | Focused gateway mode, mutation, and ledger behavior passes at the baseline commit. | This does not establish that every live writer uses enforced mode or that a durable ledger/projector transaction survived failure. |

This baseline test supplies a comparison point for a later path cutover. A
single local fixture is not an old/new equivalence decision. Record the target
revision and repeat the same fixture plus durable and adverse-path evidence
before retiring any intake or replay authority.
The backend and root `tests/` trees have conflicting `tests.conftest` import
names when collected in one invocation in this checkout, so the latter two
baseline commands were run separately. The combined invocation failed during
collection and is not counted as a test result.

## Cutover decision record

Before retiring an old path, fill in a dated row with the old owner, new owner,
consumer list, compatibility alias, data migration, old/new comparison,
rollback action, and evidence link. A directory move without that record is
not a completed authority migration.

| Date | Path or authority | Old owner | New owner | Compatibility and data handling | Evidence | Rollback | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Pending | No cutover approved | — | — | — | — | — | Pending |
