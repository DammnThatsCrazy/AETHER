---
title: Stablecoin Metrics
slug: source-of-truth/stablecoin_metrics
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Stablecoin Metrics

Gold metric identity must include tenant, metric name, metric version, entity, entity type, canonical asset, deployment, chain, window start, window end, dimensions, and source. This prevents collisions across tenants, dates, assets, deployments, chains, metric versions, and providers.

Canonical financial calculations use integer atomic amounts and decimal-safe conversion. Stablecoin amount and USD value are separate metrics.
