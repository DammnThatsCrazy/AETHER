---
title: Communications Backfill & Replay Runbook
slug: comms/comms-backfill-runbook
section: operations
visibility: I
audience: [ops, dev-senior]
source_files:
  - Backend Architecture/aether-backend/services/integrations/connectors/klaviyo.py
  - Backend Architecture/aether-backend/services/comms/ingest.py
  - Backend Architecture/aether-backend/alembic/versions/20260703_comms_intelligence.py
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
   worker; journey rebuilds trigger from touchpoints as usual. For a large
   backfill, temporarily set `AETHER_COMMS_GRAPH_ENABLED=false` to defer
   graph emission, then re-enable and re-project.
5. **Progress/errors** — watch `comms_events_ingested_total`,
   `silver_projector_failures_total`, `comms_catalog_failures_total`, and
   the connector health card in Kyber → Measurement Operations.
6. **Cancel** — disable the connector (`PUT /v1/connectors/klaviyo`
   `{"enabled": false}`); the cursor persists, so re-enabling resumes.

## Replay (Bronze → Silver)

Bronze is durable before acknowledgement, so any Silver-side incident is
recoverable by replaying the Bronze range through the dispatcher:

```python
from services.silver.dispatcher import SilverDispatcher
from services.silver.writer import SilverFactWriter
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
from services.comms.state import CommunicationStateService
await CommunicationStateService().rebuild_for_entity(tenant_id, entity_id)
```

Run after identity merges/splits, consent changes, DSR erasure, or any
suspected drift. Rebuilds are idempotent.

## Rollback

- Feature flags off: `AETHER_COMMS_INGESTION_ENABLED=false` stops new comm
  projections immediately (Bronze keeps accepting for later replay).
- Migration rollback: `alembic downgrade 20260702_fraud_decisions` — drops
  only comms-added tables/columns (see the migration's `downgrade()`);
  pre-existing `silver_comms_facts` base columns are preserved.
