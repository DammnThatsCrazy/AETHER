# Ingestion Contract

One public SDK ingestion path. All four SDKs use it.

## Endpoint

```
POST {endpoint}/v1/batch
Authorization: Bearer {apiKey}
Content-Type: application/json
```

Default `endpoint` = `https://api.aether.io`.

## Request body

```ts
{
  batch: BaseEvent[];    // 1..500 events
  sentAt: string;        // ISO8601
  context?: { library: { name: string; version: string } }
}
```

`BaseEvent` is defined in `packages/shared/events.ts`:

```ts
interface BaseEvent {
  id: string;              // UUID (client-generated)
  type: EventType;         // from canonical enum
  timestamp: string;       // ISO8601 client clock
  sessionId: string;       // UUID per session
  anonymousId: string;     // UUID per install / browser
  userId?: string;         // after hydrateIdentity
  properties?: Record<string, unknown>;
  context: EventContext;   // library + page/device/campaign/consent/...
}
```

## Auth

Bearer token = `apiKey` from Aether dashboard. Rate-limited server-side via
token bucket (`aether:ratelimit:{api_key}`).

## Response body

```json
{
  "accepted": 2,
  "duplicates": 1,
  "rejected": 0,
  "events": [
    { "id": "client-event-id", "status": "accepted" },
    { "id": "client-event-id-2", "status": "duplicate" },
    { "id": "client-event-id-3", "status": "accepted" }
  ],
  "batchId": "server-batch-uuid",
  "receivedAt": "2024-06-01T12:00:01.000Z"
}
```

Statuses:
- `accepted` — event validated, written to Bronze, published to event bus.
- `duplicate` — same `(tenant_id, event_id, schema_version)` was already accepted. No double billing.
- `rejected` — event failed validation (unknown type, malformed payload, etc.). `reason` field explains why.

A single bad event does **not** fail the whole batch.

## Durability

The accepted path is:
1. Validate per-event
2. Check tenant-scoped idempotency in Redis (Postgres fallback on miss)
3. **Write to durable Bronze tier** (`bronze_sdk_events`)
4. Publish to Kafka `aether.sdk.events.validated`
5. Return `accepted`

If step 3 or 4 fails, the server returns 503 and the SDK retries. Bronze writes are idempotent — retries are safe.

## Idempotency

Key: `SHA256(tenant_id:event_id:schema_version)` — tenant-scoped so two tenants sending the same event_id are tracked independently. Dedup window: 24 hours.

## Backend routing

`POST /v1/batch` is implemented in:
```
Backend Architecture/aether-backend/services/ingestion/batch.py
```

From there events flow into Kafka (`aether.sdk.events.validated`) and into
Bronze/Silver/Gold lake tiers via ingestion workers.

## Deprecated aliases (server-to-server only, not for SDKs)

```
POST /v1/ingest/events        — deprecated single-event alias
POST /v1/ingest/events/batch  — deprecated batch alias
POST /v1/ingest/feed          — server-to-server external feed (requires external_id)
```

SDKs **must** use `/v1/batch`. These aliases are retained for internal tools only and are marked deprecated in the OpenAPI schema.

## Retries & offline

- Web: localStorage persistence up to 1000 events; 3x exponential backoff
  (1s → 2s → 4s, cap 30s).
- Native: in-memory queue with coroutine/async flush on lifecycle events.
- RN: delegates to native.

## Schema version

Every SDK sets `context.library.name = '@aether/{platform}'` and
`context.library.version = <semver>`. The contract schema version lives in
`packages/shared/schema-version.ts` and is bumped only on breaking changes.

## Cross-device journey continuity

Canonical journey lifecycle events are first-class `EventType` values and are accepted on
`POST /v1/batch`. The ingestion validator also accepts legacy `track` envelopes whose
`properties.event` is a journey lifecycle name and annotates them as normalized legacy
journey records.

Ingestion safeguards:

- Event IDs are used for idempotency/deduplication.
- Tenant/API-key scope is preserved before any stitching decision.
- Journey payload shape is validated (`confidence` is 0..1, handoff latency is
  non-negative, known journey fields have stable scalar/array types).
- Journey events remain subject to analytics consent by default; commerce/web3/agent
  payloads must continue to use their stricter canonical event families.
- SDKs continue to use `/v1/batch`; server-to-server ingestion endpoints are not an SDK
  transport path.

Backend stitching is transparent and conservative: `userId`, wallet, and email-hash
matches are strong signals; `anonymousId` is medium/high within the same install;
fingerprint, campaign/referrer, timestamp proximity, and behavior are support signals.
Fingerprint alone must never promote a sensitive identity link to high confidence.

## Post-ingestion identity resolution

After an event batch is written to Bronze (`bronze_sdk_events`) and published to
Kafka, `services/identity/resolver.py` processes each event asynchronously to
assign or update `canonical_entity_id`. This step is **not** part of the
synchronous `POST /v1/batch` response — ingestion and resolution are decoupled.

### Resolution pipeline

```
POST /v1/batch
  │
  ├─ validate → idempotency check → write Bronze → publish Kafka
  │                                                       │
  │   (synchronous; response returned here)              │
  │                                                       ▼
  │                                          identity resolver consumes
  │                                          aether.sdk.events.validated
  │                                                       │
  │                                          extract signals from event
  │                                                       │
  │                                          score signals → MergeDecision
  │                                                       │
  │                                          ┌────────────┴───────────────┐
  │                                          │                            │
  │                                       create /                  candidate →
  │                                       link /                    conflict queue
  │                                       merge
  │                                          │
  │                                   stamp canonical_entity_id
  │                                   on identity_subjects row
  └──────────────────────────────────────────┘
```

### What the ingestion layer stamps vs. what the resolver stamps

| Field | Stamped by ingestion | Stamped by resolver |
|-------|---------------------|--------------------:|
| `event_id` | Yes (from client) | — |
| `tenant_id` | Yes (from API key) | — |
| `received_at` | Yes | — |
| `batch_id` | Yes | — |
| `anonymous_id` | Yes (from event) | — |
| `user_id` | Yes (from event, if present) | — |
| `canonical_entity_id` | **Never** | Yes, after resolution |
| `confidence_tier` | — | Yes, on `identity_aliases` row |
| `merge_decision` | — | Yes, in audit log |

### `canonical_entity_id` contract for downstream consumers

- **Silver/Gold lake tiers**: `canonical_entity_id` is joined from
  `identity_subjects` during Silver promotion. Events that arrive before
  resolution is complete carry a null `canonical_entity_id` in Silver and are
  backfilled on the next recompute cycle.
- **Analytics queries**: always filter by `canonical_entity_id`, not
  `user_id` or `anonymous_id`, to get a deduplicated view of entity behavior.
- **Profile360 / graph services**: read `canonical_entity_id` from
  `identity_subjects` as the graph vertex key.
- **SDK**: never reads or emits `canonical_entity_id`. See
  [`SDK_SCOPE.md`](./SDK_SCOPE.md) for the full SDK boundary.

### Recompute

If resolution policy changes (e.g., a new signal type added, confidence
threshold updated), `POST /v1/identity/recompute` replays Bronze events for
an entity and re-stamps `canonical_entity_id` and `identity_aliases`. This is
an operator action; it does not re-invoke `POST /v1/batch`.
