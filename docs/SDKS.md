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

## SDK Scope Boundary

> SDKs do not resolve identity truth. SDKs do not mutate the graph. SDKs do not classify wallets. SDKs do not score users, wallets, fraud, or risk. SDKs do not run workflows. SDKs do not settle payments. SDKs emit canonical observations only. Backend owns all enrichment, orchestration, and business logic.

## React Browser Wrapper (Web SDK)

Install: `npm install @aether/web react`

```tsx
import { AetherProvider, useAether, useConsentState } from '@aether/web/react';

function App() {
  return (
    <AetherProvider config={{ apiKey: 'YOUR_KEY' }}>
      <MyComponent />
    </AetherProvider>
  );
}

function MyComponent() {
  const aether = useAether();
  const consent = useConsentState();
  // ...
}
```

## Health Agent (iOS / Android)

The health agent runs automatically after SDK initialization. It POSTs a signed heartbeat to `/v1/sdk/health` every 60 seconds and fetches the remote manifest from `/v1/config` every 5 minutes. Both are fire-and-forget and gate on analytics consent in GDPR mode.

## Granular Agent Lifecycle Emitters

Available on all platforms (Web, iOS, Android, React Native):

```typescript
aether.agent.registered(agentId, properties?)
aether.agent.taskCreated(taskId, actorId, properties?)
aether.agent.taskCompleted(taskId, properties?)
aether.agent.taskFailed(taskId, reason?, properties?)
aether.agent.escalatedToHuman(taskId, reason?, properties?)
aether.agent.outcomeRecorded(taskId, outcome, properties?)
// ... 13 more — see EventType registry
```

## Granular x402 Lifecycle Emitters

```typescript
aether.x402.resourceRequested(resourceId, properties?)
aether.x402.paymentRequired(resourceId, amount, currency, properties?)
aether.x402.paymentSettled(paymentId, properties?)
aether.x402.accessGranted(resourceId, properties?)
// ... 10 more — see EventType registry
```

## Rewards Emitters

Thin observation only — backend owns eligibility, claim validation, and delivery logic.

```typescript
aether.rewards.actionQueued(campaignId, ruleId, properties?)
aether.rewards.proofGenerated(campaignId, proofId, properties?)
aether.rewards.delivered(campaignId, rewardId, properties?)
aether.rewards.claimSubmitted(campaignId, claimId, properties?)
```

## Tier C Capabilities (Web-only by design)

The following capabilities are web-only and will not be ported to native platforms:

| Capability | Notes |
|---|---|
| Plugin hooks | Web DOM lifecycle; not portable |
| Heatmaps | Requires DOM interaction capture |
| Funnels | Web page-flow specific |
| Form analytics | Web form element tracking |
| Auto-discovery | Web DOM traversal |
