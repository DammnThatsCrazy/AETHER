---
title: Provider identity and attribution
slug: architecture/brand-system/providers
section: architecture
visibility: I
audience: [dev-senior, architect, ops]
status: stable
since_version: "0.1.0"
canonical_owner: frontend@aether
---

# Provider identity and attribution

Provider metadata is in `packages/ui/brand/src/providers/`. It maps identity only;
the owning backend/shared contracts keep runtime IDs, eligibility, and health.

```tsx
import { ProviderCard, ProviderMark, ProviderSourceChip } from '@aether/ui';

<ProviderSourceChip provider={sourceId} />
<ProviderMark provider={sourceId} decorative size={20} />
<ProviderCard provider={sourceId} detail="Configured by tenant" />
```

```ts
import { providerAttribution, resolveProvider } from '@olympus/brand';

const resolved = resolveProvider(serverProviderId);
const attribution = providerAttribution(resolved.identity);
```

- Resolve every server value. Unknown input uses neutral initials, not a guessed
  brand or a failure state.
- A third-party mark is shown only when it is committed locally under
  `packages/ui/brand/src/identity/marks/providers/` and listed in `REVIEWED_MARKS`
  in `registry.ts`; never remote-load or recreate one. Every other provider
  renders the initials fallback.
- The 22 committed files (21 providers; X ships a dark and a light variant)
  came with the Olympus Labs + Aether surfaces design handoff and were approved
  for display by the site owner on 2026-10-03: Apple, Google, Google Ads, Google
  Analytics, HubSpot, Instagram, Intercom, Jira, Klaviyo, Linear, Meta,
  Microsoft, Phantom, PostHog, Salesforce, Segment, Shopify, Slack, Stripe, X,
  and Zendesk. That approval is not a trademark or legal review; record one
  here when it happens, and add a mark only through the same approval.
- Each app serves the marks at `/providers/<file>.svg` (the brand marks
  directory is every Vite app's public directory). `preferredBackground` says
  where a mark reads; X uses `x-dark.svg` on light surfaces and its
  `monochromeMark` (`x.svg`) on dark ones.
- Keep the visible provider label near the mark, especially in dense/narrow UI.
- Treat `generic_webhook`, `webhook`, and `outbound_activation` as technical
  identities. Do not turn them into third-party trademarks.
- Do not use a provider logo/color to imply connectivity, safety, severity,
  entitlement, or a recommended action.
