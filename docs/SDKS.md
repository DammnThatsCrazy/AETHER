---
title: SDKs
slug: sdks/sdks
section: sdks
visibility: I
audience: [dev-junior, dev-senior, architect]
status: stable
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# SDKs

Aether ships first-party SDKs for event ingestion. **SDK ingestion is supported
but not required** — connectors and signed webhooks provide a no-SDK path
([Data Ingestion Paths](DATA-INGESTION-PATHS.md)).

| SDK | Package | Install | Guide |
| --- | --- | --- | --- |
| Web | `@aether/web` | npm / CDN | [Web SDK](SDK-WEB.md) |
| React Native | `@aether/react-native` | npm | [React Native SDK](SDK-REACT-NATIVE.md) |
| iOS | `AetherSDK` | CocoaPods / SPM | [iOS SDK](SDK-IOS.md) |
| Android | `com.aether:sdk-android` | Maven (GitHub Packages) | [Android SDK](SDK-ANDROID.md) |
| Shared contracts | `@aether/shared` | npm | — |

## Capabilities

Batching + flush, retry/backoff, offline queue, per-event idempotency
(`event_id`), consent gating, device fingerprint, health telemetry, and signed
remote config (manifest + staged rollout). Contracts are shared across all SDKs
(`packages/shared`) — see [SDK API Contracts](SDK-API-CONTRACTS.md) and
[SDK Event Schemas](SDK-EVENT-SCHEMAS.md).

## Release

Versioned with the monorepo; published via `.github/workflows/publish-sdk.yml`.
See the [SDK Release Checklist](SDK-RELEASE-CHECKLIST.md) and per-SDK changelogs.
