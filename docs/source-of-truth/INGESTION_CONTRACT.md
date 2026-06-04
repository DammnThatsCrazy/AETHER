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

## Backend routing

The `/v1/batch` path is served by the **Data Lake ingestion service**
(`Data Lake Architecture/aether-Datalake-backend/services/ingestion/`).
From there events flow into Kafka (`aether.sdk.events.validated`) and into
Bronze/Silver/Gold lake tiers.

## Not for SDK use

The FastAPI path `POST /v1/ingest/events[/batch]` in
`Backend Architecture/aether-backend/services/ingestion/routes.py` is used
for **server-to-server connector ingestion only**. SDKs must not target it.

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
