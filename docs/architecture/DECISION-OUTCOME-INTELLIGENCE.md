---
title: Decision & Outcome Intelligence
slug: ai/decision-outcome-intelligence
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: beta
since_version: 0.1.0
source_files: [services/api/intelligence/intelligence/decision_models.py, services/api/intelligence/intelligence/ooda_engine.py, services/api/intelligence/intelligence/recommendation_families.py, services/api/intelligence/intelligence/outcome_ledger.py, services/api/intelligence/intelligence/routes.py, services/api/intelligence/intelligence/repositories.py, services/api/config/settings.py]
flags: [AETHER_RECOMMENDATIONS_ENABLED, AETHER_DECISION_RECORDS_ENABLED, AETHER_OUTCOME_FEEDBACK_ENABLED, AETHER_PLAYBOOKS_ENABLED, AETHER_RECOMMENDATION_CONFIDENCE_THRESHOLD]
related: [architecture/intelligence-graph, ai/recommendation-families, ai/investigation-workspace, operations/cicd]
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 3
source_hashes:
  "services/api/config/settings.py": "sha256:fe581665da73af478c3da53600fb0fdd4994d801f408e56f6d2796fbd00748bf"
  "services/api/intelligence/intelligence/decision_models.py": "sha256:fa7574a7f99bcebb21ff58d6cd61ffbb761a58b0022b5a247a13387c8c9853d8"
  "services/api/intelligence/intelligence/ooda_engine.py": "sha256:e029e43ee23fe742c4ad33a5023e5b04d66e2003a3b655ab177d4567747b92de"
  "services/api/intelligence/intelligence/outcome_ledger.py": "sha256:8edf9b6a8db71127202f8225cb8b03330eef96f058ae555eb38a7a576cdbf206"
  "services/api/intelligence/intelligence/recommendation_families.py": "sha256:1d4ef3823c50ca7cd13617c779fb0c83266dd9d57f1b61e4f819f8c820b5bb6a"
  "services/api/intelligence/intelligence/repositories.py": "sha256:89fc229eeb1b7dd12ced0bc8cc50ab8413277a2ca0e2d8e396b8c088f07c3e07"
  "services/api/intelligence/intelligence/routes.py": "sha256:60d5307836ffcd38c784710b60689c803347d7a3dbb0f7608a64ba66ef150241"
---
# Decision & Outcome Intelligence

Aether extends the existing intelligence graph into a graph-native OODA loop: **Observe → Orient → Recommend → Decide → Act → Learn**. This is not a separate decision-engine product or parallel application layer; it is an additive extension of the existing SDK ingestion, profile, intelligence, graph, event, approval, action, and observability patterns.

## OODA loop

1. **Observe**: SDK events, provider connectors, lake ingestion, graph mutations, and event pipelines continue to provide the observed state. Canonical SDK event contracts remain unchanged.
2. **Orient**: Intelligence, Profile360, attribution, fraud, behavioral, population, ML, trust, and economic state outputs are reused as orientation signals.
3. **Recommend**: The intelligence service generates ranked recommendations from deterministic graph rules, existing ML outputs, graph relevance, attribution confidence, economic expected value, risk, freshness, and governance penalties.
4. **Decide**: Decision records capture human/tenant choices. Approval, rejection, deferral, and escalation are explicit records and do not imply autonomous irreversible execution.
5. **Act**: Actions are logged with actor type, integration/system, economic payload, and authorization metadata. Critical or irreversible actions require human approval.
6. **Learn**: Outcomes link back to actions, decisions, recommendations, entities, and graph evidence. Confidence deltas feed future recommendation scoring.

## Recommendation lifecycle

`generated → viewed → decided → outcome_observed → confidence_updated`.
Recommendations include evidence, confidence decomposition, required approval level, policy/governance flags, graph snapshot id, and data freshness. When a recommendation is promoted from a comparison finding, optional `finding_id` and `investigation_id` provenance links are carried onto the decision, planned action/dispatch, and observed outcome records so the full loop remains traceable.

Action dispatch also persists an `action.dispatch` policy decision with the
durable dispatch. A successful record is bound to its dispatch ID, tenant,
authenticated principal, selected action, target, elevation and approval
context, and Journey or Risk association record. Journey360 and Risk360 rejoin
and validate those exact fields, as well as requiring policy evaluation to
precede delivery. For idempotent dispatches, an `authorization_pending`
reservation is claimed atomically before policy persistence. A persistence
failure returns it to the retryable pending state, preserving the dispatch ID;
only the successful claimant can proceed to delivery. This records the application permission decision; it
does not prove event-time authority, connector execution, or an external effect.

## Graph relationships

Additive OODA edges:

- `entity -> HAS_RECOMMENDATION -> recommendation`
- `recommendation -> SUPPORTED_BY -> event/entity/edge/profile signal`
- `recommendation -> SELECTED_BY -> decision`
- `decision -> EXECUTED_AS -> action`
- `action -> PRODUCED -> outcome`
- `outcome -> UPDATES_CONFIDENCE_FOR -> recommendation`

## Governance constraints

- Tenant isolation is enforced at repository filters and record lookups.
- Consent, policy flags, explanation requirements, freshness indicators, and approval levels are embedded in recommendation records.
- Human-in-the-loop approval is preserved for elevated, critical, irreversible, or low-confidence actions.
- Kyber observability uses aggregate health metrics and must not expose tenant-private intelligence across tenants.

Dispatch and graph safeguards are part of this same OODA authority. Graph
neighbours are filtered by the authenticated tenant before result limits are
applied (both `tenantId` and legacy `tenant_id` markers are normalized;
unattributed vertices are not a wildcard). An optional action idempotency key
is reserved before any connector call, and a missing adapter leaves an
auditable queued plan rather than claiming an external effect. Delivered
receipts must contain real provider evidence; simulation-shaped receipts are
not accepted. Journey360 and Risk360 can join a dispatch to canonical worker
delivery evidence, including provider receipts and signature-verified,
receipt-bound callbacks. Tenant-submitted outcome events remain
`caller_asserted`; neither those events nor a provider delivery record changes
the projection's external-effect state from `not_independently_verified`.

## Tenant vs Kyber responsibilities

- **Aether tenant app**: shows recommendation cards, evidence, decision drawer,
  entity recommendations, outcome history, and playbook controls for the current
  tenant. Approval records the authenticated actor and creates a separate
  durable `planned` action; it does not dispatch an external effect. Dispatch
  remains a later explicit operation requiring a configured tenant target and
  the applicable policy/approval checks.
- **Kyber operator console**: shows aggregate system health, volume, approval/rejection rates, outcome capture rate, confidence drift, playbook performance, and stale loops.

## API examples

- `POST /v1/intelligence/recommendations/preview` — read-only recommendation preview; does not persist rows, mutate graph edges, or emit lifecycle events.
- `POST /v1/intelligence/recommendations/generate` — write-scoped persisted generation; persists the recommendation, mutates graph edges, and emits lifecycle events.
- `GET /v1/intelligence/recommendations`
- `GET /v1/intelligence/recommendations/{id}`
- `GET /v1/intelligence/recommendations/{id}/investigation`
- `POST /v1/intelligence/recommendations/{id}/decision`
- `POST /v1/intelligence/actions`
- `POST /v1/intelligence/actions/{id}/outcome`
- `GET /v1/intelligence/outcomes`
- `GET /v1/intelligence/outcome-ledger`
- `GET /v1/intelligence/outcome-ledger/summary`
- `GET /v1/intelligence/outcome-ledger/by-recommendation-type`
- `GET /v1/intelligence/outcome-ledger/by-playbook`
- `GET /v1/intelligence/recommendations/{id}/investigation`
- `GET /v1/profile/{entity_id}/recommendations`
- `GET /v1/profile/{entity_id}/outcomes`
- `GET /v1/profile/{entity_id}/outcome-ledger`
- `GET /v1/intelligence/playbooks`
- `POST /v1/intelligence/playbooks`
- `POST /v1/intelligence/playbooks/{id}/run`

## Outcome Ledger

The Outcome Ledger makes the loop commercially legible for tenants. It answers what was recommended, what was decided, what action was taken, what outcome happened, what value was created, whether confidence improved, and which loops are stale, incomplete, or failed. Ledger APIs are read-only and are derived from existing OODA repositories; they do not create a separate product layer.

## Feature flags

Decision and outcome intelligence flags default to disabled so tenants and operators can roll the loop out gradually:

- `AETHER_RECOMMENDATIONS_ENABLED`
- `AETHER_DECISION_RECORDS_ENABLED`
- `AETHER_OUTCOME_FEEDBACK_ENABLED`
- `AETHER_PLAYBOOKS_ENABLED`
- `AETHER_RECOMMENDATION_CONFIDENCE_THRESHOLD`

## Migration notes

The implementation is additive: JSONB-backed repositories auto-create tables in production and share in-memory stores in local/test mode. Existing APIs are not removed. SDK contracts are extended through shared optional types rather than changing canonical event ingestion contracts.

## Expansion surfaces

- **Recommendation families**: `RecommendationFamilyRegistry` routes generation to retention, expansion, fraud review, attribution optimization, journey optimization, agent governance, rewards optimization, and operational failure strategies. Families own detection, scoring, candidate actions, evidence, governance, suppression reasons, and emitted recommendation shape.
- **Outcome ledger**: tenant-scoped aggregations expose value created, value pending, outcome capture rate, confidence deltas, stale loops, incomplete loops, failed loops, and value by recommendation type/playbook/entity.
- **Investigation workspace**: recommendation investigation responses include recommendation details, confidence breakdown, evidence, graph context, related events, attribution path, candidate actions, decision/action/outcome history, governance flags, data freshness, and suppression explanation.
- **Playbooks**: templates convert repeated recommendation loops into governed operational assets with trigger conditions, family mappings, candidate actions, approval thresholds, outcome mappings, ROI aggregation, and stale run detection.
- **Kyber strategic observability**: `/v1/admin/kyber/*` endpoints expose aggregate health, outcome capture, playbook performance, confidence drift, vertical solution signals, and expansion opportunities for internal operators without exposing raw cross-tenant intelligence.
- **Integration actions**: Slack, webhook, CRM task, marketing automation, and ticketing placeholders can be logged as auditable `ActionFeedback` records after required approval checks.

## Rollout and migration notes

Feature flags continue to default disabled. Existing recommendation APIs remain present, but persistence is now behind `write` permission: tenants should call preview for read-only analyst exploration and generate only when they intend to create an auditable graph-native recommendation record. Existing outcome/recommendation mismatch protection, approved-decision action constraints, and elevated/critical approval metadata requirements remain enforced.

## Enterprise packaging and audit exports

Decision records now feed tenant-scoped audit exports and Kyber solution package readiness. Exports preserve actor, approval, selected/rejected action, reason/comment, and timestamp evidence without exposing cross-tenant data. See `docs/operations/AUDIT-EXPORTS.md` and `docs/product/SOLUTION-PACKAGES.md`.

Decision actor identity is derived from the authenticated tenant principal on
the server. The compatibility request field cannot override audit identity.

## Fraud Intelligence Configuration

`FraudIntelligenceConfig` was added to `config/settings.py` alongside the existing intelligence config dataclasses. It follows the same `_env_bool` / `_env_float` / `_env_int` pattern:

| Flag | Default | Purpose |
|------|---------|---------|
| `FEATURE_FRAUD_NETWORKS` | `False` | Enable fraud network clustering service |
| `FEATURE_FLOW_TRACE` | `False` | Enable flow-of-funds BFS traversal |
| `FEATURE_RISK_OVERLAYS` | `False` | Enable Cytoscape risk overlay generation |
| `FRAUD_NETWORK_MAX_DEPTH` | `4` | Maximum graph traversal depth for clustering |
| `FLOW_TRACE_MAX_HOPS` | `10` | Maximum BFS hops for flow-of-funds trace |

These flags are independent of the decision/outcome intelligence flags and have no effect on recommendation or playbook behavior.
