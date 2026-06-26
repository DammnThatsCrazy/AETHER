---
title: Universal Intelligence Graph Contract
slug: source-of-truth/universal-graph-contract
section: source-of-truth
visibility: internal
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.10.0"
source_files:
  - packages/shared/graph-contract.ts
  - Backend Architecture/aether-backend/shared/graph/graph_contract.py
  - Backend Architecture/aether-backend/services/operational_intelligence/models.py
canonical_owner: graph@aether
last_synced_commit: fae02a9
---
# Universal Intelligence Graph Contract

Authoritative reference for all universal graph envelopes, node types, edge types, filter language, and query API shapes introduced in the Universal Intelligence Graph (v8.10.0). This supplements `GRAPH_CONTRACT.md` (four-layer relationship contract).

---

## Universal Envelopes

Every graph vertex and edge carries typed envelope sub-objects. These are standardized across all node types and relationship layers.

### TemporalEnvelope

Bitemporal semantics: valid-time (when the fact was true in the world) and system-time (when Aether recorded it).

| Field | Type | Description |
|-------|------|-------------|
| `event_time` | string (ISO 8601) | When the event occurred externally |
| `observed_time` | string | When Aether received/observed it |
| `ingestion_time` | string? | When it entered the pipeline |
| `processed_time` | string? | When it completed processing |
| `first_seen` | string | Earliest known timestamp |
| `last_seen` | string | Most recent timestamp |
| `valid_from` | string? | Bitemporal valid-time start |
| `valid_to` | string? | Bitemporal valid-time end (null = open) |
| `recorded_at` | string? | System-time when recorded |
| `superseded_at` | string? | System-time when superseded by newer version |
| `age_days` | number? | Days since first_seen |
| `recency_score` | number? | 0–1 recency score |
| `lifecycle_state` | LifecycleState | Current lifecycle state |

### ProvenanceEnvelope

Tracks the origin, collection method, and quality of a fact.

| Field | Type | Description |
|-------|------|-------------|
| `source_system` | string? | Source system identifier |
| `source_connector` | string? | Connector type (sdk/webhook/batch/api) |
| `collection_method` | string? | How it was collected |
| `processing_pipeline` | string? | Pipeline that processed it |
| `graph_projector` | string? | Service that wrote the graph node |
| `schema_version` | string? | Schema version at write time |
| `model_id` | string? | ML model that produced this (if derived) |
| `model_version` | string? | ML model version |
| `freshness_seconds` | number? | Seconds since last update |
| `quality_score` | number? | 0–1 data quality score |
| `evidence_refs` | string[] | References to supporting evidence |
| `correlation_id` | string? | Distributed trace correlation |
| `idempotency_key` | string? | Write idempotency key |
| `observation_class` | ObservationClass | How this fact was established |

### RiskEnvelope

| Field | Type | Description |
|-------|------|-------------|
| `risk_score` | number | 0–100 risk score |
| `risk_type` | string? | Category of risk |
| `severity` | 'low'\|'medium'\|'high'\|'critical'? | |
| `confidence` | number | 0–1 confidence in score |
| `reason_codes` | string[] | Machine-readable reason codes |
| `evidence_refs` | string[] | Evidence supporting the score |
| `alert_state` | string? | open/investigating/resolved/dismissed |
| `investigation_state` | string? | |
| `disposition` | string? | Outcome disposition |

### EconomicEnvelope

| Field | Type | Description |
|-------|------|-------------|
| `amount` | number? | Transaction amount |
| `currency` | string? | ISO 4217 currency code |
| `direction` | 'inflow'\|'outflow'\|'internal'? | |
| `rail` | Rail? | Payment rail (card/ach/wire/crypto/x402) |
| `revenue` | number? | Revenue attributed to this entity |
| `cost` | number? | Cost attributed |
| `value` | number? | Computed value |
| `margin` | number? | Margin (revenue − cost) |
| `counterparty_id` | string? | Counterparty entity ID |
| `economic_role` | string? | Role in economic interaction |
| `attribution_share` | number? | 0–1 share of attribution |
| `value_confidence` | number? | 0–1 confidence in value |
| `currency_normalized_to` | string? | If normalized, target currency |
| `fx_rate` | number? | FX rate applied for normalization |

### GovernanceEnvelope

| Field | Type | Description |
|-------|------|-------------|
| `tenant_id` | string | Owning tenant (required) |
| `consent_purpose` | ConsentPurpose? | analytics/marketing/web3/agent/commerce |
| `consent_state` | string? | granted/withdrawn/expired/not_required |
| `authorization_source` | string? | |
| `authorization_scope` | string[]? | |
| `jurisdiction` | string? | ISO 3166 jurisdiction code |
| `retention_days` | number? | |
| `redacted` | boolean? | True if redacted for DSR |
| `activation_eligible` | boolean? | False when consent_state=withdrawn |
| `policy_version` | string? | |

### IdentityEnvelope

| Field | Type | Description |
|-------|------|-------------|
| `canonical_entity_id` | string | Canonical resolved entity ID |
| `aliases` | string[] | Known aliases |
| `resolution_method` | string? | deterministic/probabilistic/asserted |
| `identity_confidence` | number? | 0–1 |
| `cluster_memberships` | string[] | Cluster IDs this entity belongs to |
| `merge_history` | string[]? | Prior entity IDs merged into this one |
| `split_history` | string[]? | Entity IDs split off from this one |
| `resolution_state` | string | resolved/unresolved/anonymous/pseudonymous/disputed |

### OutcomeEnvelope

| Field | Type | Description |
|-------|------|-------------|
| `intended_outcome` | string? | What was predicted/targeted |
| `observed_outcome` | string? | What actually happened |
| `value` | number? | Economic value of outcome |
| `result_state` | string? | converted/retained/churned/no_impact/unknown |
| `feedback` | string? | Human feedback text |
| `measurement_quality` | number? | 0–1 quality of outcome measurement |
| `recorded_time` | string? | When the outcome was recorded |

---

## ObservationClass

Controls visual treatment and epistemic weight of a graph node.

| Value | Meaning | Visual Treatment |
|-------|---------|-----------------|
| `observed` | Directly measured by Aether SDK | Solid border |
| `deterministic` | Resolved by deterministic rule | Solid border (slightly dimmed) |
| `probabilistic` | ML confidence score output | Dashed border |
| `derived` | Computed from observations | Semi-transparent |
| `predicted` | Future state model output | Dotted border + future-tense label |
| `simulated` | Counterfactual scenario | Dotted border + italic label |
| `manually_asserted` | Human annotation | Solid border + annotation icon |
| `externally_enriched` | Third-party data enrichment | Solid border + external badge |

Never render `predicted` or `simulated` nodes with the same visual weight as `observed` nodes.

---

## LifecycleState

| Value | Meaning |
|-------|---------|
| `provisional` | Newly created, not yet confirmed |
| `unresolved` | Identity not yet resolved |
| `active` | Normal active state |
| `growing` | Cluster expanding |
| `stable` | Steady state |
| `shrinking` | Cluster contracting |
| `dormant` | No recent activity |
| `decaying` | Losing signal confidence |
| `reactivated` | Returned from dormant |
| `merged` | Merged into another entity |
| `split` | Split into multiple entities |
| `suppressed` | Consent-suppressed (still exists, not activated) |
| `disputed` | Identity or attribution disputed |
| `expired` | Validity window passed |
| `revoked` | Consent revoked |
| `invalidated` | Invalidated by newer evidence |
| `deleted` | Soft-deleted |
| `tombstoned` | Hard-deleted with audit record |

---

## Extended Node Types (v8.10.0 additions)

Beyond the core 20+ types in `GRAPH_CONTRACT.md`, these cluster and domain types are now in `VertexType`:

| Type | Description |
|------|-------------|
| `IDENTITY_CLUSTER` | Probabilistic identity resolution cluster |
| `HOUSEHOLD_CLUSTER` | Co-residing individuals |
| `ORG_CLUSTER` | Organization members |
| `DEVICE_CLUSTER` | Shared device fingerprints |
| `BEHAVIORAL_CLUSTER` | Similar behavioral patterns |
| `GEOGRAPHIC_CLUSTER` | Geographic co-location |
| `ECONOMIC_SEGMENT` | Economic value tier grouping |
| `CAMPAIGN_COHORT` | Acquired via same campaign |
| `JOURNEY_CLUSTER` | Shared journey path |
| `FRAUD_NETWORK_CLUSTER` | Fraud ring members |
| `RISK_CLUSTER` | High-risk co-traveler cluster |
| `DORMANT_COHORT` | Dormant entity group |
| `REACTIVATED_COHORT` | Recently reactivated group |
| `UNRESOLVED_CLUSTER` | Entities awaiting identity resolution |
| `WALLET_CLUSTER` | Shared wallet behavior |
| `FRAUD_NETWORK` | Explicit fraud network entity |
| `INVESTIGATION` | Investigation case |
| `CASE` | Case management object |
| `ALERT` | Risk alert entity |
| `EVIDENCE` | Evidence item |
| `PREDICTION` | Model prediction output |
| `MODEL_OUTPUT` | ML model raw output |
| `JOURNEY` | Customer journey |
| `TOUCHPOINT` | Journey touchpoint |
| `CONVERSION` | Conversion event |

---

## Extended Edge Types and Layer Mapping

New edge types added in v8.10.0 with their required EDGE_LAYER_MAP entries:

| Edge Type | Layer | Description |
|-----------|-------|-------------|
| `ACQUIRED_VIA` | H2H | Campaign acquisition attribution |
| `MEMBER_OF_CLUSTER` | H2H | Entity belongs to identity/behavioral cluster |
| `MEMBER_OF_FRAUD_NETWORK` | H2H | Entity is a fraud network member |
| `MERGED_INTO` | H2H | Entity merged into another |
| `SPLIT_FROM` | H2H | Entity split from another |
| `BRIDGES` | H2H | Bridge entity between clusters |
| `PAYS_FOR` | A2A/H2H | Economic payment (context-dependent) |
| `TRANSFERS_TO` | A2A | Funds transfer between entities |
| `SETTLED_VIA` | A2A | x402/crypto settlement |
| `REFUNDED_BY` | H2H | Refund flow |
| `CONTROLS` | H2H | Organizational control relationship |
| `LAYERED_THROUGH` | H2H | Fraud layering relationship |
| `DELEGATED_TO` | A2A | Agent delegation |
| `HIRED` | H2A/A2A | Hiring relationship |
| `NEXT_IN_JOURNEY` | H2H | Journey step sequence |
| `TOUCHPOINT_IN` | H2H | Touchpoint belongs to journey |
| `CONVERTED_AT` | H2H | Conversion touchpoint |
| `ATTRIBUTED_TO_CAMPAIGN` | H2H | Multi-touch attribution |

---

## Boolean Filter Language

The `POST /v1/graph/query` and `POST /v1/graph/facets` endpoints accept a structured `filter` field using the following grammar:

```
FilterGroup:
  logic: "AND" | "OR" | "NOT"
  expressions: FilterExpression[] | FilterGroup[]

FilterExpression:
  field: string               # dot-notation: "risk_score", "economic.revenue"
  op: FilterOperator
  value: any
```

### Supported Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `eq` | Exact equality | `{"field":"lifecycle_state","op":"eq","value":"active"}` |
| `neq` | Not equal | |
| `gt` / `gte` | Greater than (or equal) | `{"field":"risk_score","op":"gt","value":0.7}` |
| `lt` / `lte` | Less than (or equal) | |
| `in` | Value in list | `{"field":"vertex_type","op":"in","value":["human","agent"]}` |
| `not_in` | Value not in list | |
| `exists` | Field exists and is not null | `{"field":"fraud_network_id","op":"exists","value":null}` |
| `not_exists` | Field is null or absent | |
| `contains` | String contains substring | |
| `starts_with` | String prefix | |
| `between` | Numeric or date range | `{"field":"valid_from","op":"between","value":["T1","T2"]}` |
| `relative_time` | Time window relative to now | `{"field":"last_seen","op":"relative_time","value":"-7d"}` |
| `threshold` | Alias for gte on numeric fields | |

Unknown operators are rejected with HTTP 400.

### Economic Filter Fields

Available as `field` values in `FilterExpression`:
- `economic.revenue`, `economic.spend`, `economic.ltv`, `economic.margin`
- `economic.transaction_volume`, `economic.currency`, `economic.rail`
- `economic.inflow`, `economic.outflow`

### Geography Filter Fields

- `geography.country`, `geography.region`, `geography.city`
- `geography.jurisdiction`, `geography.location_type`

---

## Query Budget Defaults

| Budget | Default | Max |
|--------|---------|-----|
| `max_depth` | 2 | 6 |
| `max_nodes` | 100 | 500 |
| `max_edges` | 500 | 2000 |
| `timeout_seconds` | 10 | 30 |

When a budget is exceeded, the response includes `meta.truncated: true` and `meta.truncation_reason`. HTTP 200 is always returned; budget violation is signaled in the response body, not as an error status.

---

## GraphResultMeta

Every graph query response includes a `meta` field:

| Field | Type | Description |
|-------|------|-------------|
| `truncated` | boolean | True if result was cut short by budget |
| `truncation_reason` | string? | "node_limit", "edge_limit", "timeout", "depth_limit" |
| `node_count` | number | Nodes in result |
| `edge_count` | number | Edges in result |
| `execution_ms` | number | Server-side query execution time |
| `query_id` | string | UUID for this query (for support/tracing) |
| `budget_used` | number | 0–1 fraction of budget consumed |
| `cursor` | string? | Opaque cursor for next page |
| `as_of` | string? | Temporal as_of applied |
| `freshness_seconds` | number? | Seconds since graph last updated |
| `warnings` | string[] | Non-fatal warnings |

---

## Cache Key Schema

Graph cache keys use the pattern:

```
aether:graph:<type>:<tenant_id>:<query_hash>[:<contract_version>][:<as_of>][:<permission_hash>]
```

All keys **must** include `tenant_id` as the second segment to prevent cross-tenant cache collisions. The `permission_hash` segment encodes redaction state — a permission change invalidates the cache without requiring an explicit flush.

---

## Causality Classification

Edge properties may include `causality_class` to express the epistemic relationship:

| Value | Meaning | Notes |
|-------|---------|-------|
| `observed_sequence` | A occurred then B occurred | No causal claim |
| `correlation` | A and B co-occur statistically | No causal claim |
| `attributed_influence` | A is credited for B (multi-touch) | Attribution model output |
| `inferred_influence` | A probably caused B (ML) | Probabilistic |
| `experiment_incremental` | A caused B (A/B test proven) | Strongest claim |
| `direct_cause` | A directly caused B | Requires experiment support |

`direct_cause` must never be set unless backed by experiment evidence.
