---
title: Noesis and OODA Integration
slug: productization/economic-interoperability-intelligence/noesis-and-ooda-integration
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [services/backend/services/noesis/adapters/stablecoin_adapter.py, services/backend/services/noesis/adapters/derivatives_adapter.py, services/backend/services/noesis/adapters/interop_adapter.py, services/backend/services/suggestions/adapters/stablecoin_adapter.py, services/backend/services/suggestions/adapters/derivatives_adapter.py, services/backend/services/suggestions/adapters/interop_adapter.py]
canonical_owner: platform@aether
source_hashes:
  "services/backend/services/noesis/adapters/derivatives_adapter.py": "sha256:fdd0f5f13da071c5cc95ca03373c3b4e55d183e97373b2c6d8c76dffaaf44d5f"
  "services/backend/services/noesis/adapters/interop_adapter.py": "sha256:66dbd63ef28c1c38e991d91c6a0bd81d5d137de53f2aa1d46e232cb073c9cb0f"
  "services/backend/services/noesis/adapters/stablecoin_adapter.py": "sha256:d7e351b6efb8bd464e17f9474555bfa292a1ff5c0ef0dbfdf7167516702fa124"
  "services/backend/services/suggestions/adapters/derivatives_adapter.py": "sha256:971714ed5db6f9e6d979f76a0f2d4526e6064a91aff62a06a4ad63cfefc8ccc6"
  "services/backend/services/suggestions/adapters/interop_adapter.py": "sha256:30e467f7d9680cdfb5466eba0ba57fa85c54692b12d12b265929d4907e764dfb"
  "services/backend/services/suggestions/adapters/stablecoin_adapter.py": "sha256:8f97b8a7144330fca2a64a77b5e562b8f77354ac0111e5700e3594799a7f2ff7"
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
