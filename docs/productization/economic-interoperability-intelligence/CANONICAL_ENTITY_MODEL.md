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
source_hashes:
  "packages/shared/derivatives.ts": "sha256:f1aa8933c643877fa2472f6d7dd0703eb67661c441a29372bf3817a8b05a4d26"
  "packages/shared/interoperability.ts": "sha256:fe72abcf3f2c2570871689112419971832674e6d74fa8259a2d9c057b2a7b049"
  "packages/shared/stablecoin-intelligence.ts": "sha256:e7fc796932dafd5dc1c900f2a5468913f534b129cf418144b5b2716e1a538138"
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
