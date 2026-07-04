---
title: Derivatives Runbooks
slug: derivatives/runbooks
section: operations
visibility: I
audience: [ops, dev-senior]
status: experimental
since_version: "8.11.0"
---

# Derivatives Runbooks

## Connector credential rotation

1. Verify the credential is read-only and lacks trading, transfer, withdrawal, key-management, and account-mutation scopes.
2. Rotate the secret in the existing secret store and update only the encrypted secret reference.
3. Use Kyber `rotate_secret_reference` to bind the new reference to a tenant-scoped connector.
4. Run `test_connection`; if it fails, pause the connector and preserve the prior checkpoint.
5. Confirm no raw credential material appears in logs, graph properties, exports, or frontend state.

## Venue outage or rate-limit exhaustion

1. Mark the connector stale and preserve durable checkpoints.
2. Pause bounded backfills that would worsen provider limits.
3. Notify affected tenants through evidence-backed alerts.
4. Resume from the last durable checkpoint after provider recovery.
5. Reconcile positions and funding against the next authoritative snapshot.

## Position, PnL, or funding mismatch

1. Open the Kyber reconciliation view and identify variance severity.
2. Compare fills, position deltas, snapshots, account ledger, funding, fees, and price lineage.
3. Run bounded `reconcile_position` or `reconcile_account`; never use an unbounded recompute.
4. Attach operator notes and source references to the variance.
5. Resolve only after replay produces deterministic state and variance thresholds are satisfied.

## Graph projection failure

1. Inspect graph quality for failed mutations, unknown edge attempts, missing evidence, and tenant-isolation rejections.
2. Confirm every edge has an explicit actor/domain layer classification.
3. Rebuild only the affected tenant, account, position, or time window.
4. Verify evidence, valid time, recorded time, and idempotency keys before closing the incident.

## Deletion, consent revocation, and legal hold

1. Confirm whether `financial_activity` consent has been revoked or a DSR deletion has been requested.
2. Stop new graph/profile/campaign/Noesis projections for revoked scopes.
3. Delete or tombstone tenant-owned derivatives projections according to retention policy unless legal hold applies.
4. Preserve audit metadata required by policy without retaining secret material or unnecessary financial details.
