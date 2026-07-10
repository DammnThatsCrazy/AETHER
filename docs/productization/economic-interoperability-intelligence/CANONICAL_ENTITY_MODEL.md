---
title: Canonical Entity Model (cross-domain)
slug: productization/economic-interoperability-intelligence/canonical-entity-model
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - packages/shared/stablecoin-intelligence.ts
  - packages/shared/derivatives.ts
  - packages/shared/interoperability.ts
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Canonical Entity Model

Per-domain detail lives in the source-of-truth docs
(`STABLECOIN_ENTITY_MODEL`, `DERIVATIVES_ENTITY_MODEL` +
`DERIVATIVES_RUNTIME_MODEL`, `INTEROP_ENTITY_MODEL`). Cross-domain rules:

- **Identity is deterministic**: content-derived ids
  (sha256 observation ids, GUID correlation keys, content-hash policy
  snapshots) so replays dedupe structurally.
- **Amounts are decimal strings** in TS and `Decimal` in Python;
  no canonical model field is a binary float (model introspection test).
- **Corrections are new rows**: no canonical fact is mutated after
  finality; reorgs demote and append.
- **Tenant scope is explicit** on every row; public reference entities
  (assets, venues, providers, paths) live in the public scope.
- **Evidence is attached, not asserted**: every fact carries source
  refs, observed-at, and provenance; Noesis/Profile360 surface them.
