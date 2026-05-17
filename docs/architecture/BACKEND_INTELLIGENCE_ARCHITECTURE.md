# Aether Backend Intelligence Architecture Blueprint

This document is an additive architecture reference for evolving Aether and Kyber
into a production-grade operational intelligence infrastructure platform. It is
based on the current repository state and deliberately preserves existing
FastAPI routers, shared TypeScript contracts, SDK ingestion envelopes, graph
mutations, Docker Compose infrastructure, and SDK source-of-truth documents.

It intentionally lives outside `docs/source-of-truth/` because that directory is
reserved for SDK behavior derived from running code. This blueprint records the
backend target state and compatibility rules for phased implementation.

## 1. Current backend audit

### Existing stable assets to preserve

| Area | Existing implementation | Preservation rule |
|---|---|---|
| Unified API | Python/FastAPI application in `Backend Architecture/aether-backend/main.py` mounts ingestion, lake, intelligence, identity, profile, population, behavioral, RWA, Web3, cross-domain, fraud, attribution, agent, diagnostics, provider, admin, and realtime routers. | Keep `/v1/*` compatibility. Add intelligence APIs as new routers or additive paths, not destructive rewrites. |
| SDK contracts | `packages/shared` exports canonical events, entities, consent, wallets, provenance, graph relationships, economic, and Profile 360 contracts. | Treat as frontend/backend source of truth. Extend with additive exported contracts only. |
| Event ingestion | Source-of-truth docs define `POST /v1/batch`, event registry, consent gating, and event-to-graph alignment. | Preserve event names and payload shape. New intelligence events must wrap or derive from existing events. |
| Graph layer | `shared/graph/graph.py` already models users, sessions, devices, identity clusters, wallets, agents, contracts, protocols, Profile 360 entities, Web3 coverage, cross-domain financial objects, and commerce control-plane vertices. | Keep vertex and edge names stable. Add new labels only when existing labels cannot represent the concept. |
| Data lake | Lake services provide raw/bronze-style ingestion, features, drift monitoring, model registry, and graph mutations. | Preserve bronze immutability and use silver/gold projections for intelligence products. |
| Journey service | `Backend Architecture/services/journey-service` contains journey FSM, causality, processor, and snapshot writer with Postgres, Redis, Kafka, and ClickHouse integration. | Promote as the bounded service for temporal replay and journey reconstruction. |
| Infrastructure | Root Docker Compose already includes PostgreSQL, Redis, Kafka/Zookeeper, ClickHouse, backend, ML serving, journey service, Kyber, and Prometheus. | Extend compose with optional graph/search/vector/object services behind profiles; do not break default local path. |
| Compliance and governance | GDPR/SOC2 package, consent routers, audit routes, admin routes, feature gates, JWT/API-key dependencies, and billing/quota logic exist. | Centralize policy enforcement but keep existing middleware and admin APIs. |
| ML/agent systems | ML model server, agent layer, agent routers, scoring routes, guardrail diagnostics, and provider gateway exist. | Use these as engines behind typed intelligence APIs. |

### Architectural gaps

1. **Explicit contract layer:** current APIs are broad but not fully normalized
   around pagination, filtering, query consistency, graph payloads, realtime
   channels, investigation payloads, and governance decisions.
2. **Service catalog:** there are many routers and side services, but no durable
   capability map showing ownership, storage, event topics, and frontend
   contracts for each intelligence engine.
3. **Graph-native query plane:** existing graph mutations and vertex enums are
   strong foundations, but traversal, shortest path, temporal graph, overlays,
   and explainability APIs need standardized contracts.
4. **Realtime intelligence:** websocket infrastructure exists, but channel names,
   subscription filters, cursors, replay semantics, and message envelopes need a
   stable frontend-safe protocol.
5. **Investigation workspace:** evidence, annotations, saved graph states,
   escalation, collaborative workflow, and case lifecycle should become a first
   class bounded context.
6. **Governance plane:** consent and audit exist; RBAC, ABAC, policy decisions,
   tenant isolation, explainability obligations, retention, and sovereign/air-gap
   deployment modes need a unified policy architecture.
7. **Schema versioning:** shared event contracts exist, but operational
   intelligence schemas need explicit version fields, migration rules, and
   compatibility guarantees.
8. **Generated SDK/API specs:** OpenAPI should be exported from FastAPI and used
   with the shared TypeScript contracts to generate frontend clients.
9. **Observability and SLOs:** diagnostics and Prometheus exist; each engine needs
   RED/USE metrics, tracing spans, lag dashboards, data quality metrics, and
   alert runbooks.
10. **Multi-store topology:** Postgres, Redis, Kafka, and ClickHouse exist;
    optional Memgraph/Neo4j/OpenSearch/object/vector stores should be added as
    profiles with clearly assigned workloads.

## 2. Target platform shape

Aether should remain a modular monorepo with four planes:

```text
SDKs + Kyber
  -> API Gateway / FastAPI routers / generated SDKs
  -> Intelligence engines and bounded services
  -> Event backbone + graph/data/search stores
  -> Governance, observability, deployment, and CI/CD control planes
```

### Design principles

- **Additive compatibility:** new APIs use `/v1/intelligence/*`, `/v1/graph/*`,
  `/v1/investigations/*`, `/v1/governance/*`, or engine-specific additive paths.
- **Canonical IDs:** every API accepts `tenantId`, optional `orgId`, and
  `EntityRef { kind, id }` where possible.
- **Immutable facts, mutable projections:** raw events and evidence are immutable;
  profiles, scores, clusters, and graph overlays are projections.
- **Graph-native core:** relationships, journeys, attribution paths, clusters,
  governance decisions, and investigations reference graph nodes and edges.
- **Realtime by default:** every material projection emits a cursor-addressable
  realtime event that can be replayed from Kafka/ClickHouse/object storage.
- **Explainable intelligence:** every score or automated decision carries
  evidence references, lineage, model refs, and policy refs.
- **Tenant isolation:** tenant ID is included in API auth context, event topics,
  storage partition keys, graph labels/properties, cache keys, and object paths.

## 3. Service boundaries

| Bounded service | Owns | Storage | Emits | Primary APIs |
|---|---|---|---|---|
| API Gateway | Auth, CORS, rate limit, request IDs, OpenAPI, SDK generation. | Redis for limits; Postgres for keys/tenants. | `governance.policy.evaluated`, audit events. | `/v1/health`, `/v1/admin/*`, `/v1/providers/*`. |
| Event Pipeline | Ingestion, validation, normalization, sequencing, enrichment, replay. | Kafka, ClickHouse, object storage, Postgres metadata. | normalized SDK events and `graph.mutated`. | `/v1/ingest/*`, `/v1/events/*`, `/v1/replay/*`. |
| Entity Resolution Engine | Identity stitching, profiles, dedupe, trust/confidence. | Postgres canonical table, graph identity edges, Redis cache. | `entity.updated`, `entity.relationship.changed`. | `/v1/entities/*`, `/v1/identity/*`, `/v1/profile/*`. |
| Graph Engine | Traversal, shortest paths, neighborhoods, temporal reconstruction, overlays. | Neptune now; optional Memgraph/Neo4j profile; ClickHouse snapshots. | `graph.mutated`. | `/v1/graph/traverse`, `/v1/graph/path`, `/v1/graph/temporal`. |
| Relationship Engine | Relationship scoring, continuity, relationship evidence. | Graph edges, Postgres relationship facts, ClickHouse features. | `entity.relationship.changed`, `score.updated`. | `/v1/entities/{id}/relationships`. |
| Journey Engine | Multi-actor journeys, FSM, causality, replay, snapshots. | Existing journey service Postgres/Redis/Kafka/ClickHouse. | `journey.updated`. | `/v1/entities/{id}/journeys`, `/v1/journeys/*`. |
| Cluster Engine | Deterministic groups, emergent clusters, wallet/fraud/geo/economic clusters. | ClickHouse features, graph cluster nodes, Postgres metadata. | `cluster.updated`, `score.updated`. | `/v1/groups/*`, `/v1/clusters/*`. |
| Attribution Engine | Lineage, touchpoints, causal paths, campaign and operational attribution. | ClickHouse paths, Postgres model runs, graph attribution edges. | attribution events and scores. | `/v1/attribution/*`. |
| Realtime Intelligence Engine | WebSocket subscriptions, cursor resume, fanout, replay. | Redis pub/sub/streams, Kafka, ClickHouse cursors. | WebSocket messages. | `/v1/realtime/ws`, existing realtime router. |
| Device Intelligence Engine | Device profiles, fingerprints, fraud/device continuity. | Postgres, Redis, graph device nodes. | `entity.updated`, `score.updated`. | `/v1/entities/{id}/devices`. |
| Geographic Intelligence Engine | Location profiles, geo clusters, movement anomalies. | PostGIS extension on Postgres, ClickHouse aggregates, graph locations. | `cluster.updated`, `score.updated`. | `/v1/entities/{id}/geography`, `/v1/clusters/geographic`. |
| Economic Intelligence Engine | Economic profiles, payments, subscriptions, stablecoin and resource flows. | Postgres commerce, graph economic nodes, ClickHouse aggregates. | `score.updated`, `graph.mutated`. | `/v1/entities/{id}/economics`. |
| Web3 Intelligence Engine | Wallets, chains, token analysis, bridge activity, contracts, DAO participation. | Existing Web3 routes/services, graph Web3 nodes, ClickHouse transactions. | `web3.wallet.updated`, `graph.mutated`. | `/v1/web3/*`. |
| Agent Intelligence Engine | Agents, delegated action, coordination, guardrails, teams. | Agent layer queues, Postgres, graph agent edges. | `agent.coordination.updated`, governance decisions. | `/v1/agent/*`. |
| Investigation Engine | Cases, evidence, annotations, saved graph states, collaboration. | Postgres cases, object storage attachments, graph case links. | `investigation.updated`, audit. | `/v1/investigations/*`. |
| Governance Engine | RBAC, ABAC, policy enforcement, audit, consent, retention, tenant isolation. | Postgres policy/audit, object retention manifests. | `governance.policy.evaluated`. | `/v1/governance/*`, existing consent/admin/audit. |
| Alerting Engine | Anomaly/risk/trust thresholds, notification routing, escalations. | Postgres rules, Redis state, Kafka topics. | `alert.created`. | `/v1/alerts/*`, existing notification routes. |

## 4. Data model architecture

### Canonical relational tables

Use Postgres for canonical operational state and metadata:

- `tenants`, `organizations`, `api_keys`, `users`, `service_accounts`
- `entity_registry(entity_id, tenant_id, kind, external_refs, status, created_at, updated_at)`
- `entity_profiles(entity_id, tenant_id, dimensions_json, scores_json, evidence_json, version)`
- `relationship_facts(id, tenant_id, source_entity_id, target_entity_id, type, valid_from, valid_to, confidence, evidence_json)`
- `journeys(id, tenant_id, primary_entity_id, state, started_at, updated_at, completed_at)`
- `clusters(id, tenant_id, type, label, parameters_json, score_json, version)`
- `cluster_members(cluster_id, entity_id, membership_score, valid_from, valid_to)`
- `investigations(id, tenant_id, title, status, created_by, graph_state_id, created_at, updated_at)`
- `investigation_evidence(investigation_id, evidence_ref_json, added_by, created_at)`
- `investigation_annotations(id, investigation_id, author_id, body, refs_json, created_at)`
- `governance_policies(id, tenant_id, type, body_json, status, version)`
- `governance_decisions(id, tenant_id, principal_ref_json, action, resource_ref_json, allowed, policies_json, explanation_json, evaluated_at)`
- `retention_manifests(id, tenant_id, object_uri, policy_id, expires_at, hold_reason)`
- `schema_versions(schema_name, version, compatibility, activated_at)`

### Analytical facts

Use ClickHouse for append-only, high-volume queries:

- `events_raw` and `events_normalized`
- `entity_timeline`
- `relationship_observations`
- `journey_steps`
- `attribution_touchpoints`
- `score_timeseries`
- `web3_transactions`
- `device_observations`
- `geo_observations`
- `agent_actions`
- `policy_decision_log`

### Object storage

Use S3-compatible storage for immutable evidence, replay bundles, model
artifacts, graph snapshots, investigation attachments, and sovereign export
bundles. Path convention:

```text
s3://aether-{env}/{tenant_id}/{domain}/{yyyy}/{mm}/{dd}/{object_id}.jsonl|parquet|bin
```

### Search and vector stores

- OpenSearch: investigation evidence search, logs, entity text search, alert
  search.
- Vector DB: optional embeddings for entity similarity, evidence retrieval,
  natural-language investigation search, and agent memory. Keep vector IDs tied
  to `EvidenceRef` or `EntityRef`; never store policy-unsafe raw data without a
  retention manifest.

## 5. Graph schema architecture

Reuse existing graph labels from `shared/graph/graph.py` and map user-requested
entity types as follows:

| Requested concept | Existing/preferred graph label |
|---|---|
| Individuals | `User` plus additive `Entity` abstraction. |
| Organizations | `Organization`, `Company`, `LegalEntity`, or `Org` API entity ref. |
| Agents | `Agent`, `AgentEconomicIdentity`, `AgentProfile360`. |
| Devices | `Device`, `DeviceFingerprint`, `IPAddress`. |
| Wallets | `Wallet`, `Chain`, `Token`, `Contract`, `Protocol`. |
| Sessions | `Session`. |
| Events | `Event`, `ActionRecord`, `BusinessEvent`. |
| Relationships | Existing edge labels plus scored relationship facts. |
| Clusters | `IdentityCluster` and additive cluster projection nodes. |
| Journeys | Journey service IDs linked to `ActionRecord`/`Event` nodes. |
| Locations | `Location`. |
| Economic profiles | `Payment`, `PaymentIntent`, `SettlementEvent`, `EconomicResource`, `StablecoinAsset`. |
| Behavioral profiles | `ActionRecord`, `Event`, Profile 360 behavior projections. |
| Attribution paths | `ATTRIBUTED_TO` edges and attribution path projections. |
| Infrastructure systems | `Service`, `App`, `FrontendDomain`, `ContractSystem`. |

### Required edge semantics

Each edge should support these optional properties:

- `tenant_id`, `org_id`
- `valid_from`, `valid_to`, `observed_at`
- `confidence_score`, `trust_score`, `risk_score`, `relationship_score`
- `source`, `evidence_refs`, `lineage_event_ids`
- `policy_scope`, `retention_class`

### Graph APIs

- `POST /v1/graph/traverse` — bounded neighborhood discovery.
- `POST /v1/graph/path` — shortest or scored paths between entities.
- `POST /v1/graph/temporal` — graph reconstruction as of a timestamp.
- `POST /v1/graph/overlay` — apply risk, trust, attribution, wallet, geo, or
  investigation overlays.
- `POST /v1/graph/filter` — graph filtering for Kyber workspace queries.

The TypeScript payloads are defined in
`packages/shared/operational-intelligence.ts` and should be mirrored by FastAPI
Pydantic models before enabling routes.

## 6. Event schemas and pipeline

### Event envelope

All derived operational events should use the stable envelope:

```ts
EventPipelineEnvelope<TPayload> {
  id, type, tenantId, orgId?, occurredAt, ingestedAt,
  schemaVersion, source, subject?, correlationId?, causationId?,
  replayable, payload
}
```

### Kafka topic convention

```text
aether.{env}.{tenant_scope}.{domain}.{event_name}.v{major}
```

Examples:

- `aether.prod.shared.ingest.sdk_event.v1`
- `aether.prod.tenant_123.graph.mutated.v1`
- `aether.prod.tenant_123.entity.updated.v1`
- `aether.prod.tenant_123.investigation.updated.v1`

### Pipeline stages

1. **Ingest:** validate SDK event registry, consent, tenant API key, idempotency.
2. **Normalize:** attach schema version, tenant, source, actor, sequence, and
   privacy classification.
3. **Enrich:** resolve entity refs, device, geo, wallet, provider, economic, and
   campaign metadata.
4. **Persist bronze:** append immutable raw event/object.
5. **Project silver:** entity timeline, journey steps, relationship observations,
   transaction facts.
6. **Mutate graph:** idempotent vertex/edge upserts with evidence refs.
7. **Score gold:** anomaly, confidence, trust, risk, relationship, attribution,
   cluster, and operational scores.
8. **Fanout realtime:** websocket cursor events and alert/escalation triggers.
9. **Replay:** rebuild silver/gold projections from bronze with schema adapters.

## 7. API and frontend integration contracts

### API standards

- **Authentication:** `Authorization: Bearer`, `X-API-Key`, or service account
  token. Tenant is derived from auth and must match request body when present.
- **Request IDs:** require/emit `X-Request-ID` for every API and websocket ack.
- **Pagination:** cursor-based `PageRequest` and `PaginatedResponse<T>`.
- **Filtering:** standardized `TimeRangeFilter`, `GraphQueryFilter`, score
  ranges, dimensions, and entity refs.
- **Consistency:** frontend can request `cache`, `read_your_writes`, or `strong`.
- **Errors:** normalized `ApiErrorBody` with `code`, `message`, `requestId`,
  optional details, and retryability.
- **Caching:** ETag and `Cache-Control` for profile/graph snapshots; Redis
  entity-profile cache keyed by `tenant:{tenantId}:entity:{kind}:{id}:v{schema}`.

### Endpoint families

| Family | Contract |
|---|---|
| Entity profiles | `GET/POST /v1/entities/profile`, dimensions selector, scores, evidence. |
| Entity relationships | `POST /v1/entities/relationships/query`, scored edges. |
| Entity timelines | `POST /v1/entities/timeline/query`, cursor timeline. |
| Entity journeys | `POST /v1/entities/journeys/query`, journey summaries and replay refs. |
| Entity devices/wallets/economics/geography/behavior/governance | dimension-specific projections under `/v1/entities/{kind}/{id}/{dimension}`. |
| Groups | `/v1/groups/deterministic`, `/v1/groups/segments`, `/v1/groups/analytics`, `/v1/groups/journeys`. |
| Clusters | `/v1/clusters/{type}`, `/v1/clusters/{id}/members`, `/v1/clusters/{id}/graph`. |
| Graph | traversal, path, neighborhood, temporal, overlays, filtering. |
| Events | ingest, replay, normalize, sequence, enrich, attribution lineage. |
| Web3 | wallet intelligence, chain indexing, token analysis, bridge activity, stablecoin analysis, NFT/contract/DAO relationships. |
| Investigations | create cases, evidence, annotations, graph states, collaboration, escalation. |
| Governance | RBAC/ABAC policies, audit logs, consent, retention, tenant isolation, explainability, policy decisions. |

### SDK generation

1. Generate OpenAPI JSON from FastAPI in CI.
2. Validate OpenAPI routes against `packages/shared/operational-intelligence.ts`.
3. Generate TypeScript clients for Kyber into `docs/_generated` or a future
   `packages/api-client` workspace.
4. Keep shared contracts as hand-authored source-of-truth types for frontend
   safety and SDK parity.

## 8. Realtime architecture

Use existing realtime router as the compatibility mount and standardize the
protocol around these channels:

- `tenant.events`
- `tenant.graph`
- `tenant.alerts`
- `entity.profile`
- `entity.relationships`
- `journey.timeline`
- `cluster.membership`
- `investigation.workspace`
- `governance.audit`
- `agent.coordination`
- `web3.wallets`

### WebSocket message flow

1. Client connects to `/v1/realtime/ws` with auth.
2. Client sends `RealtimeSubscribeMessage` with channels, filters, tenant, and
   optional cursor.
3. Server returns `RealtimeAckMessage`.
4. Server streams `RealtimeEventMessage` envelopes with monotonically resumable
   cursors.
5. Server emits heartbeat every 25-30 seconds.
6. Client can unsubscribe or reconnect with last cursor.

## 9. Investigation architecture

Investigation cases are graph-native workspaces:

- Case subjects are `EntityRef[]`.
- Evidence is a list of `EvidenceRef` entries that may point to events,
  relationships, transactions, model outputs, documents, or annotations.
- Saved graph states store node/edge IDs, overlay IDs, viewport metadata, query
  filters, and schema version.
- Escalations are governance-audited workflow transitions.
- Collaboration events publish to `investigation.workspace`.
- Evidence search uses OpenSearch and optional vector retrieval, always returning
  evidence refs rather than unbounded raw payloads.

## 10. Governance architecture

The governance engine should centralize:

- RBAC roles and grants.
- ABAC policies over tenant, org, purpose, actor kind, data classification,
  geography, consent, resource, action, and environment.
- Consent purpose enforcement from the existing consent model.
- Policy decision records with `GovernanceDecision` contracts.
- Audit log append-only writes to Postgres and ClickHouse.
- Retention manifests for events, evidence, snapshots, and exports.
- Explainability obligations for every score, alert, investigation escalation,
  or automated action.
- Sovereign mode configuration: disable external providers, pin object storage,
  use tenant-local keys, and support air-gapped model artifacts.

## 11. Deployment and local development architecture

### Local development

Keep the current root compose as the default runnable stack:

- PostgreSQL for canonical state.
- Redis for cache, rate limit, quota, websocket fanout.
- Kafka/Zookeeper for event backbone.
- ClickHouse for analytical event queries.
- FastAPI backend.
- Journey service.
- ML serving.
- Kyber.
- Prometheus.

Add optional compose profiles later:

- `graph`: Memgraph or Neo4j for local graph-native dev when Neptune is not
  available.
- `search`: OpenSearch Dashboards and OpenSearch.
- `object`: MinIO for S3-compatible evidence and replay bundles.
- `vector`: pgvector, Qdrant, or Milvus.
- `observability`: Grafana, Tempo, Loki, OpenTelemetry collector.

### Enterprise and sovereign deployments

- Kubernetes with Helm/Kustomize or Terraform modules.
- Separate control plane and data plane namespaces.
- Tenant-level encryption keys and object prefixes.
- PrivateLink/VPC endpoints for storage and providers.
- Optional external provider gateway disabled by policy.
- Air-gapped artifact registry and model registry.
- Disaster recovery with object-store replay and Postgres/ClickHouse backups.

## 12. Observability architecture

Every service and engine should emit:

- RED metrics: request rate, errors, latency.
- USE metrics: utilization, saturation, errors for stores and queues.
- Kafka consumer lag, replay lag, websocket subscriber counts, dropped messages.
- Data quality: validation rejects, schema-version distribution, enrichment
  coverage, graph mutation success, score freshness.
- Business/intelligence: entities updated, relationships scored, journeys
  reconstructed, clusters changed, alerts created, policies denied.
- Tracing spans: `ingest -> normalize -> enrich -> persist -> graph -> score -> realtime`.
- Structured logs with request ID, tenant ID, event ID, correlation ID, policy ID.

## 13. Testing architecture

- **Contract tests:** shared TypeScript types compile, OpenAPI compatibility,
  websocket message fixtures.
- **Unit tests:** engine scoring, graph query builders, policy evaluation,
  journey FSM, attribution models.
- **Integration tests:** FastAPI routers with Postgres/Redis/Kafka/ClickHouse
  test containers or compose profile.
- **Replay tests:** rebuild projections from golden bronze event bundles.
- **Graph tests:** mutation idempotency, traversal filters, temporal snapshots.
- **Governance tests:** RBAC/ABAC denies, consent purpose gating, retention
  policies, tenant isolation.
- **Load tests:** ingestion throughput, websocket fanout, graph traversal P95,
  ClickHouse query latency.
- **Security tests:** auth bypass, tenant boundary checks, provider BYOK, audit
  integrity, model extraction defenses.

## 14. CI/CD architecture

Pipeline stages:

1. Format/lint/typecheck Python and TypeScript.
2. Unit tests for shared packages, backend routers, journey service, ML and agent
   modules.
3. Generate and diff OpenAPI.
4. Run contract compatibility checks for shared TS contracts and OpenAPI.
5. Build Docker images for backend, journey service, ML serving, Kyber.
6. Run migration dry-runs and schema-version checks.
7. Run integration smoke stack with compose.
8. Produce SBOM, vulnerability scan, and signed images.
9. Deploy staging with canary and automatic rollback on SLO/error budget breach.
10. Promote production with migration gates, replay checkpoint, and governance
    approval.

## 15. Incremental implementation roadmap

### Phase 0 — preserve and codify

- Keep current routers and infrastructure intact.
- Export shared operational intelligence TypeScript contracts.
- Add Pydantic mirrors for the shared contracts.
- Export OpenAPI in CI and publish generated SDK artifacts.

### Phase 1 — graph and entity query plane

- Add `/v1/graph/*` router over existing graph client.
- Add entity profile/timeline/relationship query contracts.
- Cache profile and graph snapshots by tenant/entity/schema version.
- Emit standardized realtime messages for profile and graph updates.

### Phase 2 — event replay and temporal intelligence

- Standardize `EventPipelineEnvelope` in backend models.
- Add replay APIs and ClickHouse cursor checkpoints.
- Promote journey service replay/snapshot outputs into entity journey APIs.

### Phase 3 — investigations and governance

- Add investigation service tables and router.
- Add governance policy decision API and audit sink.
- Require explainability metadata on alerts, scores, and investigation
  escalations.

### Phase 4 — enterprise deployments

- Add compose profiles and Kubernetes deployment modules.
- Add tenant isolation test suite.
- Add sovereign/air-gapped mode config profile.
- Add OpenSearch/object/vector profiles when required by customers.

## 16. Compatibility contract

- Do not rename existing SDK `EventType` values.
- Do not remove existing `EntityKind` values.
- Do not change `BaseEvent` required fields.
- Do not remove existing `/v1/*` routers; deprecate with documented replacement
  only after frontend clients migrate.
- Add graph labels and edge properties without changing existing labels.
- Store new intelligence artifacts as projections with schema versions.
- Any breaking contract requires a new major schema version and replay adapter.
