---
title: Noesis and OODA Integration
slug: productization/economic-interoperability-intelligence/noesis-and-ooda-integration
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/noesis/adapters/stablecoin_adapter.py
  - Backend Architecture/aether-backend/services/noesis/adapters/derivatives_adapter.py
  - Backend Architecture/aether-backend/services/noesis/adapters/interop_adapter.py
  - Backend Architecture/aether-backend/services/suggestions/adapters/stablecoin_adapter.py
  - Backend Architecture/aether-backend/services/suggestions/adapters/derivatives_adapter.py
  - Backend Architecture/aether-backend/services/suggestions/adapters/interop_adapter.py
canonical_owner: platform@aether
last_synced_commit: "4e6fdad"
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

Per-adapter flags in `SuggestionsConfig`
(`AETHER_SUGGESTIONS_{STABLECOIN,DERIVATIVES,INTEROP}_ADAPTER_ENABLED`)
default OFF. Suggestions carry evidence + lineage ids; the platform's
separate execution gate remains OFF and no economic suggestion is
executable.

## Alerts

Five topics with severity-routed `_TOPIC_MAP` rows in the
notification-intelligence consumer (P1 for depeg and policy change; P2
for variance, stalled gap, stuck message). Delivery uses the existing
HMAC webhook machinery — config only, no new transport.
