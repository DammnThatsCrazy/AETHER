---
title: Aether SDKs
slug: sdks/overview
section: reference
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: 0.1.0
---

# Aether SDKs

The Aether SDK is a thin observation client.

It collects first-party observations from the host app or site, attaches canonical metadata, batches events, retries safely, and emits to `/v1/batch`.

It does not own provider sync, global identity resolution, attribution, financial normalization, or graph writes.

## Available SDKs

| SDK | Package | Status |
|---|---|---|
| Web | `packages/web` | Alpha |
| React | via Web SDK | Alpha |
| React Native | `packages/react-native` | Alpha |
| iOS | `packages/ios` | Alpha |
| Android | `packages/android` | Alpha |

## Core Concepts

Every SDK supports:

- Tenant, app, and site configuration
- Session lifecycle
- Page/screen view tracking
- Custom event emission
- Identity hints
- Batch sending to `/v1/batch`
- Heartbeat events
- Privacy and redaction controls
- Version metadata

## Further Reading

- `docs/sdks/web.md` — Web SDK
- `docs/sdks/react.md` — React SDK
- `docs/sdks/react-native.md` — React Native SDK
- `docs/sdks/ios.md` — iOS SDK
- `docs/sdks/android.md` — Android SDK
- `docs/sdks/event-contracts.md` — Event contract reference
- `docs/sdks/parity-matrix.md` — SDK capability parity
- `docs/source-of-truth/sdk-truth.md` — SDK truth document
