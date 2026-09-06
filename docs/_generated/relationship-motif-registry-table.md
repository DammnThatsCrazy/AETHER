<!-- DO NOT EDIT — generated from packages/shared/contracts/relationship-motif-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Relationship Motif Registry

Contract version: `1.0.0`

Canonical relationship-motif registry for the Relational Intelligence Spine (Social360 + Relationship Fidelity program, blueprint §§43-45). Registry-driven higher-order structure detection: each motif declares its required/optional structure, temporal + entity-kind constraints, evidence-independence and incentive policy, and the relationship hypothesis it may emit. Motifs never write canonical truth directly: evidence edges → motif matcher → RelationshipHypothesis → epistemic evaluation → RelationshipAssertion (via the canonical Graph Mutation Gateway). Engine must work deterministically without an LLM (blueprint §46); model assistance is proposal-only. Generated TS, Python, and Markdown twins derive from this file via scripts/generate_platform_contracts.py. Outputs that are relationship predicates cross-reference relationship-predicate-registry.json (outputKind RELATIONSHIP_PREDICATE); cascade/finding outputs carry bounded claims under the graph_motifs canonical authority (outputKind DERIVED_RELATIONSHIP_STATE).

## Output kinds

`RELATIONSHIP_PREDICATE`, `DERIVED_RELATIONSHIP_STATE`

## Claim ceilings

`observed`, `verified`, `resolved`, `derived`, `inferred`, `predicted`, `correlated`, `temporally_supported`

| Motif | Output kind | Output | Claim ceiling | Evidence independence | Incentive |
|---|---|---|---|---|---|
| `MUTUAL_SOCIAL_CONNECTION` | RELATIONSHIP_PREDICATE | `MUTUAL_SOCIAL_CONNECTION` | derived | SINGLE_SOURCE_NOT_SUFFICIENT | NONE_REQUIRED |
| `RECIPROCAL_COMMUNICATION` | RELATIONSHIP_PREDICATE | `RECIPROCAL_COMMUNICATION` | derived | INDEPENDENT_OBSERVATIONS_REQUIRED | NONE_REQUIRED |
| `RECURRING_CO_PRESENCE` | RELATIONSHIP_PREDICATE | `RECURRING_CO_PRESENCE` | derived | INDEPENDENT_OBSERVATIONS_REQUIRED | CONTEXT_ONLY_RECORDED |
| `COMMUNITY_ASSOCIATION` | RELATIONSHIP_PREDICATE | `COMMUNITY_ASSOCIATION` | derived | INDEPENDENT_OBSERVATIONS_REQUIRED | NONE_REQUIRED |
| `SOCIAL_ECONOMIC_TRANSITION` | DERIVED_RELATIONSHIP_STATE | `social_economic_transition` | derived | CORRELATION_DAMPING_REQUIRED | CONTEXT_ONLY_RECORDED |
| `AGENT_MEDIATED_PRINCIPAL_INTERACTION` | RELATIONSHIP_PREDICATE | `AGENT_MEDIATED_PRINCIPAL_INTERACTION` | derived | SINGLE_SOURCE_NOT_SUFFICIENT | NONE_REQUIRED |
| `INCENTIVE_ORIGINATED_CASCADE` | DERIVED_RELATIONSHIP_STATE | `incentive_originated_propagation` | derived | CORRELATION_DAMPING_REQUIRED | DETECTED_UPSTREAM_INCENTIVE_REQUIRED |
| `EARNED_DOWNSTREAM_AMPLIFICATION` | DERIVED_RELATIONSHIP_STATE | `earned_downstream_amplification` | derived | CORRELATION_DAMPING_REQUIRED | DOWNSTREAM_UNINCENTIVIZED_REQUIRED |
| `PREEXISTING_AFFINITY_INTERSECTS_CAMPAIGN` | DERIVED_RELATIONSHIP_STATE | `preexisting_relationship_intersects_campaign` | temporally_supported | INDEPENDENT_OBSERVATIONS_REQUIRED | CONTEXT_ONLY_RECORDED |
| `PERSISTENT_MULTI_CONTEXT_ASSOCIATION` | RELATIONSHIP_PREDICATE | `PERSISTENT_MULTI_CONTEXT_ASSOCIATION` | derived | INDEPENDENT_OBSERVATIONS_REQUIRED | CONTEXT_ONLY_RECORDED |
