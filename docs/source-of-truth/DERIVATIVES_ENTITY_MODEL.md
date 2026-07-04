# Derivatives Entity Model

Derivatives Intelligence extends existing observed-trading foundations such as `TradeOrderObserved`, `TradeFillObserved`, `PositionSnapshotObserved`, and `PortfolioSnapshotObserved` with canonical stateful domain entities. Observed entities remain provider observations; canonical entities in `packages/shared/derivatives.ts` are Aether-resolved objects with tenant scope, idempotency, evidence, fixed-precision decimal strings, and `execution_by_aether: false`.

## Canonical entities

PR1 establishes contracts for venues, deployments, instruments, markets, trading accounts, subaccounts, vaults, orders, fills, positions, position epochs, collateral accounts, margin snapshots, funding payments, trading fees, liquidations, price observations, risk policies, strategies, execution decisions, reconciliation variances, connector checkpoints, and credential references.

## Conversion boundary

Observation-layer records convert into canonical entities only through deterministic resolvers. Conversion must preserve raw source references, source event IDs, valid time, recorded time, calculation version, confidence, data freshness, and explicit evidence class.

## Aether remains observational

Aether may observe, normalize, analyze, explain, alert, and reconcile. Canonical records and storage constraints fail closed with `execution_by_aether: false` and credential references are read-only pointers, not secrets.
