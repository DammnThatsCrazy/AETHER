---
title: Interoperability Entity Model
slug: source-of-truth/interop-entity-model
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - packages/shared/interoperability.ts
  - Backend Architecture/aether-backend/services/interop/models.py
  - Backend Architecture/aether-backend/repositories/interop_repos.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Interoperability Entity Model

Protocol-neutral contracts live in `packages/shared/interoperability.ts`.
Provider-native concepts (GUID, EID, nonce) appear only inside adapters;
the canonical model carries neutral identities plus alias references.

## Entities

| Entity | Identity | Notes |
|---|---|---|
| `InteropMessage` | `(tenant_id, provider_kind, correlation_key)` | Current-state projection; immutable trail in message events |
| `InteropMessageEvent` | `transition_id` | Append-only lifecycle transition log |
| `InteropPath` | `path_id` | (source network, destination network, provider) lane |
| `InteropGateway` / `InteropApplication` | ids | Endpoint contracts / OApp-level actors |
| `InteropIntent` | `intent_id` | User-facing intent that resolves to messages |
| `AssetLeg` | `asset_leg_id` | Source/destination value movement attribution |
| `SecurityPolicySnapshot` | content-hash unique per path | Verifier sets, thresholds, libraries |
| `VerificationActor` / `DeliveryAttempt` / `ProviderCheckpoint` | ids | Evidence actors, attempts, scan cursors |

## Lifecycle FSM

`INTEROP_LEGAL_TRANSITIONS` in `interoperability.ts` is the single source
of truth (22 states incl. verification/delivery failure-and-retry cycles,
`reorged` re-derivation, `recovered`); `services/interop/lifecycle.py`
mirrors it with a regex-parity test. Terminal states (`settled`,
`cancelled`, `refunded`) are immutable. Legal transitions always apply;
illegal lower-rank arrivals attach as late evidence without regression.
