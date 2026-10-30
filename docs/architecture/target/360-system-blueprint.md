---
title: "360 System Blueprint"
slug: architecture/target/360-system-blueprint
section: architecture
visibility: P
audience: [dev-senior, architect]
status: experimental
since_version: "0.1.0"
source_files: [packages/shared/contracts/intelligence-projection-registry.json]
source_hashes:
  "packages/shared/contracts/intelligence-projection-registry.json": "sha256:6f2e26b373c363826258bd79d4189d700e3edbf00279f36cf757e2a0b5f7918c"
---

# 360 System Blueprint

## Authority and scope

The product catalog in `packages/shared/contracts/intelligence-projection-registry.json`
defines **18 backend 360 surfaces** and **196 required domain slots**. The
technical projection registry has 24 projection implementations and is a
separate inventory. A product slot may bind to one or more technical
projections; a registered binding does not prove full behavior.

Each 360 assembles governed, tenant-scoped reads from the owning canonical
authority. It exposes evidence, policy disposition, temporal and freshness
limits, and explicit unknown or degraded states. It does not create a parallel
truth store or mutate graph state. Agent and execution views must distinguish
observed activity from event-time authority to act, and attributed value from
independently verified outcomes.

## Full product catalog and current partial slots

The count below is from required slots with `partialImplementationReason` in
the registry on this branch. The other 69 required slots have no partial flag;
that fact alone is **not** a runtime completion finding. Every surface has at
least one explicitly partial required slot, so **0 of 18 surfaces** meet the
full backend contract today.

| Surface | Required | Explicitly partial | Partial required slots |
|---|---:|---:|---|
| Agent360 | 11 | 6 | owner_delegator, delegation_chain, capabilities, policy_boundary, risk_summary, evidence_trace |
| Execution360 | 11 | 7 | execution_summary, tool_calls, approval_chain, authority_check, latency_cost, risk_events, evidence_trace |
| Episode360 | 11 | 7 | timeline, touchpoints, communications, agent_handoffs, conversion_events, attribution_links, risk_flags |
| Profile360 | 13 | 9 | session_history, agent_delegations, communications, syndicates, relationships, value_summary, risk_summary, location_temporal, likely_next_states |
| Identity360 | 10 | 2 | namespace_map, wallets |
| Journey360 | 11 | 9 | journey_summary, stages, episodes, agent_interventions, communications, dropoffs, conversions, attribution, recommended_actions |
| Communications360 | 11 | 7 | participants, profile_links, journey_links, response_events, agent_authorship, policy_state, risk_flags |
| Risk360 | 12 | 8 | anomaly_events, policy_flags, poisoning_evidence, propagation_paths, financial_contagion, social_contagion, interventions, audit_history |
| Value360 | 11 | 9 | web2_value, web3_value, conversion_inventory, attribution_credits, revenue_events, ltv, reconciliation, financial_risk, confidence |
| Social360 | 10 | 7 | multi_hop_paths, syndicates, influence_paths, propagation, social_contagion, trust_edges, risk_edges |
| Campaign360 | 11 | 6 | source_classification, signal_sources, conversions, cohorts_syndicates, performance, anomalies |
| Signals360 | 10 | 7 | source_inventory, classification, quality, normalization, linked_entities, campaign_links, risk_flags |
| Account360 | 11 | 6 | members, profiles, journeys, communications, risk, contracts |
| Location360 | 11 | 8 | timezone, activity_density, journeys, campaigns, profiles, value, risk, normalization |
| Workflow360 | 11 | 8 | workflow_summary, triggers, actors, approvals, agent_steps, actions, outcomes, risk |
| Memory360 | 10 | 4 | memories, cards, embeddings_meta, policy_state |
| Commerce360 | 11 | 7 | product_offer_summary, catalog_links, exposures, intent, cart_checkout, availability_price, risk |
| Support360 | 10 | 10 | case_summary, conversation_history, callbacks, participants, sla, journey_links, agents, risk, resolution, evidence_trace |

Four slots declare seven unbound canonical authority references after the exact
bindings in this slice. Journey360 and Risk360 now bind the actions authority
through persisted dispatch authorization and credential-bound Jira resource
read-back. The supported verification checks the provider site, requested payload,
tenant, subject, intent, job, receipt and policy decision. Other providers remain
unverified; neither slot is complete, and business outcomes, producer coverage,
historical replay and freshness are not established by resource existence.
Value360 can expose a recorded check of attribution run
configuration lineage against the current config, while model governance and
calibration remain unbound. Campaign360
`signal_sources` now binds exact gateway-admitted SDK Bronze observations and
current touchpoint classification revisions to touchpoint-linked canonical
events; broader source-fact producer coverage remains unknown. Agent360 `risk_summary` exposes its exact canonical Agent identity
join before policy-scoped Risk360 and Social360 reads. Social risk-context
correlations require consent and shared risk-signal evidence; causality,
contagion, coverage, and freshness remain unknown.
Signals360 `quality` binds exact tenant/site installation status only when an
accepted SDK observation carries the authenticated server-stamped site
namespace. `source_inventory` also resolves the exact current site registration
as a source fact for that namespace. Event-time status, fleet health, and
source reliability remain unknown. Workflow360 `actions` preserves the exact
tenant Tool vertex evidence for admitted execution-linked call edges. Under
slot policy it may also expose the linked execution's recorded executor result
and an exact current approved resource; tool results and resource operations
remain unbound. Agent360 `capabilities` resolves
observed MCP catalog tool identity only for an exact tenant/provider/server/tool
tuple. For a complete canonical grant read, it also exposes the exact recorded
invoke action and capability or server resource with delegation evidence;
ambiguous grant scopes fail closed. It also exposes bounded persisted
`capability.invoke` evaluations with exact Agent, capability, grant, result,
and time. They do not bind to observed MCP calls or establish current effective
authority. Agent360 explicitly reports action-specific and resource-operation
authority as unknown because no such producer is joined: tool-call and resource
request lifecycle observations, catalog/install records, invoke grants, and
`capability.invoke` decisions do not establish those authorities. The slot
remains partial. Support360 `sla` now joins an operator-registered source policy revision
to an exact case timer and target. Breach evaluation, historical applicability,
source completeness, and freshness remain partial.
Campaign360 `cohorts_syndicates` can join an explicit campaign population link
to a current exact cluster definition and consent-scoped cluster or cohort
memberships backed by graph-ledger replay. A policy-authorized bounded graph
read exposes current observed FOLLOWS edges between linked members with analytics
consent receipts and relationship evidence. Roster completeness, other predicates,
syndicates, historical membership, and freshness remain unknown. Journey and Risk
can expose an exact caller-associated agent lifecycle request after slot policy.
The request can include its matching, tenant-scoped, time-checked recorded delegation decision;
current authorization, dispatch and external effect remain unverified. Journey360
and Risk360 dispatch reads also require the persisted tenant `action.dispatch`
policy decision for the exact action before dispatch creation. Risk360 also
rejects a permission decision evaluated before the associated risk decision's
recorded, observed, or effective time. These dispatch associations are
caller-supplied links; the permission record is not a canonical producer for
tool results or resource operations. Connector execution, external effect,
independent outcome verification, complete dispatch producer coverage, and
freshness remain unknown. Workflow approval decisions can
carry a recorded human permission check and the matching request-time agent
delegation decision joined to its current grant. Workflow-wide coverage,
historical policy replay, and current authorization remain unknown.
Profile360 `likely_next_states` rechecks the recorded inference decision against
the tenant, actor, model, subject, policy version, and decision time; session
models also require the exact current session identity binding. A current
artifact-reported calibration metric can be shown with unknown dataset and
evaluation scope. Explicit prediction-ID and versioned-label-contract outcome
links may be shown as reported associations after separate outcomes-domain
policy authorization and exact tenant, subject, and prediction-validity-time
checks; they do not establish prediction correctness. Current consent,
historical identity state, independently validated calibration, complete
outcome coverage, and outcome verification remain unproven.
Campaign360 `anomalies` and Location360 `risk` bind bounded exact Risk360
assessment reads, while producer coverage and whole-slot completeness remain
unknown. Their exact
authority names and the limitation of every partial slot live in the registry;
those fields are the implementation checklist, not the table alone.

## Implementation order

1. **Close exact reads already backed by canonical records.** Join by tenant,
   typed subject, stable source ID, and evidence; bound the read and reject
   ambiguity. Journey360 attribution now resolves recorded conversion and
   touchpoint IDs only to eligible current rows, while run-time state, policy,
   freshness, full coverage, and causality remain unknown. Signals360 now
   joins bounded Silver semantic model-output metadata only when the exact
   tenant event, backend-stamped namespace, type, time, and evidence agree;
   derived labels and semantic correctness remain unknown.
2. **Build missing owning producers and immutable history.** Agent action and
   resource entitlement receipts, workflow-wide approval/action evidence,
   support episode association, campaign source facts, installation health,
   risk propagation observations, and value calibration must be written by
   their canonical owners before their 360 slots can claim coverage.
3. **Apply cross-cutting proof per slot.** Resolve actor identity and delegation
   at event time, evaluate applicable consent and policy with receipts, expose
   source watermarks and bounded population completeness, and substantiate
   outcome claims independently. Keep unsupported historical or causal claims
   explicitly unknown.
4. **Verify each full surface contract.** Exercise tenant isolation, missing
   source, contradictory evidence, temporal replay, policy denial, redaction,
   pagination, and freshness cases before clearing a partial flag. Reconcile
   the product catalog, provider output, and generated contract together.

The checked-in backend source of truth is
`docs/reference/source-of-truth/AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md`.
The supplemental architectural buildout blueprint is under
`docs/archive/360-blueprint/`. This page tracks backend delivery; it does not
claim that all original blueprint capabilities are implemented.
