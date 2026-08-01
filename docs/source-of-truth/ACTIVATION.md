---
title: Self-Serve Tenant Activation
slug: concepts/activation
section: concepts
visibility: I
audience: [architect, dev-senior, ops]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/activation/models.py
  - Backend Architecture/aether-backend/services/activation/repository.py
  - Backend Architecture/aether-backend/services/activation/service.py
  - Backend Architecture/aether-backend/services/activation/routes.py
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 3
last_synced_commit: "fffcd7dc5f02"
---

# Self-Serve Tenant Activation

Activation is the tenant-facing loop that takes a new tenant from account
creation to first proven value, without operator hand-holding. It is additive
to — and does **not** replace — the CS-driven onboarding/implementation-plan
subsystem (`services/onboarding`). It is mounted at `/v1/activation` **only when
`AETHER_ACTIVATION_ENABLED=true`** (default OFF; zero runtime change when off).

## State machine

`ActivationState` (`services/activation/models.py`) — one record per tenant,
persisted in `tenant_activations`:

```
not_started → account_verified → plan_selected → billing_pending → billing_active
  → sdk_selected → keys_created → waiting_for_event → event_received
  → first_value_ready → complete
```

Off-path honest-halt states, set only when a precondition cannot be met (never
faked into a forward state): `manual_pending`, `blocked`, `externally_blocked`.

`ActivationService.advance()` enforces an explicit `allowed_from` transition map;
an illegal transition raises `ConflictError` (HTTP 409). A no-op self-transition
restamps `updated_at` but records no new history entry.

## Endpoints

| Method | Path | Effect |
|---|---|---|
| `GET`  | `/v1/activation/status` | Current record + derived `billing_state` (lazily creates `not_started`). |
| `POST` | `/v1/activation/select-plan` | Records `plan_tier` (P1–P4) only. Never calls billing checkout. |
| `POST` | `/v1/activation/sdk-selection` | Records target platforms. |
| `POST` | `/v1/activation/create-sdk-keys` | Mints ingestion keys (returns raw key **once**). |
| `POST` | `/v1/activation/test-event` | Sends a canonical event through `/v1/batch` in-process. |
| `GET`  | `/v1/activation/first-value` | Honest first-value proof from the Bronze ledger. |
| `POST` | `/v1/activation/complete` | Allowed only when state is `first_value_ready`. |

Tenant scope is derived from `request.state.tenant` only — never from the body.
GETs require `read`; state-changing POSTs require `Permissions.WRITE`.

## Reuse seams (no reimplementation)

- **Keys** — reuses the registration key-mint primitives (`APIKeyRepository` +
  `api_key_validator.register_api_key`), persisting only hashed key ids.
- **Test event** — calls `ingest_batch(...)` in-process, reusing the durable
  Bronze write, idempotency (`sha256(tenant_id:event_id:schema_version)`), and
  per-event `accepted|duplicate|rejected` semantics. A re-fired event is
  `duplicate` and does not double-count.
- **Billing state** — derived read-only from `stripe_repository.get_billing_account`;
  activation never writes billing.
- **First value** — read from `BronzeRepository("sdk_events")`; distinguishes
  `waiting_for_event` (no rows) / `event_received` (≥1 row) / `first_value_ready`
  (durable row confirmed). Evidence carries the real `event_id`/`batch_id` — never
  a hard-coded success.

## Tenant isolation

Every repository read filters on `tenant_id`; a tenant can neither read nor
advance another tenant's activation, and key ids never leak across tenants
(enforced by `tests/activation/test_activation_tenant_isolation.py`).

## Known limitations

- Flag-gated OFF by default; there is no end-to-end/integration proof under a
  live tenant yet — coverage is unit-level (`tests/activation/`, 39 tests).
- The V2/canary ingestion path writes typed Bronze rather than `bronze_sdk_events`,
  so first-value may lag for canary tenants (documented, not worked around).
