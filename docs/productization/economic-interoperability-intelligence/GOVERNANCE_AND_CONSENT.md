---
title: Governance and Consent
slug: productization/economic-interoperability-intelligence/governance-and-consent
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [packages/shared/contracts/consent-registry.json, Backend Architecture/aether-backend/shared/auth/auth.py, Backend Architecture/aether-backend/shared/privacy/consent_enforcement.py]
canonical_owner: platform@aether
source_hashes:
  Backend Architecture/aether-backend/shared/auth/auth.py: sha256:3b6cfe170ef5b8998c4a9d370430b6ea61e3596874f037c65954207e3767a205
  Backend Architecture/aether-backend/shared/privacy/consent_enforcement.py: sha256:e7fe650bd8f1f0b95c86c55954a3f5b8367c94850ba57b0aff6130955cb5d7f6
  packages/shared/contracts/consent-registry.json: sha256:7b1467bb683a609e6adad7416d3faf40c7110e07bf904ea8499c10c6a8e0cc2e
---

# Governance and Consent

## Purposes

`economic_observability` and `cross_chain_observability` (plus PR1's
`financial_activity` for derivatives): explicit opt-in, default
disabled, 2555-day retention, `allowModelTraining: false`, revocation
stops new collection and suppresses projections. `fraud_prevention`
(bot detection, abuse and platform-security signals; added to the
canonical registry in 8.12.0) is also explicit-opt-in, default disabled,
with 365-day retention and `allowModelTraining: true`. Enforcement is
registry-derived (root fix in 8.12.0 removed the stale hardcoded set).

## Permissions (18 new)

`stablecoins:read|export|investigate|operator|manage_support|manage_policy`,
`derivatives:read|connect|export|investigate|manage_policy|operator`,
`interoperability:read|connect|export|investigate|manage_policy|operator`.
Read permissions grant at VIEWER+; operator permissions at OPERATOR+ in
`KYBER_ROLE_PERMISSIONS`. Kyber admin routers additionally require the canonical
fail-closed Kyber-operator gate (a workforce session, the
`kyber:operator` grant, or the operator tenant allowlist);
Aether tenants including `Role.ADMIN` are denied.

Credential revocation is durable: when a tenant is deactivated, its API-key
rows are marked `revoked` before the tenant is marked inactive, and the shared
API-key validator refuses to rehydrate a revoked row after a Redis cache miss.
This keeps the durable auth record authoritative during cache restarts and
prevents a deactivated tenant from regaining access through fallback lookup.

## DSR

Delete scopes `stablecoin_facts` / `derivatives_facts` / `interop_facts`
map to their silver tables in `_DSR_SCOPE_TO_SILVER_TABLE`. Public
reference data (asset registries, provider topology) carries no personal
scope and is unaffected by erasure.
