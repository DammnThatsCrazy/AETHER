---
title: Stablecoin Event Registry
slug: source-of-truth/stablecoin-event-registry
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - packages/shared/contracts/event-registry.json
  - Backend Architecture/aether-backend/services/stablecoins/models.py
  - Backend Architecture/aether-backend/services/silver/projectors/stablecoin_projector.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Stablecoin Event Registry

The `stablecoin` family in `packages/shared/contracts/event-registry.json`
is the single source of truth; `scripts/generate_contracts.py` emits the
TS/Python/docs artifacts. Never hand-edit generated files.

## Family shape

- 30 events, `introducedVersion: "8.12.0"`, purposes `["economic_observability"]`.
- `silverProjection: stablecoin_facts` routes every event through
  `StablecoinProjector` (registry-derived `handles` — adding a registry
  event automatically extends the projector's routing).
- Lifecycle groups: observation intake (transfer/payment/mint/burn/
  bridge/swap/x402/treasury/payout/venue), registry curation, support
  assertions, valuation + depeg transitions, finality advance/reorg/
  correction, reconciliation, and flow materialization.
- `privacyClass` is `financial` for facts and `governance` for
  registry/ops events; `retentionClass` is `financial_7y` for facts.
- `graphProjection` is set only on material events (e.g.
  `stablecoin_transfer_observed` → `TRANSFERRED_STABLECOIN`).

## Emission points

Backend emission happens in `services/stablecoin/` (service intake,
valuation, finality, flows) via `foundation.make_event`; usage metering
uses the canonical meters `stablecoin_observation_ingested` and
`stablecoin_flow_materialized` only.

## Observer-stack taxonomy (services/stablecoins domain)

Stablecoin events preserve raw observation facts separately from derived classification. PR1 defines the canonical event taxonomy in `services/stablecoins/models.py` and the SDK parity contract in `packages/shared/stablecoin.ts`.

Finalized payment volume may only include `finalized` observations. Pending, failed, dropped, disputed, unknown, and reverted observations are excluded from finalized metrics. Reverted observations must be retained as corrections rather than deleted from history.
