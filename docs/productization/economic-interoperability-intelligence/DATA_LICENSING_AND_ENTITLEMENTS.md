---
title: Data Licensing and Entitlements
slug: productization/economic-interoperability-intelligence/data-licensing-and-entitlements
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/shared/plans/service_catalog.py
  - Backend Architecture/aether-backend/services/billing/revops.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Data Licensing and Entitlements

## Plans

Three `ServiceDefinition` rows in `shared/plans/service_catalog.py` cover
`/v1/stablecoins/*`, `/v1/derivatives/runtime/*`, `/v1/interoperability/*` with
plan access mirroring the existing premium-vertical pattern.

## Metering

Eight canonical meters (validated by `scripts/validate_meter_names.py`
against `MeteringEventType`):
`stablecoin_observation_ingested`, `stablecoin_flow_materialized`,
`derivatives_event_ingested`, `derivatives_reconciliation_run`,
`derivatives_stream_gap_detected`, `interop_observation_ingested`,
`interop_message_correlated`, `interop_reconciliation_run`.
Emission is best-effort at intake/materialization/run sites and never
blocks the request path.

## Licensing constraints

- Provider-derived data (venue snapshots, RPC logs) is observed under
  the tenant's own credentials; Aether does not resell raw provider
  feeds.
- No economic observation feeds model training
  (consent registry + gold `model_training_eligible = 0`).
- Exports go through the existing export/audit machinery and the
  `*:export` permissions.
