<!-- DO NOT EDIT — generated from packages/shared/contracts/filter-field-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Filter Field Registry

Contract version: `1.0.0`

Categories: `entity`, `time`, `geography`, `device`, `graph`, `risk`, `campaign`, `economic`, `truth`, `social`, `relationship`, `incentive`, `source`, `evidence`, `path`, `narrative`

| Field | Label | Category | Type | Operators | Sensitivity | Consent purpose | Min cohort |
|---|---|---|---|---|---|---|---|
| `campaign.attribution_model` | Attribution model | campaign | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | `marketing` | — |
| `campaign.channel` | Campaign channel | campaign | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | `marketing` | — |
| `campaign.id` | Campaign | campaign | entity_ref | `eq`, `neq`, `in`, `not_in`, `exists`, `not_exists` | tenant_internal | `marketing` | — |
| `campaign.source` | Campaign source | campaign | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | `marketing` | — |
| `device.app_version` | App version | device | string | `eq`, `neq`, `in`, `not_in`, `starts_with` | tenant_internal | — | — |
| `device.class` | Device class | device | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `device.os` | Operating system | device | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `device.platform` | Platform | device | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `economic.ltv_usd` | Lifetime value (USD) | economic | number | `gt`, `gte`, `lt`, `lte`, `between`, `threshold` | sensitive | `economic_observability` | — |
| `economic.payment_rail` | Payment rail | economic | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | `financial_activity` | — |
| `economic.revenue_usd` | Revenue (USD) | economic | number | `gt`, `gte`, `lt`, `lte`, `between`, `threshold` | sensitive | `economic_observability` | — |
| `entity.cluster_id` | Identity cluster | entity | entity_ref | `eq`, `neq`, `in`, `not_in`, `exists`, `not_exists` | sensitive | — | — |
| `entity.id` | Entity ID | entity | entity_ref | `eq`, `neq`, `in`, `not_in`, `exists`, `not_exists` | tenant_internal | — | — |
| `entity.lifecycle_state` | Lifecycle state | entity | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `entity.tags` | Tags | entity | string | `contains`, `in`, `not_in`, `exists`, `not_exists` | tenant_internal | — | — |
| `entity.type` | Entity type | entity | enum | `eq`, `neq`, `in`, `not_in` | public | — | — |
| `evidence.basis` | Evidence basis | evidence | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `geography.city` | City | geography | geography | `eq`, `neq`, `in`, `not_in` | tenant_internal | `location` | 25 |
| `geography.country` | Country | geography | geography | `eq`, `neq`, `in`, `not_in` | tenant_internal | `location` | — |
| `geography.region` | Region | geography | geography | `eq`, `neq`, `in`, `not_in` | tenant_internal | `location` | — |
| `graph.depth` | Traversal depth | graph | number | `eq`, `gt`, `gte`, `lt`, `lte`, `between` | tenant_internal | — | — |
| `graph.edge_confidence` | Edge confidence | graph | number | `gt`, `gte`, `lt`, `lte`, `between`, `threshold` | tenant_internal | — | — |
| `graph.edge_type` | Edge type | graph | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `graph.relationship_layer` | Relationship layer | graph | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `incentive.campaign_ref` | Incentive campaign | incentive | entity_ref | `eq`, `neq`, `in`, `not_in`, `exists`, `not_exists` | tenant_internal | — | — |
| `incentive.status` | Incentive status | incentive | enum | `eq`, `neq`, `in`, `not_in` | sensitive | — | — |
| `narrative.ref` | Narrative | narrative | entity_ref | `eq`, `neq`, `in`, `not_in`, `exists`, `not_exists` | tenant_internal | — | — |
| `path.type` | Path type | path | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `relationship.claim_type` | Relationship claim type | relationship | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `relationship.context_diversity` | Relationship context diversity | relationship | number | `gt`, `gte`, `lt`, `lte`, `between`, `threshold` | tenant_internal | — | — |
| `relationship.family` | Relationship family | relationship | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `relationship.persistence` | Relationship persistence | relationship | number | `gt`, `gte`, `lt`, `lte`, `between`, `threshold` | tenant_internal | — | — |
| `relationship.predicate` | Relationship predicate | relationship | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `relationship.reciprocity` | Relationship reciprocity | relationship | number | `gt`, `gte`, `lt`, `lte`, `between`, `threshold` | tenant_internal | — | — |
| `risk.anomaly_score` | Anomaly score | risk | number | `gt`, `gte`, `lt`, `lte`, `between`, `threshold` | sensitive | — | — |
| `risk.fraud_network_member` | Fraud network member | risk | boolean | `eq` | restricted | — | — |
| `risk.score` | Risk score | risk | number | `gt`, `gte`, `lt`, `lte`, `between`, `threshold` | sensitive | — | — |
| `risk.trust_score` | Trust score | risk | number | `gt`, `gte`, `lt`, `lte`, `between`, `threshold` | sensitive | — | — |
| `social.account_type` | Social account type | social | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `social.community_ref` | Social community | social | entity_ref | `eq`, `neq`, `in`, `not_in`, `exists`, `not_exists` | tenant_internal | — | — |
| `social.connection_type` | Social connection type | social | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `social.interaction_type` | Social interaction type | social | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `social.provider` | Social provider | social | string | `eq`, `neq`, `in`, `not_in`, `exists`, `not_exists` | tenant_internal | — | — |
| `source.scope` | Source scope | source | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `time.first_seen` | First seen | time | datetime | `gt`, `gte`, `lt`, `lte`, `between`, `relative_time` | public | — | — |
| `time.last_seen` | Last seen | time | datetime | `gt`, `gte`, `lt`, `lte`, `between`, `relative_time` | public | — | — |
| `time.occurred_at` | Occurred at | time | datetime | `gt`, `gte`, `lt`, `lte`, `between`, `relative_time` | public | — | — |
| `truth.confidence_min` | Minimum confidence | truth | number | `gt`, `gte`, `lt`, `lte`, `threshold` | tenant_internal | — | — |
| `truth.dimension_state` | Dimension state | truth | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
| `truth.evidence_basis` | Evidence basis | truth | enum | `eq`, `neq`, `in`, `not_in` | tenant_internal | — | — |
