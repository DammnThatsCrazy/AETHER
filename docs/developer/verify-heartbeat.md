---
title: Verify Heartbeat
slug: verify-heartbeat
section: quickstart
visibility: P
audience: [dev-junior, dev-senior]
status: experimental
since_version: "0.1.0"
---

# Verify Heartbeat

After sending your first event, verify that the SDK is correctly
communicating with the Aether ingestion endpoint.

## Check SDK Health

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

## Verify in Kyber

1. Open Kyber diagnostics.
2. Navigate to **SDK Health**.
3. Confirm your tenant shows a recent heartbeat.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `queue_depth` growing | Network issue or endpoint down | Check API key and endpoint URL |
| `ingestion_success_rate` < 1.0 | Schema validation failures | Check event types against registry |
| No heartbeat in Kyber | SDK not initialized | Verify `tenantId` and `apiKey` |

## Next Steps

Proceed to [Query the Graph](./query-the-graph.md) to see your
ingested data in the intelligence graph.
