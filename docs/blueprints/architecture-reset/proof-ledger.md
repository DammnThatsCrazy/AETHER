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
| Operator diagnosis and runbook | Not replayed | Kyber source/event/identity/graph/billing/readiness inspection without alternate write authority | Pending |
| Staging deploy, wake, smoke, and sleep | No verified snapshot recorded for this reset | Immutable release, plan/policy review, awake lease, smoke, rollback, and sleep evidence | Pending |
| Design-partner source proof | None recorded for this reset | One permitted real source and tenant traverses the proof path with recoverable failures | Pending |
| Normal PR authority | Not run during accumulation | `verification / disposition` terminal result after `ready_for_review` | Pending |
| Release claim | Not requested or run | Canonical release gate and `scripts/production_status.py` scorecard plus live operational evidence | Pending |

## Cutover decision record

Before retiring an old path, fill in a dated row with the old owner, new owner,
consumer list, compatibility alias, data migration, old/new comparison,
rollback action, and evidence link. A directory move without that record is
not a completed authority migration.

| Date | Path or authority | Old owner | New owner | Compatibility and data handling | Evidence | Rollback | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Pending | No cutover approved | — | — | — | — | — | Pending |
