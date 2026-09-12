---
title: SDK Parity Productization
slug: sdk-parity-productization
section: architecture
visibility: I
audience: [architect]
status: experimental
since_version: "0.1.0"
---

# SDK Parity Productization

## Target State

All Aether SDKs (Web, Server, React Native, iOS, Android) must reach
feature parity across observation, health, and manifest verification
capabilities.

## Parity Matrix

| Capability | Web | Server | React Native | iOS | Android |
|---|---|---|---|---|---|
| observe() | Yes | Yes | Yes | Yes | Yes |
| batch flush | Yes | Yes | Yes | Yes | Yes |
| Health heartbeat | Yes | Yes | Planned | Yes | Yes |
| Offline queue | N/A | N/A | Planned | Yes | Yes |
| Manifest verify | Yes | Yes | Planned | Planned | Planned |
| Schema validation | Yes | Yes | Planned | Planned | Planned |

## Parity Requirements

- All SDKs emit to the same `/v1/batch` ingestion endpoint.
- Event type parity is enforced by the `CANONICAL_EVENT_TYPES` registry.
- Field-trust parity is validated by the contract suite.
- SDKs are thin observation clients — no business logic.

## Dependencies

- SDK ingestion contract (shared TS ↔ backend `/v1/batch`)
- SDK import boundary enforcement
- SDK runtime parity validation (observe / manifest-verify / batch-health)

## Current Gap

Web and Server SDKs are at parity. Mobile SDKs have partial coverage.
React Native SDK needs offline queue and health heartbeat.
