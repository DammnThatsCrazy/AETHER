---
title: "Payment-Rail Financial Plane — Activation, Operations & Rollback"
slug: operations/payment-rails-activation
section: operations
visibility: I
audience: [ops, dev-senior]
status: beta
since_version: "8.12.0"
canonical_owner: platform@aether
related:
  - docs/runbooks/PAYMENT_RAILS_RUNBOOK.md
  - docs/runbooks/FINANCIAL_CREDENTIAL_READINESS_RUNBOOK.md
  - docs/source-of-truth/PAYMENT_RAIL_OBSERVABILITY.md
---

# Payment-Rail Financial Plane — Activation, Operations & Rollback

Aether **observes** payment rails. It never executes, settles, originates, or
custodies funds. This document is the operator guide for activating and running
the five payment-provider adapters and their supporting financial-observability
systems. It covers the credential authority, webhook endpoints, polling, the
receipt/canonical-delivery lifecycle, repair, observability, alerts, release
flags, the activation checklist, rollback, and the certification commands.

> Readiness language only. A provider is not "sandbox-validated" or
> "production-validated" until executable evidence exists (see
> [Evidence for promotion](#evidence-for-readiness-state-promotion)). Do not edit
> a readiness state in any doc ahead of its evidence.

## Provider capability matrix

| Provider             | Signed webhooks | Read-only polling            | Required credential slots                  |
| -------------------- | --------------: | ---------------------------- | ------------------------------------------ |
| Privy                |             Yes | No — webhook-only by design  | `webhook_signing_secret`                   |
| Stripe Crypto Onramp |             Yes | No — webhook-only by design  | `webhook_signing_secret`                   |
| Coinbase             |             Yes | Yes                          | `webhook_signing_secret`, `onramp_api_key` |
| MoonPay              |             Yes | Yes                          | `webhook_signing_secret`, `server_api_key` |
| Bridge               |             Yes | Yes                          | `webhook_signing_secret`, `api_key`        |

Privy and Stripe are webhook-only *by provider design*, not because the adapter
is unfinished — their connection test resolves to a typed `webhook_only` result.

## Credential slots & lifecycle

Provider credentials live in the durable, multi-slot **CredentialAuthority**
(`provider_credential_versions` table), KMS-encrypted at rest with a 5-key
encryption context `{tenant, provider, environment, slot, version}`. Each slot
(webhook signing secret, polling API key) rotates, validates, revokes, and
deletes **independently**. The in-memory BYOK vault is retired for payment
providers outside local development — the authority is the sole source.

Version state machine:

```
create_pending → test → activate → (rotate → previous/overlap) → revoke → delete
```

- `create_pending` — store an encrypted, PENDING version (idempotency-keyed).
- `test` — a real HMAC self-check (signing secret) or a read-only provider probe
  (polling key) outside local; a failing probe on a pending version marks it
  `test_failed` and never touches the active version.
- `activate` — promote to ACTIVE (optimistic concurrency); the prior active is
  demoted to `previous` for a bounded overlap (webhook secrets only).
- `rotate` — `create_pending` + `activate`; the previous secret still verifies
  during `CREDENTIAL_ROTATION_OVERLAP_HOURS`.
- `revoke` / `delete` — retire; ciphertext is erased on delete (audit stub kept).

### Rotation procedure (webhook signing secret)

1. `create_pending` the new secret for the slot.
2. `test` it (HMAC self-check).
3. `activate` — the old secret becomes `previous` and both verify during the
   overlap window. Provider redeliveries signed with either succeed.
4. Register the new secret with the provider.
5. After the overlap window the previous version is swept to tombstoned
   automatically.

## Webhook endpoint registration

Public webhook URLs use a durable, high-entropy, server-resolved endpoint id:

```
/v1/integrations/webhooks/payment-rails/{provider}/{endpoint_id}
```

The tenant **and** environment are resolved from the endpoint registry — never
from a request header. Unknown / revoked / cross-provider / cross-tenant /
cross-environment ids return a uniform `404` that reveals nothing. The provider
signature is still verified natively. At most one **active** endpoint exists per
(tenant, provider, environment) (DB partial-unique index).

The legacy header-tenant route `/{provider}` (`X-Aether-Tenant-ID`) is
**retired**: available only in local development behind
`AETHER_PAYMENT_LEGACY_WEBHOOK_ROUTE_ENABLED`, and returns `404` everywhere else.

Register/rotate/revoke endpoints via the tenant-admin API under
`/v1/integrations/providers/{provider}/webhook-endpoints`.

## Polling enablement (Coinbase, MoonPay, Bridge)

Read-only polling resolves its API key from the CredentialAuthority
(`onramp_api_key` / `server_api_key` / `api_key`) for the threaded environment —
never the legacy vault outside local. Polling preserves bounded pagination,
cursor/time-window incremental sync, tenant-scoped cursor state, idempotent
ingestion (webhook & polling converge on one funding session), rate-limit /
transient-error handling, and auth-failure-vs-unavailability classification. One
provider failing never aborts the sync worker cycle.

## Environment separation

Credential environment is `sandbox` | `live` and is threaded explicitly from the
webhook endpoint, the tenant connection, or the request — never selected solely
from process-wide `AETHER_ENV`. Staging validates against **sandbox** provider
credentials; production uses **live**. A sandbox credential can never be decrypted
under a live context (bound into the KMS encryption context). Provider base URLs
are selected by environment (server-owned), e.g. Bridge sandbox
`api.sandbox.bridge.xyz`.

### Provider sandbox / production setup (per provider)

For each provider: obtain sandbox credentials from the provider console, provision
them to the `sandbox` environment slots via the credential API, register the
sandbox endpoint URL with the provider, and run the connection probe (pull
providers). Repeat for `live` in production. Never commit provider credentials.

## Receipt & canonical-delivery lifecycle

Every provider delivery (a verified webhook or a polled record) gets one durable,
metadata-only **receipt** (`payment_provider_receipts`) — the delivery ledger.
Its id is deterministic (uuid5 over tenant/provider/endpoint/event-id|body-hash),
so a provider retry, a webhook↔polling overlap, or a repair all map to one
receipt. Stages:

```
received → endpoint_resolved → signature_verified → parsed → normalized →
funding_session_persisted → canonical_event_written → outbox_enqueued →
outbox_published → consumed_or_projected → completed
```

Terminal / recoverable: `rejected`, `quarantined`, `retry_pending`,
`repair_pending`, `dead_lettered`. The receipt links each observation to its
funding session, canonical event id(s), and outbox record. **No plaintext
credentials or raw sensitive payloads are stored** (only a sha256 body hash).

Canonical delivery is deterministic: `canonical_event_id` is a uuid5 over
(tenant, session, event_type), so re-emission is a downstream-idempotent no-op.
When `AETHER_PAYMENT_CANONICAL_OUTBOX_ENABLED` is on, canonical events are written
atomically to the durable Bronze + `event_outbox` spine and the supervised relay
publishes them; otherwise a direct publish is used. **Enable the canonical outbox
and `OUTBOX_RELAY_ENABLED` together** — an enabled outbox with a disabled relay
strands events (the canonical-repair worker and the `PaymentRailCanonicalBacklog`
alert catch this, but the correct configuration enables both).

### Repair, replay & dead-letter

A supervised **canonical-repair worker** (`payment_canonical_repair`, materializer
role, `AETHER_PAYMENT_CANONICAL_REPAIR_ENABLED`, default ON outside local) scans
incomplete receipts and funding sessions with an emission gap and idempotently
re-drives canonical emission / outbox enqueue (the deterministic id dedupes both
paths — never double-emits or double-bills). Bounded retries then dead-letter. A
manual, admin-authorized, audited repair endpoint
(`POST /v1/integrations/providers/payment-rails/canonical-backlog/repair`) drives
the same repair on demand. Dead-lettered receipts are durable and inspectable for
manual replay.

## Usage metering

One billable payment-rail unit = **one newly accepted canonical financial
observation**, keyed by the deterministic canonical event id and idempotent on
replay. Provider retries, polling overlap, reconciliation, repair, replays, and
duplicate deliveries are **not** billable. The meter is fail-open (a metering
failure never drops an observation) and **off by default**
(`AETHER_PAYMENT_USAGE_METERING_ENABLED=false`) until the billing contract is
confirmed — the code path is complete.

## Observability

- **Tenant** (`/v1/integrations/providers/payment-rails/health` + session
  drill-down): provider connection/health, sessions + status counts, verified /
  rejected webhooks, reconciliation match/conflict, native source/destination
  values, fees, asset/chain, and campaign/journey/user/agent/org/device
  attribution.
- **Kyber operator** (`/v1/admin/kyber/payment-rails/health` and `/{tenant_id}`):
  a typed, versioned contract (`kyber_contract.py`, mirrored by the frontend zod
  schema). Fleet totals + per-provider + per-tenant rows; per-tenant nested
  adapter + health, credential-slot states (no secrets), webhook-endpoint
  registration, delivery backlogs, recent audit, and recent repair outcomes.
  Unknown values are `null` (never a misleading `0`); provider state distinguishes
  `healthy` / `degraded` / `error` / `not_configured` / `disabled` / `unknown`.

## Alerts

Prometheus rules (group `aether_payment_rails` in
`deploy/observability/prometheus/alert_rules.yml`). Meanings:

| Alert | Meaning |
|---|---|
| `PaymentRailNoWebhookInWindow` | A webhook-only provider has gone silent past its window |
| `PaymentRailRepeatedSignatureFailures` | Sustained rejected-signature rate (rotated/wrong secret or a probing caller) |
| `PaymentRailUnknownEndpointBurst` | Burst of unknown-endpoint requests (enumeration / stale provider config) |
| `PaymentRailProviderAuthFailure` | Polling API key rejected (revoked/rotated/wrong environment) |
| `PaymentRailProviderRateLimited` | Repeated provider 429s |
| `PaymentRailProviderUnavailable` | Repeated provider 5xx/timeout/network errors |
| `PaymentRailStalePollingCursor` | No successful poll in the window |
| `PaymentRailSyncWorkerHeartbeatLoss` | Sync worker stopped completing cycles |
| `PaymentRailRepairWorkerHeartbeatLoss` | Repair worker stopped completing cycles |
| `PaymentRailOldestIncompleteReceipt` | A receipt has been incomplete past threshold |
| `PaymentRailCanonicalBacklog` | Canonical/outbox delivery is falling behind |
| `PaymentRailOutboxDeadLetterGrowth` | Dead-letters growing — manual replay required |
| `PaymentRailProviderPollDegraded` | Provider poll health non-ok |

Thresholds are environment-tunable (`AETHER_PAYMENT_SYNC_INTERVAL_SECONDS`,
`AETHER_PAYMENT_RECON_STALE_AFTER_SECONDS`, per-environment rules overlay). No
secret or provider payload ever appears in an alert.

## Release feature flags

| Flag | Default | Purpose |
|---|---|---|
| `AETHER_PAYMENT_RAILS_ENABLED` | off | Master switch |
| `AETHER_PROVIDER_{PRIVY,STRIPE,COINBASE,MOONPAY,BRIDGE}_ENABLED` | off | Per-provider |
| `KYBER_PAYMENT_RAILS_ENABLED` | off | Kyber operator surfaces |
| `AETHER_PAYMENT_CREDENTIAL_AUTHORITY_ENABLED` | **on outside local** | Durable authority (mandatory) |
| `AETHER_PAYMENT_CANONICAL_OUTBOX_ENABLED` | off | Durable canonical delivery |
| `OUTBOX_RELAY_ENABLED` | off | Event-outbox relay (enable WITH the canonical outbox) |
| `AETHER_PAYMENT_CANONICAL_REPAIR_ENABLED` | **on outside local** | Supervised repair worker |
| `AETHER_PAYMENT_USAGE_METERING_ENABLED` | off | Billing meter (keep off until contract confirmed) |
| `AETHER_PAYMENT_LEGACY_WEBHOOK_ROUTE_ENABLED` | off | Local-dev-only header route (404 elsewhere) |
| `CREDENTIAL_CIPHER` / `CREDENTIAL_KMS_KEY_ID` | `local` / — | KMS cipher (aws_kms required outside local) |

## Activation checklist

1. Apply database migrations (`alembic upgrade head`).
2. Apply/verify the AWS KMS infrastructure (terraform `modules/kms_credentials`).
3. Set `CREDENTIAL_CIPHER=aws_kms` + `CREDENTIAL_KMS_KEY_ID` (startup fails closed
   otherwise).
4. Provision all required credential slots via the credential API.
5. `test` each credential version.
6. `activate` each credential.
7. Create durable webhook endpoint ids.
8. Register endpoint-id webhook URLs with each provider.
9. Enable `AETHER_PAYMENT_RAILS_ENABLED`.
10. Enable providers one at a time.
11. Enable the canonical outbox for a canary tenant.
12. Enable `OUTBOX_RELAY_ENABLED`.
13. Enable `AETHER_PAYMENT_CANONICAL_REPAIR_ENABLED`.
14. Send real provider sandbox webhook events.
15. Run Coinbase/MoonPay/Bridge read-only connection probes.
16. Verify webhook & polling convergence.
17. Test provider-secret rotation + previous-secret overlap.
18. Simulate interrupted delivery and verify automated repair.
19. Verify Kyber fleet & tenant views.
20. Verify Aether tenant observability.
21. Run the financial certification commands.
22. Conduct a staging soak.
23. Collect evidence.
24. Promote each provider from `credential_waiting` to `sandbox_validated` only
    when evidence supports it.
25. Enable the founding tenant / design partner.
26. Promote to production-provider validation only after live evidence.

## Rollback (never deletes financial records)

- **Disable one provider** — `AETHER_PROVIDER_<X>_ENABLED=false`.
- **Disable polling, keep webhooks** — revoke/deactivate the polling API-key slot
  (webhook verification is unaffected).
- **Disable webhook ingestion** — `AETHER_PAYMENT_RAILS_ENABLED=false` (endpoints
  return the master-off response); or revoke endpoints.
- **Disable the relay without losing the outbox** — `OUTBOX_RELAY_ENABLED=false`;
  rows accumulate durably in `event_outbox` and drain when re-enabled.
- **Pause the repair worker** — `AETHER_PAYMENT_CANONICAL_REPAIR_ENABLED=false`.
- **Revoke a compromised credential** — `revoke` the slot version (fails closed).
- **Failed rotation** — `activate` the previous credential version.
- **Disable a webhook endpoint** — `revoke` the endpoint id (uniform 404).
- **Observation-only mode** — disable the canonical outbox + repair; funding
  sessions and receipts still persist.
- **Roll back frontend observability independently** — the Kyber/Aether pages are
  read-only over the same contract; reverting them does not affect ingestion.
- **Recover incomplete receipts after rollback** — re-enable the repair worker (or
  run the manual repair endpoint); it re-drives from the durable ledger.

## Certification commands

```bash
make financial-credential-readiness-strict   # fail-closed: readiness + operational code/config invariants
make payment-rails-certification             # payments cohort, strict
make stablecoin-observer-certification       # stablecoin-chain observers, strict
make financial-pilot-preflight               # strict readiness + pilot manifest validation
```

`payment-rails-certification` fails closed with a **specific** message when any
operational invariant is missing (migration/worker/flag/contract/module). The
live-evidence dimensions (migration applied, credential active, endpoint
registered, sandbox evidence, staging soak) are gated by the pilot preflight +
evidence bundle, which fail closed when their artifacts are absent.

## Evidence for readiness-state promotion

- `credential_waiting → sandbox_validated`: real provider sandbox webhook events
  verified end-to-end, connection probes green, rotation overlap proven, and an
  interrupted-delivery repair demonstrated — captured in the evidence bundle
  (`scripts/pilot_evidence.py`). Do not set `sandbox_validated` without it.
- `sandbox_validated → partner_live` (production): live provider events and a
  completed staging soak, with security review. `production_ready` is never
  inferred from structure.
