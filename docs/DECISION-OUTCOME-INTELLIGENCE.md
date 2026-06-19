---
title: Decision & Outcome Intelligence
slug: ai/decision-outcome-intelligence
section: ai
visibility: I
audience: [ai, architect, dev-senior, ops]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/intelligence/decision_models.py
  - Backend Architecture/aether-backend/services/intelligence/ooda_engine.py
  - Backend Architecture/aether-backend/services/intelligence/recommendation_families.py
  - Backend Architecture/aether-backend/services/intelligence/outcome_ledger.py
  - Backend Architecture/aether-backend/services/intelligence/routes.py
  - Backend Architecture/aether-backend/services/intelligence/repositories.py
  - Backend Architecture/aether-backend/config/settings.py
flags:
  - AETHER_RECOMMENDATIONS_ENABLED
  - AETHER_DECISION_RECORDS_ENABLED
  - AETHER_OUTCOME_FEEDBACK_ENABLED
  - AETHER_PLAYBOOKS_ENABLED
  - KYBER_RECOMMENDATION_OBSERVABILITY_ENABLED
  - AETHER_RECOMMENDATION_CONFIDENCE_THRESHOLD
related:
  - architecture/intelligence-graph
  - ai/recommendation-families
  - ai/investigation-workspace
  - operations/cicd
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 3
last_synced_commit: 111fddf
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
Recommendations include evidence, confidence decomposition, required approval level, policy/governance flags, graph snapshot id, and data freshness.

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

## Tenant vs Kyber responsibilities

- **Aether tenant app**: shows recommendation cards, evidence, decision drawer, entity recommendations, outcome history, and playbook controls for the current tenant.
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
- `KYBER_RECOMMENDATION_OBSERVABILITY_ENABLED`
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

Decision records now feed tenant-scoped audit exports and Kyber solution package readiness. Exports preserve actor, approval, selected/rejected action, reason/comment, and timestamp evidence without exposing cross-tenant data. See `docs/AUDIT-EXPORTS.md` and `docs/SOLUTION-PACKAGES.md`.
