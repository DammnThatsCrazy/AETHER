---
title: Provider identity and attribution
status: active
canonical_owner: frontend@aether
---

# Provider identity and attribution

Provider metadata is in `packages/brand/src/providers/`. It maps identity only;
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
- Every current registry mark is a fallback by design. Add a third-party mark
  only after legal review and commit it locally; never remote-load or recreate it.
- Keep the visible provider label near the mark, especially in dense/narrow UI.
- Treat `generic_webhook`, `webhook`, and `outbound_activation` as technical
  identities. Do not turn them into third-party trademarks.
- Do not use a provider logo/color to imply connectivity, safety, severity,
  entitlement, or a recommended action.
