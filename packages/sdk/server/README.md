# @olympuslabs/aether-server

Aether Server SDK for Node.js. It sends server-side observations to Aether's
canonical ingestion endpoint (`POST /v1/batch`) with batching, retries, consent
gating, sensitive-field scrubbing and per-event idempotency.

> Alpha (`0.1.0-alpha.0`). Pin the exact version until 1.0.

## Install

```bash
npm install @olympuslabs/aether-server@0.1.0-alpha.0
```

Requires Node.js 18 or later.

## Quick start

```ts
import { AetherServerSDK } from '@olympuslabs/aether-server';

// Server-side only: the write key is a secret. Never ship it to a browser or app.
const aether = new AetherServerSDK({
  writeKey: process.env.AETHER_WRITE_KEY!,
  consent: { analytics: true },
  application: { name: 'checkout-api', environment: 'production' },
});

aether.track({
  type: 'order_completed',
  userId: 'usr_4f21a9',
  properties: { orderId: 'ord_1029', total: 49.0, currency: 'USD' },
});

// Flush buffered events before the process exits.
process.on('SIGTERM', async () => {
  await aether.shutdown();
  process.exit(0);
});
```

Each event gets a stable `id` (generated if you don't supply one). Retries reuse
it, so the backend de-duplicates instead of double-counting.

## Delivery

Events are buffered in memory and sent in batches (`flushAt`, default 100;
`flushInterval`, default 5000 ms). Call `await aether.flush()` at the end of
short-lived work (scripts, serverless handlers) and `await aether.shutdown()` on
process exit. Events still in memory when a process is killed are lost unless
durable mode is enabled; see the `durable` / `spoolPath` options in
[`src/types.ts`](src/types.ts).

## Consent

Purposes are the canonical set from `@olympuslabs/aether-shared/consent`.
Explicit-opt-in purposes (`credit`, `location`, `financial_activity`,
`economic_observability`, `cross_chain_observability`, `fraud_prevention`) are
never granted implicitly; set them only after you have collected that consent.

## License

Apache-2.0. See [LICENSE](LICENSE).
