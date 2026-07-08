# Stablecoin Profile360, Identity, Graph, and Tenant APIs

Stablecoin Profile360 composes tenant-scoped stablecoin observations into entity-level views without performing authoritative identity or financial joins in the frontend. The backend owns wallet resolution, graph projection records, aggregation, provenance, and tenant filtering.

## Identity

Wallet identity links are tenant-scoped and evidence-backed. A wallet address is not legal identity. Unresolved wallets remain visible with `resolution_state=unresolved`, and identity links must include method, confidence, evidence, determinism, chain, and consent context.

## Graph projection

Stablecoin graph projection creates deterministic projection-outbox records rather than writing directly to Neptune. Projection records include stablecoin, deployment, observation, and wallet vertices plus tenant-scoped `USES_ASSET`, `OBSERVED_ON`, and `SENT_TO` edges. Replay is idempotent because projection IDs are deterministic.

## Profile360

The stablecoin Profile360 composer returns entity ID, tenant ID, kind, items, summary, pagination, computed time, freshness, provider status, provenance, warnings, and drill links. Unattributed activity and unresolved wallets are surfaced explicitly instead of being hidden or displayed as zero.

## Tenant APIs

Tenant routes are feature-flagged by `AETHER_STABLECOIN_INTELLIGENCE_ENABLED` and disabled by the kill switch. Routes require tenant read permission and derive tenant identity from authenticated request state.
