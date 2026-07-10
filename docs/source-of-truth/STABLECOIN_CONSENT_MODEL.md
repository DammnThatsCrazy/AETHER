---
title: Stablecoin Consent Model
slug: source-of-truth/stablecoin-consent-model
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

# Stablecoin Consent Model

Stablecoin events require the `economic_observability` purpose, defined in
`packages/shared/contracts/consent-registry.json`:

- `defaultEnabled: false`, `explicitOptInRequired: true` — fail-closed.
- `retentionDays: 2555` (7 years, financial records).
- `allowModelTraining: false` — economic observations never feed training.
- `revocationBehavior: stop_new_collection_and_suppress_projections`.
- `allowedFamilies` include `stablecoin`, `x402`, `wallet`, `commerce`.

Enforcement derives from the registry at import time
(`shared/privacy/consent_enforcement.py` loads the JSON — the pre-8.12.0
hardcoded purpose set was the root cause of `financial_activity` being
silently unenforceable and was removed).

DSR: the `stablecoin_facts` delete scope maps to the silver table in
`shared/privacy/retention.py::_DSR_SCOPE_TO_SILVER_TABLE`; erasure removes
tenant-scoped facts while registry (public reference) rows are unaffected.
