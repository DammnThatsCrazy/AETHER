---
title: Readme
slug: source-of-truth/readme
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Source of Truth

This directory is **the** authoritative description of SDK behavior in this
monorepo. Every file here is derived from code that actually runs:
`packages/shared/*.ts`, `packages/{web,ios,android,react-native}/**`,
`services/api/**`, `docs/archive/legacy-architecture/data-lake-architecture/**`.

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
| `CONNECTOR_TAXONOMY.md` | Six-layer connector corpus model (`ConnectorClass`/`ConnectorRole`/policies from `base.py`) + derived four-group customer catalog mirror (21 connectors / 7 ad platforms / 5 payment rails / 3 deferred bureaus) |
| `CONNECTOR_LAKE_POLICY.md` | Default lake/graph/training write policy per connector class, dual-role rule, and governed elevation |
| `AETHER_END_USER_LIFECYCLE.md` | Canonical end-user lifecycle spec: copy vocabulary, routes, connection-state projection, readiness honesty, experience categories, telemetry, integration data markers, E2E acceptance A–E |

## AETHER 360 blueprint references

The primary and supplemental references have distinct roles in the ongoing
backend buildout:

| Document | Role |
|---|---|
| `AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md` | Acceptance contract for the exact 18 backend 360 product surfaces. Its required slots, subjects, owners, and lenses are the implementation target. |
| `../../archive/360-blueprint/AETHER_360_COMPLETE_ARCHITECTURAL_BUILDOUT_BLUEPRINT_SUPPLEMENTAL.md` | Preserved supplemental architecture context for shared lenses, projection flow, and supporting subsystems. It contains historical product terminology, frontend scope, and a broader/different surface matrix; it does not replace or expand the backend 18-surface contract. |

The supplemental blueprint remains an archived reference. Apply the repository
implementation scope and the primary backend contract when its content differs;
its imperative wording is source material, not a separate repository
instruction.
