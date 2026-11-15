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
  // order_completed requires the `commerce` purpose (see the event registry);
  // grant only purposes you have actually collected consent for.
  consent: { analytics: true, commerce: true },
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
`flushInterval`, default 5000 ms). Every event keeps its `id` across retries,
so a resend is de-duplicated by the backend rather than double-counted.

What survives a crash depends on where you run:

| Hosting model | Guarantee | Configure |
|---|---|---|
| Long-running Node server (VM, bare metal) | In-memory by default: events not yet sent are lost if the process dies. With a spool, they are replayed on the next start. | `spoolPath` on local disk that persists, e.g. `/var/lib/myapp/aether-spool.jsonl` |
| ECS / Fargate, Kubernetes | Container disk is discarded on restart, so a spool only helps on a mounted volume. | `spoolPath` on an EFS / persistent volume mount; call `await aether.shutdown()` on `SIGTERM` |
| AWS Lambda and other serverless | No durable local disk: the instance can be recycled at any time. The SDK warns if you configure a spool here. | Don't rely on a spool; `await aether.flush()` before each handler returns |
| Scripts, cron jobs | In-memory | `await aether.shutdown()` before exit |

```ts
const aether = new AetherServerSDK({
  writeKey: process.env.AETHER_WRITE_KEY!,
  spoolPath: '/mnt/aether/spool.jsonl', // enables the durable disk queue
  maxSpoolBytes: 5 * 1024 * 1024,       // default; new events are rejected (onSpoolDrop) past this
});
```

Setting `spoolPath` turns on the durable queue. `durable: true` without a
`spoolPath` throws: the SDK does not fall back to the OS temp directory,
because that directory is usually discarded on exactly the restarts a spool is
meant to survive.

## Consent

Purposes are the canonical set from `@olympuslabs/aether-shared/consent`.
Explicit-opt-in purposes (`credit`, `location`, `financial_activity`,
`economic_observability`, `cross_chain_observability`, `fraud_prevention`) are
never granted implicitly; set them only after you have collected that consent.

## License

Apache-2.0. See [LICENSE](LICENSE).
