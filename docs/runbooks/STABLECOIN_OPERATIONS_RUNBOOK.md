---
title: "Stablecoin Operations Runbook"
slug: runbooks/stablecoin-operations
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/stablecoin/admin_routes.py
canonical_owner: platform@aether
last_synced_commit: "41c79d4"
---

# Stablecoin Operations Runbook

Operator surface: `/stablecoins/ops` (Kyber) → `/v1/admin/kyber/stablecoins`.
Requires `STABLECOIN_OPERATOR` permission; all actions are audited.

## Depeg alert fired (`aether.stablecoin.depeg.detected`, P1)

1. Open the valuations tab on `/stablecoins`; confirm the deviation and
   its source snapshot evidence.
2. Cross-check against an independent price source — Aether observes,
   it does not arbitrate truth.
3. If the source is wrong (stale feed, bad operator submission), record
   a corrected valuation snapshot; the peg status transitions on the
   next snapshot. Never edit rows.

## Unresolved observations accumulating

1. `/v1/admin/kyber/stablecoins/observations/unresolved` lists rows
   whose token/chain didn't resolve.
2. If the asset is legitimate, seed/extend the registry
   (`POST /registry/seed` for x402-verified assets; manual curation
   otherwise), then re-ingest — deterministic ids make replays safe.

## Reorg handling

1. `POST /finality/reorg` with tenant, chain, and fork block demotes
   non-finalized observations to `reorged` and emits corrections.
2. Finalized rows are never touched; if a finalized row looks wrong,
   that's an incident, not a reorg — escalate.

## Checkpoint stalled

Checkpoints advance via `POST /finality/advance`. A stalled checkpoint
means no operator/automation is advancing it — verify RPC credentials
(finality live-tracking is CREDENTIAL_GATED) before assuming chain issues.
