---
title: Account Lifecycle and Erasure
slug: source-of-truth/account-lifecycle
section: source-of-truth
visibility: I
audience: [dev-senior, ops, architect]
status: draft
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/account_lifecycle/models.py
  - Backend Architecture/aether-backend/services/account_lifecycle/storage_registry.py
  - Backend Architecture/aether-backend/services/account_lifecycle/service.py
  - Backend Architecture/aether-backend/services/account_lifecycle/routes.py
  - Backend Architecture/aether-backend/alembic/versions/20260813_account_deletion_workflow.py
canonical_owner: platform@aether
estimated_read_minutes: 4
toc_depth: 3
---

# Account Lifecycle and Erasure

The account-deletion model is one explicit state machine: an authenticated,
step-up-verified request suspends the tenant immediately, leaves a durable
30-day recovery window, and then permits irreversible processing. Replays use
the tenant/idempotency-key unique constraint and do not create a second
workflow.

## Durable evidence

`account_deletion_workflows` stores the request and recovery timestamps,
status, actor and re-authentication evidence metadata, idempotency key,
per-storage-domain results, retry count, completion/failure/cancellation
timestamps, and a versioned machine-readable erasure manifest. Raw passwords,
bearer tokens, and MFA assertions are never stored. Evidence must be supplied
by a trusted authentication orchestrator, be marked verified, and be no more
than 15 minutes old.

## Storage boundary

`storage_registry.py` is the authoritative coverage boundary. Every registered
tenant-scoped repository must map to a storage domain before the worker can
claim coverage. Sessions, service credentials, public ingest identifiers, and
API keys are revoked immediately using their safe service calls. Tenant core
records are erased only after the recovery window. Billing and audit records
are preserved as detached retention stubs with a pseudonymous tenant reference
and a legal-obligation reason; they are not treated as ordinary application
data.

This deployment does not expose tenant-scoped graph, object-store, or search
erasure providers. The manifest records those domains as `unavailable` or
`deferred`, with an explicit reason and `fully_erased: false`; no route or
worker claims that those providers were deleted.

## Orchestrator integration

The router is intentionally not mounted by this slice. The orchestrator must:

1. import `router` from `services.account_lifecycle.routes` and mount it after
   the existing authentication middleware and route-policy registry;
2. authorize the four routes for an authenticated tenant administrator and
   provide trusted step-up evidence to request/cancel calls;
3. schedule `process-retry` after `recovery_until` with a durable worker/retry
   policy; and
4. expose matching route and contract entries to the central API client and
   frontend in their owning change.

No `main.py`, broad auth route, or central frontend client is changed here.
