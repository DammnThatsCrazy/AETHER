<!-- DO NOT EDIT — generated from packages/shared/contracts/intelligence-projection-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Product 360 Surface Catalog

Catalog version: `0.2.0`

This product catalog has 18 surface contracts and is separate from the 24-row technical projection provider registry. Projection mappings are `catalog_only` candidate section bindings. Direct surface-provider mappings use a separate namespace; `runtime_wired` confirms a frame-runtime call path for the declared subjects and slots, not full surface completion.

The 18 product contracts and their lens lists are aligned to the recovered primary backend 360 source of truth. `source_aligned` describes blueprint alignment only. A slot needs a canonical provider read and governed frame evidence before it can be considered implemented; the binding and gap columns below show the current limits.
Declared binding counts are registry coverage, not proof that a slot or surface is complete. A bound slot can still return unknown, degraded, stale, or suppressed for a request.

## Frame lifecycle states

| State | Meaning |
|---|---|
| `ready` | Required slots are resolved and governed for this request. |
| `partial` | Some useful slots are available while other slots are degraded or unavailable. |
| `empty` | Authorities returned a known empty result. |
| `missing` | A required slot or provider is absent. |
| `unknown` | The available evidence cannot establish a state. |
| `suppressed` | Policy removed a slot from this response. |
| `stale` | Source freshness limits were exceeded. |
| `degraded` | A provider returned a partial or degraded result. |
| `unavailable` | No usable provider result is available. |
| `conflicted` | Tenant, identity, or provenance invariants conflict. |

## Catalog overview

| Product surface | Contract status | Subject kinds | Required slots | Declared required bindings | Explicit partial required slots | Unbound required slots | Optional slots | Projection providers | Direct surface providers |
|---|---|---|---:|---:|---:|---:|---:|---|---|
| [Account 360](#account-360) | source_aligned | `account`, `entity`, `workspace` | 11 | 9/11 | 4 | 2 | 4 | `communication360`, `economic360`, `profile360`, `relationship360` | `Account360Provider` (runtime_wired) |
| [Agent 360](#agent-360) | source_aligned | `agent`, `entity` | 11 | 11/11 | 6 | 0 | 4 | `agent360`, `communication360`, `economic360`, `execution360`, `outcome360`, `relationship360`, `risk360` | — |
| [Campaign 360](#campaign-360) | source_aligned | `campaign` | 11 | 10/11 | 3 | 1 | 0 | `campaign360`, `communication360`, `economic360`, `outcome360` | — |
| [Commerce 360](#commerce-360) | source_aligned | `entity`, `campaign`, `journey`, `commerce`, `product`, `offer`, `sku`, `checkout` | 11 | 7/11 | 3 | 4 | 0 | `commerce360` | — |
| [Communications 360](#communications-360) | source_aligned | `message`, `thread`, `profile`, `campaign`, `episode`, `agent`, `journey`, `source` | 11 | 11/11 | 4 | 0 | 0 | `communication360` | — |
| [Episode 360](#episode-360) | source_aligned | `episode`, `session`, `conversation`, `activity_window`, `entity`, `campaign` | 11 | 8/11 | 4 | 3 | 1 | `communication360`, `campaign360`, `episode360`, `profile360`, `relationship360` | — |
| [Execution 360](#execution-360) | source_aligned | `agent`, `entity`, `episode`, `execution`, `workflow_run` | 11 | 11/11 | 6 | 0 | 0 | `execution360` | — |
| [Identity 360](#identity-360) | source_aligned | `entity`, `agent`, `source` | 10 | 10/10 | 2 | 0 | 3 | `agent360`, `execution360`, `profile360`, `relationship360` | `Identity360Provider` (runtime_wired) |
| [Journey 360](#journey-360) | source_aligned | `journey`, `profile`, `account`, `campaign`, `episode`, `entity` | 11 | 8/11 | 6 | 3 | 2 | `episode360`, `profile360`, `communication360` | — |
| [Location 360](#location-360) | source_aligned | `location`, `place`, `geohash`, `timezone`, `region`, `entity`, `population`, `source` | 11 | 5/11 | 2 | 6 | 4 | `geographic360`, `population360`, `profile360` | — |
| [Memory 360](#memory-360) | source_aligned | `entity`, `semantic_entity`, `memory`, `card`, `topic` | 10 | 8/10 | 2 | 2 | 0 | `memory360` | — |
| [Profile 360](#profile-360) | source_aligned | `profile`, `entity`, `agent`, `anonymous_subject`, `account_member`, `cluster` | 13 | 12/13 | 8 | 1 | 6 | `economic360`, `outcome360`, `profile360`, `geographic360`, `relationship360`, `risk360` | — |
| [Risk 360](#risk-360) | source_aligned | `risk`, `entity`, `profile`, `agent`, `account`, `source`, `campaign`, `contagion_path`, `relationship`, `cluster` | 12 | 9/12 | 5 | 3 | 6 | `economic360`, `execution360`, `fraud360`, `relationship360`, `risk360`, `social360` | — |
| [Signals 360](#signals-360) | source_aligned | `entity`, `signal`, `source`, `event`, `observation`, `stream` | 10 | 8/10 | 5 | 2 | 0 | `signals360` | — |
| [Social 360](#social-360) | source_aligned | `entity`, `profile`, `relationship`, `community`, `syndicate`, `source`, `population` | 10 | 7/10 | 4 | 3 | 5 | `geographic360`, `population360`, `relationship360`, `social360`, `source360` | — |
| [Support 360](#support-360) | source_aligned | `support_case`, `callback`, `conversation`, `ticket`, `entity`, `agent`, `episode`, `source` | 10 | 5/10 | 5 | 5 | 6 | `agent360`, `episode360`, `outcome360`, `profile360`, `risk360`, `source360`, `support360` | — |
| [Value 360](#value-360) | source_aligned | `value`, `profile`, `account`, `conversion`, `cluster`, `campaign`, `episode`, `journey`, `entity`, `agent`, `source` | 11 | 11/11 | 9 | 0 | 5 | `campaign360`, `economic360`, `outcome360`, `temporal360`, `risk360` | — |
| [Workflow 360](#workflow-360) | source_aligned | `workflow`, `automation`, `trigger`, `run`, `workflow_run` | 11 | 8/11 | 5 | 3 | 0 | `workflow360` | — |

## Account 360

Product surface id: `account360`
Contract status: `source_aligned`
Subject kinds: `account`, `entity`, `workspace`

Governed account-level view composed from canonical entity, relationship, economic, and evidence authorities.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `account_identity_and_state` | optional |  | `identity`, `entity_registry` | `profile360` (primary): subjects `entity`; `summary`, `state` | — | — | Resolved account identity and state. |
| `account_relationships` | optional |  | `relationship_facts`, `graph` | `relationship360` (primary): subjects `entity`; `summary`, `interactions`, `evidence` | — | — | Relationships associated with the account. |
| `account_summary` | required |  | `entities`, `entity_registry` | — | `Account360Provider` (runtime_wired) | — | Exact tenant organization or account identity; lifecycle coverage remains unknown. |
| `agents` | required |  | `entity_registry`, `graph` | — | `Account360Provider` (runtime_wired) | — | Observed canonical agent members of the account; authority and delegation are evaluated in their owning subsystems. |
| `communications` | required |  | `communication_facts` | `communication360` (primary): subjects `entity`; `evidence`, `interactions`, `timeline` | — | Partial: `Only exact tenant-owned entity subjects are joined; account/workspace aliases and member fanout are unavailable. Communication360 preserves source timestamps but does not evaluate freshness; policy and historical consent remain frame-runtime responsibilities.` | Account communications linked to exact tenant-owned entity participants under governing frame policy, without member fanout. |
| `contracts` | required |  | `commerce` | — | — | Unbound: `canonical_account_contract_authority_not_available` | Canonical account contract and obligation records. |
| `economic_context` | optional |  | `ai_execution_facts`, `economic_facts` | `economic360` (primary): subjects `entity`; `summary`, `evidence`, `outcomes` | — | — | Economic facts associated with the account. |
| `evidence_and_limitations` | optional |  | `evidence` | `profile360` (primary): subjects `entity`; `evidence`, `findings` | — | — | Evidence and coverage for account context. |
| `evidence_trace` | required |  | `evidence` | `profile360` (primary): subjects `entity`; `evidence`, `findings` | — | — | Evidence and limits for the account entity only, not a complete member aggregate. |
| `journeys` | required |  | `journeys` | — | — | Unbound: `account_journey_membership_authority_not_joined` | Journeys directly linked to the account by a canonical relationship. |
| `members` | required |  | `entity_registry`, `graph` | — | `Account360Provider` (runtime_wired) | Partial: `Positive current membership requires a live tenant-scoped MEMBER_OF edge whose exact aggregate replay agrees with the graph candidate and whose member resolves to a tenant entity; the bounded ledger and graph scans do not establish complete roster coverage, historical membership, or freshness.` | Current tenant MEMBER_OF graph edges are candidates only; each positive membership requires an exact live graph mutation-ledger aggregate and canonical member entity. |
| `profiles` | required |  | `identity`, `entity_registry`, `graph` | — | `Account360Provider` (runtime_wired) | Partial: `Bounded exact-member Profile360 frames now run under per-member policy; roster completeness and a profile freshness SLA remain unknown.` | Profile views for validated account members with each profile policy independently applied. |
| `relationships` | required |  | `relationship_facts`, `graph` | `relationship360` (primary): subjects `entity`; `summary`, `interactions`, `evidence` | — | — | Entity scoped relationship evidence for the exact account identity. |
| `risk` | required |  | `graph`, `entity_registry`, `risk_outputs` | — | `Account360Provider` (runtime_wired) | Partial: `Direct account risk remains separate; bounded exact MEMBER_OF member contexts are included only after the account risk slot and each member Risk360 risk_summary policy allow. Roster completeness, related-account aggregation, temporal member-risk reads, and freshness remain unknown.` | Direct account-entity risk plus bounded evidence-backed risk frames for exact tenant-scoped members; roster and risk coverage remain partial. |
| `value` | required |  | `ai_execution_facts`, `economic_facts` | `economic360` (primary): subjects `entity`; `summary` | — | — | Direct entity-scoped economic value for the canonical account profile, without member or execution-cost aggregation. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `communication360` | `catalog_only` (primary) | `implemented` | `communication360.read`, `communication360.explore` |
| `economic360` | `catalog_only` (primary) | `implemented` | `economic360.read`, `economic360.explore` |
| `profile360` | `catalog_only` (primary) | `in_flight` | `profile360.read`, `profile360.explore` |
| `relationship360` | `catalog_only` (primary) | `in_flight` | `relationship360.read`, `relationship360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| `Account360Provider` | `surface_frame_provider` | `runtime_wired` | `entity` | `account_summary`, `members`, `agents`, `profiles`, `risk` | `services/api/identity/account360_provider.py` | `services/api/shared/intelligence_projections/frame_runtime.py` |

### Authority and governance contract

Canonical authorities: `ai_execution_facts`, `commerce`, `communication_facts`, `economic_facts`, `entities`, `entity_registry`, `evidence`, `graph`, `identity`, `journeys`, `relationship_facts`, `risk_outputs`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `8`; lens ids: `account`, `identity`, `relationship`, `journey`, `value`, `communications`, `risk`, `policy`.

## Agent 360

Product surface id: `agent360`
Contract status: `source_aligned`
Subject kinds: `agent`, `entity`

Governed view of an agent identity, actor attribution, authority and delegation, execution activity, communications, risk, evidence, and measured outcomes.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `actor_attribution` | optional |  | `agent_entities`, `identity` | `agent360` (supporting): subjects `agent`, `entity`; `evidence`, `state`; `execution360` (primary): subjects `agent`, `entity`; `evidence`, `state` | — | — | Optional Aether provider context retained for Agent 360: actor attribution. |
| `authority_envelope` | required | `slotActorAttribution`, `slotAuthorityDecision` | `agent_access`, `agent_executions`, `identity` | `agent360` (primary): subjects `agent`, `entity`; `evidence`, `state` | — | — | Observed current capability grants and recorded action-scoped delegation decisions; no standing action or resource authorization verdict. |
| `business_outcomes` | optional |  | `outcome_facts` | `outcome360` (primary): subjects `agent`; `evidence`, `outcomes` | — | — | Optional Aether provider context retained for Agent 360: business outcomes. |
| `capabilities` | required |  | `actions`, `resources`, `tools`, `agent_access` | `agent360` (primary): subjects `agent`, `entity`; `state`, `evidence` | — | Authority: `active_invoke_grants_do_not_evaluate_action_or_resource_specific_policy`; Partial: `current_active_grant_join_is_bounded_to_2000_records_and_does_not_replay_historical_authority` | Observed runtime capability reach joined to exact active invoke grants for the resolved canonical Agent; action and resource authorization remains unknown. |
| `communications` | optional |  | `communication_facts`, `observations` | `agent360` (supporting): subjects `agent`; `interactions`; `communication360` (primary): subjects `agent`; `evidence`, `interactions`, `timeline` | — | — | Optional Aether provider context retained for Agent 360: communications. |
| `delegation_chain` | required | `slotActorAttribution`, `slotAuthorityDecision` | `agent_access`, `identity` | `agent360` (primary): subjects `agent`, `entity`; `evidence`, `state` | — | Partial: `delegation_reads_are_bounded_and_do_not_evaluate_transitive_or_action_resource_authority` | Tenant-scoped stored delegation edges with party identity evidence; no transitive or action-specific authority is inferred. |
| `economic_cost_and_settlement` | optional |  | `ai_execution_facts`, `commerce`, `economic_facts`, `payments` | `economic360` (primary): subjects `agent`, `entity`; `evidence`, `summary` | — | — | Optional Aether provider context retained for Agent 360: economic cost and settlement. |
| `evidence_trace` | required |  | `evidence`, `source_provenance` | `agent360` (supporting): subjects `agent`, `entity`; `evidence` | — | Partial: `Canonical Bronze links are joined to exact tenant, agent, source-row, event, schema, and timestamp references. Registered Rights source identity, source trust, freshness SLA, complete lineage coverage, and unlinked historical rows remain unknown.` | Required Agent 360 blueprint slot: evidence trace. |
| `execution_history` | required |  | `agent_executions`, `execution_facts` | `execution360` (primary): subjects `agent`, `entity`; `evidence`, `state`, `timeline` | — | — | Required Agent 360 blueprint slot: execution history. |
| `identity` | required |  | `agent_entity`, `identity` | `agent360` (primary): subjects `agent`, `entity`; `state`, `summary` | — | — | Required Agent 360 blueprint slot: identity. |
| `owner_delegator` | required | `slotActorAttribution` | `agent_access`, `graph`, `identity` | `agent360` (primary): subjects `agent`, `entity`; `evidence`, `state` | — | Partial: `Configured owner reference is resolved to an exact tenant entity and joined only to an exact tenant graph OWNS or OWNS_AGENT edge targeting the resolved canonical Agent. Legal or effective ownership, action authorization, historical validity, graph completeness, and freshness remain unknown.` | Tenant-scoped owner and delegator records with canonical party identity only where resolved; no effective action authorization is inferred. |
| `policy_boundary` | required |  | `agent_access`, `agent_executions`, `identity` | `agent360` (primary): subjects `agent`, `entity`; `policy_boundary` | — | Partial: `only_stored_execution_time_decisions_are_available_and_standing_policy_is_not_exposed` | Recorded execution-scoped policy decisions; standing agent policy and a new action decision remain unknown. |
| `risk_summary` | required |  | `agent_entities`, `identity`, `relationship_facts`, `risk_outputs`, `social_observations` | `risk360` (primary): subjects `agent`, `entity`; `evidence`, `findings` | — | Authority: `agent_risk_summary_identity_relationship_and_social_authorities_not_fully_joined`; Partial: `Canonical Risk360 evidence requires resolved Agent identity and an affirmative current analytics receipt. The nested read proceeds only after the frame runtime forwards the exact allowed risk_summary slot decision and the bound risk360.read capability. Agent-specific freshness, historical replay, unbound identity and social authority joins, and causal contagion remain unknown.` | Required Agent 360 blueprint slot: risk summary. |
| `spawned_agents` | required |  | `graph`, `relationship_facts`, `temporal` | `relationship360` (primary): subjects `agent`, `entity`; `agent_spawned_agents` | — | — | Required Agent 360 blueprint slot: spawned agents. |
| `tool_usage` | required |  | `actions`, `resources`, `tools` | `execution360` (primary): subjects `agent`, `entity`; `evidence`, `interactions` | — | — | Required Agent 360 blueprint slot: tool usage. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `agent360` | `catalog_only` (primary) | `in_flight` | `agent360.read`, `agent360.explore` |
| `communication360` | `catalog_only` (primary) | `implemented` | `communication360.read`, `communication360.explore` |
| `economic360` | `catalog_only` (primary) | `implemented` | `economic360.read`, `economic360.explore` |
| `execution360` | `catalog_only` (primary) | `in_flight` | `execution360.read`, `execution360.explore` |
| `outcome360` | `catalog_only` (primary) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `relationship360` | `catalog_only` (primary) | `in_flight` | `relationship360.read`, `relationship360.explore` |
| `risk360` | `catalog_only` (primary) | `implemented` | `risk360.read`, `risk360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `actions`, `agent_access`, `agent_entities`, `agent_entity`, `agent_executions`, `ai_execution_facts`, `commerce`, `communication_facts`, `economic_facts`, `evidence`, `execution_facts`, `graph`, `identity`, `observations`, `outcome_facts`, `payments`, `relationship_facts`, `resources`, `risk_outputs`, `social_observations`, `source_provenance`, `temporal`, `tools`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `8`; lens ids: `identity`, `agentic`, `authority`, `execution`, `risk`, `relationship`, `policy`, `provenance`.

## Campaign 360

Product surface id: `campaign360`
Contract status: `source_aligned`
Subject kinds: `campaign`

Governed view of canonical campaign identity, source classification, signals, touchpoints, journeys, conversions, attribution, cohorts, performance, anomalies, and evidence.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `anomalies` | required |  | `targeting_leakage_findings`, `risk_outputs`, `source_provenance` | `campaign360` (primary): subjects `campaign`; `anomalies` | — | Authority: `General campaign risk outputs are not joined by this targeting leakage finding provider.`; Partial: `Exact targeting leakage findings are joined with a bounded evidence chain; general risk outputs and source anomalies remain unknown.` | Tenant-scoped targeting leakage findings backed by source observation and eligibility-snapshot evidence; broader risk and source anomalies stay unknown. |
| `attribution` | required |  | `attribution_credits` | `campaign360` (primary): subjects `campaign`; `evidence`, `outcomes`, `findings` | — | — | Active, evidence-backed attribution credits associated with the campaign. |
| `campaign_identity` | required |  | `campaign_facts` | `campaign360` (primary): subjects `campaign`; `summary`, `state`, `evidence` | — | — | Canonical Aether campaign identity and registered state. |
| `cohorts_syndicates` | required |  | `cluster_definitions`, `cluster_membership`, `cohort_membership`, `relationship_facts` | — | — | Unbound: `No exact campaign-to-cohort or campaign-to-syndicate relationship is currently joined.` | Canonical cohort, cluster, and syndicate memberships associated with the campaign. |
| `conversions` | required |  | `measurement_contract`, `outcome_facts` | `outcome360` (primary): subjects `campaign`; `outcomes`, `evidence` | — | — | Canonical conversion and measured-outcome records scoped to the campaign. |
| `evidence_trace` | required |  | `attribution_credits`, `campaign_facts`, `campaign_touchpoints`, `journeys`, `touchpoints` | `campaign360` (primary): subjects `campaign`; `evidence` | — | — | Source evidence references supporting the campaign frame and its claims. |
| `journeys` | required |  | `journeys` | `campaign360` (primary): subjects `campaign`; `evidence`, `state` | — | — | Current journey versions that explicitly reference this canonical campaign. |
| `performance` | required |  | `ai_execution_facts`, `commerce`, `economic_facts`, `outcome_facts`, `payments` | `economic360` (primary): subjects `campaign`; `summary`, `evidence`, `outcomes` | — | — | Observed economic and outcome performance facts for the campaign. |
| `signal_sources` | required |  | `events`, `observations`, `source_facts` | `campaign360` (primary): subjects `campaign`; `state` | — | Authority: `Canonical observations and source facts are not joined to the exact touchpoint-linked campaign event rows.`; Partial: `Exact campaign touchpoint event references are joined to tenant-scoped canonical events; broader observation and source-fact authorities, complete event coverage, and a freshness SLA remain unresolved.` | Tenant-scoped signal and source observations associated with the campaign. |
| `source_classification` | required |  | `campaign_touchpoints`, `source_facts`, `source_provenance` | `campaign360` (primary): subjects `campaign`; `state`, `evidence` | — | Authority: `Touchpoint classification revisions do not classify the campaign registry source or every asserting source.`; Partial: `Only classified tenant campaign touchpoints on the requested page are joined; campaign registry provenance remains unknown.` | Canonical classification of the source that asserted or synchronized campaign evidence. |
| `touchpoints` | required |  | `campaign_touchpoints`, `communication_facts`, `touchpoints` | `campaign360` (primary): subjects `campaign`; `evidence`, `state`; `communication360` (supporting): subjects `campaign`; `timeline`, `interactions`, `evidence` | — | — | Campaign touchpoints with linked, policy-governed communication evidence. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `campaign360` | `catalog_only` (primary) | `in_flight` | `campaign360.read`, `campaign360.explore` |
| `communication360` | `catalog_only` (supporting) | `implemented` | `communication360.read`, `communication360.explore` |
| `economic360` | `catalog_only` (primary) | `implemented` | `economic360.read`, `economic360.explore` |
| `outcome360` | `catalog_only` (primary) | `implemented` | `outcome360.read`, `outcome360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `attribution_credits`, `campaign_facts`, `campaign_touchpoints`, `cluster_definitions`, `cluster_membership`, `cohort_membership`, `commerce`, `communication_facts`, `economic_facts`, `events`, `journeys`, `measurement_contract`, `observations`, `outcome_facts`, `payments`, `relationship_facts`, `risk_outputs`, `source_facts`, `source_provenance`, `targeting_leakage_findings`, `touchpoints`, `ai_execution_facts`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `8`; lens ids: `campaign`, `signals`, `journey`, `attribution`, `value`, `communications`, `risk`, `provenance`.

## Commerce 360

Product surface id: `commerce360`
Contract status: `source_aligned`
Subject kinds: `entity`, `campaign`, `journey`, `commerce`, `product`, `offer`, `sku`, `checkout`

Governed view of commerce and payment facts, economic value, attributed outcomes, and supporting evidence.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `availability_price` | required |  | `commerce_product_offer_graph`, `source_provenance` | `commerce360` (primary): subjects `product`, `offer`; `availability_price` | — | Partial: `Exact tenant product and offer catalog revisions provide lifecycle and provenance evidence only; inventory availability, current offer price, and freshness remain unknown because their authorities and joins are not connected.` | Exact tenant product or offer catalog lifecycle evidence, with inventory availability, current offer price, and freshness represented independently. |
| `campaign_links` | required |  | `campaign_facts`, `commerce`, `source_provenance` | `commerce360` (primary): subjects `campaign`; `campaign_links` | — | — | Explicit campaign scoped commerce order references. |
| `cart_checkout` | required |  | `commerce` | — | — | Unbound: `commerce_cart_checkout_authority_not_connected` | Required commerce360 slot: cart checkout. |
| `catalog_links` | required |  | `commerce_product_offer_graph`, `source_provenance` | `commerce360` (primary): subjects `product`, `offer`; `catalog_links` | — | Partial: `catalog_link_coverage_is_limited_to_persisted_product_offer_revisions_and_freshness_sla_is_unconfigured` | Offer to product links from exact tenant-scoped catalog revisions. |
| `evidence_trace` | required |  | `commerce`, `payments`, `source_provenance` | `commerce360` (primary): subjects `entity`, `campaign`, `journey`; `evidence_trace` | — | — | Source evidence for exact scoped commerce facts. |
| `exposures` | required |  | `commerce` | — | — | Unbound: `commerce_exposure_subject_join_not_available` | Required commerce360 slot: exposures. |
| `intent` | required |  | `commerce` | — | — | Unbound: `commerce_intent_subject_join_not_available` | Required commerce360 slot: intent. |
| `product_offer_summary` | required |  | `commerce_product_offer_graph`, `source_provenance` | `commerce360` (primary): subjects `product`, `offer`; `product_offer_summary` | — | Partial: `catalog_source_ingestion_coverage_and_freshness_sla_are_unconfigured` | Exact tenant-scoped product and offer revisions by canonical product or offer ID. |
| `purchase` | required |  | `commerce`, `payments`, `source_provenance` | `commerce360` (primary): subjects `entity`, `campaign`, `journey`; `purchase` | — | — | Explicit scoped commerce order and payment fact references. |
| `risk` | required |  | `risk_outputs` | — | — | Unbound: `commerce_risk_subject_join_not_available` | Required commerce360 slot: risk. |
| `value` | required |  | `payments`, `source_provenance` | `commerce360` (primary): subjects `entity`, `campaign`, `journey`; `value` | — | — | Observed purchase amounts and currency without unsupported aggregation. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `commerce360` | `catalog_only` (primary) | `in_flight` | `commerce360.read` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `campaign_facts`, `commerce`, `commerce_product_offer_graph`, `payments`, `risk_outputs`, `source_provenance`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `8`; lens ids: `commerce`, `product-offer`, `campaign`, `journey`, `value`, `identity`, `risk`, `provenance`.

## Communications 360

Product surface id: `communications360`
Contract status: `source_aligned`
Subject kinds: `message`, `thread`, `profile`, `campaign`, `episode`, `agent`, `journey`, `source`

Governed view of communication facts, delivery and engagement evidence, campaign and journey context, and applicable consent policy.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `agent_authorship` | required |  | `communication_facts`, `entities` | `communication360` (primary): subjects `agent`; `interactions`, `evidence` | — | — | Observed agent author bindings; delegation authority remains unjoined. |
| `campaign_links` | required |  | `communication_facts`, `campaign_touchpoints` | `communication360` (primary): subjects `campaign`; `state`, `evidence` | — | — | Explicit campaign scoped communication and touchpoint refs. |
| `evidence_trace` | required |  | `communication_facts`, `evidence` | `communication360` (primary): subjects `agent`, `campaign`; `evidence` | — | — | Communication fact and message evidence with partial source provenance. |
| `journey_links` | required |  | `communication_facts`, `journeys` | `communication360` (primary): subjects `agent`, `campaign`, `episode`, `journey`, `source`; `summary`, `evidence` | — | Partial: `current_explicit_journey_references_only_no_historical_replay` | Explicit journey references on in-scope communication facts resolved to current tenant journey versions. |
| `message_inventory` | required |  | `communication_facts`, `evidence` | `communication360` (primary): subjects `agent`, `campaign`; `timeline`, `evidence` | — | — | Bounded observed message entries with message evidence. |
| `participants` | required |  | `communication_facts`, `entities` | `communication360` (primary): subjects `agent`, `campaign`; `interactions` | — | — | Participant binding rows and endpoint metadata; full role resolution is pending. |
| `policy_state` | required |  | `communication_facts`, `consent_policy_decisions`, `evidence` | `communication360` (primary): subjects `agent`, `campaign`, `episode`, `journey`, `source`; `summary` | — | Partial: `Current consent is evaluated only for exact tenant, recipient-entity, and purpose pairs supported by communication identity and evidence. Historical write-time outcomes are separate; non-consent policy, durable current-decision evidence, complete recipient coverage, and freshness remain unknown.` | Current server-consent decisions for exact tenant-scoped recipient and purpose pairs, separated from historical communication-time decisions. |
| `profile_links` | required |  | `communication_facts`, `evidence`, `identity` | `communication360` (primary): subjects `agent`, `campaign`, `episode`, `journey`, `source`; `summary`, `evidence` | — | Partial: `Explicit profile references are joined to exact tenant profile records only when the communication fact carries evidence. Current profile identity is not a historical identity snapshot; unresolved links, temporal validity, and freshness remain unknown.` | Explicit profile identifiers on evidence-backed communication facts resolved against exact tenant profile records. |
| `response_events` | required |  | `communication_facts` | `communication360` (primary): subjects `agent`, `campaign`; `interactions` | — | — | Observed response-like communication acts; expectations stay distinct. |
| `risk_flags` | required |  | `communication_facts`, `consent_policy_decisions`, `evidence`, `identity`, `risk_outputs`, `risk_signals` | `communication360` (primary): subjects `agent`, `source`; `summary`, `evidence` | — | Authority: `message_scoped_composite_risk_output_not_joined`; Partial: `Source, recipient, and resolved-agent RiskSignal reads require current analytics consent; recipient reads also require exact tenant identity mappings and evidence. Message-edge risk transfer, composite Risk360 output, complete identity/source coverage, and freshness remain unknown.` | Exact-subject canonical RiskSignal records for resolved agents and sources and mapped recipient entities; source and recipient reads are consent-gated, and message-edge propagation is never inferred. |
| `thread_summary` | required |  | `communication_facts` | `communication360` (primary): subjects `agent`, `campaign`; `summary`, `interactions` | — | — | Partial thread counts and canonical thread facts; message-thread composition is incomplete. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `communication360` | `catalog_only` (primary) | `implemented` | `communication360.read`, `communication360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `campaign_touchpoints`, `communication_facts`, `consent_policy_decisions`, `entities`, `evidence`, `identity`, `journeys`, `risk_outputs`, `risk_signals`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `7`; lens ids: `communications`, `identity`, `campaign`, `journey`, `risk`, `policy`, `provenance`.

## Episode 360

Product surface id: `episode360`
Contract status: `source_aligned`
Subject kinds: `episode`, `session`, `conversation`, `activity_window`, `entity`, `campaign`

Governed time-bounded view of related events and journey activity, with entity context, evidence, and optional outcomes.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `agent_handoffs` | required |  | `agent_executions` | — | — | Unbound: `episode_records_and_observations_do_not_reference_canonical_agent_execution_or_handoff_id` | Required episode360 slot: agent handoffs. |
| `attribution_links` | required |  | `attribution_credits` | — | — | Unbound: `episode_attribution_credit_authority_not_joined` | Required episode360 slot: attribution links. |
| `communications` | required |  | `communication_facts` | `communication360` (supporting): subjects `episode`; `interactions` | — | Partial: `episode_communication_facts_are_exact_but_message_spine_join_and_completeness_are_unavailable` | Exact tenant episode_id-linked communication facts; message history and complete conversation membership remain unavailable. |
| `conversion_events` | required |  | `episode_facts`, `outcome_facts`, `evidence` | `episode360` (primary): subjects `episode`; `outcomes` | — | Partial: `Only outcome IDs explicitly recorded by tenant episode rows are joined and admitted for registered campaign_conversion or journey_completion definitions with canonical evidence; these references do not establish complete coverage or causal attribution, and freshness and policy remain unknown.` | Canonical conversion outcomes explicitly referenced by exact tenant episode records; only registered conversion definitions are admitted. |
| `entity_and_relationship_context` | optional |  | `campaign_facts`, `episode_facts`, `graph`, `identity`, `relationship_facts` | `profile360` (primary): subjects `entity`, `episode`; `evidence`, `state`, `summary`; `relationship360` (supporting): subjects `entity`, `episode`; `interactions`, `evidence`; `episode360` (supporting): subjects `campaign`, `entity`, `episode`; `episode_context`; `campaign360` (primary): subjects `campaign`; `evidence`, `state`, `summary` | — | — | Canonical identity for entity and episode subjects, campaign identity for campaign subjects, and graph relationships where the subject has a supported entity graph. |
| `episode_summary` | required |  | `episode_facts`, `evidence` | `episode360` (primary): subjects `episode`; `summary`, `evidence` | — | — | Exact tenant episode record with evidence lineage. |
| `evidence_trace` | required |  | `episode_facts`, `evidence` | `episode360` (primary): subjects `episode`; `evidence` | — | — | Episode record and lineage refs; source event provenance is partial. |
| `participants` | required |  | `episode_facts` | `episode360` (primary): subjects `episode`; `interactions`, `episode_context` | — | — | Primary user or agent subject reference only; full participant resolution is pending. |
| `risk_flags` | required |  | `risk_outputs` | — | — | Unbound: `episode_risk_authority_not_joined` | Required episode360 slot: risk flags. |
| `sessions` | required |  | `episode_facts` | `episode360` (primary): subjects `episode`; `episode_context` | — | — | Primary session reference only; session inventory is pending. |
| `timeline` | required |  | `episode_facts`, `temporal`, `silver_semantic_observations`, `evidence` | `episode360` (primary): subjects `episode`; `timeline` | — | Partial: `Only observation IDs explicitly recorded by episodes are resolved; source namespaces are untyped, broader activity and session completeness is unavailable, and freshness and policy remain unknown.` | Episode observation IDs joined to active tenant-scoped semantic Silver rows with bounded temporal context. |
| `touchpoints` | required |  | `episode_facts`, `campaign_touchpoints` | `episode360` (primary): subjects `episode`; `interactions` | — | Partial: `Only journey_touchpoint_ids explicitly recorded by tenant-scoped EpisodeRecords are resolved to canonical touchpoint rows with evidence. Legacy records, incomplete link inventories, freshness, policy, and attribution links remain unknown.` | Exact tenant touchpoints explicitly linked by canonical episode records; journey touchpoints remain separate from attribution credits. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `communication360` | `catalog_only` (supporting) | `implemented` | `communication360.read`, `communication360.explore` |
| `campaign360` | `catalog_only` (primary) | `in_flight` | `campaign360.read`, `campaign360.explore` |
| `episode360` | `catalog_only` (primary) | `in_flight` | `episode360.read`, `episode360.explore` |
| `profile360` | `catalog_only` (primary) | `in_flight` | `profile360.read`, `profile360.explore` |
| `relationship360` | `catalog_only` (supporting) | `in_flight` | `relationship360.read`, `relationship360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `agent_executions`, `attribution_credits`, `campaign_facts`, `campaign_touchpoints`, `communication_facts`, `episode_facts`, `evidence`, `graph`, `identity`, `outcome_facts`, `relationship_facts`, `risk_outputs`, `silver_semantic_observations`, `temporal`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `8`; lens ids: `activity`, `journey`, `communications`, `campaign`, `identity`, `location`, `risk`, `provenance`.

## Execution 360

Product surface id: `execution360`
Contract status: `source_aligned`
Subject kinds: `agent`, `entity`, `episode`, `execution`, `workflow_run`

Governed view of one execution lifecycle, attributed actors and delegation, action/tool/resource activity, evidence, and outcomes.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `actor_attribution` | required | `slotActorAttribution` | `agent_access`, `agent_entities`, `identity` | `execution360` (supporting): subjects `agent`, `entity`, `episode`, `execution`; `evidence`, `state` | — | — | Required Execution 360 blueprint slot: actor attribution. |
| `approval_chain` | required | `slotActorAttribution`, `slotAuthorityDecision` | `agent_access`, `agent_entities`, `commerce`, `identity` | `execution360` (primary): subjects `agent`, `entity`, `episode`, `execution`; `interactions` | — | Partial: `Execution360 joins exact tenant, admitted execution, approval request, decision, and lifecycle references; stored action/resource conflicts are rejected. Other approval authorities, effective authorization, historical run linkage, full authority-decision coverage, and a freshness threshold remain unknown.` | Exact tenant-scoped x402 commerce approval requests and decisions linked to admitted agent execution records and lifecycle action/resource references where recorded. |
| `authority_check` | required | `slotActorAttribution`, `slotAuthorityDecision` | `agent_access`, `agent_entities`, `identity` | `execution360` (supporting): subjects `agent`, `entity`, `episode`, `execution`; `evidence`, `state` | — | — | Required Execution 360 blueprint slot: authority check. |
| `evidence_trace` | required |  | `evidence`, `source_provenance`, `ai_execution_facts` | `execution360` (primary): subjects `agent`, `entity`, `episode`, `execution`, `workflow_run`; `evidence` | — | Authority: `exact_subject_authority_join_not_implemented`; Partial: `Exact workflow_run execution references include matching invocation evidence; source provenance joins, source telemetry, complete workflow step coverage, and a freshness threshold remain unknown.` | Required Execution 360 blueprint slot: evidence trace. |
| `execution_summary` | required |  | `agent_executions`, `execution_facts`, `ai_execution_facts` | `execution360` (primary): subjects `agent`, `entity`, `episode`, `execution`, `workflow_run`; `state`, `summary` | — | Partial: `For workflow_run subjects, execution evidence is limited to tenant-scoped agent_executions rows whose stored workflow_run_id and invocation IDs match current ai_execution_facts; this does not prove all workflow steps, completion, or external effects.` | Required Execution 360 blueprint slot: execution summary. |
| `failures` | required |  | `agent_executions`, `execution_facts` | `execution360` (primary): subjects `agent`, `entity`, `episode`, `execution`; `state`, `summary` | — | — | Required Execution 360 blueprint slot: failures. |
| `inputs_outputs` | required |  | `actions`, `agent_executions`, `execution_facts`, `resources`, `tools` | `execution360` (primary): subjects `agent`, `entity`, `episode`, `execution`; `evidence`, `interactions`, `state`, `summary`, `timeline` | — | — | Required Execution 360 blueprint slot: inputs outputs. |
| `latency_cost` | required |  | `agent_executions`, `ai_execution_facts`, `economic_facts`, `execution_facts`, `outcome_facts` | `execution360` (primary): subjects `agent`, `entity`, `episode`, `execution`; `state`, `summary` | — | Partial: `AI invocation facts are joined only when tenant, execution action_id, and canonical agent match; selected cost is exposed only with a valid known cost basis. This is not provider/tool execution cost or business value. Other cost authorities, historical replay, complete coverage, and a freshness SLA remain unknown.` | Server lifecycle duration and exact action-linked AI invocation latency and selected-cost evidence by currency. |
| `plan_steps` | required |  | `agent_executions`, `episode_facts`, `events`, `execution_facts`, `temporal_kernel` | `execution360` (primary): subjects `agent`, `entity`, `episode`, `execution`; `episode_context`, `evidence`, `state`, `summary`, `timeline` | — | — | Required Execution 360 blueprint slot: plan steps. |
| `risk_events` | required |  | `agent_executions`, `execution_facts`, `risk_signals`, `risk_assessments` | `execution360` (primary): subjects `agent`, `entity`, `episode`, `execution`; `interactions` | — | Partial: `bounded_execution_subject_risk_signals_and_assessment_snapshots_joined_to_admitted_lifecycle_executions_producer_coverage_history_freshness_and_causality_unknown` | Bounded current RiskSignals and RiskAssessment snapshots joined by exact tenant/execution subject to lifecycle-admitted executions; producer coverage, assessment history, freshness, and causal attribution remain unknown. |
| `tool_calls` | required |  | `actions`, `resources`, `tools` | `execution360` (primary): subjects `agent`, `entity`, `episode`, `execution`; `evidence`, `interactions` | — | Partial: `Exact lifecycle edges are exposed, but source completeness, authorization outcome, and external execution receipt remain unknown.` | Tenant-scoped CALLED_TOOL lifecycle edges joined to admitted executions and canonical agent identity; source completeness and external receipt remain unknown. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `execution360` | `catalog_only` (primary) | `in_flight` | `execution360.read`, `execution360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `actions`, `agent_access`, `agent_entities`, `agent_executions`, `ai_execution_facts`, `commerce`, `economic_facts`, `episode_facts`, `events`, `evidence`, `execution_facts`, `identity`, `outcome_facts`, `resources`, `risk_assessments`, `risk_signals`, `source_provenance`, `temporal_kernel`, `tools`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `8`; lens ids: `execution`, `authority`, `agentic`, `identity`, `policy`, `risk`, `provenance`, `value`.

## Identity 360

Product surface id: `identity360`
Contract status: `source_aligned`
Subject kinds: `entity`, `agent`, `source`

Governed view of resolved identities, source identifiers, actor bindings, relationships, and supporting evidence.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `actor_and_agent_binding` | optional |  | `agent_access`, `agent_entities`, `agent_entity` | `agent360` (primary): subjects `agent`, `entity`; `evidence`, `state`; `execution360` (supporting): subjects `agent`, `entity`; `evidence`, `state` | — | — | Optional Aether provider context retained for Identity 360: actor and agent binding. |
| `aliases` | required |  | `identity`, `evidence` | — | `Identity360Provider` (runtime_wired) | — | Required Identity 360 blueprint slot: aliases. |
| `confidence` | required |  | `identity`, `evidence` | — | `Identity360Provider` (runtime_wired) | — | Required Identity 360 blueprint slot: confidence. |
| `conflicts` | required |  | `identity`, `evidence` | — | `Identity360Provider` (runtime_wired) | — | Required Identity 360 blueprint slot: conflicts. |
| `devices_sessions` | required |  | `identity`, `source_provenance`, `evidence` | — | `Identity360Provider` (runtime_wired) | — | Required Identity 360 blueprint slot: devices sessions. |
| `evidence_trace` | required |  | `identity`, `source_provenance`, `evidence` | — | `Identity360Provider` (runtime_wired) | — | Required Identity 360 blueprint slot: evidence trace. |
| `identifier_inventory` | required |  | `identity`, `source_provenance`, `evidence` | — | `Identity360Provider` (runtime_wired) | — | Required Identity 360 blueprint slot: identifier inventory. |
| `match_evidence` | required |  | `identity`, `entities`, `entity_registry`, `evidence` | — | `Identity360Provider` (runtime_wired) | — | Required Identity 360 blueprint slot: match evidence. |
| `namespace_map` | required |  | `identity`, `provider_registry`, `source_provenance`, `evidence` | — | `Identity360Provider` (runtime_wired) | Partial: `Only exact recorded source_system_id values on tenant- and evidence-validated source identities are resolved; missing provider keys remain unknown and provider registry freshness is unavailable.` | Maps an exact source-system identity namespace to an already registered provider runtime identity without inferring a provider from namespace prefixes. |
| `policy_redactions` | required |  | `identity`, `evidence` | — | `Identity360Provider` (runtime_wired) | — | Required Identity 360 blueprint slot: policy redactions. |
| `relationship_identity_context` | optional |  | `graph`, `relationship_facts` | `relationship360` (primary): subjects `entity`; `evidence`, `interactions` | — | — | Optional Aether provider context retained for Identity 360: relationship identity context. |
| `resolved_subject_identity` | optional |  | `entity_registry`, `identity` | `profile360` (primary): subjects `agent`, `entity`; `state`, `summary` | — | — | Optional Aether provider context retained for Identity 360: resolved subject identity. |
| `wallets` | required |  | `identity`, `source_provenance`, `evidence` | — | `Identity360Provider` (runtime_wired) | Partial: `Historical ownership verification evidence can be surfaced, but wallet inventory and current control are not established.` | Historical canonical-subject-bound wallet verification proofs; wallet inventory and current control remain unknown. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `agent360` | `catalog_only` (primary) | `in_flight` | `agent360.read`, `agent360.explore` |
| `execution360` | `catalog_only` (supporting) | `in_flight` | `execution360.read`, `execution360.explore` |
| `profile360` | `catalog_only` (primary) | `in_flight` | `profile360.read`, `profile360.explore` |
| `relationship360` | `catalog_only` (primary) | `in_flight` | `relationship360.read`, `relationship360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| `Identity360Provider` | `surface_authority_reader` | `runtime_wired` | `agent`, `entity`, `source` | `identifier_inventory`, `namespace_map`, `match_evidence`, `conflicts`, `confidence`, `aliases`, `devices_sessions`, `wallets`, `policy_redactions`, `evidence_trace` | `services/api/identity/identity/identity360_provider.py` | `services/api/shared/intelligence_projections/frame_runtime.py` |

### Authority and governance contract

Canonical authorities: `agent_access`, `agent_entities`, `agent_entity`, `entities`, `entity_registry`, `evidence`, `graph`, `identity`, `provider_registry`, `relationship_facts`, `source_provenance`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `5`; lens ids: `identity`, `provenance`, `policy`, `risk`, `location`.

## Journey 360

Product surface id: `journey360`
Contract status: `source_aligned`
Subject kinds: `journey`, `profile`, `account`, `campaign`, `episode`, `entity`

Governed temporal view of journey state, stages, events, handoffs, and measured outcomes.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `agent_interventions` | required |  | `evidence`, `journeys` | `episode360` (primary): subjects `journey`; `interactions` | — | Partial: `Only current journey version activity IDs join to unique, current tenant-scoped agent-family journey steps with version and step evidence. Canonical agent identity, delegated authority, intervention outcome, and full step-inventory completeness remain unknown.` | Explicit current-journey references to agent-family JourneySteps, with exact step evidence; actor identity, authority, and intervention outcome remain unjoined. |
| `attribution` | required |  | `attribution_credits` | — | — | Unbound: `immutable_attribution_credit_authority_not_joined` | Required journey360 slot: attribution. |
| `communications` | required |  | `communication_facts` | `communication360` (primary): subjects `journey`; `evidence`, `interactions` | — | Partial: `Only tenant-scoped canonical communication facts carrying this exact typed journey ID are joined. Message-spine coverage, completeness, freshness, and historical replay remain unestablished.` | Tenant-scoped canonical communication facts carrying this exact typed journey ID. |
| `conversions` | required |  | `canonical_conversions`, `journeys` | `episode360` (primary): subjects `journey`; `outcomes` | — | Partial: `Only the current journey version's explicit conversion IDs are resolved; wider conversion inventory and historical versions are not established.` | Canonical conversions explicitly referenced by the current JourneyVersion. |
| `dropoffs` | required |  | `outcome_facts` | — | — | Unbound: `journey_dropoff_authority_not_joined` | Required journey360 slot: dropoffs. |
| `entity_context` | optional |  | `episode_facts`, `graph`, `identity`, `journeys` | `profile360` (primary): subjects `entity`, `episode`, `journey`; `summary`, `state`, `evidence` | — | — | Resolved linked user-profile context for entity, journey, or episode subjects; parent identity is not substituted for the requested subject. |
| `episodes` | required |  | `episode_facts` | `episode360` (primary): subjects `journey`; `episode_context` | — | Partial: `Only EpisodeRecords with an explicit journey_id are joined through the tenant-scoped episode store. Legacy or unlinked records, association-population completeness, store freshness, policy, and historical replay remain unknown.` | Tenant-scoped episodes that explicitly record the exact journey ID. |
| `events_and_episode_context` | optional |  | `events`, `episode_facts` | `episode360` (primary): subjects `journey`, `entity`, `episode`; `timeline`, `evidence` | — | — | Events and episode facts associated with the journey. |
| `evidence_trace` | required |  | `journeys`, `campaign_touchpoints`, `evidence` | `episode360` (primary): subjects `journey`; `evidence` | — | — | Journey version, step, and exact touchpoint record refs. |
| `journey_summary` | required |  | `journeys` | `episode360` (primary): subjects `journey`; `summary` | — | Partial: `current_version_only_and_source_freshness_threshold_is_unconfigured` | Exact current JourneyVersion record and version evidence. |
| `recommended_actions` | required |  | `actions` | — | — | Unbound: `governed_journey_recommendation_authority_not_joined` | Required journey360 slot: recommended actions. |
| `stages` | required |  | `journeys` | `episode360` (primary): subjects `journey`; `stages` | — | Partial: `Only persisted explicit journey-role markers are exposed; stage taxonomy and completeness remain unknown.` | Explicit journey-role markers on exact current-version steps; no inferred stage boundaries or taxonomy. |
| `touchpoints` | required |  | `journeys`, `campaign_touchpoints` | `episode360` (primary): subjects `journey`; `timeline`, `evidence` | — | — | Exact tenant touchpoints named by current JourneyVersion references. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `episode360` | `catalog_only` (primary) | `in_flight` | `episode360.read`, `episode360.explore` |
| `profile360` | `catalog_only` (primary) | `in_flight` | `profile360.read`, `profile360.explore` |
| `communication360` | `catalog_only` (primary) | `implemented` | `communication360.read`, `communication360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `actions`, `attribution_credits`, `campaign_touchpoints`, `canonical_conversions`, `communication_facts`, `episode_facts`, `events`, `evidence`, `graph`, `identity`, `journeys`, `outcome_facts`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `9`; lens ids: `journey`, `activity`, `campaign`, `communications`, `value`, `identity`, `agentic`, `location`, `risk`.

## Location 360

Product surface id: `location360`
Contract status: `source_aligned`
Subject kinds: `location`, `place`, `geohash`, `timezone`, `region`, `entity`, `population`, `source`

Governed view of locations and geographic observations linked to entities, populations, and temporal context.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `activity_density` | required |  | `geo_observations`, `gold_temporal_heatmap` | `geographic360` (primary): subjects `entity`; `state` | — | Partial: `The exact entity heatmap supplies temporal counts but has no join from a count to a particular location fact or place.` | Tenant scoped density aggregation with location privacy. |
| `campaigns` | required |  | `campaign_facts`, `locations` | — | — | Unbound: `exact_location_campaign_join_unavailable` | Exact campaigns linked to a canonical location fact. |
| `entity_graph_context` | optional |  | `entity_graph`, `graph` | `geographic360` (primary): subjects `entity`, `population`, `source`; `summary`, `findings`; `profile360` (supporting): subjects `entity`; `summary`, `findings` | — | — | Entity graph context linked to locations. |
| `evidence_trace` | required |  | `locations`, `context_capsules` | `geographic360` (primary): subjects `entity`, `population`, `source`; `evidence`, `state` | — | — | Location fact and source observation references at allowed precision. |
| `geo_hierarchy` | required |  | `locations`, `geo_observations` | `geographic360` (primary): subjects `entity`, `population`, `source`; `state`, `evidence` | — | — | Recorded geographic labels at source supported precision. |
| `geographic_observations` | optional |  | `geo_observations`, `temporal` | `geographic360` (primary): subjects `entity`, `population`, `source`; `timeline`, `evidence` | — | — | Observed geographic facts and their temporal context. |
| `journeys` | required |  | `journeys`, `locations` | — | — | Unbound: `exact_location_journey_join_unavailable` | Exact journeys linked to a canonical location fact. |
| `location_identity_and_state` | optional |  | `locations`, `context_capsules` | `geographic360` (primary): subjects `entity`, `population`, `source`; `summary`, `state`, `evidence` | — | — | Location registry and geographic context. |
| `normalization` | required |  | `locations` | `geographic360` (primary): subjects `entity`, `population`, `source`; `normalization` | — | Partial: `Canonical location fact source links are surfaced, but normalization and validation versions, raw record refs, and normalization timestamps are unavailable.` | Source links recorded on canonical location facts, without claiming transformation-version or normalization-time lineage. |
| `place_summary` | required |  | `locations`, `geo_observations`, `context_capsules` | `geographic360` (primary): subjects `entity`, `population`, `source`; `summary`, `state` | — | — | Best supported place fact at policy capped precision. |
| `population_context` | optional |  | `population_definitions`, `cohort_membership` | `population360` (primary): subjects `entity`, `population`; `summary`, `state`, `findings` | — | — | Population context for a location. |
| `profiles` | required |  | `identity`, `locations` | — | — | Unbound: `exact_location_profile_join_and_policy_unavailable` | Profiles linked to place with profile policy applied. |
| `risk` | required |  | `risk_outputs`, `locations` | — | — | Unbound: `exact_location_risk_join_unavailable` | Risk outputs linked to place with evidence. |
| `timezone` | required |  | `temporal`, `locations` | — | — | Unbound: `canonical_timezone_authority_not_joined` | Verified time zone and temporal conversion evidence. |
| `value` | required |  | `economic_facts`, `locations` | — | — | Unbound: `exact_location_value_join_unavailable` | Economic facts linked to place without subject inference. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `geographic360` | `catalog_only` (primary) | `implemented` | `geographic360.read`, `geographic360.explore` |
| `population360` | `catalog_only` (primary) | `implemented` | `population360.read`, `population360.explore` |
| `profile360` | `catalog_only` (supporting) | `in_flight` | `profile360.read`, `profile360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `campaign_facts`, `cohort_membership`, `context_capsules`, `economic_facts`, `entity_graph`, `geo_observations`, `gold_temporal_heatmap`, `graph`, `identity`, `journeys`, `locations`, `population_definitions`, `risk_outputs`, `temporal`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `8`; lens ids: `location`, `identity`, `journey`, `signals`, `campaign`, `value`, `risk`, `provenance`.

## Memory 360

Product surface id: `memory360`
Contract status: `source_aligned`
Subject kinds: `entity`, `semantic_entity`, `memory`, `card`, `topic`

Governed temporal and evidentiary view of entity and agent history, episodes, and observed state; it does not own memory truth.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `cards` | required |  | `semantic_memory_graph` | — | — | Unbound: `canonical_context_card_authority_not_available` | Required memory360 slot: cards. |
| `conflicts` | required |  | `semantic_memory_graph` | `memory360` (primary): subjects `entity`, `semantic_entity`; `conflicts` | — | — | Derived contradiction signal only; canonical conflict objects remain unknown. |
| `decay` | required |  | `semantic_memory_graph` | `memory360` (primary): subjects `entity`, `semantic_entity`; `decay` | — | — | Reducer half-life parameter only; per-memory decay remains unknown. |
| `embeddings_meta` | required |  | `semantic_memory_graph` | — | — | Unbound: `canonical_embedding_metadata_authority_not_available` | Required memory360 slot: embeddings meta. |
| `evidence_trace` | required |  | `semantic_memory_graph`, `evidence` | `memory360` (primary): subjects `entity`, `semantic_entity`; `evidence_trace` | — | — | Gold and active Silver semantic record lineage. |
| `memories` | required |  | `semantic_memory_graph`, `semantic_memory_records`, `silver_semantic_observations`, `consent_policy_decisions` | `memory360` (primary): subjects `entity`, `semantic_entity`; `memories` | — | Partial: `Only explicit stored memories with exact source and historical consent-decision evidence are read; no automatic memory producer or configured freshness SLA is available.` | Required memory360 slot: memories. |
| `policy_state` | required |  | `semantic_memory_records`, `consent_policy_decisions`, `evidence` | `memory360` (primary): subjects `entity`, `semantic_entity`; `policy_state` | — | Partial: `Exact tenant and subject historical allow decisions are rendered with timestamped canonical consent-policy evidence. Current consent and policy are not evaluated, so present authorization remains unknown.` | Required memory360 slot: policy state. |
| `semantic_summary` | required |  | `semantic_memory_graph` | `memory360` (primary): subjects `entity`, `semantic_entity`; `semantic_summary` | — | — | Current Gold semantic entity state with explicit scope and provenance. |
| `source_links` | required |  | `semantic_memory_graph`, `source_provenance` | `memory360` (primary): subjects `entity`, `semantic_entity`; `source_links` | — | — | Exact tenant scoped semantic observation source event references. |
| `topics` | required |  | `semantic_memory_graph` | `memory360` (primary): subjects `entity`, `semantic_entity`; `topics` | — | — | Derived reducer topic labels with inferred epistemic state. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `memory360` | `catalog_only` (primary) | `in_flight` | `memory360.read` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `consent_policy_decisions`, `evidence`, `semantic_memory_records`, `semantic_memory_graph`, `silver_semantic_observations`, `source_provenance`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `6`; lens ids: `semantic-memory`, `topic`, `identity`, `provenance`, `risk`, `policy`.

## Profile 360

Product surface id: `profile360`
Contract status: `source_aligned`
Subject kinds: `profile`, `entity`, `agent`, `anonymous_subject`, `account_member`, `cluster`

Governed entity-level contextual frame combining identity, observations, relationships, evidence, and optional risk and value context.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `agent_delegations` | required |  | `agent_access`, `agent_executions`, `identity` | `profile360` (primary): subjects `agent`, `entity`; `agent_delegations` | — | Partial: `Exact Agent subjects and canonical Agent entities reuse Agent360 identity and delegation evidence; unbound profile links, historical replay, effective authorization, and freshness remain unknown.` | Current delegation and action-scoped authority evidence for an exact Agent subject or canonical Agent entity; unbound profiles remain unknown. |
| `communications` | required |  | `communication_facts` | `profile360` (primary): subjects `entity`; `interactions` | — | Partial: `recipient_message_history_is_bounded_and_sender_thread_semantics_and_freshness_sla_are_unverified` | Exact tenant-scoped recipient messages for a resolved profile entity with recorded consent; sender identity, unknown consent, threads, and semantic interaction remain unknown. |
| `economic_value_context` | optional |  | `ai_execution_facts`, `economic_facts`, `outcome_facts` | `economic360` (primary): subjects `entity`, `agent`; `summary`, `evidence`, `outcomes`; `outcome360` (supporting): subjects none; `outcomes`, `evidence` | — | — | Economic facts and measured outcomes. |
| `entity_identity` | optional |  | `identity`, `entity_registry` | `profile360` (primary): subjects `entity`, `agent`; `summary`, `state` | — | — | Resolved entity identity and registry context. |
| `evidence_and_limitations` | optional |  | `evidence` | `profile360` (primary): subjects `entity`, `agent`; `evidence`, `findings` | — | — | Evidence supporting the displayed profile claims. |
| `evidence_trace` | required |  | `evidence` | `profile360` (primary): subjects `entity`; `evidence`, `findings` | — | — | Source references and coverage limits for the exact tenant profile. |
| `identity_spine` | required |  | `identity`, `entity_registry` | `profile360` (primary): subjects `entity`; `summary`, `state` | — | — | Exact tenant profile and canonical entity identity; other identifier resolution remains unknown. |
| `journey_participation` | required |  | `journeys` | `profile360` (primary): subjects `entity`; `journeys` | — | — | Current journey versions joined by exact tenant and typed profile ID; history and completeness remain explicit. |
| `known_unknown_resolution` | required |  | `identity`, `entity_registry` | `profile360` (primary): subjects `entity`; `summary`, `state` | — | — | Known canonical entity identity and stated unresolved limits, without inferring an anonymous match. |
| `likely_next_states` | required |  | `model_governance`, `outcome_facts` | — | — | Unbound: `profile_prediction_authority_not_available` | Evidence backed future states when an approved model supplies them. |
| `location_temporal` | required |  | `geo_observations`, `temporal` | `geographic360` (primary): subjects `entity`; `evidence`, `timeline` | — | Partial: `The source reports recorded entity location facts only; profile alias resolution, continuous trajectory reconstruction, cross-surface completeness, historical point-in-time reconstruction, and Profile-specific freshness remain unknown.` | Tenant-scoped observed location facts and their recorded temporal bounds for the exact entity subject. |
| `observed_state_and_activity` | optional |  | `observations`, `graph`, `temporal` | `profile360` (primary): subjects `entity`, `agent`; `state`, `timeline`, `interactions` | — | — | Observed state and temporal activity with explicit provenance. |
| `relationship_context` | optional |  | `relationship_facts` | `relationship360` (primary): subjects `entity`; `interactions`, `timeline`, `evidence` | — | — | Relationships around the entity. |
| `relationships` | required |  | `graph`, `relationship_facts` | `relationship360` (primary): subjects `entity`; `evidence`, `interactions`, `summary` | — | Partial: `Relationship360 reads the exact tenant entity from the graph mutation ledger; profile/member alias resolution, a ledger completeness watermark, and Profile-specific freshness remain unknown.` | Tenant-scoped canonical graph relationships observed for the exact entity subject; no profile, account-member, or alias identity is inferred. |
| `risk_context` | optional |  | `risk_outputs`, `model_governance` | `risk360` (primary): subjects `entity`; `summary`, `findings`, `evidence` | — | — | Governed risk and fraud context. |
| `risk_summary` | required |  | `evidence`, `risk_outputs` | `risk360` (primary): subjects `agent`, `entity`; `evidence`, `findings`, `state`, `summary` | — | Partial: `Risk assessment and evidence reads bind by exact tenant, subject kind, and subject ID; a Profile-specific freshness threshold remains unknown.` | Tenant-exact Risk360 assessment and evidence for the same canonical entity or Agent subject; no profile identity is inferred. |
| `session_history` | required |  | `identity` | `profile360` (primary): subjects `entity`; `sessions` | — | Partial: `event_session_timeline_and_complete_roster_not_available` | Resolved source identities with session identifiers linked to the exact canonical profile; event timeline and completeness remain unknown. |
| `syndicates` | required |  | `cohort_membership`, `evidence`, `population_definitions` | `profile360` (primary): subjects `entity`; `syndicates` | — | Partial: `Exact current MEMBER_OF edges for explicitly opted-in tenant populations are evidence-backed; unbounded roster completeness, historical replay, and a membership freshness policy remain unavailable.` | Exact current tenant entity membership in an explicitly opted-in Syndicates population, verified by the live graph ledger edge. |
| `value_summary` | required |  | `ai_execution_facts`, `economic_facts`, `outcome_facts` | `economic360` (primary): subjects `agent`, `entity`; `evidence`, `summary` | — | Partial: `Economic360 reads exact tenant-scoped economic facts for canonical entity and Agent subjects; Outcome360 does not yet support exact entity/profile subjects for attributed outcomes, and Profile-specific freshness remains unknown.` | Direct tenant-scoped economic facts for the exact canonical entity or Agent subject; measured outcomes and attribution remain unresolved. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `economic360` | `catalog_only` (primary) | `implemented` | `economic360.read`, `economic360.explore` |
| `outcome360` | `catalog_only` (supporting) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `profile360` | `catalog_only` (primary) | `in_flight` | `profile360.read`, `profile360.explore` |
| `geographic360` | `catalog_only` (primary) | `implemented` | `geographic360.read`, `geographic360.explore` |
| `relationship360` | `catalog_only` (primary) | `in_flight` | `relationship360.read`, `relationship360.explore` |
| `risk360` | `catalog_only` (primary) | `implemented` | `risk360.read`, `risk360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `agent_access`, `agent_executions`, `ai_execution_facts`, `cohort_membership`, `communication_facts`, `economic_facts`, `entity_registry`, `evidence`, `geo_observations`, `graph`, `identity`, `journeys`, `model_governance`, `observations`, `population_definitions`, `outcome_facts`, `relationship_facts`, `risk_outputs`, `temporal`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `10`; lens ids: `identity`, `journey`, `communications`, `agentic`, `relationship`, `value`, `risk`, `location`, `campaign`, `provenance`.

## Risk 360

Product surface id: `risk360`
Contract status: `source_aligned`
Subject kinds: `risk`, `entity`, `profile`, `agent`, `account`, `source`, `campaign`, `contagion_path`, `relationship`, `cluster`

Governed view of risk findings, evidence, relationship and economic exposure, with explicit coverage and uncertainty.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `agent_amplification` | required |  | `risk_outputs`, `evidence` | `risk360` (primary): subjects `agent`; `evidence`, `findings`, `health` | — | — | Persisted agentic delegation abuse signal only for exact agent subject. |
| `anomaly_events` | required |  | `risk_outputs`, `observations` | — | — | Unbound: `canonical_anomaly_event_authority_not_connected` | Typed anomaly event records. |
| `audit_history` | required |  | `computation`, `evidence`, `risk_assessments` | `risk360` (primary): subjects `agent`, `cluster`, `contagion_path`, `entity`, `relationship`, `source`; `evidence`, `findings` | — | Partial: `assessment_run_history_available_intervention_audit_and_full_restatement_lineage_unavailable` | Versioned risk assessment and intervention audit lineage. |
| `economic_exposure` | optional |  | `ai_execution_facts`, `economic_facts` | `economic360` (primary): subjects `entity`, `agent`; `summary`, `evidence`, `outcomes` | — | — | Economic facts associated with the risk subject and network. |
| `evidence_trace` | required |  | `evidence`, `flow_trace_paths`, `flow_traces`, `risk_assessments`, `risk_outputs`, `risk_signals`, `source_provenance`, `transfers` | `risk360` (primary): subjects `agent`, `cluster`, `contagion_path`, `entity`, `relationship`, `source`; `evidence`, `findings`, `health` | — | — | Exact assessment, signal, and source ingress evidence references. |
| `execution_exposure` | optional |  | `execution_facts` | `execution360` (primary): subjects `entity`, `agent`; `summary`, `timeline`, `evidence` | — | — | Execution facts associated with an agent or execution subject. |
| `financial_contagion` | required |  | `flow_trace_paths`, `flow_traces`, `transfers`, `risk_assessments`, `risk_signals` | `risk360` (primary): subjects `contagion_path`; `findings` | — | Partial: `causal_contagion_exposure_and_loss_model_not_available` | Exact financial transfer path linked to risk evidence for each node; causal contagion, exposure, and loss remain unproven. |
| `fraud_and_social_patterns` | optional |  | `fraud_synthesis`, `graph_motifs`, `social_observations` | `fraud360` (primary): subjects `entity`, `relationship`, `agent`; `findings`, `evidence`, `health`; `social360` (supporting): subjects `entity`, `relationship`; `findings`, `evidence` | — | — | Fraud synthesis, graph motifs, and social observations. |
| `interventions` | required |  | `actions`, `risk_outputs` | — | — | Unbound: `risk_intervention_authority_not_connected` | Recorded risk interventions and results. |
| `poisoning_evidence` | required |  | `risk_outputs`, `source_provenance` | `risk360` (primary): subjects `agent`, `cluster`, `contagion_path`, `entity`, `relationship`, `source`; `evidence`, `findings` | — | Partial: `Risk360 reads explicitly stored detector evidence for exact tenant and subject bindings, with temporal anchors, lifecycle, restatement lineage, and evidence references. Detector coverage, independent source verification, population-wide completeness, and a source freshness SLA remain unknown.` | Tenant-scoped detector evidence for exact subjects, with versioned lifecycle and evidence references; detector completeness and source reputation remain unknown. |
| `policy_flags` | required |  | `model_governance`, `risk_outputs`, `risk_signals` | `risk360` (primary): subjects `agent`; `evidence`, `findings` | — | Partial: `Only exact tenant-scoped current agent risk-signal records are exposed as reported observations. Policy evaluation, model/version, non-agent subjects, historical replay, and complete coverage remain unknown.` | Exact agent risk-signal policy-flag observations with evidence; evaluated flags require versioned model-governance decisions. |
| `propagation_paths` | required |  | `graph`, `relationship_facts`, `consent_policy_decisions`, `evidence` | `risk360` (primary): subjects `entity`; `findings` | — | Partial: `Bounded current tenant-scoped FOLLOWS paths are emitted only with analytics consent, canonical graph and relationship evidence, exact endpoint scope, valid edge state, and acceptable evidence times. Observed edges do not prove causal risk propagation; historical reads, complete path coverage, and freshness remain unknown.` | Observed, consent-governed social graph paths used as risk investigation context; path evidence alone does not establish risk propagation. |
| `relationship_network_context` | optional |  | `entity_graph`, `relationship_facts`, `graph` | `relationship360` (primary): subjects `agent`, `entity`, `relationship`; `summary`, `interactions`, `evidence`; `risk360` (supporting): subjects `entity`, `relationship`, `cluster`; `summary`, `evidence` | — | — | Entity graph and relationship evidence relevant to risk. |
| `risk_assessment_state` | optional |  | `risk_outputs`, `model_governance` | `risk360` (primary): subjects `agent`, `entity`, `relationship`, `cluster`; `summary`, `state`, `findings`, `health` | — | — | Risk outputs, model governance context, and assessment state. |
| `risk_evidence_and_limitations` | optional |  | `evidence` | `risk360` (primary): subjects `agent`, `entity`, `relationship`, `cluster`; `evidence`, `findings` | — | — | Evidence and limitations supporting risk findings. |
| `risk_summary` | required |  | `risk_outputs`, `evidence` | `risk360` (primary): subjects `agent`, `cluster`, `entity`, `relationship`, `source`; `summary`, `state`, `evidence`, `findings` | — | — | Exact scoped canonical assessment and dimension state with evidence and confidence. |
| `social_contagion` | required |  | `social_observations`, `risk_outputs` | — | — | Unbound: `social_contagion_causal_authority_not_connected` | Social contagion supported by exact propagation evidence. |
| `source_trust` | required |  | `source_provenance` | `risk360` (primary): subjects `source`; `health`, `findings`, `evidence` | — | — | Gateway stamped ingress classification for an exact source subject; reliability remains unknown. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `economic360` | `catalog_only` (primary) | `implemented` | `economic360.read`, `economic360.explore` |
| `execution360` | `catalog_only` (primary) | `in_flight` | `execution360.read`, `execution360.explore` |
| `fraud360` | `catalog_only` (primary) | `implemented` | `fraud360.read`, `fraud360.explore` |
| `relationship360` | `catalog_only` (primary) | `in_flight` | `relationship360.read`, `relationship360.explore` |
| `risk360` | `catalog_only` (primary) | `implemented` | `risk360.read`, `risk360.explore` |
| `social360` | `catalog_only` (supporting) | `in_flight` | `social360.read`, `social360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `actions`, `ai_execution_facts`, `consent_policy_decisions`, `computation`, `economic_facts`, `entity_graph`, `evidence`, `execution_facts`, `flow_trace_paths`, `flow_traces`, `fraud_synthesis`, `graph`, `graph_motifs`, `model_governance`, `observations`, `relationship_facts`, `risk_assessments`, `risk_outputs`, `risk_signals`, `social_observations`, `source_provenance`, `transfers`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `9`; lens ids: `risk`, `provenance`, `policy`, `identity`, `relationship`, `social`, `value`, `agentic`, `communications`.

## Signals 360

Product surface id: `signals360`
Contract status: `source_aligned`
Subject kinds: `entity`, `signal`, `source`, `event`, `observation`, `stream`

Governed view of risk, fraud, source, social, and outcome signals with evidence and freshness status.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `campaign_links` | required |  | `campaign_facts`, `campaign_touchpoints` | `signals360` (primary): subjects `event`, `observation`; `campaign_links` | — | Partial: `Only exact event or observation IDs linked by tenant-scoped campaign touchpoints and resolved to canonical tenant campaigns are available; entity, source, stream, missing-reference, and incomplete reads remain unknown or degraded.` | Exact tenant source-event links from campaign touchpoints, admitted only after the campaign owner resolves the referenced canonical campaign. |
| `classification` | required |  | `events`, `observations` | `signals360` (primary): subjects `event`, `observation`; `classification` | — | Partial: `Exact gateway-accepted SDK event type and family are registry-validated; source attribution, semantic signal classification, policy, and freshness remain unknown.` | Required signals360 slot: classification. |
| `evidence_trace` | required |  | `behavioral_signals` | `signals360` (primary): subjects `entity`; `evidence_trace` | — | — | Evidence references for bounded derived signal records. |
| `freshness` | required |  | `behavioral_signals` | `signals360` (primary): subjects `entity`; `freshness` | — | — | Source timestamps retained from bounded derived signal records; freshness threshold remains unknown. |
| `linked_entities` | required |  | `behavioral_signals`, `identity` | `signals360` (primary): subjects `signal`, `event`, `observation`; `linked_entities` | — | Partial: `Exact links are emitted for signal, event, and matching observation IDs; entity, source, stream, absent-link, and incomplete reads remain unknown or degraded.` | Exact tenant signal, event, or observation bindings to active canonical identity subjects; observation IDs join only when recorded as the matching source_event_id. |
| `normalization` | required |  | `observations`, `source_schema` | — | — | Unbound: `canonical_observation_normalization_read_not_joined` | Required signals360 slot: normalization. |
| `quality` | required |  | `ingestion_health`, `source_schema`, `observations` | `signals360` (primary): subjects `event`, `observation`; `quality` | — | Authority: `source_reliability_and_semantic_quality_authorities_not_joined`; Partial: `gateway_acceptance_only_no_reliability_semantic_quality_or_freshness_sla` | Exact SDK Bronze gateway acceptance for an event or observation; source reliability and semantic quality remain unknown. |
| `risk_flags` | required |  | `risk_outputs` | — | — | Unbound: `canonical_signal_risk_join_not_available` | Required signals360 slot: risk flags. |
| `signal_summary` | required |  | `behavioral_signals` | `signals360` (primary): subjects `entity`; `signal_summary` | — | — | Bounded tenant and entity scoped translator-derived signal records. |
| `source_inventory` | required |  | `source_facts`, `source_provenance` | `signals360` (primary): subjects `event`, `observation`; `source_inventory` | — | Authority: `This read is limited to authenticated Envelope-B metadata on one SDK event and does not join a tenant source registry or inventory.`; Partial: `Only one exact SDK event or observation is described; the provider cannot enumerate sources or establish source reliability.` | Authenticated source metadata for an exact SDK event or observation; fleet inventory remains unknown. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `signals360` | `catalog_only` (primary) | `in_flight` | `signals360.read` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `behavioral_signals`, `campaign_facts`, `campaign_touchpoints`, `events`, `identity`, `ingestion_health`, `observations`, `risk_outputs`, `source_facts`, `source_provenance`, `source_schema`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `7`; lens ids: `event-signal`, `provenance`, `campaign`, `identity`, `risk`, `location`, `policy`.

## Social 360

Product surface id: `social360`
Contract status: `source_aligned`
Subject kinds: `entity`, `profile`, `relationship`, `community`, `syndicate`, `source`, `population`

Governed view of social observations, source-backed relationships, evidence, and optional population or geographic context.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `communities` | required |  | `social_observations` | `social360` (primary): subjects `entity`, `relationship`, `source`, `population`; `findings`, `evidence` | — | — | Recorded Social Silver community membership observations. |
| `evidence_and_coverage` | optional |  | `evidence`, `source_coverage`, `identity`, `cohort_membership` | `social360` (primary): subjects `entity`, `relationship`, `source`, `population`; `evidence`, `findings`; `source360` (supporting): subjects `source`; `evidence`, `coverage` | — | — | Evidence and source coverage for social claims. |
| `evidence_trace` | required |  | `evidence`, `social_observations` | `social360` (primary): subjects `entity`, `relationship`, `source`, `population`; `evidence` | — | — | Source references for exact scoped social observations. |
| `geographic_context` | optional |  | `geo_observations`, `locations` | `geographic360` (primary): subjects `entity`, `source`, `population`; `summary`, `timeline`, `evidence` | — | — | Location context for social observations. |
| `influence_paths` | required |  | `computation`, `graph`, `influence_propagation`, `relationship_facts`, `relationship_fidelity`, `relationship_predicate_registry` | `social360` (primary): subjects `entity`, `relationship`; `influence` | — | Partial: `bounded_paths_and_exact_m7_evidence_join_only_component_measurements_may_be_partial_completeness_freshness_and_causality_unknown` | Bounded evidence-backed directed FOLLOWS paths enriched with exact per-hop persisted RelationshipFidelity measurements when their evidence fully matches the graph relationship facts. Paths do not establish actual influence, trust, or causal contagion. |
| `multi_hop_paths` | required |  | `graph`, `relationship_facts` | `social360` (primary): subjects `entity`; `paths` | — | Partial: `bounded_observed_paths_only_no_exhaustive_or_causal_social_semantics` | Bounded observed FOLLOWS edge sequences for an exact entity; no transitive trust, influence, or exhaustive path claim. |
| `population_context` | optional |  | `population_definitions`, `cohort_membership` | `population360` (primary): subjects `entity`, `population`; `summary`, `state`, `evidence` | — | — | Population and cohort context for social observations. |
| `propagation` | required |  | `graph`, `influence_propagation`, `relationship_facts`, `relationship_predicate_registry`, `social_observations` | `social360` (primary): subjects `entity`, `relationship`; `propagation` | — | Partial: `bounded_observed_paths_have_no_component_measurements_or_completeness_and_freshness_sla` | Exact tenant-scoped, consent-authorized FOLLOWS paths whose predicates permit propagation analysis; component measurements and full path completeness remain unavailable. |
| `relationship_graph` | optional |  | `relationship_facts`, `graph`, `identity`, `cohort_membership` | `relationship360` (primary): subjects `entity`, `relationship`, `source`, `population`; `summary`, `interactions`, `evidence` | — | — | Relationship facts and graph context. |
| `relationship_map` | required |  | `social_observations` | `social360` (primary): subjects `entity`, `relationship`, `source`, `population`; `findings`, `evidence` | — | — | Recorded Social Silver connection facts; not canonical graph edges. |
| `risk_edges` | required |  | `risk_outputs`, `graph` | — | — | Unbound: `social_risk_edge_derivation_not_connected` | Policy governed risk relationship edges. |
| `social_contagion` | required |  | `risk_outputs`, `social_observations` | — | — | Unbound: `social_contagion_causal_evidence_authority_unavailable` | Causal contagion evidence with source trust and policy. |
| `social_observations_and_sources` | optional |  | `social_observations`, `source_facts`, `identity`, `cohort_membership` | `social360` (primary): subjects `entity`, `relationship`, `source`, `population`; `summary`, `timeline`, `interactions`, `evidence` | — | — | Social observations and their source facts. |
| `syndicates` | required |  | `cohort_membership`, `evidence`, `graph`, `population_definitions` | `social360` (primary): subjects `entity`; `syndicates` | — | Partial: `membership_roster_completeness_historical_replay_and_freshness_remain_unknown` | Verified syndicate membership and topology. |
| `trust_edges` | required |  | `relationship_facts` | — | — | Unbound: `social_trust_edge_derivation_not_connected` | Policy governed trust relationship edges. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `geographic360` | `catalog_only` (primary) | `implemented` | `geographic360.read`, `geographic360.explore` |
| `population360` | `catalog_only` (primary) | `implemented` | `population360.read`, `population360.explore` |
| `relationship360` | `catalog_only` (primary) | `in_flight` | `relationship360.read`, `relationship360.explore` |
| `social360` | `catalog_only` (primary) | `in_flight` | `social360.read`, `social360.explore` |
| `source360` | `catalog_only` (supporting) | `in_flight` | `source360.read`, `source360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `cohort_membership`, `computation`, `evidence`, `geo_observations`, `graph`, `identity`, `influence_propagation`, `locations`, `population_definitions`, `relationship_facts`, `relationship_fidelity`, `relationship_predicate_registry`, `risk_outputs`, `social_observations`, `source_coverage`, `source_facts`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `8`; lens ids: `relationship`, `social`, `syndicate`, `identity`, `risk`, `communications`, `value`, `provenance`.

## Support 360

Product surface id: `support360`
Contract status: `source_aligned`
Subject kinds: `support_case`, `callback`, `conversation`, `ticket`, `entity`, `agent`, `episode`, `source`

Governed support context composed from communications, episodes and journeys, entity identity, and evidence.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `agents` | required |  | `agent_entities`, `communication_facts` | — | — | Unbound: `canonical_support_case_agent_assignment_unavailable` | Validated support agent assignments and handoffs. |
| `callbacks` | required |  | `communication_facts` | — | — | Unbound: `canonical_support_callback_authority_unavailable` | Canonical callback schedule and execution records. |
| `case_summary` | required |  | `support_cases`, `support_case_events`, `provider_connections`, `evidence` | `support360` (primary): subjects `support_case`; `summary`, `state`, `evidence` | — | Partial: `persisted_case_events_do_not_prove_source_history_completeness_or_freshness_sla` | Exact tenant-owned support case identity and observed lifecycle state from persisted source events. |
| `conversation_history` | required |  | `communication_facts`, `evidence`, `provider_connections`, `support_cases`, `support_case_events` | `support360` (primary): subjects `entity`, `support_case`; `interactions` | — | Partial: `Canonical support_case history joins only through the exact tenant, provider connection, and source case key; message bodies and participant identities stay suppressed without their separate authorities, source-history completeness is unverified, and no freshness SLA is available.` | Tenant scoped support communication metadata; bodies require separate content permission. |
| `entity_and_agent_context` | optional |  | `identity`, `agent_entity` | `profile360` (primary): subjects `entity`, `agent`; `summary`, `state`; `agent360` (supporting): subjects `entity`, `agent`; `summary`, `state`, `evidence` | — | — | Identity and agent context associated with support activity. |
| `evidence_trace` | required |  | `communication_facts`, `evidence`, `provider_connections`, `support_cases`, `support_case_events` | `support360` (primary): subjects `entity`, `support_case`; `evidence`, `summary`, `state` | — | Partial: `source_history_completeness_and_freshness_sla_are_unverified` | Source references for exact support communication metadata or case lifecycle; message bodies are excluded. |
| `journey_links` | required |  | `journeys`, `episode_facts` | — | — | Unbound: `canonical_support_case_journey_join_unavailable` | Exact support case to journey relationships. |
| `measured_outcomes` | optional |  | `outcome_facts` | `outcome360` (primary): subjects `episode`; `outcomes`, `evidence` | — | — | Measured support outcomes where an authoritative provider exists. |
| `participants` | required |  | `communication_facts`, `identity` | — | — | Unbound: `canonical_support_case_participants_unavailable` | Case participants with identity and content policy. |
| `resolution` | required |  | `support_cases`, `support_case_events` | `support360` (primary): subjects `support_case`; `outcomes`, `state` | — | Partial: `exact_applied_case_lifecycle_event_and_provider_connection_evidence_support_resolved_or_closed_state; canonical_business_outcome_facts_remain_unavailable` | Recorded support outcome and resolution state; lifecycle resolution alone does not prove the business outcome. |
| `risk` | required |  | `risk_outputs`, `risk_signals`, `support_cases`, `evidence` | `risk360` (primary): subjects `support_case`; `summary`, `state`, `evidence`, `findings` | — | Partial: `The tenant-owned support case and its exact risk assessment and signals are joined with canonical evidence; risk-history completeness, support-case freshness SLA, and business outcome remain unknown.` | Risk outputs associated with the exact support case. |
| `risk_context` | optional |  | `risk_outputs` | `risk360` (primary): subjects `entity`; `summary`, `findings`, `evidence` | — | — | Risk context from its governing projection, subject to policy. |
| `sla` | required |  | `measurement_contract` | — | — | Unbound: `canonical_support_sla_authority_unavailable` | Support service level contract and timer state. |
| `source_lineage_and_coverage` | optional |  | `source_provenance`, `source_coverage` | `source360` (primary): subjects `source`; `evidence`, `coverage` | — | — | Source provenance and coverage for support context. |
| `support_communications` | optional |  | `communication_facts`, `evidence` | `support360` (primary): subjects `entity`; `summary`, `state`, `timeline`, `evidence`, `interactions`, `outcomes` | — | — | Communication events and interaction evidence. |
| `support_episode_and_journey` | optional |  | `episode_facts`, `journeys`, `events` | `episode360` (primary): subjects `entity`, `episode`; `summary`, `state`, `timeline`, `evidence` | — | — | Episode and journey context for support interactions. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `agent360` | `catalog_only` (supporting) | `in_flight` | `agent360.read`, `agent360.explore` |
| `episode360` | `catalog_only` (primary) | `in_flight` | `episode360.read`, `episode360.explore` |
| `outcome360` | `catalog_only` (primary) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `profile360` | `catalog_only` (primary) | `in_flight` | `profile360.read`, `profile360.explore` |
| `risk360` | `catalog_only` (primary) | `implemented` | `risk360.read`, `risk360.explore` |
| `source360` | `catalog_only` (primary) | `in_flight` | `source360.read`, `source360.explore` |
| `support360` | `catalog_only` (primary) | `in_flight` | `support360.read`, `support360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `agent_entities`, `agent_entity`, `communication_facts`, `episode_facts`, `events`, `evidence`, `identity`, `journeys`, `measurement_contract`, `outcome_facts`, `provider_connections`, `risk_outputs`, `risk_signals`, `support_cases`, `support_case_events`, `source_coverage`, `source_provenance`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `7`; lens ids: `support`, `communications`, `journey`, `identity`, `risk`, `workflow`, `policy`.

## Value 360

Product surface id: `value360`
Contract status: `source_aligned`
Subject kinds: `value`, `profile`, `account`, `conversion`, `cluster`, `campaign`, `episode`, `journey`, `entity`, `agent`, `source`

Governed view of economic facts, payment and commerce evidence, attribution, and measured outcomes; missing values remain explicit.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `attribution_credits` | required |  | `ai_execution_facts`, `attribution_credits`, `attribution_runs`, `campaign_touchpoints`, `canonical_conversions` | `economic360` (primary): subjects `conversion`, `profile`, `entity`, `cluster`, `campaign`, `journey`, `account`, `agent`, `episode`, `source`; `evidence` | — | Partial: `current_credit_read_is_unbounded_and_attribution_history_is_not_bitemporal` | Credited value allocated by canonical attribution authority. |
| `campaign_and_attribution_context` | optional |  | `attribution_credits`, `campaign_facts` | `campaign360` (primary): subjects `campaign`, `episode`; `summary`, `evidence`, `outcomes` | — | — | Campaign facts and attribution credits associated with value. |
| `confidence` | required |  | `ai_execution_facts`, `attribution_credits`, `attribution_runs`, `canonical_conversions`, `model_governance` | `economic360` (primary): subjects `account`, `agent`, `campaign`, `cluster`, `conversion`, `entity`, `journey`, `profile`; `evidence` | — | Authority: `model_governance_calibration_and_validation_not_joined`; Partial: `Only exact conversion/run/credit-linked model-reported attribution confidence with model type and version is exposed; calibration and applicability to realized value remain unvalidated.` | Evidence-linked, model-reported attribution confidence only; not a calibrated estimate of realized value or ROI. |
| `conversion_inventory` | required |  | `ai_execution_facts`, `canonical_conversions` | `economic360` (primary): subjects `conversion`, `profile`, `entity`, `cluster`, `campaign`, `journey`, `account`, `agent`; `evidence` | — | Partial: `value_subject_wallet_cluster_and_historical_inventory_joins_not_available` | Canonical conversion ledger records linked to an exact subject reference; aggregate attribution and unsupported value or wallet-cluster joins remain unknown. |
| `economic_facts_and_state` | optional |  | `ai_execution_facts`, `currency_value_normalization`, `economic_facts` | `economic360` (primary): subjects `campaign`, `episode`, `journey`; `summary`, `state`, `evidence` | — | — | Economic facts and value state with currency normalization provenance. |
| `evidence_trace` | required |  | `ai_execution_facts`, `canonical_conversions`, `commerce`, `economic_facts`, `payments` | `economic360` (primary): subjects `agent`, `campaign`, `entity`, `episode`, `journey`, `source`, `conversion`, `profile`, `account`, `cluster`; `summary`, `evidence` | — | — | Canonical economic, payment, commerce, and conversion evidence references for exact supported subjects. |
| `financial_risk` | required |  | `risk_outputs`, `economic_facts` | `economic360` (primary): subjects `agent`, `cluster`, `entity`, `source`; `evidence`, `summary`; `risk360` (supporting): subjects `agent`, `cluster`, `entity`, `source`; `financial_risk` | — | Partial: `Exact tenant and subject economic claims join only to assessed economic, payment, or transaction Risk360 dimension claims on current reads; historical joins, coordinated freshness thresholds, and complete source coverage remain unknown.` | Financial risk linked to economic facts by exact subject. |
| `ltv` | required |  | `ai_execution_facts`, `canonical_conversions`, `evidence` | `economic360` (primary): subjects `profile`, `entity`, `account`, `cluster`, `campaign`, `journey`, `agent`; `evidence` | — | Partial: `Exact evidence-backed confirmed_or_adjusted conversion net values are reported only for the canonical rows returned; lifetime and historical completeness, outcome attribution, and freshness remain unknown, missing net values degrade the slot, and native currency totals are not combined.` | Evidence-backed confirmed or adjusted canonical conversion net value over a defined subject and temporal scope; full lifetime coverage remains unknown and native currencies stay partitioned. |
| `measured_outcomes` | optional |  | `outcome_facts`, `measurement_contract` | `outcome360` (primary): subjects `campaign`, `episode`, `journey`; `summary`, `evidence`, `outcomes` | — | — | Measured outcome facts linked to economic value. |
| `payments_and_commerce_evidence` | optional |  | `ai_execution_facts`, `commerce`, `payments` | `economic360` (primary): subjects `campaign`, `episode`, `journey`; `evidence`, `outcomes` | — | — | Payment and commerce evidence from the corresponding authorities. |
| `reconciliation` | required |  | `ai_execution_facts`, `commerce`, `currency_value_normalization`, `economic_facts`, `evidence`, `payments` | `economic360` (primary): subjects `campaign`, `entity`, `journey`; `evidence` | — | Partial: `Subject-scoped economic rows and exact order-linked commerce facts remain separate observations. Settlement-to-payment links require the explicit provider payment ID and same commerce order reference; only native USD identity normalization is accepted. Economic records lack exact order, payment, and settlement IDs, so cross-source matching, non-USD commerce normalization, reconciled totals, and completeness remain unavailable.` | Separate source-native economic and commerce observations with exact settlement-to-payment references; cross-source reconciliation remains explicit. |
| `revenue_events` | required |  | `ai_execution_facts`, `economic_facts`, `payments` | `economic360` (primary): subjects `campaign`, `entity`, `journey`; `evidence` | — | Partial: `all_revenue_event_sources_and_attribution_not_joined` | Source-recorded settled payment events with an explicit operation join and transaction evidence; no attributed revenue total. |
| `temporal_context` | optional |  | `temporal_kernel` | `temporal360` (primary): subjects none; `state`, `timeline` | — | — | Temporal context for value facts and comparisons. |
| `value_summary` | required |  | `ai_execution_facts`, `currency_value_normalization`, `economic_facts` | `economic360` (primary): subjects `agent`, `campaign`, `entity`, `episode`, `journey`, `source`; `summary` | — | — | Subject-scoped computed economic value with explicit missing, zero, and source currency states; no inferred attribution or AI cost aggregation. |
| `web2_value` | required |  | `payments`, `commerce` | `economic360` (primary): subjects `campaign`, `entity`, `journey`; `evidence` | — | Partial: `Only completed exact-order-linked payment facts for campaign, entity, and journey subjects are classified when their source rail is explicitly card, ACH, wire, SEPA, or bank transfer. Non-USD normalization, source coverage, policy, and freshness remain unknown.` | Evidence-backed Web2 payment observations classified only from exact order-linked payment facts with an explicit supported payment rail. |
| `web3_value` | required |  | `commerce`, `currency_value_normalization` | `economic360` (primary): subjects `campaign`, `entity`, `journey`; `evidence` | — | Partial: `Only completed exact-order-linked payment facts with explicit crypto flow or on-chain rail and a complete source or destination asset leg plus transaction-hash evidence are classified. Wallet identity, currency normalization, source coverage, policy, and freshness remain unknown.` | Evidence-backed Web3 native-asset payment observations with explicit flow, rail, chain, asset, amount, and transaction-hash evidence. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `campaign360` | `catalog_only` (primary) | `in_flight` | `campaign360.read`, `campaign360.explore` |
| `economic360` | `catalog_only` (primary) | `implemented` | `economic360.read`, `economic360.explore` |
| `outcome360` | `catalog_only` (primary) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `temporal360` | `catalog_only` (primary) | `implemented` | `temporal360.read`, `temporal360.explore` |
| `risk360` | `catalog_only` (supporting) | `implemented` | `risk360.read`, `risk360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `ai_execution_facts`, `attribution_runs`, `attribution_credits`, `campaign_facts`, `campaign_touchpoints`, `canonical_conversions`, `commerce`, `currency_value_normalization`, `economic_facts`, `evidence`, `measurement_contract`, `model_governance`, `outcome_facts`, `payments`, `risk_outputs`, `temporal_kernel`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `8`; lens ids: `value`, `attribution`, `campaign`, `identity`, `journey`, `commerce`, `risk`, `provenance`.

## Workflow 360

Product surface id: `workflow360`
Contract status: `source_aligned`
Subject kinds: `workflow`, `automation`, `trigger`, `run`, `workflow_run`

Governed operational view of agent executions, actions and tools, integration lifecycle, evidence, and optional outcomes.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Direct surface provider | Implementation gap | Description |
|---|---|---|---|---|---|---|---|
| `actions` | required |  | `actions`, `tools`, `resources` | — | — | Unbound: `canonical_workflow_action_authority_not_joined` | Required Workflow 360 slot: actions. |
| `actors` | required |  | `ai_execution_facts`, `agent_entities`, `agent_executions`, `commerce`, `identity` | `workflow360` (primary): subjects `run`, `workflow_run`; `actors` | — | Partial: `Exact execution initiator and approval decider references resolve through unique active tenant USER_ID aliases; workflow-wide actor coverage and authority remain unknown.` | Exact run-linked AI invocation agents plus human initiator and approver identities resolved through active tenant USER_ID aliases; full actor coverage and workflow authority remain unknown. |
| `agent_steps` | required |  | `agent_executions` | `workflow360` (primary): subjects `run`, `workflow_run`; `agent_steps` | — | Partial: `The canonical AgentExecution writer persists workflow_run_id and exact invocation IDs when a unique tenant-scoped AI invocation has action_id equal to the stable execution ID. Workflow definition, complete step coverage, policy, and freshness remain unknown.` | Exact tenant and run-linked AgentExecution records admitted only when stored invocation IDs match run-linked AI facts and the stable action/execution ID; complete workflow step coverage remains unknown. |
| `approvals` | required |  | `agent_access`, `agent_executions`, `commerce` | `workflow360` (primary): subjects `run`, `workflow_run`; `approvals` | — | Authority: `canonical_workflow_approval_authority_not_joined`; Partial: `Only exact x402 approval decisions referenced by admitted run-linked AgentExecutions are joined; workflow-level approval coverage and authorization remain unknown.` | Exact x402 approval requests and decisions referenced by tenant and run-linked AgentExecutions; workflow-wide approval coverage and authorization policy remain unknown. |
| `evidence_trace` | required |  | `ai_execution_facts` | `workflow360` (primary): subjects `run`, `workflow_run`; `evidence_trace` | — | — | Lineage of exact workflow run linked AI invocation facts. |
| `failures` | required |  | `ai_execution_facts` | `workflow360` (primary): subjects `run`, `workflow_run`; `failures` | — | — | Observed AI invocation failure status only; workflow failure state is unknown. |
| `outcomes` | required |  | `ai_execution_facts`, `outcome_facts`, `evidence` | `workflow360` (primary): subjects `run`, `workflow_run`; `outcomes` | — | Partial: `Only canonical outcome IDs explicitly referenced by tenant/run invocation facts are joined with invocation and outcome evidence; this association does not establish workflow causality or complete outcome coverage, and policy and freshness remain unknown.` | Canonical outcomes explicitly referenced by tenant-scoped invocation facts for an exact workflow run. |
| `risk` | required |  | `risk_outputs` | — | — | Unbound: `canonical_workflow_risk_policy_join_not_available` | Required Workflow 360 slot: risk. |
| `runs` | required |  | `ai_execution_facts` | `workflow360` (primary): subjects `run`, `workflow_run`; `runs` | — | — | AI invocation facts explicitly linked to a workflow run ID; run state is partial. |
| `triggers` | required |  | `agent_executions`, `events` | `workflow360` (primary): subjects `run`, `workflow_run`; `triggers` | — | Partial: `Only exact tenant/run-linked AgentExecution records and their stored trigger event references are joined; trigger definitions, workflow causality, complete coverage, policy authority, and freshness remain unknown.` | Exact run-linked event references stored on admitted AgentExecution records; does not establish workflow trigger causality or coverage. |
| `workflow_summary` | required |  | `execution_facts` | — | — | Unbound: `canonical_workflow_definition_authority_not_available` | Required Workflow 360 slot: workflow summary. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `workflow360` | `catalog_only` (primary) | `in_flight` | `workflow360.read` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `actions`, `agent_access`, `agent_entities`, `agent_executions`, `ai_execution_facts`, `evidence`, `events`, `execution_facts`, `commerce`, `identity`, `outcome_facts`, `resources`, `risk_outputs`, `tools`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `8`; lens ids: `workflow`, `automation`, `execution`, `agentic`, `policy`, `identity`, `risk`, `value`.
