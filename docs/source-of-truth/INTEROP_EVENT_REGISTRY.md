---
title: Interoperability Event Registry
slug: source-of-truth/interop-event-registry
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - packages/shared/contracts/event-registry.json
  - Backend Architecture/aether-backend/services/silver/projectors/interop_projector.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Interoperability Event Registry

The `interop` family in `packages/shared/contracts/event-registry.json`:
events with `introducedVersion: "8.12.0"`, purposes
`["cross_chain_observability"]`, `silverProjection: interop_facts` routed
through `InteropProjector` (registry-derived handles).

Lifecycle groups: provider/gateway/path/application registry, message
lifecycle transitions (discovery → source → verification → delivery →
execution/settlement, failures, timeouts, reorgs, recovery), intents,
asset legs, security-policy snapshots/changes, verification evidence,
checkpoints, correlation (`interop_message_correlated` emitted exactly
once per completed join), reconciliation, and materialization.

`privacyClass` is `financial` for value-bearing facts and `governance`
for registry/ops; facts retain `financial_7y`, checkpoints/ops shorter.
Graph projection only on material events (e.g. `SENT_VIA_PATH`,
`VERIFIED_BY`, `SECURED_BY_POLICY`).

Meters: `interop_observation_ingested`, `interop_message_correlated`,
`interop_reconciliation_run` — canonical names only
(`scripts/validate_meter_names.py` must agree with `MeteringEventType`).
