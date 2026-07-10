---
title: Interoperability Consent Model
slug: source-of-truth/interop-consent-model
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - packages/shared/contracts/consent-registry.json
  - Backend Architecture/aether-backend/shared/privacy/consent_enforcement.py
  - Backend Architecture/aether-backend/shared/privacy/retention.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Interoperability Consent Model

Interop events require the `cross_chain_observability` purpose
(`packages/shared/contracts/consent-registry.json`):

- `defaultEnabled: false`, `explicitOptInRequired: true` — fail-closed.
- `retentionDays: 2555`; `allowModelTraining: false`.
- `revocationBehavior: stop_new_collection_and_suppress_projections`.
- `allowedFamilies` include `interop`, `web3_lc`, `wallet`.

Public-scope topology (providers, gateways, paths, security policies) is
reference data and carries no personal scope; tenant-scoped rows (intents,
messages attributed to tenant entities, asset legs) are consent-gated and
DSR-erasable via the `interop_facts` scope in
`retention.py::_DSR_SCOPE_TO_SILVER_TABLE`.
