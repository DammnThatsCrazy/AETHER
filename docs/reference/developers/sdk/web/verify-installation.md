---
title: Verify Web SDK Installation — Aether
slug: developers/sdk/web/verify-installation
section: developer
visibility: P
audience: [dev-junior, dev-senior]
status: experimental
since_version: 0.1.0
---

# Verify Web SDK Installation

This guide walks through installing the Aether Web SDK, adding your key, initializing, emitting a heartbeat, tracking an event, identifying a user, and verifying the result in the Aether UI. It is the practical companion to the [Web SDK reference](/docs/sdks/web.md) and the [Send Your First Event](/docs/developer/send-first-event.md) guide.

Related tickets: FPS-011 (Web SDK smoke), FPS-027 (Web SDK activation E2E).

## Install the SDK

```bash
npm install @olympuslabs/aether-web
```

If you use TypeScript, the package includes types. No separate types package is needed.

## Add your key

You need the SDK key Aether issued for this app or site in the environment you are targeting (onboarding issues one per SDK; browser SDKs get a site-bound publishable `pk_` key). The key identifies the tenant, so there is no separate tenant ID. For a proof run, use the proof tenant credentials from the staging environment. For local development, use your local tenant credentials. API keys are provisioned per tenant. See [Tenant Setup](/docs/developer/tenant-setup.md).

The publishable key is bound to your site's origins and can only ingest, so it is safe in page code. Never put a secret (`ak_`) key in browser code.

## Initialize

```typescript
import aether from '@olympuslabs/aether-web';

aether.init({
  apiKey: 'pk_live_…',   // the site-bound publishable key
  siteId: 'site_…',      // the site the key is bound to
  onBatchResult: (health) => console.debug('[aether] batch', health),
});

// Events are gated by consent. Grant the purposes your consent banner collected.
aether.consent.grant(['analytics']);
```

The key identifies the tenant on the server, so there is no tenant ID to pass.
The ingestion endpoint defaults to `https://api.olympuslabsml.com` (override with
`endpoint`). If you install with the one-line CDN script tag instead, the tag's
`data-key` and `data-site` attributes carry the same values.

If initialization fails, the SDK surfaces a clear error. A failure to initialize is a reportable failure in the proof spine, with reason `INITIALIZATION_FAILED` and likely owning subsystem Web SDK.

## Emit a heartbeat

Every Aether SDK emits periodic heartbeats to confirm liveness. The Web SDK starts its fleet heartbeat when `init()` runs, and records a `heartbeat` session event every 30 seconds by default (`advanced.heartbeatInterval`).

To check delivery from code, use the `onBatchResult` callback passed to `init()`, which reports each batch's outcome, and the queue diagnostics:

```typescript
// onBatchResult receives, per batch:
// { accepted: 3, duplicate: 0, rejected: 0, dropped_by_consent: 0, queue_depth: 0 }

aether.getQueueDepth();   // events waiting to send
aether.getDiagnostics();  // dropped-event counts by reason, or null before init
```

The heartbeat includes session state, SDK version, and contract version. See [SDK Heartbeat](/docs/sdks/heartbeat.md) for the full heartbeat contract.

In a proof run, the heartbeat is verified by the proof web app's heartbeat control and by confirmation in the proof tenant's ingestion surface. A missing heartbeat is a reportable failure with reason `HEARTBEAT_NOT_SENT` and likely owning subsystem Web SDK.

## Track an event

Use `pageView()` for page views and `observe(type, properties)` for other canonical event types.

```typescript
aether.pageView(window.location.pathname, { title: document.title });
```

The event type must be a canonical type from the event registry. Non-canonical types are ignored at ingestion. See [SDK Ingestion Contract](/docs/sdks/ingestion-contract.md) and [Event Contracts](/docs/sdks/event-contracts.md).

In a proof run, the tracked event is verified by the proof web app's track control and by confirmation in the proof tenant's ingestion surface. An event that is not tracked is a reportable failure with reason `EVENT_NOT_TRACKED` and likely owning subsystem Web SDK.

## Identify a user

Attach an identity hint so the graph can associate events with a known user.

```typescript
aether.hydrateIdentity({
  userId: 'user_123',
  traits: { email: 'user@example.com', name: 'Example User' },
});
```

Identity hints are not identity resolution. They are hints the SDK sends so the backend can associate events. See [Tenant Setup](/docs/developer/tenant-setup.md) for identity merge rules.

In a proof run, the identity hint is verified by the proof web app's identify control and by confirmation that the identity appears in the Profile 360 or the graph. An identity that is not attached is a reportable failure with reason `IDENTITY_NOT_ATTACHED` and likely owning subsystem Web SDK.

## Verify in the Aether UI

After emitting a heartbeat and a tracked event, verify that the proof tenant received them.

1. Open the Aether Console or Kyber Operator Console on staging.
2. Navigate to the proof tenant's ingestion or SDK health surface.
3. Confirm the heartbeat is present with the expected session state and SDK version.
4. Confirm the tracked event is present with the expected type and properties.
5. If you identified a user, confirm the identity hint is associated with the events.

The verification path for a proof run is described in [E2E Testing](/docs/testing/e2e-testing.md) and the Web SDK activation flow. A heartbeat or event that is not visible in the Aether UI is a reportable failure with the appropriate reason code and likely owning subsystem.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| SDK does not initialize | Missing or invalid publishable key, or the page origin is not bound to the site | Check the key and site ID, and that the page's origin is one of the site's origins. |
| No heartbeat in the Aether UI | SDK did not emit a heartbeat, or the event did not reach ingestion | Confirm `init()` ran. Check `onBatchResult` and `aether.getDiagnostics()`. |
| Tracked event not in the Aether UI | Consent not granted, or the event did not reach ingestion | Confirm `analytics` consent is granted (`dropped_by_consent` in `onBatchResult`). Call `await aether.flush()`. |
| Identity not associated | Identity hint not sent, or identity resolution not configured | Confirm the identify call fired. Check the tenant's identity merge rules. |
| `queue_depth` growing | Network issue or endpoint down | Check the key and endpoint URL. |
| `rejected` above 0 in `onBatchResult` | Schema validation failures | Check the event types and properties against the event registry. |

For the full heartbeat troubleshooting table, see [Verify Heartbeat](/docs/developer/verify-heartbeat.md).

## Next steps

- [Send Your First Event](/docs/developer/send-first-event.md)
- [Verify Heartbeat](/docs/developer/verify-heartbeat.md)
- [Query the Graph](/docs/developer/query-the-graph.md)
- [SDK Testing](/docs/testing/sdk-testing.md)
- [Web SDK Activation E2E](/docs/testing/e2e-testing.md)
