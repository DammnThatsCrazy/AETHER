---
title: "Derivatives Stream Runbook"
slug: runbooks/derivatives-stream
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/derivatives/connectors/stream.py
  - Backend Architecture/aether-backend/services/derivatives/admin_routes.py
canonical_owner: platform@aether
last_synced_commit: "ac900d5"
---

# Derivatives Stream Runbook

Operator surface: `/derivatives/ops` (Kyber) → `/v1/admin/kyber/derivatives/runtime`.
Requires `DERIVATIVES_OPERATOR`; all actions audited. Aether never places,
modifies, or cancels orders — remediation is evidence review, never trading.
This runbook covers the **market WebSocket stream** (sequence tracking, gap
detection/recovery, reconnect). For projection-vs-snapshot variance triage see
`docs/runbooks/DERIVATIVES_RECONCILIATION_RUNBOOK.md`.

The four venue adapters (Hyperliquid, dYdX, GMX, Drift) are `CREDENTIAL_WAITING`
(credential readiness; implementation status `CREDENTIAL_GATED`) and the stream
currently runs on the local transport — the Kafka topics they would stream to
are **declared** in the broker-free declarative contract
(`services/derivatives/topic_contract.py`:
`DERIVATIVES_TOPIC_CONTRACTS`, per-topic partitions/retention/DLQ/consumer
ownership, validated by `assert_valid_topic_contracts`) but are **not
provisioned** in this environment, so there are zero `PARTNER_LIVE` venues.
Two new preconditions gate a live stream: the read-only credential resolver
(`services/derivatives/credentials.py` —
`resolve_read_only_credential` rejects mutating/expired/revoked scopes) and the
entitlement gate (`services/derivatives/guards.py` —
`require_derivatives_entitlement`, fail-closed until a resolver is installed).
Until both are wired, no venue may be promoted to live.

## Stream gap detected (`derivatives_stream_gap_detected`)

1. A gap is a hole in the sequence (e.g. 1 then 5). The `ReconnectingStream`
   driver back-fills within `gap_threshold`; a matching
   `derivatives_stream_gap_recovered` should follow within the same connection
   or across one reconnect.
2. If the gap does not recover, the stream is dead or the venue skipped
   sequences permanently. Check the connector checkpoint — a stale checkpoint
   with an open gap means the adapter stopped (restart/credential issue).
3. After recovery, run reconciliation on affected accounts to confirm
   projections caught up.

## WebSocket disconnect / reconnect storm

1. A `StreamDisconnect` is a recoverable drop: the driver reconnects with a
   resume cursor set to the next expected sequence. Bounded by `max_reconnects`
   — after the bound it stops and reports `disconnected_out`, it never loops.
2. A rising reconnect count with no accepted frames means the venue endpoint is
   down. This is a credential/endpoint issue, not a data issue.
3. Duplicate frames are dropped and small reorders below threshold are buffered
   then drained in order — neither is an incident.

## Never do

- Never place, modify, or cancel any order.
- Never hand-edit fills, positions, or sequence state.
- Never enable venue adapters without read-only credentials and a validated
  staging stream (see `CREDENTIAL_WAITING_PROMOTION_GUIDE`).
- Never bypass the derivatives entitlement gate
  (`require_derivatives_entitlement`) or the read-only credential resolver —
  a tenant without `derivatives.enabled` entitlement is denied by design
  (fail-closed) until a real resolver is installed.

See also: `docs/source-of-truth/DERIVATIVES_RUNTIME_MODEL.md`,
`docs/runbooks/DERIVATIVES_RECONCILIATION_RUNBOOK.md`,
`docs/derivatives/RUNBOOKS.md`.
