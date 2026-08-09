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
last_synced_commit: "eefd9d5"
---

# Data Licensing and Entitlements

## Plans

Three `ServiceDefinition` rows in `shared/plans/service_catalog.py` cover
`/v1/stablecoins/*`, `/v1/derivatives/runtime/*`, `/v1/interoperability/*` with
plan access mirroring the existing premium-vertical pattern.

## Metering

The economic domains meter through `scripts/validate_meter_names.py`-validated
metric names AND billable `metering_evidence.usage_dimension` records
(`services/metering_evidence/`). Stablecoin / derivatives / payment-rail metric
names: `stablecoin_observation_ingested`, `stablecoin_flow_materialized`,
`derivatives_event_ingested`, `derivatives_reconciliation_run`,
`derivatives_stream_gap_detected`, `payment_rail_observation_ingested`.

Interop billable usage dimensions (canonical in `services/interop/metering.py`,
recorded as `metering_evidence.usage_dimension` values, dedupe-safe on
checkpoint replay):
`interop_observations_ingested`, `interop_messages_correlated`,
`interop_reconciliation_runs`, `interop_security_policy_snapshots`,
`interop_provider_cycles`.

Emission is best-effort at intake/materialization/run sites and never
blocks the request path — the payment-rail and stablecoin observation
meters are default-off, accept-then-meter, and fail-open (a metering-store
failure is swallowed and never rejects or drops the observation).

## Licensing constraints

- Provider-derived data (venue snapshots, RPC logs) is observed under
  the tenant's own credentials; Aether does not resell raw provider
  feeds.
- No economic observation feeds model training
  (consent registry + gold `model_training_eligible = 0`).
- Exports go through the existing export/audit machinery and the
  `*:export` permissions.
