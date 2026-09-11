---
title: "SDK Architecture"
slug: architecture/current/sdk-architecture
section: architecture
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# SDK Architecture

## Design

Aether SDKs are thin observation clients. They collect local observations, batch them, and emit canonical event envelopes to `/v1/batch`.

## Packages

| Package | Platform | Path |
|---|---|---|
| Web SDK | Browser | `packages/web` |
| React Native | Mobile (cross-platform) | `packages/react-native` |
| iOS | Native iOS | `packages/ios` |
| Android | Native Android | `packages/android` |
| Mobile Core | Shared mobile logic | `packages/mobile-core` |

## Event Flow

```txt
App code → SDK API → local event queue → batch → /v1/batch → ingestion pipeline
```

## Current State

Web and React Native SDKs are functional. iOS and Android SDKs are in development.
