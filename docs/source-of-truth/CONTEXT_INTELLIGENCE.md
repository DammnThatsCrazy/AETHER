---
title: Contextual Session Intelligence Source of Truth
status: stable
source_files:
  - packages/shared/contracts/context-capsule-registry.json
  - packages/shared/context-capsule.ts
  - Backend Architecture/aether-backend/shared/context_capsule/models.py
  - Backend Architecture/aether-backend/shared/context_capsule/generated_taxonomy.py
  - Backend Architecture/aether-backend/services/ingestion/context_enricher.py
  - Backend Architecture/aether-backend/services/ingestion/geo_provider.py
  - Backend Architecture/aether-backend/shared/privacy/ip_hmac.py
  - tests/security/test_no_raw_ip_persistence.py
last_synced_commit: a500f1f
---

# Contextual Session Intelligence (PR 1 scope)

The circumstance layer: evidence-backed device/network/geo/session context.
Observation, resolution, inference, measurement, and suggestion remain
distinct claims; network geography is **network egress**, never physical
presence.

## Ownership

| Concern | Canonical owner |
|---|---|
| Location source/semantics/precision taxonomies, context states, conflict states, retention classes, capsule transition types | `packages/shared/contracts/context-capsule-registry.json` → generated TS/Py twins |
| `LocationObservation` + `ContextCapsule` contracts + deterministic `capsule_hash()` (sha256 over a sorted-key identity allowlist; excludes ids/validity/lineage) | `shared/context_capsule/models.py` ↔ `context-capsule.ts` (parity-tested, incl. hash determinism) |
| Trusted client-IP resolution (trusted-proxy CIDRs, right-to-left XFF walk, CF header only when enabled AND peer trusted) | `services/ingestion/context_enricher.py` |
| Geo/ASN lookup (local MaxMind fail-closed `not_provisioned`, deterministic test, honest null) | `services/ingestion/geo_provider.py` |
| The ONLY permitted IP transform: tenant-scoped rotating HMAC (windowed key derivation, one-way, no key table) | `shared/privacy/ip_hmac.py` |

## Safety posture (defaults ON)

- `AETHER_RAW_IP_PERSISTENCE_BLOCKED=true` — raw IPs exist transiently in
  the enricher only; export/consent-audit routes persist the HMAC token;
  guarded by `tests/security/test_no_raw_ip_persistence.py`.
- `AETHER_LOCATION_IDENTITY_MERGE_BLOCKED=true` — context never merges
  identities alone and never solely causes adverse action.
- Enrichment (`AETHER_CONTEXT_ENRICHMENT_ENABLED`, default off) never
  rejects a valid event; failures yield explicit states
  (`not_provisioned` / `private_address` / `provider_error` / …).
- Capsule lifecycle processing, transitions/conflicts persistence, operating
  envelopes, episodes, and the geo product surfaces land in PR 2/3; the
  retention classes (raw_ip 0h, ephemeral token 24h, coarse 30d, precise
  tenant-policy) are contract-declared here and enforced by those PRs' jobs.
