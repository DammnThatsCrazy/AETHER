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
npm install @aether/web
```

If you use TypeScript, the package includes types. No separate types package is needed.

## Add your key

You need a tenant ID and an API key for the environment you are targeting. For a proof run, use the proof tenant credentials from the staging environment. For local development, use your local tenant credentials. API keys are provisioned per tenant. See [Tenant Setup](/docs/developer/tenant-setup.md).

Do not commit API keys to the repository. Read them from the environment or your app's secret store.

## Initialize

```typescript
import { AetherSDK } from '@aether/web';

const aether = AetherSDK.init({
  tenantId: process.env.AETHER_TENANT_ID,
  apiKey: process.env.AETHER_API_KEY,
  appId: 'my-app',
});
```

Initialization configures the SDK with your tenant, app, and site metadata. The SDK does not start emitting until you call the tracking methods, but it does validate the configuration and prepare the batch queue.

If initialization fails, the SDK surfaces a clear error. A failure to initialize is a reportable failure in the proof spine, with reason `INITIALIZATION_FAILED` and likely owning subsystem Web SDK.

## Emit a heartbeat

Every Aether SDK emits periodic heartbeat events to confirm liveness and session continuity. The Web SDK emits the first heartbeat on initialization and subsequent heartbeats at the configured interval.

To verify heartbeat emission in code:

```typescript
const health = await aether.health();
console.log(health);
// {
//   status: 'ok',
//   queue_depth: 0,
//   endpoint_latency_ms: 42,
//   ingestion_success_rate: 1.0
// }
```

The heartbeat includes session state, SDK version, and contract version. See [SDK Heartbeat](/docs/sdks/heartbeat.md) for the full heartbeat contract.

In a proof run, the heartbeat is verified by the proof web app's heartbeat control and by confirmation in the proof tenant's ingestion surface. A missing heartbeat is a reportable failure with reason `HEARTBEAT_NOT_SENT` and likely owning subsystem Web SDK.

## Track an event

The canonical event capture entry point is `observe(type, properties)`.

```typescript
aether.observe('page_view', {
  url: window.location.href,
  title: document.title,
});
```

The event type must be a canonical type from the event registry. Non-canonical types are ignored at ingestion. See [SDK Ingestion Contract](/docs/sdks/ingestion-contract.md) and [Event Contracts](/docs/sdks/event-contracts.md).

In a proof run, the tracked event is verified by the proof web app's track control and by confirmation in the proof tenant's ingestion surface. An event that is not tracked is a reportable failure with reason `EVENT_NOT_TRACKED` and likely owning subsystem Web SDK.

## Identify a user

Attach an identity hint so the graph can associate events with a known user.

```typescript
aether.identify('user_123', {
  email: 'user@example.com',
  name: 'Example User',
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
| SDK does not initialize | Missing or invalid tenant ID or API key | Check the environment variables and the proof tenant credentials. |
| No heartbeat in the Aether UI | SDK did not emit a heartbeat, or the event did not reach ingestion | Check `aether.health()` and the SDK version. Confirm the SDK is initialized. |
| Tracked event not in the Aether UI | Event type is non-canonical, or the event did not reach ingestion | Confirm the event type is canonical. Check the ingestion surface. |
| Identity not associated | Identity hint not sent, or identity resolution not configured | Confirm the identify call fired. Check the tenant's identity merge rules. |
| `queue_depth` growing | Network issue or endpoint down | Check the API key and endpoint URL. Check the SDK's offline spool. |
| `ingestion_success_rate` below 1.0 | Schema validation failures | Check the event types and properties against the event registry. |

For the full heartbeat troubleshooting table, see [Verify Heartbeat](/docs/developer/verify-heartbeat.md).

## Next steps

- [Send Your First Event](/docs/developer/send-first-event.md)
- [Verify Heartbeat](/docs/developer/verify-heartbeat.md)
- [Query the Graph](/docs/developer/query-the-graph.md)
- [SDK Testing](/docs/testing/sdk-testing.md)
- [Web SDK Activation E2E](/docs/testing/e2e-testing.md)
