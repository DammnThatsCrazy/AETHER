---
title: Data Licensing and Entitlements
slug: productization/economic-interoperability-intelligence/data-licensing-and-entitlements
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [services/api/shared/plans/service_catalog.py, services/api/billing/billing/revops.py]
canonical_owner: platform@aether
source_hashes:
  "services/api/billing/billing/revops.py": "sha256:3f42aa9c50d475a8efa360f43ed8a14faebbc773e715ba34b4e2c57f1b0d82af"
  "services/api/shared/plans/service_catalog.py": "sha256:9c219b76d41c52f8691d2ed11f888c91f051768a58933174e0852d1741519a15"
---

# Data Licensing and Entitlements

## Plans

Three `ServiceDefinition` rows in `shared/plans/service_catalog.py` cover
`/v1/stablecoins/*`, `/v1/derivatives/runtime/*`, `/v1/interoperability/*` with
plan access mirroring the existing premium-vertical pattern.

## Metering

Nine canonical meters (validated by `scripts/validate_meter_names.py`
against `MeteringEventType`):
`stablecoin_observation_ingested`, `stablecoin_flow_materialized`,
`derivatives_event_ingested`, `derivatives_reconciliation_run`,
`derivatives_stream_gap_detected`, `interop_observation_ingested`,
`interop_message_correlated`, `interop_reconciliation_run`,
`payment_rail_observation_ingested`.
Emission is best-effort at intake/materialization/run sites and never
blocks the request path — the payment-rail and stablecoin observation
meters are default-off, accept-then-meter, and fail-open (a metering-store
failure is swallowed and never rejects or drops the observation).

Access Kit interaction accounting is a separate, visibility-only dimension
(`access_interaction`). It is explicitly non-billable until a pricing contract
is approved and does not change these nine economic meters or invoice charges.

## Licensing constraints

- Provider-derived data (venue snapshots, RPC logs) is observed under
  the tenant's own credentials; Aether does not resell raw provider
  feeds.
- No economic observation feeds model training
  (consent registry + gold `model_training_eligible = 0`).
- Exports go through the existing export/audit machinery and the
  `*:export` permissions.
