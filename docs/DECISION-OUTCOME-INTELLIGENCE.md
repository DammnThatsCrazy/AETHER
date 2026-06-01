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

- `POST /v1/intelligence/recommendations/generate`
- `GET /v1/intelligence/recommendations`
- `GET /v1/intelligence/recommendations/{id}`
- `POST /v1/intelligence/recommendations/{id}/decision`
- `POST /v1/intelligence/actions`
- `POST /v1/intelligence/actions/{id}/outcome`
- `GET /v1/intelligence/outcomes`
- `GET /v1/profile/{entity_id}/recommendations`
- `GET /v1/profile/{entity_id}/outcomes`
- `GET /v1/intelligence/playbooks`
- `POST /v1/intelligence/playbooks`
- `POST /v1/intelligence/playbooks/{id}/run`

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
