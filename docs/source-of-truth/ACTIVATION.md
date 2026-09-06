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
  - Backend Architecture/aether-backend/services/activation/intents.py
  - Backend Architecture/aether-backend/services/activation/planner.py
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
| `GET`  | `/v1/activation/status` | Current record + derived `billing_state` + the tenant's durable `intents` (WS-3, lazily creates `not_started`). |
| `POST` | `/v1/activation/select-plan` | Records `plan_tier` (P1–P4) only. Never calls billing checkout. |
| `POST` | `/v1/activation/sdk-selection` | Records target platforms. |
| `POST` | `/v1/activation/create-sdk-keys` | Mints ingestion keys (returns raw key **once**). |
| `POST` | `/v1/activation/test-event` | Sends a canonical event through `/v1/batch` in-process. |
| `GET`  | `/v1/activation/first-value` | Honest first-value proof from the Bronze ledger. |
| `POST` | `/v1/activation/complete` | Allowed only when state is `first_value_ready`. |
| `GET`  | `/v1/activation/intents` | WS-3 intent picker: every `ActivationIntent` goal + its recommended experience categories, plus the canonical category order/labels. |
| `POST` | `/v1/activation/intents` | Saves the tenant's chosen intent tokens (validated, canonical order, replace-on-reselect). |
| `GET`  | `/v1/activation/plan` | Recommended connect plan per experience, derived from REAL tenant connector rows (never fabricated). |
| `POST` | `/v1/activation/connect-action` | Runs one connect step through `connector_service` (`create_tenant_integration \| configure_credential \| enable_connection \| first_sync`). |

Tenant scope is derived from `request.state.tenant` only — never from the body.
GETs require `read`; state-changing POSTs require `Permissions.WRITE`.

## Intent-driven activation (WS-3)

The activation flow also turns a tenant's *goals* into connect steps over the
shared connect contracts (`connector_service` + the credential service + the
consent policy — the same runtime behind Settings). Goal vocabulary lives in
`ActivationIntent` (`services/activation/intents.py`, stable snake_case tokens
shared with the tenant UI: `grow_revenue`, `run_advertising`, `know_customers`,
`engage_customers`, `understand_behavior`, `grow_community`,
`support_customers`, `streamline_work`). Each intent recommends an ordered set
of `ExperienceCategory` values; recommended integrations are derived from the
one catalog (`ALL_MANIFESTS`) — never a hand-synced provider list.

The planner (`services/activation/planner.py`) reads the tenant's chosen
intents (persisted on the same `tenant_activations` record, orthogonal to the
SDK state machine) and derives, per recommended experience, each integration's
next connect step from the tenant's REAL connector row facts (enabled /
`secret_configured` / `sync_status`). Only a healthy sync yields `connected`;
a missing credential / disabled connector / never-synced integration each maps
to exactly one next action (`configure_credential` / `enable_connection` /
`first_sync`); a failed or degraded sync surfaces an honest attention state
with no fabricated forward step. Integration connect steps reuse
`connector_service.configure`/`sync`, so credentials go to the credential
service and enablement through the consent policy, with no second
implementation. Only self-service `ingestion`-product manifests offer an
activation connect action; advertising/payment-rail entries with their own
connect flows are surfaced honestly as non-actionable (`connectable: false`).

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
  live tenant yet — coverage is unit-level + route-surface (`tests/activation/`),
  including the WS-3 intent/plan/connect-action suites.
- The V2/canary ingestion path writes typed Bronze rather than `bronze_sdk_events`,
  so first-value may lag for canary tenants (documented, not worked around).
