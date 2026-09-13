---
title: Getting Started with the Node SDK
slug: quickstart/node-sdk
section: developer
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: 0.1.0
canonical_owner: sdk@aether
estimated_read_minutes: 5
toc_depth: 3
---

# Getting Started with the Node SDK

`@aether/server` is Aether's server-side observation client for Node.js. It
observes — API requests, job runs, connector syncs, webhook deliveries — it
never executes on your behalf, and every event is batched and delivered
through the same canonical `POST /v1/batch` endpoint the browser SDK uses.

## Install

```bash
npm install @aether/server
```

## Initialize

```typescript
import { AetherServerSDK } from '@aether/server';

const aether = new AetherServerSDK({
  writeKey: process.env.AETHER_WRITE_KEY!,
  consent: { analytics: true },
});
```

Consent on the server SDK is deny-by-default across the full registry, same
as the browser SDK. Grant only what your service is actually allowed to
observe:

```typescript
aether.grant(['analytics', 'commerce']);

// grantAll() grants every purpose EXCEPT the explicit-opt-in ones
// (credit, location, financial_activity, economic_observability,
// cross_chain_observability, fraud_prevention) — those must be granted
// individually, with their own legal basis.
aether.grantAll();
```

## Track events

```typescript
aether.track({
  type: 'api_request_observed',
  properties: {
    method: 'POST',
    path: '/v1/orders',
    statusCode: 201,
    durationMs: 42,
  },
});
```

Only canonical registry event types are accepted — an unrecognized `type` is
dropped locally with a console warning rather than shipped to an endpoint
that would reject it anyway.

For the most common server-side event shapes, use the typed `observe` helpers
instead of building the event object yourself:

```typescript
aether.observe.apiRequest({
  method: 'GET',
  path: '/v1/profile/usr_18f2',
  statusCode: 200,
  durationMs: 18,
  tenantId: 'tnt_492',
});

aether.observe.job({ jobType: 'nightly-export', status: 'completed', durationMs: 3021 });
aether.observe.webhookDelivery({ webhookId: 'wh_1', event: 'order.paid', statusCode: 200, durationMs: 210, attempt: 1 });
aether.observe.connectorSync({ connectorId: 'shopify', status: 'completed', recordsProcessed: 148 });
aether.observe.rateLimit({ path: '/v1/batch', limitType: 'burst', retryAfterMs: 2000 });
aether.observe.dependencyFailure({ dependency: 'redis', errorCode: 'ECONNREFUSED' });
```

## Batching and flush

Events are queued in memory and flushed automatically every `flushInterval`
milliseconds (default 5000) or once `flushAt` events have queued (default
100), whichever comes first:

```typescript
const aether = new AetherServerSDK({
  writeKey: process.env.AETHER_WRITE_KEY!,
  flushAt: 50,
  flushInterval: 2000,
});

// Flush explicitly before your process exits (serverless handlers,
// short-lived scripts, CI jobs).
await aether.shutdown();
```

`shutdown()` flushes any remaining events and stops the internal timer;
`flush()` alone flushes without stopping the timer, which is what you want
inside a long-running service.

### Durable delivery

For a long-running process where losing a batch on crash or restart is
unacceptable, enable the disk-backed durable queue. Spooled events survive a
process restart and are replayed automatically:

```typescript
const aether = new AetherServerSDK({
  writeKey: process.env.AETHER_WRITE_KEY!,
  durable: true,
  onSpoolDrop: (info) => logger.error('aether spool full', info),
});

aether.isDurable();     // true
aether.spoolHealthy();  // true | false | null (null when durability is off)
```

## Health and batch results

```typescript
aether.healthSnapshot();   // queued / delivered / failed counters
aether.lastBatchResult();  // { accepted, duplicate, rejected, queue_depth }
aether.queueDepth();
```

## Next steps

- [Ingestion API reference](../api/ingestion.md) — the request/response
  shapes `AetherServerSDK` sends over the wire.
- [Webhooks](../api/webhooks.md) — receive events *from* Aether (delivery
  confirmations, entitlement changes) in your own services.
