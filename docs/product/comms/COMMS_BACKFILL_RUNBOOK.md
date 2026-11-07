---
title: Communications Backfill & Replay Runbook
slug: comms/comms-backfill-runbook
section: operations
visibility: I
audience: [ops, dev-senior]
status: experimental
since_version: 0.1.0
source_files: [services/api/connectors/integrations/connectors/klaviyo.py, services/api/journeys/comms/ingest.py, services/api/journeys/communication360/participant_writer.py, services/api/journeys/communication360/contracts.py, services/api/journeys/communication360/repository.py, services/api/alembic/versions/20260703_comms_intelligence.py, services/api/journeys/comms/repository.py, services/api/journeys/communication360/observations.py]
reviewed_source_commits:
  - commit: "3906b500a"
    reason: "Reviewed the 360 PR Communication360 repository diff: atomic participant-roster writes and bounded exact-reference reads are additive; provider backfill cursor, dedupe, and replay procedure are unchanged."
source_hashes:
  "services/api/alembic/versions/20260703_comms_intelligence.py": "sha256:651ee8f17a6e86e00d49d09cdbc0041d525682817851af1368576984c27fec76"
  "services/api/connectors/integrations/connectors/klaviyo.py": "sha256:4255adaf7e0669b8e7d75a632a331fd85ce16696ccfbc8511dba1c37d8539aea"
  "services/api/journeys/comms/ingest.py": "sha256:e5b199aaff506d136758b1a89c12a36c3622da3c224e5c39732cc4b428ed22a5"
  "services/api/journeys/comms/repository.py": "sha256:40708d0baed19cdaed65102938ab27af782859213cef991ca7b823eed941d028"
  "services/api/journeys/communication360/contracts.py": "sha256:f6f10414aec7e8659fbc6952b183cb0312b2eab43346e3373d940b20cd3bbf1a"
  "services/api/journeys/communication360/observations.py": "sha256:e564be344a2ee6380d8c79c1c9b89e8648b8bf3bd0e4c928108699172c90d0f8"
  "services/api/journeys/communication360/participant_writer.py": "sha256:26ebbb76e6c1dd928b4f047371e248e73f58892c6439954ed4c19a91dac6c142"
  "services/api/journeys/communication360/repository.py": "sha256:acd4fe9dd547ff1092511e4571910085494ba818c03d7d8efa2fe1576867b989"
---

# Communications Backfill & Replay Runbook

## Historical backfill (provider → facts)

1. **Preconditions** — connector configured and credentialed for the tenant;
   `AETHER_COMMS_INGESTION_ENABLED=true`; migration `20260703_comms_intel`
   applied (`alembic upgrade head`).
2. **Kick off** — `POST /v1/connectors/klaviyo/sync` with `since=<ISO8601>`
   (the connector pulls events, campaigns, flows, and profiles incrementally;
   event pagination is bounded to 25 pages per run and resumes from the
   persisted cursor on the next run — repeat until the run ingests 0 new
   events).
3. **Dedupe guarantee** — every fact is idempotent on
   `(tenant_id, idempotency_key)` where the key derives from
   `provider + provider_account + provider_event_id + event_type`; overlap
   between backfill and realtime webhooks is safe.
4. **Downstream** — comm state rebuilds are coalesced per entity by the
   worker; journey rebuilds trigger from touchpoints as usual. Graph emission
   has no switch of its own (an `AETHER_COMMS_GRAPH_ENABLED` setting used to be
   documented here; nothing read it). To relieve graph pressure during a large
   backfill, pause the backfill (step 6) and resume it later.
5. **Progress/errors** — watch `comms_events_ingested_total`,
   `silver_projector_failures_total`, `comms_catalog_failures_total`, and
   the connector health card in Kyber → Measurement Operations.
6. **Cancel** — disable the connector (`PUT /v1/connectors/klaviyo`
   `{"enabled": false}`); the cursor persists, so re-enabling resumes.

## Replay (Bronze → Silver)

Qualifying Silver writes now atomically persist a provider-thread observation
in `communication360_facts` with exact tenant/provider/account/thread/message
scope, Silver fact ID and evidence. On replay, observations derive from the
persisted first-write Silver row, never replacement source/account claims.
Replaying old Silver records can materialize these observations; records without
the required scope remain unlinked. A canonical observation failure rolls back
the PostgreSQL Silver write, so replay must retry both. This does not backfill
canonical Conversation membership or establish complete provider history.

Explicit `In-Reply-To` target and correlation-method metadata persist in the
Silver payload, separately from the reply's own provider message ID. Replay does
not infer missing references or account/thread scope in older records. Such
records remain unresolved in Communication360; cursor and dedupe procedures are
unchanged, and a resolved association does not prove complete provider history.

Bronze is durable before acknowledgement, so any Silver-side incident is
recoverable by replaying the Bronze range through the dispatcher:

```python
from ingestion.silver.dispatcher import SilverDispatcher
from ingestion.silver.writer import SilverFactWriter
# for each bronze payload in range:
outcome = await SilverDispatcher().project_with_outcome(envelope)
await SilverFactWriter().persist(outcome.results)
```

Replays create no duplicate facts, no duplicate canonical activity, and no
duplicate graph relationships (verified by
`tests/unit/comms/test_silver_multi_projector.py::TestReplaySafety`).

## State rebuilds

Communication state is a pure function of facts:

```python
from journeys.comms.state import CommunicationStateService
await CommunicationStateService().rebuild_for_entity(tenant_id, entity_id)
```

Run after identity merges/splits, consent changes, DSR erasure, or any
suspected drift. Rebuilds are idempotent.

When a connector-originated event is replayed, the server-owned identity and
consent bridge remains authoritative. Provider-supplied canonical entity IDs
and consent fields are not restored as authority; missing or non-matching
bindings remain unresolved or unknown after replay.

Typed participant-role rosters are currently accepted on
`POST /v1/comms/webhook` only when the tenant has a configured webhook secret
and the request HMAC verifies. Ingestion stores the signed assertion in Bronze,
then writes role facts only after every participant resolves through an exact
tenant/provider/account identity mapping. A Bronze-to-Silver replay does not
replace that identity-bound roster writer. If roster authoring fails after the
Bronze write, resolve the mapping issue and retry the same signed event; the
roster facts are idempotent. Explicit authenticated `membership` assertions now
atomically persist the canonical Conversation, exact provider/account/thread
membership and participant roles. Conflicting reassignment fails closed. Source
thread IDs alone and ordinary Silver replay do not create membership; older
events need an explicit signed membership assertion, not inferred links. Bounded
latest-roster evidence does not establish historical membership, complete
message coverage or freshness.

## Rollback

- Feature flags off: `AETHER_COMMS_INGESTION_ENABLED=false` stops new comm
  projections immediately (Bronze keeps accepting for later replay).
- Migration rollback: `alembic downgrade 20260702_fraud_decisions` — drops
  only comms-added tables/columns (see the migration's `downgrade()`);
  pre-existing `silver_comms_facts` base columns are preserved.
