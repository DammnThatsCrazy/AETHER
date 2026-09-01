---
title: Operational Intelligence — Stub vs. Production Audit
slug: operations/operational-intelligence-audit
section: operations
visibility: I
audience: [dev-senior, architect, ops]
status: stable
source_files:
  - Backend Architecture/aether-backend/services/investigation/routes.py
  - Backend Architecture/aether-backend/services/governance/routes.py
  - Backend Architecture/aether-backend/services/events/routes.py
  - Backend Architecture/aether-backend/services/events/worker.py
  - Backend Architecture/aether-backend/services/realtime/channel_hub.py
  - Backend Architecture/aether-backend/repositories/repos.py
  - Backend Architecture/aether-backend/shared/events/events.py
  - frontend/kyber/src/features/investigation/use-investigations.ts
  - frontend/kyber/src/features/governance/use-governance.ts
  - frontend/kyber/src/features/graph/use-graph-intelligence.ts
last_synced_commit: "a4276ce1"
reviewed_source_commits:
  - commit: "54eaac5d"
    reason: "Reviewed the staging first-admin bootstrap change; operational-intelligence findings remain unchanged."
---

# Operational Intelligence — Stub vs. Production Audit

**Scope:** PRs #107–#115 — operational intelligence services (investigation, governance, event
replay, realtime), shared contracts, and Kyber frontend hooks.

**Audit date:** 2026-05-17

---

## Section A — Confirmed Stubs (as of PR #115)

Each item below is a confirmed stub that was intentionally deferred or accidentally incomplete.
Items marked **FIXED** have been addressed in the commit that accompanies this document.

### A1. Event Replay Worker — No Republish (P0) — **FIXED**

| Field | Detail |
|---|---|
| **File** | `Backend Architecture/aether-backend/services/events/worker.py` |
| **Symptom** | `_process_job` incremented a counter for each matching envelope but never called `producer.publish()` |
| **Impact** | Replay jobs completed with `totalReplayed: N` but zero events reached the event bus; WebSocket clients on `tenant.events` received nothing |
| **Fix applied** | Worker now calls `await producer.publish(Event(topic=..., tenant_id=..., payload=...))` for each matching envelope. Dry-run jobs count but skip publish. Unknown Topic values are skipped with a warning. |

### A2. EventPipelineEnvelope Storage — Ephemeral In-Memory Dict (P0) — **FIXED**

| Field | Detail |
|---|---|
| **File** | `Backend Architecture/aether-backend/services/events/routes.py` |
| **Symptom** | `POST /v1/events/ingest` stored envelopes in `_EVENTS: dict[str, dict]` only; server restart lost all data; worker could only replay events ingested in the current process lifetime |
| **Fix applied** | `ingest_event` now calls `await _envelope_repo.create(envelope_dict)` before updating the hot cache. `EventEnvelopeRepository` added to `repos.py`, backed by PostgreSQL in staging/production and by the shared `_IN_MEMORY_STORES` dict in local/test. |

### A3. Investigation Status Machine — Unconstrained Transitions (P0) — **FIXED**

| Field | Detail |
|---|---|
| **File** | `Backend Architecture/aether-backend/services/investigation/routes.py` |
| **Symptom** | `PATCH /v1/investigations/{id}/status` accepted any `→ any` transition with comment `# any → any for MVP` |
| **Impact** | Closed cases could be re-opened; escalated cases could regress to open; compliance audit trail would be unreliable |
| **Fix applied** | `_VALID_TRANSITIONS` dict added; `transition_status` raises `HTTP 422` on invalid transitions. Valid graph: `open → {triage, active, escalated, closed}`, `triage → {active, escalated, closed}`, `active → {escalated, closed}`, `escalated → {closed}`, `closed → {}` (terminal). |

### A4. Governance Decision Engine — Default-Allow MVP (P1)

| Field | Detail |
|---|---|
| **File** | `Backend Architecture/aether-backend/services/governance/routes.py:86` |
| **Symptom** | `allowed = not bool(body.context.get("deny", False))` — always allows unless caller passes `{"deny": true}` in context |
| **Impact** | Frontend `useEvaluateGovernance()` returns decisions that appear authoritative but apply no real policies |
| **Status** | Deferred — requires a `PolicyRepository`, policy DSL, and an evaluation engine. Tracked as Phase 2. |
| **Interim mitigation** | Response payload includes `explanation.summary` that reads `"No explicit policies specified; default-allow applied."` — frontend should surface this string so operators know evaluation is not yet enforced. |

### A5. Realtime Channel Subscriptions — No Per-Channel Authorization (P1)

| Field | Detail |
|---|---|
| **File** | `Backend Architecture/aether-backend/services/realtime/routes.py` |
| **Symptom** | WebSocket `subscribe` action accepts any channel name without checking whether the authenticated entity holds a delegation that grants access |
| **Impact** | Tenant-scoped isolation is partially enforced (events are only fanned out to queues keyed by `(tenant_id, channel)`), but any authenticated user in that tenant can subscribe to any channel |
| **Status** | Deferred — requires delegation scope lookup at subscription time. Tracked as Phase 2. |

### A6. Realtime Subscriptions — No Cursor Resumption (P2)

| Field | Detail |
|---|---|
| **File** | `Backend Architecture/aether-backend/services/realtime/routes.py` |
| **Symptom** | Cursors are generated and sent to clients but the server does not store a rolling event window; reconnecting clients receive no missed events |
| **Status** | Deferred — requires a short-TTL event buffer (e.g., Redis sorted-set keyed by `(tenant_id, channel)`). Tracked as Phase 3. |

---

## Section B — Productized (Production-Ready)

| Component | File | Evidence of Production Readiness |
|---|---|---|
| **BaseRepository** | `repos.py:97+` | asyncpg connection pool, parameterized queries, UPSERT-on-conflict, full async |
| **InvestigationRepository** | `repos.py:1463` | PostgreSQL-backed create/list_by_tenant with tenant isolation |
| **GovernanceRepository** | `repos.py:1482` | PostgreSQL-backed; principal_id flat key for O(1) filtering |
| **EventReplayRepository** | `repos.py:1505` | PostgreSQL-backed; `list_queued` for worker polling |
| **EventEnvelopeRepository** | `repos.py:1519` | PostgreSQL-backed durable envelope storage with replayable filter |
| **EventProducer** | `shared/events/events.py:328` | AIOKafka with acks=all, retries=3, exponential backoff, DLQ; batch overflow falls back to individual publish; DLQ events include `original_payload` for replay |
| **EventConsumer** | `shared/events/events.py:438` | Concurrency-limited (semaphore=10), per-handler retry, dead-letter on exhaustion |
| **ChannelHub** | `services/realtime/channel_hub.py` | 54 topics → 9 named channels; monotonic cursor; lock-protected fanout; QueueFull logged |
| **Investigation Routes** | `services/investigation/routes.py` | Full CRUD + state machine + evidence + annotations; EventProducer wired |
| **Governance Routes** | `services/governance/routes.py` | Decision persistence + audit trail; EventProducer wired; principal_id filter fixed |
| **Event Replay Routes** | `services/events/routes.py` | Job CRUD; envelope durable ingest; EventProducer wired for submit/cancel |
| **Replay Worker** | `services/events/worker.py` | Polls queued jobs; filters envelopes from durable repo; republishes via producer; dry-run support |
| **Kyber investigation hooks** | `apps/kyber/src/features/investigation/` | useInvestigations, useInvestigation, useCreateInvestigation, useTransitionInvestigationStatus, useAddInvestigationEvidence, useAddInvestigationAnnotation — all wired to live endpoints |
| **Kyber governance hooks** | `apps/kyber/src/features/governance/` | useGovernanceDecisions, useGovernanceAudit, useEvaluateGovernance — all wired |
| **Kyber graph intelligence hooks** | `apps/kyber/src/features/graph/` | use-graph-intelligence.ts + use-entity-intelligence.ts — wired to /v1/graph/* |
| **Shared TS contracts** | `packages/shared/operational-intelligence.ts` | InvestigationCase, GovernanceDecision, ReplayJobResponse, RealtimeChannel — mirrors Pydantic models |
| **topics.json** | `docs/_generated/topics.json` | All 7 new operational intelligence topics present (101 total) |
| **PaymentIntentRepository** | `repos.py` | `record_intent`, `list_for_agent(agent_id, tenant_id)`, `find_for_tenant(intent_id, tenant_id)`, `update_status` — all tenant-scoped; in-memory locally, PostgreSQL in staging/production |
| **SettlementEventRepository** | `repos.py` | `record_event`, `list_for_agent(agent_id, tenant_id)`, `list_for_intent(intent_id, tenant_id)`, `mark_receipt_verified` — all tenant-scoped |
| **AgentEconomicIdentityRepository** | `repos.py` | `upsert_identity`, `find_for_agent(agent_id, tenant_id)` — tenant-scoped key: `{tenant_id}:{agent_id}:economic_identity` |
| **EconomicResourceRepository** | `repos.py` | `upsert_resource`, `list_for_tenant(tenant_id)` — tenant-isolated purchasable capabilities |
| **FacilitatorRepository** | `repos.py` | `upsert_facilitator`, `list_active(tenant_id)` — x402 facilitator/trust-broker registry |
| **X402LifecycleMapper** | `services/x402/lifecycle_mapper.py` | Routes 14 canonical x402 events to repositories; idempotent via event_id; full tenant isolation |
| **AgentLifecycleMapper** | `services/agent/lifecycle_mapper.py` | Routes 19 canonical agent lifecycle events to graph mutations + repos; all vertex IDs use `{tenant_id}:agent:{id}` format |
| **Four-layer graph coverage** | `/v1/graph/*` + `shared/graph-contract.ts` | All four interaction layers implemented: H2H (human↔human), H2A (human→agent), A2H (agent→human), A2A (agent↔agent). `classifyEdgeType` routes each edge type to its layer; `countEdgesByLayer` aggregates per-layer stats exposed via `/v1/graph/health`. |

---

## Section C — Missing Wiring / Gaps (Remaining After This Commit)

### C1. Governance — No Policy Engine (P1 — Phase 2)

The `evaluate_decision` endpoint applies a single hardcoded rule. A real policy engine requires:

1. **PolicyRepository** — new table `policies` with columns `(id, tenant_id, name, rules JSONB)`
2. **Policy evaluation** — iterate `body.policyIds`, load each policy, evaluate `rules` against `(principal, action, resource, context)`
3. **Obligations** — persist any `obligations` the matched policy produces
4. **Frontend** — `useEvaluateGovernance` needs a policy-selector input; the result card should show each policy's outcome, not a single allow/deny

**No changes to routes.py are needed yet** — the MVP default-allow behavior is safe; it fails open, which is acceptable while the policy store is being built.

### C2. Realtime — Channel Authorization (P1 — Phase 2)

At subscription time, the WebSocket handler should:

```python
# After authenticating the tenant:
active_scopes = await delegation_repo.scopes_for(tenant.entity_id)
if not all(ch in active_scopes for ch in sub.channels):
    await websocket.close(code=4403, reason="unauthorized_channel")
    return
```

This is safe to defer because tenant isolation already prevents cross-tenant leakage.

### C3. Replay Worker — Separate Container (P1 — Phase 2)

The worker currently runs as an asyncio task inside the main FastAPI process
(`main.py:189`). This means:

- Worker stops if the API process crashes
- No horizontal scaling of workers

**Phase 2 fix:** Extract to a standalone `worker.py` entrypoint, deploy as a separate
ECS task/Kubernetes Job, and use a SQS FIFO queue or Postgres advisory lock for
single-consumer semantics.

### C4. API Response Envelope Inconsistency (P1)

Investigation and governance endpoints return raw Pydantic models. Other platform
endpoints wrap in `APIResponse { data, status, timestamp }`. Until the investigation/
governance endpoints are updated, frontend callers must unwrap manually.

**Fix (in routes.py):** Wrap return values in `APIResponse(data=result)` and update
`response_model=APIResponse[InvestigationCase]`.

---

## Section D — Deployment / Compliance Gaps

### D1. Kafka Topic Configuration

New topics added in PR #115 (`aether.investigation.case.*`, `aether.governance.decision.*`,
`aether.event.replay.*`) must be pre-created in the Kafka broker before deploying to staging.

**Required topics and settings:**

| Topic | Partitions | Replication | Retention |
|---|---|---|---|
| `aether.investigation.case.created` | 3 | 2 | 7d |
| `aether.investigation.case.updated` | 3 | 2 | 7d |
| `aether.investigation.status.changed` | 3 | 2 | 7d |
| `aether.governance.decision.evaluated` | 3 | 2 | 30d |
| `aether.event.replay.submitted` | 1 | 2 | 3d |
| `aether.event.replay.completed` | 1 | 2 | 3d |
| `aether.event.replay.cancelled` | 1 | 2 | 3d |

**Action:** Add to the pre-deploy Kafka provisioning script before staging rollout.

### D2. Database Migrations

Three new tables are auto-created in local/test via the in-memory fallback, but PostgreSQL
requires explicit DDL for staging/production:

```sql
CREATE TABLE IF NOT EXISTS investigations (
    id TEXT PRIMARY KEY,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX investigations_tenant_idx ON investigations ((data->>'tenant_id'));
CREATE INDEX investigations_status_idx ON investigations ((data->>'status'));

CREATE TABLE IF NOT EXISTS governance_decisions (
    id TEXT PRIMARY KEY,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX governance_tenant_idx ON governance_decisions ((data->>'tenant_id'));
CREATE INDEX governance_principal_idx ON governance_decisions ((data->>'principal_id'));

CREATE TABLE IF NOT EXISTS event_replay_jobs (
    id TEXT PRIMARY KEY,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX replay_jobs_status_idx ON event_replay_jobs ((data->>'status'));
CREATE INDEX replay_jobs_tenant_idx ON event_replay_jobs ((data->>'tenant_id'));

CREATE TABLE IF NOT EXISTS event_envelopes (
    id TEXT PRIMARY KEY,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX envelopes_tenant_replay_idx ON event_envelopes ((data->>'tenantId'), (data->>'replayable'));
```

**Action:** Add these to the migration script before staging rollout.

### D3. Replay Worker Process

Add to `docker-compose.yml` and ECS task definitions:

```yaml
# docker-compose.yml addition
aether-replay-worker:
  build: ./Backend Architecture/aether-backend
  command: python -m services.events.worker_entrypoint
  environment:
    - AETHER_ENV=${AETHER_ENV}
    - DATABASE_URL=${DATABASE_URL}
    - KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS}
  depends_on: [aether-backend, kafka]
  restart: unless-stopped
```

---

## Section E — Remediation Implementation Status

| Item | Priority | Status |
|---|---|---|
| Replay worker calls `producer.publish()` | P0 | **Done** (this commit) |
| Envelope durable storage via `EventEnvelopeRepository` | P0 | **Done** (this commit) |
| Investigation state machine validation | P0 | **Done** (this commit) |
| `EventEnvelopeRepository` added to repos.py | P0 | **Done** (this commit) |
| Governance default-allow surfaced in explanation | P1 | Done (already in response payload) |
| Governance policy engine | P1 | Phase 2 — deferred |
| Realtime channel authorization | P1 | Phase 2 — deferred |
| Replay worker separate container | P1 | Phase 2 — deferred |
| API response envelope consistency | P1 | Phase 2 — deferred |
| Cursor-based realtime resumption | P2 | Phase 3 — deferred |
| Kafka topic pre-provisioning script | P0 (infra) | Pre-staging action required |
| Fraud network repositories added to repos.py | P1 | **Done** (PR #344) |
| Flow trace repositories added to repos.py | P1 | **Done** (PR #344) |
| Fraud network event topics added to events.py | P1 | **Done** (PR #344) |
| Investigation fraud-summary and report endpoints | P1 | **Done** (PR #344) |

### PR #344 Additions

PR #344 added the following operational artifacts that affect this audit scope:

**New Repositories** (`repositories/repos.py`): `FraudNetworkRepository`, `FraudNetworkMemberRepository`, `FraudNetworkEdgeRepository`, `FlowTraceRepository`, `FlowTracePathRepository`, `RiskOverlaySnapshotRepository` — all following the same `BaseRepository` ABC with in-memory/DynamoDB/Postgres backends.

**New Event Topics** (`shared/events/events.py`): `FRAUD_NETWORK_CREATED`, `FRAUD_NETWORK_UPDATED`, `FRAUD_NETWORK_REFRESHED`, `FRAUD_NETWORK_ESCALATED`, `FRAUD_NETWORK_SUPPRESSED`, `FLOW_TRACE_CREATED`, `FLOW_TRACE_COMPLETED`, `RISK_OVERLAY_GENERATED`.

**New Investigation Endpoints** (`services/investigation/routes.py`): Six new endpoints for attaching fraud networks and flow traces to investigation cases, retrieving fraud summaries, generating investigation reports, and exporting case bundles — all tenant-scoped, permission-gated, and using the existing state machine.
| PostgreSQL DDL migrations | P0 (infra) | Pre-staging action required |
