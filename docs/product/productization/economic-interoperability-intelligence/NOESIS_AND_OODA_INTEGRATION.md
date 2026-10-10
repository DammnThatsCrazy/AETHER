---
title: Noesis and OODA Integration
slug: productization/economic-interoperability-intelligence/noesis-and-ooda-integration
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [services/api/intelligence/noesis/adapters/stablecoin_adapter.py, services/api/intelligence/noesis/adapters/derivatives_adapter.py, services/api/intelligence/noesis/adapters/interop_adapter.py, services/api/intelligence/suggestions/adapters/stablecoin_adapter.py, services/api/intelligence/suggestions/adapters/derivatives_adapter.py, services/api/intelligence/suggestions/adapters/interop_adapter.py]
canonical_owner: platform@aether
source_hashes:
  "services/api/intelligence/noesis/adapters/derivatives_adapter.py": "sha256:fdd0f5f13da071c5cc95ca03373c3b4e55d183e97373b2c6d8c76dffaaf44d5f"
  "services/api/intelligence/noesis/adapters/interop_adapter.py": "sha256:66dbd63ef28c1c38e991d91c6a0bd81d5d137de53f2aa1d46e232cb073c9cb0f"
  "services/api/intelligence/noesis/adapters/stablecoin_adapter.py": "sha256:d7e351b6efb8bd464e17f9474555bfa292a1ff5c0ef0dbfdf7167516702fa124"
  "services/api/intelligence/suggestions/adapters/derivatives_adapter.py": "sha256:3ea1d9d4658effbe2bb324453262837f0ad2eff2991f9b8bedf6afa3a24bcce5"
  "services/api/intelligence/suggestions/adapters/interop_adapter.py": "sha256:760120f88f05f1aa960758df5a8e820699fc93169f5809c9c604ecf76f04967d"
  "services/api/intelligence/suggestions/adapters/stablecoin_adapter.py": "sha256:5c3765eed4f3f08dd4329b1f98477bdbf729dc77192d53fa2827f34dd90b4edf"
---

# Noesis and OODA Integration

## Noesis (read-only)

Five intents in `SUPPORTED_INTENTS` + capability registry + deterministic
classifier candidates + `_economic_dispatch`, each gated on its domain's
`noesis_enabled` flag (disabled domains answer honestly with a
`service_disabled` error instead of guessing). Adapters read typed
repositories, serialize Decimals as strings, and return
`EvidenceEnvelope` sources; Noesis never mutates domain state.

## OODA (suggestions only — execution stays impossible)

Rule-sourced factories mapping observed facts to `SuggestionCreate`:

| Trigger | Suggestion class |
|---|---|
| Depeg/minor-deviation valuation snapshot | `STABLECOIN_DEPEG` |
| Unresolved reconciliation variance ≥ medium | `DERIVATIVES_RECONCILIATION` |
| Unrecovered stream gap | `DERIVATIVES_RISK` |
| Message stuck past phase SLA | `INTEROP_DELIVERY_HEALTH` |
| Security-policy content-hash change | `INTEROP_DELIVERY_HEALTH` |

The stablecoin, derivatives and interop suggestion adapters are written and
tested but nothing registers them with the suggestion dispatcher yet. Per-adapter
`SuggestionsConfig` flags (`AETHER_SUGGESTIONS_{STABLECOIN,DERIVATIVES,INTEROP}_ADAPTER_ENABLED`)
used to claim to gate them; nothing read those flags, so they were retired.
Suggestions carry evidence + lineage ids; the platform's separate execution gate
remains OFF and no economic suggestion is executable.

## Alerts

Five topics with severity-routed `_TOPIC_MAP` rows in the
notification-intelligence consumer (P1 for depeg and policy change; P2
for variance, stalled gap, stuck message). Delivery uses the existing
HMAC webhook machinery — config only, no new transport.
