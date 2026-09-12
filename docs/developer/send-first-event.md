---
title: Send Your First Event
slug: send-first-event
section: quickstart
visibility: P
audience: [dev-junior, dev-senior]
status: experimental
since_version: "0.1.0"
---

# Send Your First Event

## Initialize the SDK

```typescript
import { Aether } from '@aether/web';

const aether = new Aether({
  tenantId: 'your-tenant-id',
  apiKey: 'your-api-key',
});
```

## Send an Observation

```typescript
aether.observe({
  type: 'page_view',
  properties: {
    url: window.location.href,
    title: document.title,
  },
});
```

## What Happens Next

1. The SDK batches the observation locally.
2. On flush, the batch is sent to `/v1/batch`.
3. The ingestion pipeline normalizes the event (Bronze).
4. The event is projected into the tenant intelligence graph (Silver).
5. 360 surfaces reflect the updated graph state.

## Verify Delivery

Check that your event was received by following
[Verify Heartbeat](./verify-heartbeat.md).
