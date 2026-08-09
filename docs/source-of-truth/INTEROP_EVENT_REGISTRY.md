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

Billable usage dimensions (canonical names from `services/interop/metering.py`,
recorded as `metering_evidence.usage_dimension` values, best-effort and
dedupe-safe — a restart replay of the same checkpoint is recorded non-billable):
`interop_observations_ingested`, `interop_messages_correlated`,
`interop_reconciliation_runs`, `interop_security_policy_snapshots`, and
`interop_provider_cycles`. Dimensions are measured here; pricing is not invented
by this service.
