---
title: Query the Graph
slug: query-the-graph
section: developer
visibility: P
audience: [dev-junior, dev-senior]
status: experimental
since_version: 0.1.0
---

# Query the Graph

After events are ingested and projected into the intelligence graph,
you can query entity state through the API.

## Entity Lookup

```bash
curl -H "Authorization: Bearer $API_KEY" \
  https://api.aether.example/v1/entities/{entity_id}
```

## Graph Query

```bash
curl -H "Authorization: Bearer $API_KEY" \
  -d '{"entity_id": "...", "depth": 2}' \
  https://api.aether.example/v1/graph/query
```

## 360 Surface

360 surfaces provide productized views over graph state:

- **Profile 360**: entity attributes, activity timeline, value summary
- **Campaign 360**: campaign performance, touchpoints, attribution
- **Journey 360**: journey stage progression, touchpoint sequence

## SDK Query (Server)

```typescript
import { AetherServer } from '@aether/server';

const client = new AetherServer({ apiKey: 'your-api-key' });
const entity = await client.entities.get('entity-id');
```

## Next Steps

See [Tenant Setup](./tenant-setup.md) for configuring your tenant
environment.
