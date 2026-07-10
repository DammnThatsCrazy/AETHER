---
title: "Interop Provider Operations Runbook"
slug: runbooks/interop-provider-operations
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/interop/admin_routes.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Interop Provider Operations Runbook

Operator surface: `/interoperability/ops` (Kyber) → `/v1/admin/kyber/interop`.
Requires `INTEROP_OPERATOR`; all actions audited. Aether never relays,
retries, or recovers messages — a stuck message is the provider's to fix;
Aether's job is honest evidence.

## Message stuck alert (`aether.interop.message.stuck`, P2)

1. Open the message trace (`/interoperability/messages/{id}`): the
   append-only timeline shows exactly which lifecycle leg is missing.
2. Stuck in verification → check the path's security-policy snapshot
   (verifier set may have changed) and the provider's status page.
3. Stuck in delivery → check delivery attempts and the destination
   chain's health.
4. Run a governed scan (`POST /scan/{provider_id}`) to collect fresh
   evidence — the message may have progressed since the last scan.

## Security policy changed (`aether.interop.security.policy.changed`, P1)

1. The policy-drift panel shows distinct policy hashes per path.
2. Diff the snapshots (verifier ids, thresholds, libraries) and confirm
   the change matches the provider's announced configuration.
3. Unannounced verifier-set changes on a live path are a security
   event — escalate; do not silently accept the new baseline.

## Checkpoint lag

1. Provider health shows checkpoints per provider. Lag beyond the
   confirmation horizon means scans aren't running.
2. LayerZero requires `AETHER_INTEROP_LAYERZERO_ENABLED` + RPC
   credentials; scaffolded providers refuse scans by design
   (409 with an honest message) — that is not an incident.

## Reorg observed

Parent-hash mismatch during a scan rolls provisional evidence back
automatically and re-derives message state. Verify affected messages
re-correlate on subsequent scans; finalized evidence is never rolled back.
