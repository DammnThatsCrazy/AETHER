# Stablecoin Pipeline

Stablecoin PR2 keeps the observation-first boundary from PR1. Provider payloads are admitted as governed Bronze records, then deterministic normalization creates eligible stablecoin observation facts. Unknown deployments are rejected for operator registration or quarantine before Silver promotion and before any graph projection.

## Bronze

Bronze records preserve tenant, source, source execution, manifest, raw payload, provenance, license, terms, commercial-use status, payload hash, and quarantine state. Repeated provider executions must remain distinct through execution-scoped provider record identity.

## Silver normalization

Silver normalization resolves chain/network/contract to a canonical deployment, converts atomic amounts with deployment decimals, assigns deterministic observation IDs, and persists tenant-scoped observations. Quarantined Bronze records cannot promote.

## Verification and finality

A transaction hash alone is not proof of payment. Payment reconciliation compares payer, recipient, deployment, chain, amount, and finality. Pending and confirmed transactions do not enter finalized payment volume. Reverted finalized observations require downstream correction events.

## Gold

Gold materialization only includes finalized payment-like events and excludes pending, reverted, mint/burn, and internal-transfer rows. Metrics retain asset, deployment, chain, tenant, source, metric version, and window identity.

## Alerts

PR2 alert evaluation covers peg deviation and reconciliation mismatch foundations with deterministic dedupe keys. Delivery adapters remain a later integration surface.
