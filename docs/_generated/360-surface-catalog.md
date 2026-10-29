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
| [Account 360](#account-360) | source_aligned | `account`, `entity`, `workspace` | 11 | 11/11 | 6 | 0 | 4 | `communication360`, `economic360`, `profile360`, `relationship360` | `Account360Provider` (runtime_wired) |
| [Agent 360](#agent-360) | source_aligned | `agent`, `entity` | 11 | 11/11 | 6 | 0 | 4 | `agent360`, `communication360`, `economic360`, `execution360`, `outcome360`, `relationship360`, `risk360` | — |
| [Campaign 360](#campaign-360) | source_aligned | `campaign` | 11 | 11/11 | 6 | 0 | 0 | `campaign360`, `communication360`, `economic360`, `outcome360` | — |
| [Commerce 360](#commerce-360) | source_aligned | `entity`, `campaign`, `journey`, `commerce`, `product`, `offer`, `sku`, `checkout` | 11 | 11/11 | 7 | 0 | 0 | `commerce360` | — |
| [Communications 360](#communications-360) | source_aligned | `message`, `thread`, `profile`, `campaign`, `episode`, `agent`, `journey`, `source` | 11 | 11/11 | 7 | 0 | 0 | `communication360` | — |
| [Episode 360](#episode-360) | source_aligned | `episode`, `session`, `conversation`, `activity_window`, `entity`, `campaign` | 11 | 11/11 | 7 | 0 | 1 | `communication360`, `campaign360`, `episode360`, `profile360`, `relationship360` | — |
| [Execution 360](#execution-360) | source_aligned | `agent`, `entity`, `episode`, `execution`, `workflow_run` | 11 | 11/11 | 7 | 0 | 0 | `execution360` | — |
| [Identity 360](#identity-360) | source_aligned | `entity`, `agent`, `source` | 10 | 10/10 | 2 | 0 | 3 | `agent360`, `execution360`, `profile360`, `relationship360` | `Identity360Provider` (runtime_wired) |
| [Journey 360](#journey-360) | source_aligned | `journey`, `profile`, `account`, `campaign`, `episode`, `entity` | 11 | 11/11 | 9 | 0 | 2 | `episode360`, `profile360`, `communication360` | — |
| [Location 360](#location-360) | source_aligned | `location`, `place`, `geohash`, `timezone`, `region`, `entity`, `population`, `source` | 11 | 11/11 | 8 | 0 | 4 | `geographic360`, `population360`, `profile360` | — |
| [Memory 360](#memory-360) | source_aligned | `entity`, `semantic_entity`, `memory`, `card`, `topic` | 10 | 10/10 | 4 | 0 | 0 | `memory360` | — |
| [Profile 360](#profile-360) | source_aligned | `profile`, `entity`, `agent`, `anonymous_subject`, `account_member`, `cluster` | 13 | 13/13 | 9 | 0 | 6 | `economic360`, `outcome360`, `profile360`, `geographic360`, `risk360` | — |
| [Risk 360](#risk-360) | source_aligned | `risk`, `entity`, `profile`, `agent`, `account`, `source`, `campaign`, `contagion_path`, `relationship`, `cluster` | 12 | 12/12 | 8 | 0 | 6 | `economic360`, `execution360`, `fraud360`, `relationship360`, `risk360`, `social360` | — |
| [Signals 360](#signals-360) | source_aligned | `entity`, `signal`, `source`, `event`, `observation`, `stream` | 10 | 10/10 | 7 | 0 | 0 | `signals360` | — |
| [Social 360](#social-360) | source_aligned | `entity`, `profile`, `relationship`, `community`, `syndicate`, `source`, `population` | 10 | 10/10 | 7 | 0 | 5 | `geographic360`, `population360`, `relationship360`, `social360`, `source360` | — |
| [Support 360](#support-360) | source_aligned | `support_case`, `callback`, `conversation`, `ticket`, `entity`, `agent`, `episode`, `source` | 10 | 10/10 | 10 | 0 | 6 | `agent360`, `episode360`, `outcome360`, `profile360`, `risk360`, `source360`, `support360` | — |
| [Value 360](#value-360) | source_aligned | `value`, `profile`, `account`, `conversion`, `cluster`, `campaign`, `episode`, `journey`, `entity`, `agent`, `source` | 11 | 11/11 | 9 | 0 | 5 | `campaign360`, `economic360`, `outcome360`, `temporal360`, `risk360` | — |
| [Workflow 360](#workflow-360) | source_aligned | `workflow`, `automation`, `trigger`, `run`, `workflow_run` | 11 | 11/11 | 8 | 0 | 0 | `workflow360` | — |

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
| `contracts` | required |  | `commerce`, `tenant_contract_profiles` | — | `Account360Provider` (runtime_wired) | Partial: `Tenant contract profiles are exact current account-linked records; obligation execution, upstream contract completeness, historical replay, and freshness SLA remain unknown.` | Exact tenant and canonical account-id contract profiles from the commerce billing authority; tenant defaults do not imply account contracts. |
| `economic_context` | optional |  | `ai_execution_facts`, `economic_facts` | `economic360` (primary): subjects `entity`; `summary`, `evidence`, `outcomes` | — | — | Economic facts associated with the account. |
| `evidence_and_limitations` | optional |  | `evidence` | `profile360` (primary): subjects `entity`; `evidence`, `findings` | — | — | Evidence and coverage for account context. |
| `evidence_trace` | required |  | `evidence` | `profile360` (primary): subjects `entity`; `evidence`, `findings` | — | — | Evidence and limits for the account entity only, not a complete member aggregate. |
| `journeys` | required |  | `graph`, `entity_registry`, `journeys` | — | `Account360Provider` (runtime_wired) | Partial: `Current journey participation is joined through exact observed human membership and per-member Profile360 policy; historical membership, roster completeness, direct account journey ownership, and a freshness SLA remain unknown.` | Current human member journey participation joined through exact MEMBER_OF graph evidence and independently policy-approved Profile360 journey slots. |
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
| `Account360Provider` | `surface_frame_provider` | `runtime_wired` | `entity` | `account_summary`, `members`, `agents`, `profiles`, `risk`, `journeys`, `contracts` | `services/api/identity/account360_provider.py` | `services/api/shared/intelligence_projections/frame_runtime.py` |

### Authority and governance contract

Canonical authorities: `ai_execution_facts`, `commerce`, `communication_facts`, `economic_facts`, `entities`, `entity_registry`, `evidence`, `graph`, `identity`, `journeys`, `relationship_facts`, `risk_outputs`, `tenant_contract_profiles`.

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
| `capabilities` | required |  | `actions`, `resources`, `tools`, `agent_access` | `agent360` (primary): subjects `agent`, `entity`; `state`, `evidence` | — | Authority: `active_invoke_grants_do_not_evaluate_action_or_resource_specific_policy`; Partial: `Current active grant join is bounded to 2000 records. Observed catalog identity for an exact MCP tool does not prove remote ownership, effective tool authorization, action or resource policy, or historical authority.` | Observed runtime capability reach joined to exact active invoke grants for the resolved canonical Agent and exact observed MCP tool catalog identity; action and resource authorization remains unknown. |
| `communications` | optional |  | `communication_facts`, `observations` | `agent360` (supporting): subjects `agent`; `interactions`; `communication360` (primary): subjects `agent`; `evidence`, `interactions`, `timeline` | — | — | Optional Aether provider context retained for Agent 360: communications. |
| `delegation_chain` | required | `slotActorAttribution`, `slotAuthorityDecision` | `agent_access`, `identity` | `agent360` (primary): subjects `agent`, `entity`; `evidence`, `state` | — | Partial: `delegation_reads_are_bounded_and_do_not_evaluate_transitive_or_action_resource_authority` | Tenant-scoped stored delegation edges with party identity evidence; no transitive or action-specific authority is inferred. |
| `economic_cost_and_settlement` | optional |  | `ai_execution_facts`, `commerce`, `economic_facts`, `payments` | `economic360` (primary): subjects `agent`, `entity`; `evidence`, `summary` | — | — | Optional Aether provider context retained for Agent 360: economic cost and settlement. |
| `evidence_trace` | required |  | `evidence`, `source_provenance` | `agent360` (supporting): subjects `agent`, `entity`; `evidence` | — | Partial: `Canonical Bronze links are joined to exact tenant, agent, source-row, event, schema, and timestamp references. Registered Rights source identity, source trust, freshness SLA, complete lineage coverage, and unlinked historical rows remain unknown.` | Required Agent 360 blueprint slot: evidence trace. |
| `execution_history` | required |  | `agent_executions`, `execution_facts` | `execution360` (primary): subjects `agent`, `entity`; `evidence`, `state`, `timeline` | — | — | Required Agent 360 blueprint slot: execution history. |
| `identity` | required |  | `agent_entity`, `identity` | `agent360` (primary): subjects `agent`, `entity`; `state`, `summary` | — | — | Required Agent 360 blueprint slot: identity. |
| `owner_delegator` | required | `slotActorAttribution` | `agent_access`, `graph`, `identity` | `agent360` (primary): subjects `agent`, `entity`; `evidence`, `state` | — | Partial: `Configured owner reference is resolved to an exact tenant entity and joined only to an exact tenant graph OWNS or OWNS_AGENT edge targeting the resolved canonical Agent. Legal or effective ownership, action authorization, historical validity, graph completeness, and freshness remain unknown.` | Tenant-scoped owner and delegator records with canonical party identity only where resolved; no effective action authorization is inferred. |
| `policy_boundary` | required |  | `agent_access`, `agent_executions`, `delegations`, `entities`, `identity` | `agent360` (primary): subjects `agent`, `entity`; `policy_boundary` | — | Partial: `current_repository_active_delegation_scopes_are_bounded_and_may_lag_revocation; non_delegation_policy_historical_replay_and_new_action_authorization_remain_unknown` | Exact stored active delegation scopes and recorded execution-scoped policy decisions; complete standing agent policy and a new action decision remain unknown. |
| `risk_summary` | required |  | `agent_entities`, `identity`, `relationship_facts`, `risk_outputs`, `social_observations` | `risk360` (primary): subjects `agent`, `entity`; `evidence`, `findings`; `agent360` (supporting): subjects `agent`, `entity`; `state` | — | Partial: `The Agent360 supporting path resolves exact tenant canonical Agent identity before policy-authorized Risk360 and Social360 reads. Social risk-context edges require consent and shared risk-signal evidence and are correlated context only. Agent-specific freshness, historical replay, social observation coverage, and causal contagion remain unknown.` | Required Agent 360 blueprint slot: risk summary. |
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

Canonical authorities: `actions`, `agent_access`, `agent_entities`, `agent_entity`, `agent_executions`, `ai_execution_facts`, `commerce`, `communication_facts`, `delegations`, `economic_facts`, `entities`, `evidence`, `execution_facts`, `graph`, `identity`, `observations`, `outcome_facts`, `payments`, `relationship_facts`, `resources`, `risk_outputs`, `social_observations`, `source_provenance`, `temporal`, `tools`.

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
| `anomalies` | required |  | `targeting_leakage_findings`, `risk_outputs`, `source_provenance` | `campaign360` (primary): subjects `campaign`; `anomalies` | — | Partial: `Exact targeting leakage findings and bounded exact-tenant campaign Risk360 assessments are read as separate dimensions with their own evidence. Campaign-specific risk production, complete risk and source-anomaly coverage, history, policy, and freshness remain unknown.` | Tenant-scoped targeting leakage findings backed by source observation and eligibility-snapshot evidence, alongside exact campaign Risk360 assessment output; producer coverage and source anomalies stay unknown. |
| `attribution` | required |  | `attribution_credits` | `campaign360` (primary): subjects `campaign`; `evidence`, `outcomes`, `findings` | — | — | Active, evidence-backed attribution credits associated with the campaign. |
| `campaign_identity` | required |  | `campaign_facts` | `campaign360` (primary): subjects `campaign`; `summary`, `state`, `evidence` | — | — | Canonical Aether campaign identity and registered state. |
| `cohorts_syndicates` | required |  | `campaign_facts`, `campaign_population_link_events`, `cluster_definitions`, `cluster_membership`, `cohort_membership`, `population_definitions`, `relationship_facts` | `campaign360` (primary): subjects `campaign`; `outcomes` | — | Partial: `Explicit links can resolve current exact cluster definition revisions and bounded consent-scoped cluster or cohort memberships backed by live graph ledger replay. A separate policy-authorized read can expose current evidence-backed FOLLOWS edges between consented linked members. Population and roster coverage, other relationship predicates, syndicates, historical membership and freshness remain unknown.` | Explicit campaign-to-population associations with current versioned cluster definitions and consent-scoped membership evidence where exact tenant records resolve. |
| `conversions` | required |  | `attribution_credits`, `canonical_conversions`, `measurement_contract`, `outcome_facts` | `campaign360` (primary): subjects `campaign`; `outcomes`; `outcome360` (primary): subjects `campaign`; `outcomes`, `evidence` | — | Partial: `Only actively attributed exact conversions are visible; unattributed conversions, outcome facts, historical completeness and freshness remain unknown.` | Exact canonical conversion rows reached through active attribution credits scoped to the canonical campaign, preserving conversion and credit evidence. |
| `evidence_trace` | required |  | `attribution_credits`, `campaign_facts`, `campaign_touchpoints`, `journeys`, `touchpoints` | `campaign360` (primary): subjects `campaign`; `evidence` | — | — | Source evidence references supporting the campaign frame and its claims. |
| `journeys` | required |  | `journeys` | `campaign360` (primary): subjects `campaign`; `evidence`, `state` | — | — | Current journey versions that explicitly reference this canonical campaign. |
| `performance` | required |  | `ai_execution_facts`, `attribution_credits`, `canonical_conversions`, `commerce`, `economic_facts`, `outcome_facts`, `payments`, `spend_records` | `economic360` (primary): subjects `campaign`; `summary`, `evidence`, `outcomes`; `campaign360` (supporting): subjects `campaign`; `state` | — | Partial: `Spend ledger lacks a coverage watermark, so spend totals, ROAS and ROI are unknown. Only complete active-credit conversion joins yield currency-scoped attributed revenue; unattributed conversions and adjusted-after-run amounts remain unknown.` | Exact active-attribution conversion revenue and bounded campaign spend ledger observations, with incomplete aggregates left unknown. |
| `signal_sources` | required |  | `events`, `observations`, `source_facts` | `campaign360` (primary): subjects `campaign`; `state` | — | Partial: `Exact campaign touchpoint event references join tenant-scoped canonical events, matching gateway-admitted SDK Bronze observations, and verified current touchpoint classification revisions as source facts. Broader observation and source-fact producers, complete event coverage, and a freshness SLA remain unresolved.` | Tenant-scoped signal and source observations associated with the campaign. |
| `source_classification` | required |  | `campaign_touchpoints`, `source_facts`, `source_provenance` | `campaign360` (primary): subjects `campaign`; `state`, `evidence` | — | Partial: `Exact current tenant touchpoint classification revisions are read and verified against the touchpoint classification pointer, class, classifier version, and time. Only classified touchpoints on the requested page are joined; campaign registry provenance and other asserting sources remain unknown.` | Canonical classification of the source that asserted or synchronized campaign evidence. |
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

Canonical authorities: `ai_execution_facts`, `attribution_credits`, `campaign_facts`, `campaign_population_link_events`, `campaign_touchpoints`, `canonical_conversions`, `cluster_definitions`, `cluster_membership`, `cohort_membership`, `commerce`, `communication_facts`, `economic_facts`, `events`, `journeys`, `measurement_contract`, `observations`, `outcome_facts`, `payments`, `population_definitions`, `relationship_facts`, `risk_outputs`, `source_facts`, `source_provenance`, `spend_records`, `targeting_leakage_findings`, `touchpoints`.

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
| `cart_checkout` | required |  | `commerce_product_offer_graph`, `silver_commerce_flow_facts`, `source_provenance` | `commerce360` (primary): subjects `product`, `offer`; `cart_checkout` | — | Partial: `exact_source_asserted_catalog_keyed_cart_checkout_events_only; current_cart_state_purchase_producer_coverage_and_freshness_unknown` | Accepted source cart and checkout events with one explicit tenant catalog product or offer key and Silver event evidence. |
| `catalog_links` | required |  | `commerce_product_offer_graph`, `source_provenance` | `commerce360` (primary): subjects `product`, `offer`; `catalog_links` | — | Partial: `catalog_link_coverage_is_limited_to_persisted_product_offer_revisions_and_freshness_sla_is_unconfigured` | Offer to product links from exact tenant-scoped catalog revisions. |
| `evidence_trace` | required |  | `commerce`, `payments`, `commerce_product_offer_graph`, `commerce_intent_authority`, `silver_exposure_facts`, `silver_commerce_flow_facts`, `source_provenance` | `commerce360` (primary): subjects `entity`, `campaign`, `journey`, `product`, `offer`; `evidence_trace` | — | — | Source evidence for exact scoped commerce facts. |
| `exposures` | required |  | `commerce_product_offer_graph`, `silver_exposure_facts`, `source_provenance` | `commerce360` (primary): subjects `product`, `offer`; `exposures` | — | Partial: `exact_source_asserted_product_offer_exposure_events_only; producer_coverage_effect_and_freshness_unknown` | Accepted source exposure observations with an explicit tenant catalog product or offer key and Silver event evidence. |
| `intent` | required |  | `commerce_intent_authority`, `commerce_product_offer_graph`, `source_provenance` | `commerce360` (primary): subjects `offer`, `product`; `intent` | — | Partial: `explicit_intent_subject_join_is_implemented_for_product_and_offer_only; commerce_sku_and_checkout_authorities_are_not_connected; freshness_threshold_is_unconfigured` | Explicit tenant-owned intent records joined to an exact product or offer subject, with actor, source revision, timestamps, and evidence. |
| `product_offer_summary` | required |  | `commerce_product_offer_graph`, `source_provenance` | `commerce360` (primary): subjects `product`, `offer`; `product_offer_summary` | — | Partial: `catalog_source_ingestion_coverage_and_freshness_sla_are_unconfigured` | Exact tenant-scoped product and offer revisions by canonical product or offer ID. |
| `purchase` | required |  | `commerce`, `payments`, `source_provenance` | `commerce360` (primary): subjects `entity`, `campaign`, `journey`; `purchase` | — | — | Explicit scoped commerce order and payment fact references. |
| `risk` | required |  | `risk_outputs` | `commerce360` (primary): subjects `product`, `offer`; `risk` | — | Partial: `Current RiskSignal and RiskAssessment rows join only after exact tenant-scoped canonical product or offer resolution; historical coverage, freshness, policy, and causality remain unknown.` | Required commerce360 slot: risk. |
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

Canonical authorities: `campaign_facts`, `commerce`, `commerce_intent_authority`, `commerce_product_offer_graph`, `payments`, `risk_outputs`, `silver_commerce_flow_facts`, `silver_exposure_facts`, `source_provenance`.

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
| `agent_authorship` | required |  | `communication_facts`, `delegations`, `entities` | `communication360` (primary): subjects `agent`; `interactions`, `evidence` | — | Partial: `Event-time delegation is read only for bounded exact agent author bindings. Provider grant references without a unique canonical metadata match remain unknown; complete author roster, current action authority, and freshness remain unproven.` | Observed agent author bindings with exact event-time delegation decisions when tenant, parties, provider reference, and communication scope resolve. |
| `campaign_links` | required |  | `communication_facts`, `campaign_touchpoints` | `communication360` (primary): subjects `campaign`; `state`, `evidence` | — | — | Explicit campaign scoped communication and touchpoint refs. |
| `evidence_trace` | required |  | `communication_facts`, `evidence` | `communication360` (primary): subjects `agent`, `campaign`; `evidence` | — | — | Communication fact and message evidence with partial source provenance. |
| `journey_links` | required |  | `communication_facts`, `journeys` | `communication360` (primary): subjects `agent`, `campaign`, `episode`, `journey`, `source`; `summary`, `evidence` | — | Partial: `current_explicit_journey_references_only_no_historical_replay` | Explicit journey references on in-scope communication facts resolved to current tenant journey versions. |
| `message_inventory` | required |  | `communication_facts`, `evidence` | `communication360` (primary): subjects `agent`, `campaign`; `timeline`, `evidence` | — | — | Bounded observed message entries with message evidence. |
| `participants` | required |  | `communication_facts`, `entities`, `identity`, `evidence` | `communication360` (primary): subjects `agent`, `campaign`; `interactions` | — | Partial: `participant_roles_are_observed_from_signed_provider_rosters_and_exact_tenant_identity_mappings_but_canonical_conversation_membership_and_full_message_coverage_are_unresolved; provider_delegation_refs_are_not_canonical_grants` | Typed, source-authenticated participant role bindings joined through exact tenant-owned provider identity mappings; canonical conversation membership remains unresolved. |
| `policy_state` | required |  | `communication_facts`, `consent_policy_decisions`, `evidence` | `communication360` (primary): subjects `agent`, `campaign`, `episode`, `journey`, `source`; `summary` | — | Partial: `Current consent is evaluated only for exact tenant, recipient-entity, and purpose pairs supported by communication identity and evidence. Historical write-time outcomes are separate; non-consent policy, durable current-decision evidence, complete recipient coverage, and freshness remain unknown.` | Current server-consent decisions for exact tenant-scoped recipient and purpose pairs, separated from historical communication-time decisions. |
| `profile_links` | required |  | `communication_facts`, `entity_registry`, `evidence`, `identity` | `communication360` (primary): subjects `agent`, `campaign`, `episode`, `journey`, `source`; `summary`, `evidence` | — | Partial: `Evidence-backed communication profile references now require both an exact tenant profile record and an exact same-ID canonical human entity record. Alias and independently keyed profile/entity identities, historical binding validity, complete link coverage, and freshness remain unknown.` | Explicit profile identifiers on evidence-backed communication facts resolved against exact tenant profile records and the same canonical human entity. |
| `response_events` | required |  | `communication`, `communication_facts`, `evidence`, `identity` | `communication360` (primary): subjects `agent`, `campaign`; `interactions` | — | Partial: `Only bounded exact act-to-message and sender joins are observed. Reply target, causal response outcome, complete message history, and source freshness remain unknown.` | Response-like canonical communication acts joined to exact tenant-scoped message and authenticated sender identity where available. |
| `risk_flags` | required |  | `communication_facts`, `consent_policy_decisions`, `evidence`, `identity`, `risk_assessments`, `risk_outputs`, `risk_signals` | `communication360` (primary): subjects `agent`, `source`; `summary`, `evidence` | — | Partial: `Source, recipient, and resolved-agent RiskSignal and RiskAssessment reads require current analytics consent and exact tenant identity evidence. Assessment output remains attached only to its assessed subject; message-edge transfer, communication-specific composite risk, historical and producer coverage, and freshness remain unknown.` | Exact-subject canonical RiskSignal and RiskAssessment observations for resolved agents and sources and mapped recipient entities after current analytics consent; message-edge propagation is never inferred. |
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

Canonical authorities: `campaign_touchpoints`, `communication`, `communication_facts`, `consent_policy_decisions`, `delegations`, `entities`, `entity_registry`, `evidence`, `identity`, `journeys`, `risk_assessments`, `risk_outputs`, `risk_signals`.

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
| `agent_handoffs` | required |  | `agent_executions`, `delegations`, `episode_facts`, `episode_journey_authority_records` | `episode360` (primary): subjects `episode`; `interactions`, `evidence` | — | Partial: `Only recorded exact links are projected; complete handoff inventory, current delegation authorization, policy and freshness remain unknown.` | Explicit exact-episode link joining the canonical agent execution, delegation grant and episode source event with persisted evidence. |
| `attribution_links` | required |  | `attribution_credits`, `attribution_runs`, `canonical_conversions`, `episode_facts`, `episode_journey_authority_records`, `outcome_facts` | `episode360` (primary): subjects `episode`; `outcomes`, `evidence` | — | Partial: `Only recorded exact links are projected; complete attribution inventory, current credit policy and freshness remain unknown.` | Explicit exact-episode and outcome link joining canonical conversion, attribution run and credit evidence. |
| `communications` | required |  | `communication_facts` | `communication360` (supporting): subjects `episode`; `interactions` | — | Partial: `Episode communication facts join by exact typed episode references and preserve evidence, but this does not establish complete message or conversation coverage, source freshness, or provider policy evaluation.` | Bounded exact tenant episode_id or episode_ids-linked canonical communication facts with event-time and anchored receipt-time filtering; message history and complete conversation membership remain unavailable. |
| `conversion_events` | required |  | `episode_facts`, `outcome_facts`, `evidence` | `episode360` (primary): subjects `episode`; `outcomes` | — | Partial: `Only outcome IDs explicitly recorded by tenant episode rows are joined and admitted for registered campaign_conversion or journey_completion definitions with canonical evidence; these references do not establish complete coverage or causal attribution, and freshness and policy remain unknown.` | Canonical conversion outcomes explicitly referenced by exact tenant episode records; only registered conversion definitions are admitted. |
| `entity_and_relationship_context` | optional |  | `campaign_facts`, `episode_facts`, `graph`, `identity`, `relationship_facts` | `profile360` (primary): subjects `entity`, `episode`; `evidence`, `state`, `summary`; `relationship360` (supporting): subjects `entity`, `episode`; `interactions`, `evidence`; `episode360` (supporting): subjects `campaign`, `entity`, `episode`; `episode_context`; `campaign360` (primary): subjects `campaign`; `evidence`, `state`, `summary` | — | — | Canonical identity for entity and episode subjects, campaign identity for campaign subjects, and graph relationships where the subject has a supported entity graph. |
| `episode_summary` | required |  | `episode_facts`, `evidence` | `episode360` (primary): subjects `episode`; `summary`, `evidence` | — | — | Exact tenant episode record with evidence lineage. |
| `evidence_trace` | required |  | `episode_facts`, `evidence` | `episode360` (primary): subjects `episode`; `evidence` | — | — | Episode record and lineage refs; source event provenance is partial. |
| `participants` | required |  | `episode_facts` | `episode360` (primary): subjects `episode`; `interactions`, `episode_context` | — | — | Primary user or agent subject reference only; full participant resolution is pending. |
| `risk_flags` | required |  | `episode_facts`, `risk_signals` | `episode360` (primary): subjects `episode`; `risk_flags` | — | Partial: `Only current RiskSignals for the exact typed primary subject of one tenant-scoped EpisodeRecord are joined; risk history, complete signal coverage, policy, freshness, and causality remain unknown.` | Current canonical RiskSignals for an exact tenant episode primary subject; no episode-to-risk causality is inferred. |
| `sessions` | required |  | `episode_facts` | `episode360` (primary): subjects `episode`; `episode_context` | — | — | Primary session reference only; session inventory is pending. |
| `timeline` | required |  | `episode_facts`, `episode_journey_authority_records`, `temporal`, `silver_semantic_observations`, `evidence` | `episode360` (primary): subjects `episode`; `timeline` | — | Partial: `Only explicitly authored typed observation references are resolved against exact semantic Silver event, namespace, timestamp, and evidence fields. EpisodeEngine can produce the exact typed link when its caller supplies a semantic observation authority marker, but no live semantic-to-episode association caller is connected. Legacy Silver rows without authenticated source namespace remain unknown; broader activity/session completeness, source freshness, and policy remain unverified.` | Typed episode observation references joined by exact tenant, source namespace, observation ID, source event, association time, and semantic Silver evidence within bounded temporal context. |
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

Canonical authorities: `agent_executions`, `attribution_credits`, `attribution_runs`, `campaign_facts`, `campaign_touchpoints`, `canonical_conversions`, `communication_facts`, `delegations`, `episode_facts`, `episode_journey_authority_records`, `evidence`, `graph`, `identity`, `outcome_facts`, `relationship_facts`, `risk_signals`, `silver_semantic_observations`, `temporal`.

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
| `authority_check` | required | `slotActorAttribution`, `slotAuthorityDecision` | `agent_access`, `agent_entities`, `identity` | `execution360` (supporting): subjects `agent`, `entity`, `episode`, `execution`; `evidence`, `state` | — | Partial: `New delegation-engine decisions persist an evaluation timestamp in the exact tenant-scoped agent_executions policy log and Execution360 verifies it against execution-record creation time; legacy rows without that timestamp remain unknown. This is request-time application evidence only and does not establish current or standing authority, policy input replay, other authority sources, or freshness.` | Required Execution 360 blueprint slot: authority check. |
| `evidence_trace` | required |  | `evidence`, `source_provenance`, `ai_execution_facts` | `execution360` (primary): subjects `agent`, `entity`, `episode`, `execution`, `workflow_run`; `evidence` | — | Partial: `Exact workflow_run execution references include matching invocation evidence. Admitted external telemetry joins unique same-tenant Bronze event/type/time envelopes for ingress provenance only; registered source identity, external execution receipts, complete source coverage, workflow step coverage, historical replay, and a freshness threshold remain unknown.` | Exact execution and invocation evidence, plus bounded Bronze ingress provenance for admitted external telemetry events. |
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
| `wallets` | required |  | `entity_wallets`, `evidence`, `identity`, `source_provenance` | — | `Identity360Provider` (runtime_wired) | Partial: `Exact tenant and canonical-entity wallet links are read from entity_wallets, with separate historical verification evidence; current control, complete ownership, and freshness remain unknown.` | Exact canonical-entity wallet inventory joined to historical verification evidence; current wallet control and completeness remain unknown. |

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

Canonical authorities: `agent_access`, `agent_entities`, `agent_entity`, `entities`, `entity_registry`, `entity_wallets`, `evidence`, `graph`, `identity`, `provider_registry`, `relationship_facts`, `source_provenance`.

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
| `attribution` | required |  | `journeys`, `attribution_runs`, `attribution_credits`, `canonical_conversions`, `touchpoints` | `episode360` (primary): subjects `journey`; `journey_attribution` | — | Partial: `Only active completed credits from exact same-tenant attribution runs for the current journey version are joined. Recorded conversion and touchpoint IDs resolve only to eligible current exact-tenant rows when their event times do not follow run completion; missing or conflicting rows stay unknown. Inactive and historical runs, subject state at run time, policy, freshness, complete coverage, and causal validity remain unknown.` | Active completed attribution credits linked through a same-tenant run for the exact current JourneyVersion. |
| `communications` | required |  | `communication_facts` | `communication360` (primary): subjects `journey`; `evidence`, `interactions` | — | Partial: `Only exact typed journey-linked canonical communication facts are joined. Message-spine coverage, completeness, freshness, and historical replay remain unestablished.` | Bounded tenant-scoped canonical communication facts carrying this exact typed journey_id or journey_ids reference. |
| `conversions` | required |  | `canonical_conversions`, `journeys` | `episode360` (primary): subjects `journey`; `outcomes` | — | Partial: `Only the current journey version's explicit conversion IDs are resolved; wider conversion inventory and historical versions are not established.` | Canonical conversions explicitly referenced by the current JourneyVersion. |
| `dropoffs` | required |  | `episode_journey_authority_records`, `journeys`, `events`, `evidence` | `episode360` (primary): subjects `journey`; `summary`, `interactions`, `evidence` | — | Partial: `Only explicit current-version abandonment records are joined. Complete journey history, causal dropoff reason, permanence, and source freshness remain unknown.` | Exact current-version journey abandonment records with evidence-backed journey-step events; missing history does not imply no dropoff. |
| `entity_context` | optional |  | `episode_facts`, `graph`, `identity`, `journeys` | `profile360` (primary): subjects `entity`, `episode`, `journey`; `summary`, `state`, `evidence` | — | — | Resolved linked user-profile context for entity, journey, or episode subjects; parent identity is not substituted for the requested subject. |
| `episodes` | required |  | `episode_facts` | `episode360` (primary): subjects `journey`; `episode_context` | — | Partial: `Only EpisodeRecords with an explicit journey_id are joined through the tenant-scoped episode store. Legacy or unlinked records, association-population completeness, store freshness, policy, and historical replay remain unknown.` | Tenant-scoped episodes that explicitly record the exact journey ID. |
| `events_and_episode_context` | optional |  | `events`, `episode_facts` | `episode360` (primary): subjects `journey`, `entity`, `episode`; `timeline`, `evidence` | — | — | Events and episode facts associated with the journey. |
| `evidence_trace` | required |  | `journeys`, `campaign_touchpoints`, `evidence` | `episode360` (primary): subjects `journey`; `evidence` | — | — | Journey version, step, and exact touchpoint record refs. |
| `journey_summary` | required |  | `journeys` | `episode360` (primary): subjects `journey`; `summary` | — | Partial: `current_version_only_and_source_freshness_threshold_is_unconfigured` | Exact current JourneyVersion record and version evidence. |
| `recommended_actions` | required |  | `actions`, `episode_journey_authority_records`, `journeys` | `episode360` (primary): subjects `journey`; `summary`, `interactions`, `evidence` | — | Authority: `A non-executable recommendation record does not join the canonical action execution authority.`; Partial: `Current-version intents and exact caller-associated agent lifecycle requests are visible after slot policy; action dispatch, external effects, policy replay, outcomes, full recommendation inventory and freshness remain unknown.` | Exact current-journey-version non-executable action intent records validated against canonical journey and step evidence. |
| `stages` | required |  | `events`, `evidence`, `journeys` | `episode360` (primary): subjects `journey`; `stages` | — | Partial: `Exact v3.0 role markers and a bounded, fully evidenced current-version marker inventory are available. No canonical business-stage definition or boundary authority exists, so stage taxonomy and stage completeness remain unknown.` | Versioned source-role markers on exact current-version journey steps, with typed v3.0 role and event evidence; business stages remain distinct. |
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

Canonical authorities: `actions`, `attribution_credits`, `attribution_runs`, `campaign_touchpoints`, `canonical_conversions`, `communication_facts`, `episode_facts`, `episode_journey_authority_records`, `events`, `evidence`, `graph`, `identity`, `journeys`, `touchpoints`.

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
| `activity_density` | required |  | `geo_observations`, `gold_temporal_heatmap` | `geographic360` (primary): subjects `entity`; `state` | — | Partial: `Exact-linked heatmap bins carry both Gold and location-fact evidence. Aggregate-only bins remain unknown; location-specific coverage, freshness, and privacy policy evaluation remain unestablished.` | Tenant-scoped heatmap density bins only when an explicit location_id or source_observation_id names the exact canonical location fact. |
| `campaigns` | required |  | `campaign_facts`, `locations` | `geographic360` (primary): subjects `entity`, `population`, `source`; `state` | — | Partial: `Campaign touchpoints join only by exact location source observation ID; missing touchpoints, full campaign coverage, history, and freshness remain unknown.` | Exact campaigns linked to a canonical location fact. |
| `entity_graph_context` | optional |  | `entity_graph`, `graph` | `geographic360` (primary): subjects `entity`, `population`, `source`; `summary`, `findings`; `profile360` (supporting): subjects `entity`; `summary`, `findings` | — | — | Entity graph context linked to locations. |
| `evidence_trace` | required |  | `locations`, `context_capsules` | `geographic360` (primary): subjects `entity`, `population`, `source`; `evidence`, `state` | — | — | Location fact and source observation references at allowed precision. |
| `geo_hierarchy` | required |  | `locations`, `geo_observations` | `geographic360` (primary): subjects `entity`, `population`, `source`; `state`, `evidence` | — | — | Recorded geographic labels at source supported precision. |
| `geographic_observations` | optional |  | `geo_observations`, `temporal` | `geographic360` (primary): subjects `entity`, `population`, `source`; `timeline`, `evidence` | — | — | Observed geographic facts and their temporal context. |
| `journeys` | required |  | `journeys`, `locations` | `geographic360` (primary): subjects `entity`; `state` | — | Partial: `Current exact entity journey versions are joined only when they cite the location source observation; historical versions, other subject kinds, and complete coverage remain unknown.` | Exact journeys linked to a canonical location fact. |
| `location_identity_and_state` | optional |  | `locations`, `context_capsules` | `geographic360` (primary): subjects `entity`, `population`, `source`; `summary`, `state`, `evidence` | — | — | Location registry and geographic context. |
| `normalization` | required |  | `locations` | `geographic360` (primary): subjects `entity`, `population`, `source`; `normalization` | — | Partial: `Capsule transformation version and location-fact materialization timestamp are recorded separately from schema version. Validation version, raw record reference, complete lineage, and freshness remain unknown.` | Canonical location-fact source links, capsule transformation version, and materialization time; raw record and validation lineage are explicit unknowns. |
| `place_summary` | required |  | `locations`, `geo_observations`, `context_capsules` | `geographic360` (primary): subjects `entity`, `population`, `source`; `summary`, `state` | — | — | Best supported place fact at policy capped precision. |
| `population_context` | optional |  | `population_definitions`, `cohort_membership` | `population360` (primary): subjects `entity`, `population`; `summary`, `state`, `findings` | — | — | Population context for a location. |
| `profiles` | required |  | `identity`, `locations` | `geographic360` (primary): subjects `entity`; `state` | — | Partial: `Only exact tenant entity profile records are joined; other location subject kinds, history, complete identity coverage, and freshness remain unknown.` | Profiles linked to place with profile policy applied. |
| `risk` | required |  | `locations`, `risk_outputs`, `risk_signals` | `geographic360` (primary): subjects `entity`, `population`, `source`; `state` | — | Partial: `RiskSignals and canonical RiskAssessments join only when exact typed-subject evidence cites the location observation. Assessment output is separate from signal input; causal location risk, producer coverage, history, policy, and freshness remain unknown.` | Risk outputs linked to place with evidence. |
| `timezone` | required |  | `geo_temporal_timezone_assertions`, `locations`, `temporal` | `geographic360` (primary): subjects `entity`, `population`, `source`; `state`, `evidence` | — | Partial: `Timezone assertions join exact location facts with effective and recorded time; source assertion coverage, non-geographic projection subjects, and freshness SLA remain unknown.` | Verified time zone and temporal conversion evidence. |
| `value` | required |  | `economic_facts`, `locations` | `geographic360` (primary): subjects `entity`; `state` | — | Partial: `Economic facts join only by exact location source observation ID for entity subjects; causal location value, other subject kinds, history, and freshness remain unknown.` | Economic facts linked to place without subject inference. |

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

Canonical authorities: `campaign_facts`, `cohort_membership`, `context_capsules`, `economic_facts`, `entity_graph`, `geo_observations`, `geo_temporal_timezone_assertions`, `gold_temporal_heatmap`, `graph`, `identity`, `journeys`, `locations`, `population_definitions`, `risk_outputs`, `risk_signals`, `temporal`.

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
| `cards` | required |  | `consent_policy_decisions`, `semantic_context_cards`, `semantic_memory_records` | `memory360` (primary): subjects `entity`, `semantic_entity`; `cards` | — | Partial: `Only active same-tenant policy-allowed records project from bounded pages; actor identity resolution, complete producer coverage, historical replay, and freshness thresholds remain unknown.` | Append-only exact tenant/subject context-card records with source-memory evidence and recorded policy disposition. |
| `conflicts` | required |  | `semantic_memory_graph` | `memory360` (primary): subjects `entity`, `semantic_entity`; `conflicts` | — | — | Derived contradiction signal only; canonical conflict objects remain unknown. |
| `decay` | required |  | `semantic_memory_graph` | `memory360` (primary): subjects `entity`, `semantic_entity`; `decay` | — | — | Reducer half-life parameter only; per-memory decay remains unknown. |
| `embeddings_meta` | required |  | `consent_policy_decisions`, `semantic_context_cards`, `semantic_embedding_metadata` | `memory360` (primary): subjects `entity`, `semantic_entity`; `embeddings_meta` | — | Partial: `Metadata is bounded and always degraded when present because vector existence, provider inventory, actor identity resolution, complete producer coverage, and freshness thresholds remain unknown.` | Append-only exact tenant/subject embedding producer metadata linked through canonical context cards and source evidence. |
| `evidence_trace` | required |  | `semantic_memory_graph`, `evidence` | `memory360` (primary): subjects `entity`, `semantic_entity`; `evidence_trace` | — | — | Gold and active Silver semantic record lineage. |
| `memories` | required |  | `semantic_memory_graph`, `semantic_memory_records`, `silver_semantic_observations`, `consent_policy_decisions` | `memory360` (primary): subjects `entity`, `semantic_entity`; `memories` | — | Partial: `Only explicit stored memories with exact source and historical consent-decision evidence are read; no automatic memory producer or configured freshness SLA is available.` | Required memory360 slot: memories. |
| `policy_state` | required |  | `semantic_memory_records`, `consent_policy_decisions`, `evidence` | `memory360` (primary): subjects `entity`, `semantic_entity`; `policy_state` | — | Partial: `Exact tenant and subject historical allow decisions are rendered with timestamped canonical consent-policy evidence. Explicit nonempty required purposes stamped from that verified write-time decision are surfaced; legacy unstamped purposes remain unknown. Current consent and policy are not evaluated, so present authorization remains unknown.` | Required memory360 slot: policy state. |
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

Canonical authorities: `consent_policy_decisions`, `evidence`, `semantic_context_cards`, `semantic_embedding_metadata`, `semantic_memory_graph`, `semantic_memory_records`, `silver_semantic_observations`, `source_provenance`.

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
| `likely_next_states` | required |  | `analytics_events`, `consent_policy_decisions`, `identity_source_identities`, `model_artifact_registry`, `model_governance`, `outcome_facts`, `profile_prediction_outputs` | `profile360` (primary): subjects `entity`; `likely_next_states` | — | Authority: `Model calibration and independent outcome verification are not joined to prediction outputs.`; Partial: `The read rechecks the exact recorded inference policy decision and, for session models, the current session-to-entity evidence, alongside the future-state schema, current production artifact, validity interval, and freshness. An artifact-reported calibration metric may be exposed with unknown evaluation scope. Current serving outputs omit required fields; historical identity, current consent, revocation history, outcome verification, and independently validated model calibration remain unknown.` | Policy-admitted append-only future-state predictions for an exact canonical human entity, versioned state schema, active production artifact checksum, source event evidence, and bounded validity and freshness. |
| `location_temporal` | required |  | `geo_observations`, `temporal` | `geographic360` (primary): subjects `entity`; `evidence`, `timeline` | — | Partial: `The source reports recorded entity location facts only; profile alias resolution, continuous trajectory reconstruction, cross-surface completeness, historical point-in-time reconstruction, and Profile-specific freshness remain unknown.` | Tenant-scoped observed location facts and their recorded temporal bounds for the exact entity subject. |
| `observed_state_and_activity` | optional |  | `observations`, `graph`, `temporal` | `profile360` (primary): subjects `entity`, `agent`; `state`, `timeline`, `interactions` | — | — | Observed state and temporal activity with explicit provenance. |
| `relationship_context` | optional |  | `relationship_facts` | `profile360` (primary): subjects `entity`; `relationships` | — | — | Relationship context through the Profile360 identity and policy gate. |
| `relationships` | required |  | `graph`, `relationship_facts` | `profile360` (primary): subjects `entity`; `relationships` | — | Partial: `Profile360 now requires an exact tenant human profile/entity same-ID binding and an allowed relationships slot before a nested Relationship360 ledger read. Alias and account-member identities remain unresolved; bounded ledger evidence, history, complete edge coverage, and Profile-specific freshness remain unknown.` | Tenant-scoped canonical human profile identity gates a nested Relationship360 read over the exact entity's graph mutation ledger with bounded edge evidence. |
| `risk_context` | optional |  | `risk_outputs`, `model_governance` | `risk360` (primary): subjects `entity`; `summary`, `findings`, `evidence` | — | — | Governed risk and fraud context. |
| `risk_summary` | required |  | `evidence`, `risk_outputs` | `risk360` (primary): subjects `agent`, `entity`; `evidence`, `findings`, `state`, `summary` | — | Partial: `Risk assessment and evidence reads bind by exact tenant, subject kind, and subject ID; a Profile-specific freshness threshold remains unknown.` | Tenant-exact Risk360 assessment and evidence for the same canonical entity or Agent subject; no profile identity is inferred. |
| `session_history` | required |  | `analytics_events`, `evidence`, `identity` | `profile360` (primary): subjects `entity`; `sessions` | — | Partial: `Only exact identity-owned session and event records are observed. Session roster and event-timeline completeness remain partial without source watermarks; missing records do not prove inactivity.` | Resolved tenant/profile identities join exact analytics session rollups and identity-owned activity event IDs in the requested window. |
| `syndicates` | required |  | `cohort_membership`, `evidence`, `population_definitions` | `profile360` (primary): subjects `entity`; `syndicates` | — | Partial: `Exact current MEMBER_OF edges for explicitly opted-in tenant populations are evidence-backed; unbounded roster completeness, historical replay, and a membership freshness policy remain unavailable.` | Exact current tenant entity membership in an explicitly opted-in Syndicates population, verified by the live graph ledger edge. |
| `value_summary` | required |  | `ai_execution_facts`, `economic_facts`, `outcome_facts` | `economic360` (primary): subjects `agent`, `entity`; `evidence`, `summary` | — | Partial: `Economic360 reads exact tenant-scoped economic facts for canonical entity and Agent subjects; Outcome360 does not yet support exact entity/profile subjects for attributed outcomes, and Profile-specific freshness remains unknown.` | Direct tenant-scoped economic facts for the exact canonical entity or Agent subject; measured outcomes and attribution remain unresolved. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `economic360` | `catalog_only` (primary) | `implemented` | `economic360.read`, `economic360.explore` |
| `outcome360` | `catalog_only` (supporting) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `profile360` | `catalog_only` (primary) | `in_flight` | `profile360.read`, `profile360.explore` |
| `geographic360` | `catalog_only` (primary) | `implemented` | `geographic360.read`, `geographic360.explore` |
| `risk360` | `catalog_only` (primary) | `implemented` | `risk360.read`, `risk360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `agent_access`, `agent_executions`, `ai_execution_facts`, `analytics_events`, `cohort_membership`, `communication_facts`, `consent_policy_decisions`, `economic_facts`, `entity_registry`, `evidence`, `geo_observations`, `graph`, `identity`, `identity_source_identities`, `journeys`, `model_artifact_registry`, `model_governance`, `observations`, `outcome_facts`, `population_definitions`, `profile_prediction_outputs`, `relationship_facts`, `risk_outputs`, `temporal`.

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
| `anomaly_events` | required |  | `risk_outputs`, `observations`, `risk_signals`, `evidence` | `risk360` (primary): subjects `agent`, `cluster`, `contagion_path`, `entity`, `relationship`, `source`; `findings`, `evidence`, `health` | — | Partial: `Authenticated Gold alert materialization verifies an exact tenant/subject RiskSignal and one selected event EvidenceRef before writing the link triplet. For explicit bronze_sdk_events references, Risk360 also checks one exact tenant Bronze V1/V2 record without exposing payload; missing, duplicate, tombstoned, or quarantined records remain unverified. Legacy alerts remain metadata only. This is a caller-selected alert path, not an automatic detector producer; complete event coverage, detector coverage, cause, severity, and freshness remain unknown.` | Exact tenant and typed-subject Gold anomaly alerts, with optional bounded RiskSignal, event evidence, and Bronze SDK event-record metadata when explicit identifiers match. |
| `audit_history` | required |  | `computation`, `evidence`, `risk_assessments`, `risk_intervention_records` | `risk360` (primary): subjects `agent`, `cluster`, `contagion_path`, `entity`, `relationship`, `source`; `evidence`, `findings` | — | Partial: `Assessment-run and append-only intervention histories are available for exact subjects; direct supersedes references are exposed only after exact predecessor verification. Cross-assessment late-data lineage, full restatement history, actor authority, producer completeness, independent outcome verification, and freshness remain unknown.` | Exact-subject assessment-run and intervention histories with bounded, verified direct predecessor links when the stored supersedes reference agrees on tenant, subject, definition, version, and context. |
| `economic_exposure` | optional |  | `ai_execution_facts`, `economic_facts` | `economic360` (primary): subjects `entity`, `agent`; `summary`, `evidence`, `outcomes` | — | — | Economic facts associated with the risk subject and network. |
| `evidence_trace` | required |  | `evidence`, `flow_trace_paths`, `flow_traces`, `risk_assessments`, `risk_outputs`, `risk_signals`, `source_provenance`, `transfers` | `risk360` (primary): subjects `agent`, `cluster`, `contagion_path`, `entity`, `relationship`, `source`; `evidence`, `findings`, `health` | — | — | Exact assessment, signal, and source ingress evidence references. |
| `execution_exposure` | optional |  | `execution_facts` | `execution360` (primary): subjects `entity`, `agent`; `summary`, `timeline`, `evidence` | — | — | Execution facts associated with an agent or execution subject. |
| `financial_contagion` | required |  | `flow_trace_paths`, `flow_traces`, `transfers`, `risk_assessments`, `risk_signals`, `consent_policy_decisions` | `risk360` (primary): subjects `contagion_path`; `findings` | — | Partial: `The bounded path is a correlated observation only. Causal contagion, exposure, loss, source coverage, current risk policy outcome, and freshness are unknown; missing or denied entity consent suppresses path details.` | Exact financial transfer path linked to risk evidence for each node after affirmative current analytics consent for every path entity; causal contagion, exposure, and loss remain unproven. |
| `fraud_and_social_patterns` | optional |  | `fraud_synthesis`, `graph_motifs`, `social_observations` | `fraud360` (primary): subjects `entity`, `relationship`, `agent`; `findings`, `evidence`, `health`; `social360` (supporting): subjects `entity`, `relationship`; `findings`, `evidence` | — | — | Fraud synthesis, graph motifs, and social observations. |
| `interventions` | required |  | `actions`, `risk_intervention_records`, `risk_outputs` | `risk360` (primary): subjects `agent`, `cluster`, `contagion_path`, `entity`, `relationship`, `source`; `findings`, `evidence`, `health` | — | Authority: `Append-only exact-subject intervention decisions and reported outcomes are readable; actor authority, producer coverage, independent outcome verification, and freshness remain unknown.`; Partial: `Exact-subject intervention decisions and reported outcomes can include slot-authorized, caller-associated agent lifecycle requests; dispatch, external effects, actor authority, producer coverage, independent outcome verification, and freshness remain unknown.` | Recorded risk interventions and results. |
| `poisoning_evidence` | required |  | `risk_outputs`, `source_provenance` | `risk360` (primary): subjects `agent`, `cluster`, `contagion_path`, `entity`, `relationship`, `source`; `evidence`, `findings` | — | Partial: `Risk360 reads explicitly stored detector evidence for exact tenant and subject bindings, with temporal anchors, lifecycle, restatement lineage, and evidence references. Detector coverage, independent source verification, population-wide completeness, and a source freshness SLA remain unknown.` | Tenant-scoped detector evidence for exact subjects, with versioned lifecycle and evidence references; detector completeness and source reputation remain unknown. |
| `policy_flags` | required |  | `model_governance`, `risk_outputs`, `risk_signals` | `risk360` (primary): subjects `agent`; `evidence`, `findings` | — | Partial: `Only exact tenant-scoped current agent risk-signal records are exposed as reported observations. Policy evaluation, model/version, non-agent subjects, historical replay, and complete coverage remain unknown.` | Exact agent risk-signal policy-flag observations with evidence; evaluated flags require versioned model-governance decisions. |
| `propagation_paths` | required |  | `graph`, `relationship_facts`, `consent_policy_decisions`, `evidence` | `risk360` (primary): subjects `entity`; `findings` | — | Partial: `Bounded current tenant-scoped FOLLOWS paths are emitted only with analytics consent, canonical graph and relationship evidence, exact endpoint scope, valid edge state, and acceptable evidence times. Observed edges do not prove causal risk propagation; historical reads, complete path coverage, and freshness remain unknown.` | Observed, consent-governed social graph paths used as risk investigation context; path evidence alone does not establish risk propagation. |
| `relationship_network_context` | optional |  | `entity_graph`, `relationship_facts`, `graph` | `relationship360` (primary): subjects `agent`, `entity`, `relationship`; `summary`, `interactions`, `evidence`; `risk360` (supporting): subjects `entity`, `relationship`, `cluster`; `summary`, `evidence` | — | — | Entity graph and relationship evidence relevant to risk. |
| `risk_assessment_state` | optional |  | `risk_outputs`, `model_governance` | `risk360` (primary): subjects `agent`, `entity`, `relationship`, `cluster`; `summary`, `state`, `findings`, `health` | — | — | Risk outputs, model governance context, and assessment state. |
| `risk_evidence_and_limitations` | optional |  | `evidence` | `risk360` (primary): subjects `agent`, `entity`, `relationship`, `cluster`; `evidence`, `findings` | — | — | Evidence and limitations supporting risk findings. |
| `risk_summary` | required |  | `risk_outputs`, `evidence` | `risk360` (primary): subjects `agent`, `cluster`, `entity`, `relationship`, `source`; `summary`, `state`, `evidence`, `findings` | — | — | Exact scoped canonical assessment and dimension state with evidence and confidence. |
| `social_contagion` | required |  | `social_relationship_evidence_events`, `bronze_sdk_events`, `entity_graph`, `relationship_facts`, `risk_signals`, `consent_policy_decisions` | `risk360` (primary): subjects `entity`; `findings` | — | Partial: `The bounded source-reported path is correlated only; causal contagion, complete source coverage, current policy outcome, and freshness are unproven. Consent denial suppresses content.` | Exact source-reported social path evidence joined to tenant-scoped risk, relationship, and event authorities; causality remains unverified. |
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

Canonical authorities: `actions`, `ai_execution_facts`, `bronze_sdk_events`, `computation`, `consent_policy_decisions`, `economic_facts`, `entity_graph`, `evidence`, `execution_facts`, `flow_trace_paths`, `flow_traces`, `fraud_synthesis`, `graph`, `graph_motifs`, `model_governance`, `observations`, `relationship_facts`, `risk_assessments`, `risk_intervention_records`, `risk_outputs`, `risk_signals`, `social_observations`, `social_relationship_evidence_events`, `source_provenance`, `transfers`.

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
| `classification` | required |  | `events`, `observations`, `silver_semantic_observations` | `signals360` (primary): subjects `event`, `observation`; `classification` | — | Partial: `Exact gateway-accepted SDK event type and family are registry-validated. A bounded current Silver semantic read may expose model-output metadata only when tenant, event ID, stamped namespace, event type, time, and source evidence match. Derived labels remain suppressed; source attribution, semantic correctness, policy, producer coverage, and freshness remain unknown.` | Required signals360 slot: classification. |
| `evidence_trace` | required |  | `behavioral_signals` | `signals360` (primary): subjects `entity`; `evidence_trace` | — | — | Evidence references for bounded derived signal records. |
| `freshness` | required |  | `behavioral_signals` | `signals360` (primary): subjects `entity`; `freshness` | — | — | Source timestamps retained from bounded derived signal records; freshness threshold remains unknown. |
| `linked_entities` | required |  | `behavioral_signals`, `identity` | `signals360` (primary): subjects `signal`, `event`, `observation`; `linked_entities` | — | Partial: `Exact links are emitted for signal, event, and matching observation IDs; entity, source, stream, absent-link, and incomplete reads remain unknown or degraded.` | Exact tenant signal, event, or observation bindings to active canonical identity subjects; observation IDs join only when recorded as the matching source_event_id. |
| `normalization` | required |  | `observations`, `source_schema` | `signals360` (primary): subjects `event`, `observation`; `normalization` | — | Partial: `exact_gateway_accepted_sdk_adapter_and_envelope_schema_lineage_only; semantic_correctness_producer_coverage_and_freshness_sla_unknown` | Exact tenant SDK observation gateway normalization lineage with adapter and envelope schema versions; semantic correctness and producer coverage remain unknown. |
| `quality` | required |  | `ingestion_health`, `source_schema`, `observations` | `signals360` (primary): subjects `event`, `observation`; `quality` | — | Partial: `Gateway acceptance and exact tenant/site install-signal status are separate observations. Mobile and tenant-wide events have no installation-health join; event-time health, fleet completeness, source reliability, semantic quality, and a freshness SLA remain unknown.` | Exact SDK Bronze gateway acceptance and, for an authenticated site namespace, separately observed current site install-signal status; event and fleet health remain unknown. |
| `risk_flags` | required |  | `risk_outputs` | `signals360` (primary): subjects `event`, `observation`, `signal`, `source`, `stream`; `risk_flags` | — | Partial: `Exact tenant and typed-subject RiskSignal records are projected as partial observations; producer coverage, assessment history, policy, freshness, and causality remain unknown.` | Required signals360 slot: risk flags. |
| `signal_summary` | required |  | `behavioral_signals` | `signals360` (primary): subjects `entity`; `signal_summary` | — | — | Bounded tenant and entity scoped translator-derived signal records. |
| `source_inventory` | required |  | `source_facts`, `source_provenance` | `signals360` (primary): subjects `event`, `observation`; `source_inventory` | — | Partial: `One exact SDK event or observation is described; authenticated site-scoped events may join the current canonical tenant site registry. Mobile and tenant-wide events, historical registration state, fleet inventory, and source reliability remain unknown.` | Authenticated source metadata for an exact SDK event or observation, with an exact current tenant site registration fact when its server-stamped site namespace resolves; fleet inventory remains unknown. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `signals360` | `catalog_only` (primary) | `in_flight` | `signals360.read` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `behavioral_signals`, `campaign_facts`, `campaign_touchpoints`, `events`, `identity`, `ingestion_health`, `observations`, `risk_outputs`, `silver_semantic_observations`, `source_facts`, `source_provenance`, `source_schema`.

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
| `risk_edges` | required |  | `graph`, `relationship_facts`, `risk_outputs` | `social360` (primary): subjects `entity`, `relationship`; `risk_edges` | — | Partial: `Only evidence-linked current SHARES_RISK_CONTEXT_WITH edges are projected as correlated context; policy, freshness, trust, propagation, contagion, and causality remain unestablished.` | Policy governed risk relationship edges. |
| `social_contagion` | required |  | `entity_identity`, `graph`, `relationship_facts`, `risk_outputs`, `risk_signals`, `social_observations`, `social_relationship_evidence_events`, `source_provenance` | `social360` (primary): subjects `entity`; `social_contagion` | — | Partial: `Source-reported correlated path evidence is available, but causal contagion, source reliability policy, completeness and freshness remain unknown.` | Exact source-reported social risk association over a validated canonical entity path with source ingress, risk signal, actor and evidence references; causality remains unverified. |
| `social_observations_and_sources` | optional |  | `social_observations`, `source_facts`, `identity`, `cohort_membership` | `social360` (primary): subjects `entity`, `relationship`, `source`, `population`; `summary`, `timeline`, `interactions`, `evidence` | — | — | Social observations and their source facts. |
| `syndicates` | required |  | `cohort_membership`, `evidence`, `graph`, `population_definitions` | `social360` (primary): subjects `entity`; `syndicates` | — | Partial: `membership_roster_completeness_historical_replay_and_freshness_remain_unknown` | Verified syndicate membership and topology. |
| `trust_edges` | required |  | `authenticated_tenant_permission`, `entity_identity`, `relationship_facts`, `social_relationship_evidence_events` | `social360` (primary): subjects `entity`; `trust_edges` | — | Partial: `Operator-asserted directional trust is available; policy-derived trust semantics, relationship graph mutation, score, completeness and freshness remain unknown.` | Authenticated tenant operator trust assertion for an exact canonical entity pair, with actor and policy-grant evidence; no inferred trust score or graph edge. |

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

Canonical authorities: `authenticated_tenant_permission`, `cohort_membership`, `computation`, `entity_identity`, `evidence`, `geo_observations`, `graph`, `identity`, `influence_propagation`, `locations`, `population_definitions`, `relationship_facts`, `relationship_fidelity`, `relationship_predicate_registry`, `risk_outputs`, `risk_signals`, `social_observations`, `social_relationship_evidence_events`, `source_coverage`, `source_facts`, `source_provenance`.

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
| `agents` | required |  | `agent_entities`, `communication_facts`, `support_case_agent_assignment_events`, `support_cases` | `support360` (primary): subjects `support_case`; `state`, `evidence` | — | Partial: `Append-only exact case assignment and handoff events resolve canonical Agent identities and assigning principals; upstream history, delegation authority, and freshness remain unknown.` | Validated support agent assignments and handoffs. |
| `callbacks` | required |  | `support_callbacks`, `support_callback_events`, `support_cases`, `support_case_events`, `provider_connections`, `evidence` | `support360` (primary): subjects `support_case`, `callback`; `state`, `timeline`, `evidence` | — | Partial: `callback_schedule_and_execution_authority_is_tenant_case_connection_scoped_but_upstream_provider_origin_and_actor_attribution_are_unverified; source_history_completeness_and_freshness_remain_unknown` | Canonical callback schedule and execution records joined to the exact tenant, support case, provider connection, and retained callback events. |
| `case_summary` | required |  | `support_cases`, `support_case_events`, `provider_connections`, `evidence` | `support360` (primary): subjects `support_case`; `summary`, `state`, `evidence` | — | Partial: `persisted_case_events_do_not_prove_source_history_completeness_or_freshness_sla` | Exact tenant-owned support case identity and observed lifecycle state from persisted source events. |
| `conversation_history` | required |  | `communication_facts`, `evidence`, `provider_connections`, `support_cases`, `support_case_events` | `support360` (primary): subjects `entity`, `support_case`; `interactions` | — | Partial: `Canonical support_case history joins only through the exact tenant, provider connection, and source case key; message bodies and participant identities stay suppressed without their separate authorities, source-history completeness is unverified, and no freshness SLA is available.` | Tenant scoped support communication metadata; bodies require separate content permission. |
| `entity_and_agent_context` | optional |  | `identity`, `agent_entity` | `profile360` (primary): subjects `entity`, `agent`; `summary`, `state`; `agent360` (supporting): subjects `entity`, `agent`; `summary`, `state`, `evidence` | — | — | Identity and agent context associated with support activity. |
| `evidence_trace` | required |  | `communication_facts`, `evidence`, `provider_connections`, `support_cases`, `support_case_events` | `support360` (primary): subjects `entity`, `support_case`; `evidence`, `summary`, `state` | — | Partial: `source_history_completeness_and_freshness_sla_are_unverified` | Source references for exact support communication metadata or case lifecycle; message bodies are excluded. |
| `journey_links` | required |  | `episode_facts`, `journeys`, `support_case_context_events`, `support_cases` | `support360` (primary): subjects `support_case`; `state`, `evidence` | — | Partial: `Append-only support case journey-link events join current exact tenant journey records. An EpisodeRecord is linked only when it names the same journey and cites the exact verified case context event; no live producer populates that relation today, and source authorship, historical state, complete population, and freshness remain unknown.` | Exact support case to journey relationships. |
| `measured_outcomes` | optional |  | `outcome_facts` | `outcome360` (primary): subjects `episode`; `outcomes`, `evidence` | — | — | Measured support outcomes where an authoritative provider exists. |
| `participants` | required |  | `communication_facts`, `identity`, `provider_connections`, `support_cases` | `support360` (primary): subjects `support_case`; `interactions`, `evidence` | — | Partial: `Participants require exact support-scoped communication thread and current provider account binding; identity linkage, source history, historical membership, and freshness may remain unknown.` | Case participants with identity and content policy. |
| `resolution` | required |  | `support_cases`, `support_case_events` | `support360` (primary): subjects `support_case`; `outcomes`, `state` | — | Partial: `exact_applied_case_lifecycle_event_and_provider_connection_evidence_support_resolved_or_closed_state; canonical_business_outcome_facts_remain_unavailable` | Recorded support outcome and resolution state; lifecycle resolution alone does not prove the business outcome. |
| `risk` | required |  | `risk_outputs`, `risk_signals`, `support_cases`, `evidence` | `risk360` (primary): subjects `support_case`; `summary`, `state`, `evidence`, `findings` | — | Partial: `The tenant-owned support case and its exact risk assessment and signals are joined with canonical evidence; risk-history completeness, support-case freshness SLA, and business outcome remain unknown.` | Risk outputs associated with the exact support case. |
| `risk_context` | optional |  | `risk_outputs` | `risk360` (primary): subjects `entity`; `summary`, `findings`, `evidence` | — | — | Risk context from its governing projection, subject to policy. |
| `sla` | required |  | `measurement_contract`, `support_case_context_events`, `support_cases` | `support360` (primary): subjects `support_case`; `state`, `evidence` | — | Partial: `Exact tenant-registered source policy revisions bind matching case timers and target durations, with contract evidence. Historical applicability, measured breach evaluation, source-history completeness, and freshness remain unknown.` | Support service level contract and timer state. |
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

Canonical authorities: `agent_entities`, `agent_entity`, `communication_facts`, `episode_facts`, `events`, `evidence`, `identity`, `journeys`, `measurement_contract`, `outcome_facts`, `provider_connections`, `risk_outputs`, `risk_signals`, `source_coverage`, `source_provenance`, `support_callback_events`, `support_callbacks`, `support_case_agent_assignment_events`, `support_case_context_events`, `support_case_events`, `support_cases`.

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
| `attribution_credits` | required |  | `ai_execution_facts`, `attribution_credits`, `attribution_runs`, `campaign_touchpoints`, `canonical_conversions` | `economic360` (primary): subjects `conversion`, `profile`, `entity`, `cluster`, `campaign`, `journey`, `account`, `agent`, `episode`, `source`; `evidence` | — | Partial: `attribution_credit_reads_are_bounded_and_explicitly_truncated_but_history_is_not_bitemporal_and_model_credit_is_not_independently_measured_value` | Credited value allocated by canonical attribution authority. |
| `campaign_and_attribution_context` | optional |  | `attribution_credits`, `campaign_facts` | `campaign360` (primary): subjects `campaign`, `episode`; `summary`, `evidence`, `outcomes` | — | — | Campaign facts and attribution credits associated with value. |
| `confidence` | required |  | `ai_execution_facts`, `attribution_credits`, `attribution_runs`, `canonical_conversions`, `model_governance` | `economic360` (primary): subjects `account`, `agent`, `campaign`, `cluster`, `conversion`, `entity`, `journey`, `profile`; `evidence` | — | Authority: `model_governance_calibration_and_validation_not_joined`; Partial: `Exact conversion/run/credit-linked model-reported confidence may include a persisted check of recorded run configuration lineage against the current matching config. Model governance approval, calibration, historical config immutability, and applicability to realized value remain unvalidated.` | Evidence-linked, model-reported attribution confidence only; not a calibrated estimate of realized value or ROI. |
| `conversion_inventory` | required |  | `ai_execution_facts`, `canonical_conversions`, `entity_registry`, `identity_clusters_v2` | `economic360` (primary): subjects `conversion`, `profile`, `entity`, `cluster`, `campaign`, `journey`, `account`, `agent`; `evidence` | — | Partial: `Exact account entity identity and active identity-cluster records gate their conversion inventories; wallet-cluster crosswalks, historical replay, full source coverage, and freshness remain unknown.` | Canonical conversion ledger records linked to exact tenant-scoped subject identity; account subjects resolve through Account360 entity authority and cluster subjects through the active identity-cluster authority before current conversion reads. |
| `economic_facts_and_state` | optional |  | `ai_execution_facts`, `currency_value_normalization`, `economic_facts` | `economic360` (primary): subjects `campaign`, `episode`, `journey`; `summary`, `state`, `evidence` | — | — | Economic facts and value state with currency normalization provenance. |
| `evidence_trace` | required |  | `ai_execution_facts`, `canonical_conversions`, `commerce`, `economic_facts`, `payments` | `economic360` (primary): subjects `agent`, `campaign`, `entity`, `episode`, `journey`, `source`, `conversion`, `profile`, `account`, `cluster`; `summary`, `evidence` | — | — | Canonical economic, payment, commerce, and conversion evidence references for exact supported subjects. |
| `financial_risk` | required |  | `ai_execution_facts`, `risk_outputs`, `economic_facts` | `economic360` (primary): subjects `agent`, `cluster`, `entity`, `source`; `evidence`, `summary`; `risk360` (supporting): subjects `agent`, `cluster`, `entity`, `source`; `financial_risk` | — | Partial: `Exact tenant and subject economic claims join only to assessed economic, payment, or transaction Risk360 dimension claims on current reads; historical joins, coordinated freshness thresholds, and complete source coverage remain unknown.` | Financial risk linked to economic facts by exact subject. |
| `ltv` | required |  | `ai_execution_facts`, `canonical_conversions`, `evidence` | `economic360` (primary): subjects `profile`, `entity`, `account`, `cluster`, `campaign`, `journey`, `agent`; `evidence` | — | Partial: `Exact evidence-backed confirmed_or_adjusted conversion net values are reported only for the canonical rows returned; lifetime and historical completeness, outcome attribution, and freshness remain unknown, missing net values degrade the slot, and native currency totals are not combined.` | Evidence-backed confirmed or adjusted canonical conversion net value over a defined subject and temporal scope; full lifetime coverage remains unknown and native currencies stay partitioned. |
| `measured_outcomes` | optional |  | `outcome_facts`, `measurement_contract` | `outcome360` (primary): subjects `campaign`, `episode`, `journey`; `summary`, `evidence`, `outcomes` | — | — | Measured outcome facts linked to economic value. |
| `payments_and_commerce_evidence` | optional |  | `ai_execution_facts`, `commerce`, `payments` | `economic360` (primary): subjects `campaign`, `episode`, `journey`; `evidence`, `outcomes` | — | — | Payment and commerce evidence from the corresponding authorities. |
| `reconciliation` | required |  | `ai_execution_facts`, `commerce`, `currency_value_normalization`, `economic_facts`, `evidence`, `payments` | `economic360` (primary): subjects `campaign`, `entity`, `journey`; `evidence` | — | Partial: `Subject-scoped economic rows and exact order-linked commerce facts remain separate observations. Settlement-to-payment links require the explicit provider payment ID and same commerce order reference; only native USD identity normalization is accepted. Economic records lack exact order, payment, and settlement IDs, so cross-source matching, non-USD commerce normalization, reconciled totals, and completeness remain unavailable.` | Separate source-native economic and commerce observations with exact settlement-to-payment references; cross-source reconciliation remains explicit. |
| `revenue_events` | required |  | `ai_execution_facts`, `canonical_conversions`, `economic_facts`, `payments`, `revenue_adjustments` | `economic360` (primary): subjects `conversion`, `profile`, `account`, `cluster`, `campaign`, `entity`, `journey`, `agent`; `evidence` | — | Partial: `Bounded revenue-adjustment reads join exact canonical conversions and apply strict event-time windows; conversion subjects are re-read without a conversion-occurrence filter so older conversions adjusted in the requested window remain eligible. Broader subject cohorts can still omit older conversions; other revenue sources, historical replay, full source coverage, reconciliation, and attribution remain unknown.` | Source-settled payment observations and append-only canonical conversion revenue-adjustment events with exact tenant-scoped joins and transaction evidence; adjustment event-time windows are queried against the exact unwindowed conversion subject or the returned conversion cohort, without a recognized revenue total. |
| `temporal_context` | optional |  | `temporal_kernel` | `temporal360` (primary): subjects none; `state`, `timeline` | — | — | Temporal context for value facts and comparisons. |
| `value_summary` | required |  | `ai_execution_facts`, `currency_value_normalization`, `economic_facts` | `economic360` (primary): subjects `agent`, `campaign`, `entity`, `episode`, `journey`, `source`; `summary` | — | — | Subject-scoped computed economic value with explicit missing, zero, and source currency states; no inferred attribution or AI cost aggregation. |
| `web2_value` | required |  | `ai_execution_facts`, `canonical_activity`, `commerce`, `commerce_order_payment_ledger`, `journey_steps`, `payments` | `economic360` (primary): subjects `campaign`, `entity`, `journey`; `evidence` | — | Partial: `Only completed payment facts with exact campaign/entity activity or current journey-step evidence, the same tenant commerce-ledger order reference, and source transaction evidence are classified when the rail is explicitly supported. Non-USD normalization, historical association, source coverage, policy, and freshness remain unknown.` | Evidence-backed Web2 payment observations classified only after exact subject activity or journey-step association, tenant commerce-ledger order reference, and source payment evidence agree on a supported rail. |
| `web3_value` | required |  | `ai_execution_facts`, `canonical_activity`, `commerce`, `commerce_order_payment_ledger`, `currency_value_normalization`, `journey_steps` | `economic360` (primary): subjects `campaign`, `entity`, `journey`; `evidence` | — | Partial: `Only completed source payment facts with exact campaign/entity activity or current journey-step evidence, the same tenant commerce-ledger order reference, explicit crypto flow or on-chain rail, and a complete asset leg plus transaction-hash evidence are classified. Wallet identity, currency normalization, historical association, source coverage, policy, and freshness remain unknown.` | Evidence-backed Web3 native-asset payment observations with exact subject association and commerce-ledger order reference plus explicit flow, rail, chain, asset, amount, and transaction-hash evidence. |

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

Canonical authorities: `ai_execution_facts`, `attribution_credits`, `attribution_runs`, `campaign_facts`, `campaign_touchpoints`, `canonical_activity`, `canonical_conversions`, `commerce`, `commerce_order_payment_ledger`, `currency_value_normalization`, `economic_facts`, `entity_registry`, `evidence`, `identity_clusters_v2`, `journey_steps`, `measurement_contract`, `model_governance`, `outcome_facts`, `payments`, `revenue_adjustments`, `risk_outputs`, `temporal_kernel`.

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
| `actions` | required |  | `actions`, `agent_executions`, `graph_edges`, `resources`, `tools` | `workflow360` (primary): subjects `run`, `workflow_run`; `actions` | — | Authority: `Action and resource result authorities are not joined beyond the recorded execution to Tool call edge.`; Partial: `Call edges are bounded to 200 execution rows and 10000 graph edges. Exact tenant Tool vertices now have separate identity evidence when resolved; authorization, completion, external effects, resource results, producer coverage, historical replay, and freshness remain unknown.` | Exact tenant/run agent execution call edges joined to CALLED_TOOL graph edges and Tool vertices. |
| `actors` | required |  | `ai_execution_facts`, `agent_entities`, `agent_executions`, `commerce`, `identity` | `workflow360` (primary): subjects `run`, `workflow_run`; `actors` | — | Partial: `Exact execution initiator and approval decider references resolve through unique active tenant USER_ID aliases; workflow-wide actor coverage and authority remain unknown.` | Exact run-linked AI invocation agents plus human initiator and approver identities resolved through active tenant USER_ID aliases; full actor coverage and workflow authority remain unknown. |
| `agent_steps` | required |  | `agent_executions` | `workflow360` (primary): subjects `run`, `workflow_run`; `agent_steps` | — | Partial: `The canonical AgentExecution writer persists workflow_run_id and exact invocation IDs when a unique tenant-scoped AI invocation has action_id equal to the stable execution ID. Workflow definition, complete step coverage, policy, and freshness remain unknown.` | Exact tenant and run-linked AgentExecution records admitted only when stored invocation IDs match run-linked AI facts and the stable action/execution ID; complete workflow step coverage remains unknown. |
| `approvals` | required |  | `agent_access`, `agent_executions`, `commerce` | `workflow360` (primary): subjects `run`, `workflow_run`; `approvals` | — | Partial: `Exact x402 approval decisions referenced by admitted run-linked AgentExecutions can carry the recorded human permission check and a matching request-time agent delegation decision with exact current grant, agent, action, resource and amount evidence. Workflow-wide coverage, historical policy replay, and current effective agent authorization remain unknown.` | Exact x402 approval requests and decisions referenced by tenant and run-linked AgentExecutions; workflow-wide approval coverage and authorization policy remain unknown. |
| `evidence_trace` | required |  | `ai_execution_facts` | `workflow360` (primary): subjects `run`, `workflow_run`; `evidence_trace` | — | — | Lineage of exact workflow run linked AI invocation facts. |
| `failures` | required |  | `ai_execution_facts` | `workflow360` (primary): subjects `run`, `workflow_run`; `failures` | — | — | Observed AI invocation failure status only; workflow failure state is unknown. |
| `outcomes` | required |  | `ai_execution_facts`, `outcome_facts`, `evidence` | `workflow360` (primary): subjects `run`, `workflow_run`; `outcomes` | — | Partial: `Only canonical outcome IDs explicitly referenced by tenant/run invocation facts are joined with invocation and outcome evidence; this association does not establish workflow causality or complete outcome coverage, and policy and freshness remain unknown.` | Canonical outcomes explicitly referenced by tenant-scoped invocation facts for an exact workflow run. |
| `risk` | required |  | `agent_executions`, `risk_assessments` | `workflow360` (primary): subjects `run`, `workflow_run`; `risk` | — | Partial: `Only current RiskAssessments for exact admitted AgentExecution subjects linked to the requested run are joined; workflow execution coverage, risk history, policy authority and replay, freshness, and causality remain unknown.` | Current canonical RiskAssessments for exact run-linked AgentExecution subjects. |
| `runs` | required |  | `ai_execution_facts` | `workflow360` (primary): subjects `run`, `workflow_run`; `runs` | — | — | AI invocation facts explicitly linked to a workflow run ID; run state is partial. |
| `triggers` | required |  | `agent_executions`, `events` | `workflow360` (primary): subjects `run`, `workflow_run`; `triggers` | — | Partial: `Only exact tenant/run-linked AgentExecution records and their stored trigger event references are joined; trigger definitions, workflow causality, complete coverage, policy authority, and freshness remain unknown.` | Exact run-linked event references stored on admitted AgentExecution records; does not establish workflow trigger causality or coverage. |
| `workflow_summary` | required |  | `execution_facts`, `workflow_definition_revisions`, `identity` | `workflow360` (primary): subjects `workflow`, `automation`, `run`, `workflow_run`; `workflow_summary` | — | Partial: `Registered definition revision is bounded to an exact tenant workflow and a complete 200-revision as-of history read. The authenticated registrar can resolve through a current active tenant USER_ID alias with Human evidence. An exact run-linked AgentExecution may persist a caller-reported workflow id, revision, and digest only after tenant AI invocation and definition validation; Workflow360 rechecks the link and exposes it as a partial observation. Historical registrar identity and run-definition replay, unsupported external runs, complete run actors, trigger or step completion, external effects, and freshness remain unknown.` | Latest or exact as-of tenant workflow definition revision, with registration evidence, current registrar identity when proven, and bounded caller-reported run association when exact execution references match. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `workflow360` | `catalog_only` (primary) | `in_flight` | `workflow360.read` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `actions`, `agent_access`, `agent_entities`, `agent_executions`, `ai_execution_facts`, `commerce`, `events`, `evidence`, `execution_facts`, `graph_edges`, `identity`, `outcome_facts`, `resources`, `risk_assessments`, `tools`, `workflow_definition_revisions`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: `source_aligned`; expected count `8`; lens ids: `workflow`, `automation`, `execution`, `agentic`, `policy`, `identity`, `risk`, `value`.
