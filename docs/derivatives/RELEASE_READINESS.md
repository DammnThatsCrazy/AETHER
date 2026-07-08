---
title: Derivatives Release Readiness
slug: derivatives/release-readiness
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: experimental
since_version: "8.11.0"
---

# Derivatives Release Readiness

PR5 expands Derivatives Intelligence from a single reference venue into a governed multi-venue release domain. The release gate proves that dYdX, GMX, Drift, a centralized futures source, and the existing Hyperliquid foundation use the same canonical concepts instead of provider-specific product APIs.

## Cross-venue normalization

Supported adapters publish capability profiles for markets, orders, fills, positions, funding, fees, margin, liquidations, and account state. Missing venue concepts are represented as explicit capability gaps rather than fake values. Fixture normalization produces canonical fill facts with tenant-scoped idempotency keys, fixed-precision decimals, source references, canonical market IDs, and `execution_by_aether: false`.

## Deterministic intelligence before ML

The strict gate validates deterministic metrics before any model is allowed to influence a release: effective leverage, margin utilization, liquidation buffer, concentration, fee burden, funding burden, drawdown, position duration, order-to-fill ratio, human intervention, agent policy violations, and execution quality.

## ML governance

ML candidates remain optional and fail closed unless tenant consent allows `financial_activity` training and reliable labels exist. Each model card requires time-based splits, no future leakage, calibration, explainability, tenant-safe training, drift checks, shadow mode, kill switches, and deterministic-rule fallback.

## Coordination safeguards

Coordination and copy-trading intelligence is non-accusatory. Timing similarity alone returns insufficient evidence; hypotheses require multiple signal categories and human review.

## Scale, recovery, licensing, and deployment

The release matrix covers load bursts, liquidation spikes, high-frequency fills, imports, connector fanout, reconnect storms, graph mutation throughput, Profile360/Cluster360 latency, Noesis, exports, backfills, and reconciliation sweeps. Recovery relies on Bronze plus canonical source records for cache loss, projection loss, checkpoint rollback, graph rebuilds, provider outage, corrections, chain reorganizations, failed migrations, and bad model deployments. Provider licensing controls govern storage, derived data, redistribution, display, export, retention, and ML-training restrictions.
