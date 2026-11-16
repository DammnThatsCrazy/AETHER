---
title: Verify React SDK Installation — Aether
slug: developers/sdk/react/verify-installation
section: developer
visibility: P
audience: [dev-junior, dev-senior]
status: experimental
since_version: 0.1.0
---

# Verify React SDK Installation

This guide walks through installing the Aether React SDK, adding your key, initializing with the provider, using the hooks, and verifying the result in the Aether UI. It is the practical companion to the [React SDK reference](/docs/sdks/react.md) and the [Web SDK verify installation](/docs/developers/sdk/web/verify-installation.md) guide.

Related tickets: FPS-011 (Web SDK smoke — the React SDK is built on the Web SDK), FPS-027 (Web SDK activation E2E, which covers React where applicable).

## Install the SDK

```bash
npm install @olympuslabs/aether-web
```

The React SDK is delivered through `@olympuslabs/aether-web/react`. You install the same package as the Web SDK because the React SDK wraps the Web SDK.

## Add your key

You need the SDK key Aether issued for this app or site in the environment you are targeting (onboarding issues one per SDK; browser SDKs get a site-bound publishable `pk_` key). The key identifies the tenant, so there is no separate tenant ID. For a proof run, use the proof tenant credentials from the staging environment. For local development, use your local tenant credentials. API keys are provisioned per tenant. See [Tenant Setup](/docs/developer/tenant-setup.md).

Do not commit API keys to the repository. Read them from the environment or your app's secret store.

## Initialize with the provider

Wrap your app in the `AetherProvider` at the root of your component tree.

```tsx
import { AetherProvider } from '@olympuslabs/aether-web/react';

// Define the config outside the component so it is stable across renders.
const AETHER_CONFIG = {
  apiKey: 'pk_live_…',   // the site-bound publishable key (safe in page code)
  siteId: 'site_…',
  onBatchResult: (health) => console.debug('[aether] batch', health),
};

function App() {
  return (
    <AetherProvider config={AETHER_CONFIG}>
      <YourApp />
    </AetherProvider>
  );
}
```

The provider loads and initializes the Web SDK in the browser (it does nothing during server rendering), then makes it available to the hooks below. It renders nothing until the SDK is ready, so hooks never see an uninitialized SDK. The key identifies the tenant on the server, so there is no tenant ID to pass.

## Use the hooks

### Track an event

Use `useScreenOrPageTracking` for page views, or `useAether` to reach the SDK for other canonical events.

```tsx
import { useEffect } from 'react';
import { useAether, useScreenOrPageTracking } from '@olympuslabs/aether-web/react';

function CheckoutPage() {
  useScreenOrPageTracking('/checkout');   // records a page view when the name changes

  const aether = useAether();
  useEffect(() => {
    aether.consent.grant(['analytics']);  // after your consent banner records it
  }, [aether]);

  return null;
}
```

The event type must be a canonical type from the event registry. Non-canonical types are ignored at ingestion. See [SDK Ingestion Contract](/docs/sdks/ingestion-contract.md) and [Event Contracts](/docs/sdks/event-contracts.md).

For client-side routing, call `useScreenOrPageTracking(location.pathname)` in a component that re-renders on route changes; each new path records one page view.

### Identify a user

```tsx
import { useEffect } from 'react';
import { useAether } from '@olympuslabs/aether-web/react';

function UserBadge({ user }) {
  const aether = useAether();

  useEffect(() => {
    aether.hydrateIdentity({
      userId: user.id,
      traits: { email: user.email, name: user.name },
    });
  }, [aether, user.id]);

  return <span>{user.name}</span>;
}
```

Identity hints are not identity resolution. They are hints the SDK sends so the backend can associate events. See [Tenant Setup](/docs/developer/tenant-setup.md) for identity merge rules.

### Emit a heartbeat

The React integration inherits the Web SDK's heartbeat behavior: the fleet heartbeat starts when the provider initializes the SDK, and a `heartbeat` session event is recorded every 30 seconds by default. You do not need to call anything. To watch delivery, use the `onBatchResult` callback in the provider config, which receives `{ accepted, duplicate, rejected, dropped_by_consent, queue_depth }` for each batch.

The heartbeat includes session state, SDK version, and contract version. See [SDK Heartbeat](/docs/sdks/heartbeat.md) for the full heartbeat contract.

## Verify in the Aether UI

After tracking an event and identifying a user, verify that the proof tenant received them.

1. Open the Aether Console or Kyber Operator Console on staging.
2. Navigate to the proof tenant's ingestion or SDK health surface.
3. Confirm the heartbeat is present with the expected session state and SDK version.
4. Confirm the tracked event is present with the expected type and properties.
5. If you identified a user, confirm the identity hint is associated with the events.

The verification path for a proof run is described in [E2E Testing](/docs/testing/e2e-testing.md) and the Web SDK activation flow, which covers React where the React SDK is the SDK in scope. A heartbeat or event that is not visible in the Aether UI is a reportable failure with the appropriate reason code and likely owning subsystem.

## Required visible state in the proof React app

The proof React app exposes the same controls and visible state as the proof web app, so a tester or the proof runner can exercise the same behaviors.

| Control | Purpose |
|---|---|
| Initialize / config display | Show the site ID and key status, or an error if initialization failed. |
| Emit heartbeat | Confirm the SDK's heartbeat is active and the health surface responds. |
| Track event | Trigger a canonical event through a hook and show that it was sent. |
| Identify user | Attach an identity hint through a hook and show that it was attached. |
| Event log / visible state | Show the events that were sent, or the visible state the tester can verify. |
| Reset / clear | Clear the local state so the app can be re-run from a clean baseline. |

A control that exists but does nothing is not a control. A control that crashes the app is worse than no control.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Provider does not initialize | Missing or invalid publishable key, or the page origin is not bound to the site | Check the key and site ID, and that the page's origin is one of the site's origins. |
| `useAether()` throws | Provider not wrapped around the component tree | Confirm `AetherProvider` is an ancestor of the component using `useAether`. |
| No heartbeat in the Aether UI | SDK did not emit a heartbeat, or the event did not reach ingestion | Confirm the provider rendered its children (the SDK is ready). Check `onBatchResult`. |
| Tracked event not in the Aether UI | Consent not granted, or the event did not reach ingestion | Confirm `analytics` consent is granted (`dropped_by_consent` in `onBatchResult`). |
| Identity not associated | Identity hint not sent, or identity resolution not configured | Confirm the identify call fired. Check the tenant's identity merge rules. |
| `queue_depth` growing | Network issue or endpoint down | Check the API key and endpoint URL. Check the SDK's offline spool. |
| `ingestion_success_rate` below 1.0 | Schema validation failures | Check the event types and properties against the event registry. |

For the full heartbeat troubleshooting table, see [Verify Heartbeat](/docs/developer/verify-heartbeat.md).

## Next steps

- [Install the SDK](/docs/developer/install-the-sdk.md)
- [Send Your First Event](/docs/developer/send-first-event.md)
- [Verify Heartbeat](/docs/developer/verify-heartbeat.md)
- [Query the Graph](/docs/developer/query-the-graph.md)
- [SDK Testing](/docs/testing/sdk-testing.md)
- [Web SDK Activation E2E](/docs/testing/e2e-testing.md)
