# Source of Truth

This directory is **the** authoritative description of SDK behavior in this
monorepo. Every file here is derived from code that actually runs:
`packages/shared/*.ts`, `packages/{web,ios,android,react-native}/**`,
`Backend Architecture/aether-backend/**`, `Data Lake Architecture/**`.

If another doc contradicts a file in this directory, this directory wins.

| Doc | Covers |
|---|---|
| `SDK_SCOPE.md` | What the SDK is and is not responsible for |
| `ENTITY_MODEL.md` | Canonical entities (Web2 + Web3 + hybrid) |
| `EVENT_REGISTRY.md` | Every event type the SDK emits, with consent purpose |
| `CONSENT_MODEL.md` | The canonical (registry-derived) consent purposes and gating rules |
| `INGESTION_CONTRACT.md` | How SDKs talk to the backend (`/v1/batch`) |
| `PLATFORM_PARITY.md` | Which capabilities are Tier A / B / C |
| `CAPABILITY_MANIFEST.md` | `/v1/config` contract |
| `GRAPH_ALIGNMENT.md` | Which SDK events feed which graph layer |
| `BACKEND_INTELLIGENCE_ARCHITECTURE.md` | Additive backend target architecture, service boundaries, graph/event/realtime/API contracts, and operational roadmap |
