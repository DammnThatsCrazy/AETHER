---
title: "Interoperability Observer Runbook"
slug: runbooks/interop-observer
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/interop/correlation.py
  - Backend Architecture/aether-backend/services/interop/admin_routes.py
canonical_owner: platform@aether
last_synced_commit: "41c79d4"
---

# Interoperability Observer Runbook

Operator surface: `/interoperability/ops` (Kyber) → `/v1/admin/kyber/interop`.
Requires `INTEROP_OPERATOR`; all actions audited. This runbook covers the
**cross-chain message lifecycle** — scanning, GUID correlation, reorg rollback.
For provider enable/disable and health triage see the companion
`docs/runbooks/INTEROP_PROVIDER_OPERATIONS_RUNBOOK.md`.

The seven providers (LayerZero, Wormhole, Axelar, Chainlink CCIP, Hyperlane,
IBC, deBridge) are `CREDENTIAL_WAITING`: fixture-proven decode, live scanning
needs per-network JSON-RPC credentials. No live provider is validated.

## Scan degraded / rate-limited

1. When an RPC endpoint fails or rate-limits, the scan returns no observations
   for that network and records `rate_limited` health with a `retry_after` on
   the checkpoint. Nothing is dropped — the next scan resumes from the
   checkpoint. This is graceful degradation, not data loss.
2. Persistent `rate_limited` means the RPC provider is throttling; rotate or
   provision a higher-tier endpoint.

## Reorg observed (`phase = reorged`)

1. A reorg is emitted when a scanned block's hash changes (`discontinuity_kind =
   block_hash`) or the cursor drifted past head (`cursor_drift`). The scanner
   rewinds `last_scanned_block` below the fork and re-observes.
2. A reorg is a legal lifecycle regression — correlation attaches late evidence
   in any order and does not lose the message GUID. Do not hand-repair.

## Out-of-order evidence

Delivery observed before its source is expected: the message is held
`out_of_order` and the later source attaches as `late_evidence_attached`. The
final status is correct once all evidence arrives; no action needed.

## Never do

- Never influence any cross-chain message — observation only.
- Never hand-edit message state, correlation records, or checkpoints.
- Never enable live scanning without per-network RPC credentials and a validated
  staging scan (see `CREDENTIAL_WAITING_PROMOTION_GUIDE`).

See also: `docs/source-of-truth/INTEROP_EVENT_REGISTRY.md`,
`docs/runbooks/INTEROP_PROVIDER_OPERATIONS_RUNBOOK.md`,
`docs/productization/economic-interoperability-intelligence/ADAPTER_CAPABILITY_MATRIX.md`.
