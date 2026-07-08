# Stablecoin Operations, Governance, and Release Gates

Stablecoin Intelligence PR4 introduces Kyber-facing operational controls as audited, observation-first service primitives. Kyber health and lineage can inspect Bronze, Silver, durable observations, reconciliation, support, and Gold counts, but remediation requests are recorded as durable audit intents and do not execute replay, rollback, graph mutation, or financial correction inline.

## Remediation

Every remediation request requires tenant, action, actor, reason, evidence reference, target, timestamp, before state, and after state. Records use `recorded_not_executed` status until an authorized operator workflow performs a separate action.

## Olympus benchmarks

Market intelligence data is classified as tenant raw, tenant aggregate, platform anonymized benchmark, public onchain, licensed market, Olympus-owned, model estimate, or synthetic. Tenant raw data cannot be published as an Olympus benchmark. Platform anonymized benchmarks require a minimum cohort threshold, and model estimates are explicitly labeled.

## Entitlements and metering

Stablecoin access is capability-based rather than plan-name based. Metering reports observations, normalized transactions, support assertions, reconciliation records, Gold materializations, Profile360 requests, alerts evaluated, and exports generated. Metering is read-only and must not alter metric truth.

## Release recommendation

The current release gate is `controlled_staging_only` with production recommendation `NOT_READY`. Staging provider validation, backup/restore, load/chaos evidence, operator UI, remediation workers, billing-plan wiring, quota enforcement, and licensed market validation remain release blockers.
