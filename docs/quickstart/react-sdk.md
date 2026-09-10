---
title: Getting Started with the React SDK
slug: quickstart/react-sdk
section: quickstart
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: sdk@aether
estimated_read_minutes: 4
toc_depth: 3
---

# Getting Started with the React SDK

The React bindings live inside `@aether/web` (import from `@aether/web/react`)
and wrap the same underlying SDK described in the
[Web SDK quickstart](web-sdk.md) with a provider and a handful of hooks —
`AetherProvider`, `useAether`, `useIdentity`, `useConsentState`, and
`useScreenOrPageTracking`.

## Install

```bash
npm install @aether/web
```

No separate package — the React entry point ships inside `@aether/web`.

## Wrap your app

`AetherProvider` lazily imports the SDK client-side only (so it is safe in
Next.js / SSR apps) and initializes it once, on mount:

```tsx
import { AetherProvider } from '@aether/web/react';

export default function App({ children }: { children: React.ReactNode }) {
  return (
    <AetherProvider
      config={{
        apiKey: process.env.NEXT_PUBLIC_AETHER_WRITE_KEY!,
        environment: process.env.NODE_ENV === 'production' ? 'production' : 'development',
      }}
    >
      {children}
    </AetherProvider>
  );
}
```

`AetherProvider` doesn't render `children` until the SDK has finished
initializing, so any component under it can safely call `useAether()`
without a null check.

## Use the SDK from components

```tsx
import { useAether } from '@aether/web/react';

function UpgradeButton() {
  const aether = useAether();

  return (
    <button
      onClick={() => {
        aether.track('upgrade_clicked', { plan: 'pro' });
      }}
    >
      Upgrade
    </button>
  );
}
```

`useAether()` returns the same `AetherSDKInterface` singleton you'd get from
`import aether from '@aether/web'` — `track`, `observe`, `hydrateIdentity`,
`consent`, `wallet`, `commerce`, and the rest of the surface documented in the
[Web SDK guide](web-sdk.md) are all available.

## Track route changes

`@aether/web`'s auto-discovery module already tracks SPA navigation for most
routers via `history.pushState`/`replaceState`. For app frameworks that don't
go through those APIs (or when you want an explicit, named page view), use
`useScreenOrPageTracking`:

```tsx
import { useScreenOrPageTracking } from '@aether/web/react';

function PricingPage() {
  useScreenOrPageTracking('Pricing');
  return <div>…</div>;
}
```

## Read identity and consent state

```tsx
import { useIdentity, useConsentState } from '@aether/web/react';

function AccountBadge() {
  const identity = useIdentity();
  const consent = useConsentState();

  if (!consent?.analytics) return null;
  return <span>{identity?.userId ?? 'Anonymous'}</span>;
}
```

Both hooks subscribe to live updates — `useConsentState` re-renders whenever
`aether.consent.grant()` / `revoke()` changes the state, and `useIdentity`
reflects the latest resolved identity after `hydrateIdentity()` runs.

## Next steps

- [Node SDK quickstart](node-sdk.md) — mirror your client-side events with
  server-side observation for API requests, jobs, and webhooks.
- [Journeys](../concepts/journeys.md) — `useJourneyResumed` and the
  `startJourney` / `checkpointJourney` lifecycle for multi-step flows.
