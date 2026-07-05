# Stablecoin Intelligence Domain

Aether Stablecoin Intelligence is observation-first. It records externally executed stablecoin activity, evidence, verification state, finality, reconciliation, and tenant-scoped intelligence. It does not custody assets, hold keys, sign transactions, originate transfers, execute trades, settle as merchant of record, or treat payment intents as proof of settlement.

Canonical identity is split between `canonical_asset_id` (for example USDC) and `deployment_id` (the chain/network/contract or mint identity). Financial metrics must include tenant, asset, deployment, chain, network, finality state, valuation timestamp, valuation source, source lineage, and metric version where applicable.

Token quantities are stored as atomic integers and converted with decimal-safe arithmetic. Unlike deployments must not be summed as raw quantities. USD valuation is a separate fact with its own timestamp, source, confidence, and peg deviation.

Feature flags for downstream surfaces default off until their backend pipeline, permissions, provenance, and documentation are complete.
