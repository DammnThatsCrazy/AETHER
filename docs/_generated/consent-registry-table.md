<!-- DO NOT EDIT — generated from packages/shared/contracts/consent-registry.json -->
<!-- Run: python scripts/generate_contracts.py -->

# Aether Consent Registry (9 purposes, contract v8.10.0)

| Purpose | Label | Default | Explicit Opt-in | Retention | Revocation | Description |
|---|---|---|---|---|---|---|
| `analytics` | Analytics | yes | no | 90d | stop_new_collection | Basic product usage and operational analytics. Required for core platform function. |
| `marketing` | Marketing | no | no | 180d | stop_new_collection | Attribution, experiments, conversion tracking, and advertising attribution. |
| `personalization` | Personalization | no | no | 180d | stop_and_delete_local_fingerprint | Cross-device fingerprinting, recommendations, and personalised content. Required for device fingerprint generation. |
| `web3` | Web3 | no | no | 365d | stop_new_collection | Wallet connections, on-chain transactions, and decentralised protocol observations. |
| `agent` | Agent | no | no | 90d | stop_new_collection | Agentic workflow observations, AI task lifecycle, delegation, and tool usage. |
| `commerce` | Commerce | no | no | 2555d | stop_new_collection | Payments, approvals, entitlements, subscriptions, orders, and access control events. |
| `financial_activity` | Financial Activity | no | ✓ required | 2555d | stop_new_collection_and_suppress_projections | Read-only derivatives trading analytics: account connections, orders, fills, positions, collateral, margin, funding, fees, PnL, risk profiling, agent trading activity, campaign linkage, and governed model training. |
| `credit` | Credit | no | ✓ required | 730d | stop_new_collection | Credit signals, account observations, and credit decisions. Always requires explicit opt-in. |
| `location` | Location | no | ✓ required | 30d | stop_and_delete_cached | Precise or coarse location observations and geofence transitions. Always requires explicit opt-in. |
