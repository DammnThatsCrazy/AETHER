---
title: Governance and Consent
slug: productization/economic-interoperability-intelligence/governance-and-consent
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - packages/shared/contracts/consent-registry.json
  - Backend Architecture/aether-backend/shared/auth/auth.py
  - Backend Architecture/aether-backend/shared/privacy/consent_enforcement.py
canonical_owner: platform@aether
last_synced_commit: "94332c5"
---

# Governance and Consent

## Purposes

`economic_observability` and `cross_chain_observability` (plus PR1's
`financial_activity` for derivatives): explicit opt-in, default
disabled, 2555-day retention, `allowModelTraining: false`, revocation
stops new collection and suppresses projections. Enforcement is
registry-derived (root fix in 8.12.0 removed the stale hardcoded set).

## Permissions (18 new)

`stablecoins:read|export|investigate|operator|manage_support|manage_policy`,
`derivatives:read|connect|export|investigate|manage_policy|operator`,
`interoperability:read|connect|export|investigate|manage_policy|operator`.
Read permissions grant at VIEWER+; operator permissions at OPERATOR+ in
`KYBER_ROLE_PERMISSIONS`. Kyber admin routers additionally require
platform-admin gating.

## DSR

Delete scopes `stablecoin_facts` / `derivatives_facts` / `interop_facts`
map to their silver tables in `_DSR_SCOPE_TO_SILVER_TABLE`. Public
reference data (asset registries, provider topology) carries no personal
scope and is unaffected by erasure.
