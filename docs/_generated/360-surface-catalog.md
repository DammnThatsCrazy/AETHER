<!-- DO NOT EDIT — generated from packages/shared/contracts/intelligence-projection-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Product 360 Surface Catalog

Catalog version: `0.1.0`

This product catalog has 18 surface contracts and is separate from the 20-row technical projection provider registry. Projection mappings are `catalog_only` candidate section bindings. Direct surface-provider mappings use a separate namespace; `runtime_wired` confirms a frame-runtime call path for the declared subjects and slots, not full surface completion.

The originally reviewed 3,013-line 360 SSOT is not available in this checkout. The catalog below is reconstructed from repository contracts and must be aligned to that source before its names or slot details are treated as exact. Reconstructed fields are marked accordingly in the machine-readable contract.

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

| Product surface | Contract status | Subject kinds | Required slots | Optional slots | Projection providers | Direct surface providers |
|---|---|---|---:|---:|---|---|
| [Account 360](#account-360) | reconstructed_pending_source_alignment | `entity` | 3 | 1 | `economic360`, `profile360`, `relationship360` | `Account360Provider` (runtime_wired) |
| [Agent 360](#agent-360) | reconstructed_pending_source_alignment | `agent`, `entity` | 6 | 5 | `agent360`, `communication360`, `economic360`, `execution360`, `outcome360`, `profile360`, `relationship360`, `risk360`, `social360`, `source360`, `temporal360` | — |
| [Campaign 360](#campaign-360) | reconstructed_pending_source_alignment | `campaign`, `episode`, `population`, `source` | 4 | 2 | `campaign360`, `cluster360`, `communication360`, `economic360`, `episode360`, `outcome360`, `population360` | — |
| [Commerce 360](#commerce-360) | reconstructed_pending_source_alignment | `entity`, `campaign`, `journey` | 3 | 2 | `campaign360`, `economic360`, `outcome360`, `profile360` | — |
| [Communications 360](#communications-360) | reconstructed_pending_source_alignment | `campaign`, `episode`, `journey`, `source` | 2 | 3 | `campaign360`, `communication360`, `episode360`, `outcome360`, `source360` | — |
| [Episode 360](#episode-360) | reconstructed_pending_source_alignment | `episode`, `entity`, `campaign` | 4 | 2 | `campaign360`, `communication360`, `episode360`, `outcome360`, `profile360`, `relationship360`, `source360`, `temporal360` | — |
| [Execution 360](#execution-360) | reconstructed_pending_source_alignment | `agent`, `episode`, `entity` | 5 | 1 | `agent360`, `economic360`, `episode360`, `execution360`, `outcome360`, `source360`, `temporal360` | — |
| [Identity 360](#identity-360) | reconstructed_pending_source_alignment | `entity`, `agent`, `source` | 3 | 2 | `agent360`, `execution360`, `profile360`, `relationship360`, `source360` | `Identity360Provider` (runtime_wired) |
| [Journey 360](#journey-360) | reconstructed_pending_source_alignment | `journey`, `entity`, `episode` | 3 | 2 | `communication360`, `episode360`, `outcome360`, `profile360`, `temporal360` | — |
| [Location 360](#location-360) | reconstructed_pending_source_alignment | `entity`, `population`, `source` | 3 | 1 | `geographic360`, `population360`, `profile360` | — |
| [Memory 360](#memory-360) | reconstructed_pending_source_alignment | `entity`, `agent`, `episode`, `journey` | 4 | 2 | `agent360`, `episode360`, `outcome360`, `profile360`, `relationship360`, `source360`, `temporal360` | — |
| [Profile 360](#profile-360) | reconstructed_pending_source_alignment | `entity`, `agent` | 3 | 3 | `economic360`, `outcome360`, `profile360`, `relationship360`, `risk360` | — |
| [Risk 360](#risk-360) | reconstructed_pending_source_alignment | `entity`, `relationship`, `agent`, `cluster` | 3 | 3 | `economic360`, `execution360`, `fraud360`, `relationship360`, `risk360`, `social360` | — |
| [Signals 360](#signals-360) | reconstructed_pending_source_alignment | `entity`, `agent`, `relationship`, `source` | 2 | 3 | `connection360`, `fraud360`, `outcome360`, `risk360`, `social360`, `source360`, `temporal360` | — |
| [Social 360](#social-360) | reconstructed_pending_source_alignment | `entity`, `relationship`, `source`, `population` | 3 | 2 | `geographic360`, `population360`, `relationship360`, `social360`, `source360` | — |
| [Support 360](#support-360) | reconstructed_pending_source_alignment | `entity`, `agent`, `episode`, `source` | 4 | 2 | `agent360`, `episode360`, `outcome360`, `profile360`, `risk360`, `source360`, `support360` | — |
| [Value 360](#value-360) | reconstructed_pending_source_alignment | `campaign`, `episode`, `journey` | 3 | 2 | `campaign360`, `economic360`, `outcome360`, `temporal360` | — |
| [Workflow 360](#workflow-360) | reconstructed_pending_source_alignment | `agent`, `episode`, `connection` | 4 | 2 | `agent360`, `connection360`, `execution360`, `infrastructure360`, `outcome360`, `source360` | — |

## Account 360

Product surface id: `account360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `entity`

Governed account-level view composed from canonical entity, relationship, economic, and evidence authorities.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `account_identity_and_state` | required |  | `identity`, `entity_registry` | `profile360` (primary): subjects `entity`; `summary`, `state` | Resolved account identity and state. |
| `account_relationships` | required |  | `relationship_facts`, `graph` | `relationship360` (primary): subjects `entity`; `summary`, `interactions`, `evidence` | Relationships associated with the account. |
| `economic_context` | optional |  | `economic_facts`, `ai_execution_facts` | `economic360` (primary): subjects `entity`; `summary`, `evidence`, `outcomes` | Economic facts associated with the account. |
| `evidence_and_limitations` | required |  | `evidence` | `profile360` (primary): subjects `entity`; `evidence`, `findings` | Evidence and coverage for account context. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `economic360` | `catalog_only` (primary) | `implemented` | `economic360.read`, `economic360.explore` |
| `profile360` | `catalog_only` (primary) | `in_flight` | `profile360.read`, `profile360.explore` |
| `relationship360` | `catalog_only` (primary) | `in_flight` | `relationship360.read`, `relationship360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| `Account360Provider` | `surface_frame_provider` | `runtime_wired` | `entity` | `account_identity_and_state` | `services/api/identity/account360_provider.py` | `services/api/shared/intelligence_projections/frame_runtime.py` |

### Authority and governance contract

Canonical authorities: `ai_execution_facts`, `economic_facts`, `entity_registry`, `evidence`, `graph`, `identity`, `relationship_facts`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Agent 360

Product surface id: `agent360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `agent`, `entity`

Governed view of an agent identity, actor attribution, authority and delegation, execution activity, communications, risk, evidence, and measured outcomes.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `actions_tools_resources` | required |  | `actions`, `tools`, `resources` | `execution360` (primary): subjects `agent`, `entity`; `interactions`, `evidence` | Observed actions, tools, and resource activity. |
| `actor_attribution` | required | `slotActorAttribution` | `agent_entities`, `identity` | `execution360` (primary): subjects `agent`, `entity`; `state`, `evidence`; `agent360` (supporting): subjects `agent`, `entity`; `state`, `evidence` | Canonical actor and subject attribution attached to agent activity. |
| `agent_identity` | required |  | `agent_entity`, `identity` | `agent360` (primary): subjects `agent`, `entity`; `summary`, `state`; `profile360` (supporting): subjects `agent`, `entity`; `summary`, `state` | Agent identity and canonical entity context. |
| `authority_and_delegation` | required | `slotActorAttribution`, `slotAuthorityDecision` | `agent_access`, `identity` | `agent360` (primary): subjects `agent`, `entity`; `state`, `evidence` | Agent access, authority context, and delegation lineage. |
| `business_outcomes` | optional |  | `outcome_facts` | `outcome360` (primary): subjects `agent`; `outcomes`, `evidence` | Measured outcomes linked to the agent activity. |
| `communications` | optional |  | `communication_facts`, `observations` | `communication360` (primary): subjects `agent`; `timeline`, `interactions`, `evidence`; `agent360` (supporting): subjects `agent`; `interactions`, `evidence` | Observed agent messages joined through tenant-scoped inbox records, alongside communication events associated with agent work. |
| `economic_cost_and_settlement` | optional |  | `economic_facts`, `payments`, `commerce`, `ai_execution_facts` | `economic360` (primary): subjects `agent`, `entity`; `summary`, `evidence` | Economic facts and authoritative payment or commerce evidence. |
| `execution_lifecycle` | required |  | `agent_executions`, `execution_facts` | `execution360` (primary): subjects `agent`, `entity`; `state`, `timeline`, `evidence`; `agent360` (supporting): subjects `agent`, `entity`; `timeline`, `evidence` | Execution lifecycle evidence and temporal trace. |
| `risk_and_contagion` | optional |  | `agent_entities`, `identity`, `relationship_facts`, `risk_outputs`, `social_observations` | `risk360` (primary): subjects `agent`, `entity`; `findings`, `evidence`; `social360` (supporting): subjects `agent`, `entity`; `findings`, `evidence`; `relationship360` (supporting): subjects `agent`, `entity`; `interactions`, `evidence` | Risk, fraud, social, and relationship context with source evidence. |
| `source_evidence_lineage` | required |  | `evidence`, `source_provenance` | `source360` (primary): subjects `agent`; `evidence`, `coverage`; `agent360` (supporting): subjects `agent`, `entity`; `evidence` | Evidence and source provenance for claims included in the frame. |
| `temporal_relationship_context` | optional |  | `temporal_kernel`, `relationship_facts`, `graph` | `temporal360` (primary): subjects `entity`; `timeline`, `evidence`; `relationship360` (supporting): subjects `agent`, `entity`; `interactions`, `timeline` | Temporal state and relationship context surrounding agent activity. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `agent360` | `catalog_only` (primary) | `in_flight` | `agent360.read`, `agent360.explore` |
| `communication360` | `catalog_only` (primary) | `implemented` | `communication360.read`, `communication360.explore` |
| `economic360` | `catalog_only` (primary) | `implemented` | `economic360.read`, `economic360.explore` |
| `execution360` | `catalog_only` (primary) | `in_flight` | `execution360.read`, `execution360.explore` |
| `outcome360` | `catalog_only` (primary) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `profile360` | `catalog_only` (supporting) | `in_flight` | `profile360.read`, `profile360.explore` |
| `relationship360` | `catalog_only` (supporting) | `in_flight` | `relationship360.read`, `relationship360.explore` |
| `risk360` | `catalog_only` (primary) | `implemented` | `risk360.read`, `risk360.explore` |
| `social360` | `catalog_only` (supporting) | `in_flight` | `social360.read`, `social360.explore` |
| `source360` | `catalog_only` (primary) | `in_flight` | `source360.read`, `source360.explore` |
| `temporal360` | `catalog_only` (primary) | `implemented` | `temporal360.read`, `temporal360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `actions`, `agent_access`, `agent_entities`, `agent_entity`, `agent_executions`, `ai_execution_facts`, `commerce`, `communication_facts`, `economic_facts`, `evidence`, `execution_facts`, `graph`, `identity`, `observations`, `outcome_facts`, `payments`, `relationship_facts`, `resources`, `risk_outputs`, `social_observations`, `source_provenance`, `temporal_kernel`, `tools`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `8`; exact lens ids are pending source alignment.

Recovered Agent blueprint review records 11 domain slots and 8 lenses. The 11 slot labels in this reconstructed catalog and all exact lens ids still require alignment to the original SSOT; no original lens names are asserted here.

## Campaign 360

Product surface id: `campaign360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `campaign`, `episode`, `population`, `source`

Governed campaign view of campaign facts, touchpoints, journeys, communications, attribution, outcomes, and optional economic context.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `attribution_and_outcomes` | required |  | `attribution_credits`, `outcome_facts`, `outcomes` | `campaign360` (primary): subjects `campaign`, `episode`, `population`, `source`; `outcomes`, `findings`; `outcome360` (supporting): subjects `campaign`, `episode`, `population`; `outcomes`, `evidence` | Attribution credits and measured outcomes. |
| `campaign_identity_and_state` | required |  | `campaign_facts` | `campaign360` (primary): subjects `campaign`, `episode`, `population`, `source`; `summary`, `state`, `evidence` | Campaign facts and state. |
| `economic_context` | optional |  | `economic`, `economic_facts`, `ai_execution_facts` | `economic360` (primary): subjects `campaign`, `episode`, `source`; `summary`, `evidence`, `outcomes`; `campaign360` (supporting): subjects `campaign`, `episode`, `population`, `source`; `summary`, `evidence`, `outcomes` | Economic facts associated with campaigns. |
| `journey_and_episode_context` | required |  | `journeys`, `episode_facts` | `episode360` (primary): subjects `campaign`, `episode`; `timeline`, `evidence` | Journeys and episodes associated with campaign activity. |
| `population_context` | optional |  | `population`, `population_definitions` | `population360` (primary): subjects `population`; `summary`, `state`, `findings`; `cluster360` (supporting): subjects `population`; `summary`, `state`, `evidence` | Population context for campaign reach and measurement. |
| `touchpoints_and_communications` | required |  | `touchpoints`, `campaign_touchpoints`, `communication_facts` | `campaign360` (primary): subjects `campaign`, `episode`, `population`, `source`; `evidence`, `outcomes`; `communication360` (supporting): subjects `campaign`, `episode`, `source`; `timeline`, `interactions`, `evidence` | Campaign touchpoints and linked communication evidence. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `campaign360` | `catalog_only` (primary) | `in_flight` | `campaign360.read`, `campaign360.explore` |
| `cluster360` | `catalog_only` (supporting) | `in_flight` | `cluster360.read`, `cluster360.explore` |
| `communication360` | `catalog_only` (supporting) | `implemented` | `communication360.read`, `communication360.explore` |
| `economic360` | `catalog_only` (primary) | `implemented` | `economic360.read`, `economic360.explore` |
| `episode360` | `catalog_only` (primary) | `in_flight` | `episode360.read`, `episode360.explore` |
| `outcome360` | `catalog_only` (supporting) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `population360` | `catalog_only` (primary) | `implemented` | `population360.read`, `population360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `ai_execution_facts`, `attribution_credits`, `campaign_facts`, `campaign_touchpoints`, `communication_facts`, `economic`, `economic_facts`, `episode_facts`, `journeys`, `outcome_facts`, `outcomes`, `population`, `population_definitions`, `touchpoints`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Commerce 360

Product surface id: `commerce360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `entity`, `campaign`, `journey`

Governed view of commerce and payment facts, economic value, attributed outcomes, and supporting evidence.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `attribution_and_campaign_context` | optional |  | `attribution_credits`, `campaign_facts` | `campaign360` (primary): subjects `campaign`; `summary`, `evidence`, `outcomes` | Campaign attribution associated with commerce activity. |
| `commerce_and_payment_facts` | required |  | `commerce`, `payments`, `economic_facts`, `ai_execution_facts` | `economic360` (primary): subjects `entity`, `campaign`, `journey`; `summary`, `state`, `evidence`, `outcomes` | Commerce and payment facts with authoritative source evidence. |
| `economic_value_and_normalization` | required |  | `economic_facts`, `currency_value_normalization`, `ai_execution_facts` | `economic360` (primary): subjects `entity`, `campaign`, `journey`; `summary`, `evidence` | Economic value and currency normalization context. |
| `entity_context` | required |  | `identity`, `entity_registry` | `profile360` (primary): subjects `entity`; `summary`, `state`, `evidence` | Resolved entity context for commerce subjects. |
| `measured_outcomes` | optional |  | `outcome_facts`, `measurement_contract` | `outcome360` (primary): subjects `campaign`; `summary`, `evidence`, `outcomes` | Measured outcomes associated with commerce facts. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `campaign360` | `catalog_only` (primary) | `in_flight` | `campaign360.read`, `campaign360.explore` |
| `economic360` | `catalog_only` (primary) | `implemented` | `economic360.read`, `economic360.explore` |
| `outcome360` | `catalog_only` (primary) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `profile360` | `catalog_only` (primary) | `in_flight` | `profile360.read`, `profile360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `ai_execution_facts`, `attribution_credits`, `campaign_facts`, `commerce`, `currency_value_normalization`, `economic_facts`, `entity_registry`, `identity`, `measurement_contract`, `outcome_facts`, `payments`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Communications 360

Product surface id: `communications360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `campaign`, `episode`, `journey`, `source`

Governed view of communication facts, delivery and engagement evidence, campaign and journey context, and applicable consent policy.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `campaign_context` | optional |  | `campaign_touchpoints`, `campaign_facts` | `campaign360` (primary): subjects `campaign`, `episode`, `source`; `summary`, `evidence`, `outcomes`; `communication360` (supporting): subjects `campaign`, `episode`, `journey`, `source`; `state`, `evidence` | Campaign touchpoints associated with communications. |
| `communication_events` | required |  | `communication_facts`, `evidence` | `communication360` (primary): subjects `campaign`, `episode`, `journey`, `source`; `summary`, `timeline`, `interactions`, `evidence` | Communication facts and evidence about events and interactions. |
| `journey_and_episode_context` | optional |  | `journeys`, `episode_facts`, `events` | `episode360` (primary): subjects `campaign`, `episode`, `journey`; `timeline`, `evidence` | Journey and episode context for communication activity. |
| `measured_outcomes` | optional |  | `outcome_facts` | `outcome360` (primary): subjects `campaign`, `episode`, `journey`; `outcomes`, `evidence` | Measured outcomes associated with communications. |
| `source_and_policy_context` | required |  | `source_provenance`, `provider_registry` | `source360` (primary): subjects `source`; `evidence`, `coverage` | Source lineage for communications; consent and policy are evaluated by their governing authorities. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `campaign360` | `catalog_only` (primary) | `in_flight` | `campaign360.read`, `campaign360.explore` |
| `communication360` | `catalog_only` (primary) | `implemented` | `communication360.read`, `communication360.explore` |
| `episode360` | `catalog_only` (primary) | `in_flight` | `episode360.read`, `episode360.explore` |
| `outcome360` | `catalog_only` (primary) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `source360` | `catalog_only` (primary) | `in_flight` | `source360.read`, `source360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `campaign_facts`, `campaign_touchpoints`, `communication_facts`, `episode_facts`, `events`, `evidence`, `journeys`, `outcome_facts`, `provider_registry`, `source_provenance`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Episode 360

Product surface id: `episode360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `episode`, `entity`, `campaign`

Governed time-bounded view of related events and journey activity, with entity context, evidence, and optional outcomes.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `communication_context` | optional |  | `communication_facts` | `communication360` (primary): subjects `episode`, `campaign`; `timeline`, `interactions`, `evidence` | Communication events associated with the episode. |
| `entity_and_relationship_context` | required |  | `campaign_facts`, `episode_facts`, `graph`, `identity`, `relationship_facts` | `profile360` (primary): subjects `entity`, `episode`; `evidence`, `state`, `summary`; `relationship360` (supporting): subjects `entity`, `episode`; `interactions`, `evidence`; `episode360` (supporting): subjects `campaign`, `entity`, `episode`; `episode_context`; `campaign360` (primary): subjects `campaign`; `evidence`, `state`, `summary` | Canonical identity for entity and episode subjects, campaign identity for campaign subjects, and graph relationships where the subject has a supported entity graph. |
| `episode_identity_and_state` | required |  | `episode_facts` | `episode360` (primary): subjects `episode`, `entity`, `campaign`; `summary`, `state` | Episode identity, state, and canonical episode facts. |
| `event_and_journey_timeline` | required |  | `events`, `journeys`, `temporal_kernel` | `episode360` (primary): subjects `episode`, `entity`, `campaign`; `timeline`; `temporal360` (supporting): subjects `entity`; `timeline`, `state` | Ordered event, journey, and temporal context. |
| `evidence_and_source_lineage` | required |  | `evidence`, `source_provenance` | `episode360` (primary): subjects `episode`, `entity`, `campaign`; `evidence`; `source360` (supporting): subjects none; `evidence`, `coverage` | Evidence and source lineage for episode facts. |
| `measured_outcomes` | optional |  | `outcome_facts` | `outcome360` (primary): subjects `episode`, `campaign`; `outcomes`, `evidence` | Measured outcomes linked to the episode. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `campaign360` | `catalog_only` (primary) | `in_flight` | `campaign360.read`, `campaign360.explore` |
| `communication360` | `catalog_only` (primary) | `implemented` | `communication360.read`, `communication360.explore` |
| `episode360` | `catalog_only` (primary) | `in_flight` | `episode360.read`, `episode360.explore` |
| `outcome360` | `catalog_only` (primary) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `profile360` | `catalog_only` (primary) | `in_flight` | `profile360.read`, `profile360.explore` |
| `relationship360` | `catalog_only` (supporting) | `in_flight` | `relationship360.read`, `relationship360.explore` |
| `source360` | `catalog_only` (supporting) | `in_flight` | `source360.read`, `source360.explore` |
| `temporal360` | `catalog_only` (supporting) | `implemented` | `temporal360.read`, `temporal360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `campaign_facts`, `communication_facts`, `episode_facts`, `events`, `evidence`, `graph`, `identity`, `journeys`, `outcome_facts`, `relationship_facts`, `source_provenance`, `temporal_kernel`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Execution 360

Product surface id: `execution360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `agent`, `episode`, `entity`

Governed view of one execution lifecycle, attributed actors and delegation, action/tool/resource activity, evidence, and outcomes.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `action_tool_resource_trace` | required |  | `actions`, `tools`, `resources` | `execution360` (primary): subjects `agent`, `episode`, `entity`; `interactions`, `timeline`, `evidence` | Observed actions, tools, and resources in the execution. |
| `actor_and_delegation` | required | `slotActorAttribution`, `slotAuthorityDecision` | `agent_entities`, `agent_access`, `identity` | `agent360` (primary): subjects `agent`, `entity`; `state`, `evidence`; `execution360` (supporting): subjects `agent`, `episode`, `entity`; `state`, `evidence` | Agent and actor attribution plus authority context. |
| `economic_and_business_outcomes` | optional |  | `economic_facts`, `outcome_facts`, `ai_execution_facts` | `economic360` (primary): subjects `agent`, `episode`, `entity`; `summary`, `evidence`, `outcomes`; `outcome360` (supporting): subjects `episode`; `evidence`, `outcomes` | Exact AI execution costs and separately measured business outcomes linked to a run. |
| `evidence_and_lineage` | required |  | `evidence`, `source_provenance` | `execution360` (primary): subjects `agent`, `episode`, `entity`; `evidence`; `source360` (supporting): subjects none; `evidence`, `coverage` | Evidence and source trace for execution claims. |
| `execution_identity_and_state` | required |  | `execution_facts`, `agent_executions` | `execution360` (primary): subjects `agent`, `episode`, `entity`; `summary`, `state`; `agent360` (supporting): subjects `agent`, `entity`; `timeline`, `evidence` | Execution identity, lifecycle state, and execution facts. |
| `temporal_and_episode_context` | required |  | `temporal_kernel`, `episode_facts`, `events` | `temporal360` (primary): subjects `entity`; `timeline`, `state`; `episode360` (supporting): subjects `episode`, `entity`; `timeline`, `evidence`; `execution360` (primary): subjects `agent`; `episode_context`, `timeline`, `evidence` | Execution time context and associated episode. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `agent360` | `catalog_only` (primary) | `in_flight` | `agent360.read`, `agent360.explore` |
| `economic360` | `catalog_only` (primary) | `implemented` | `economic360.read`, `economic360.explore` |
| `episode360` | `catalog_only` (supporting) | `in_flight` | `episode360.read`, `episode360.explore` |
| `execution360` | `catalog_only` (primary) | `in_flight` | `execution360.read`, `execution360.explore` |
| `outcome360` | `catalog_only` (supporting) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `source360` | `catalog_only` (supporting) | `in_flight` | `source360.read`, `source360.explore` |
| `temporal360` | `catalog_only` (primary) | `implemented` | `temporal360.read`, `temporal360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `actions`, `agent_access`, `agent_entities`, `agent_executions`, `ai_execution_facts`, `economic_facts`, `episode_facts`, `events`, `evidence`, `execution_facts`, `identity`, `outcome_facts`, `resources`, `source_provenance`, `temporal_kernel`, `tools`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Identity 360

Product surface id: `identity360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `entity`, `agent`, `source`

Governed view of resolved identities, source identifiers, actor bindings, relationships, and supporting evidence.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `actor_and_agent_binding` | optional |  | `agent_entity`, `agent_entities`, `agent_access` | `agent360` (primary): subjects `entity`, `agent`; `state`, `evidence`; `execution360` (supporting): subjects `entity`, `agent`; `state`, `evidence` | Agent identity and actor binding evidence. |
| `identity_evidence` | required |  | `evidence` | `profile360` (primary): subjects `entity`, `agent`; `evidence` | Evidence and limitations associated with the identity view. |
| `relationship_identity_context` | optional |  | `relationship_facts`, `graph` | `relationship360` (primary): subjects `entity`; `interactions`, `evidence` | Relationship facts associated with the resolved entity. |
| `resolved_subject_identity` | required |  | `identity`, `entity_registry` | `profile360` (primary): subjects `entity`, `agent`; `summary`, `state` | Resolved identity and entity registry state. |
| `source_identifier_lineage` | required |  | `source_provenance`, `provider_registry` | `source360` (primary): subjects `entity`, `agent`; `summary`, `evidence`, `coverage` | Source provenance and source identifiers supporting identity resolution. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `agent360` | `catalog_only` (primary) | `in_flight` | `agent360.read`, `agent360.explore` |
| `execution360` | `catalog_only` (supporting) | `in_flight` | `execution360.read`, `execution360.explore` |
| `profile360` | `catalog_only` (primary) | `in_flight` | `profile360.read`, `profile360.explore` |
| `relationship360` | `catalog_only` (primary) | `in_flight` | `relationship360.read`, `relationship360.explore` |
| `source360` | `catalog_only` (primary) | `in_flight` | `source360.read`, `source360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| `Identity360Provider` | `surface_authority_reader` | `runtime_wired` | `agent`, `entity`, `source` | `identity_evidence`, `relationship_identity_context`, `resolved_subject_identity`, `source_identifier_lineage` | `services/api/identity/identity/identity360_provider.py` | `services/api/shared/intelligence_projections/frame_runtime.py` |

### Authority and governance contract

Canonical authorities: `agent_access`, `agent_entities`, `agent_entity`, `entity_registry`, `evidence`, `graph`, `identity`, `provider_registry`, `relationship_facts`, `source_provenance`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Journey 360

Product surface id: `journey360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `journey`, `entity`, `episode`

Governed temporal view of journey state, stages, events, handoffs, and measured outcomes.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `communication_handoffs` | optional |  | `communication_facts` | `communication360` (primary): subjects `journey`, `episode`; `timeline`, `interactions`, `evidence` | Communication events associated with journey stages. |
| `entity_context` | required |  | `episode_facts`, `graph`, `identity`, `journeys` | `profile360` (primary): subjects `entity`, `episode`, `journey`; `summary`, `state`, `evidence` | Resolved linked user-profile context for entity, journey, or episode subjects; parent identity is not substituted for the requested subject. |
| `events_and_episode_context` | required |  | `events`, `episode_facts` | `episode360` (primary): subjects `journey`, `entity`, `episode`; `timeline`, `evidence` | Events and episode facts associated with the journey. |
| `journey_state_and_path` | required |  | `journeys`, `temporal_kernel` | `episode360` (primary): subjects `journey`, `entity`, `episode`; `summary`, `state`, `timeline`; `temporal360` (supporting): subjects `entity`; `state`, `timeline` | Journey state and ordered path context. |
| `measured_outcomes` | optional |  | `outcome_facts` | `outcome360` (primary): subjects `episode`; `outcomes`, `evidence` | Measured outcomes associated with the journey. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `communication360` | `catalog_only` (primary) | `implemented` | `communication360.read`, `communication360.explore` |
| `episode360` | `catalog_only` (primary) | `in_flight` | `episode360.read`, `episode360.explore` |
| `outcome360` | `catalog_only` (primary) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `profile360` | `catalog_only` (primary) | `in_flight` | `profile360.read`, `profile360.explore` |
| `temporal360` | `catalog_only` (supporting) | `implemented` | `temporal360.read`, `temporal360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `communication_facts`, `episode_facts`, `events`, `graph`, `identity`, `journeys`, `outcome_facts`, `temporal_kernel`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Location 360

Product surface id: `location360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `entity`, `population`, `source`

Governed view of locations and geographic observations linked to entities, populations, and temporal context.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `entity_graph_context` | required |  | `entity_graph`, `graph` | `geographic360` (primary): subjects `entity`, `population`, `source`; `summary`, `findings`; `profile360` (supporting): subjects `entity`; `summary`, `findings` | Entity graph context linked to locations. |
| `geographic_observations` | required |  | `geo_observations`, `temporal` | `geographic360` (primary): subjects `entity`, `population`, `source`; `timeline`, `evidence` | Observed geographic facts and their temporal context. |
| `location_identity_and_state` | required |  | `locations`, `context_capsules` | `geographic360` (primary): subjects `entity`, `population`, `source`; `summary`, `state`, `evidence` | Location registry and geographic context. |
| `population_context` | optional |  | `population_definitions`, `cohort_membership` | `population360` (primary): subjects `entity`, `population`; `summary`, `state`, `findings` | Population context for a location. |

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

Canonical authorities: `cohort_membership`, `context_capsules`, `entity_graph`, `geo_observations`, `graph`, `locations`, `population_definitions`, `temporal`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Memory 360

Product surface id: `memory360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `entity`, `agent`, `episode`, `journey`

Governed temporal and evidentiary view of entity and agent history, episodes, and observed state; it does not own memory truth.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `entity_and_agent_context` | required |  | `identity`, `agent_entity`, `agent_executions` | `profile360` (primary): subjects `entity`, `agent`; `summary`, `state`; `agent360` (supporting): subjects `entity`, `agent`; `summary`, `state`, `evidence` | Entity and agent context for history attribution. |
| `episodes_events_and_journeys` | required |  | `episode_facts`, `events`, `journeys` | `episode360` (primary): subjects `entity`, `episode`, `journey`; `summary`, `timeline`, `evidence` | Episode, event, and journey context. |
| `evidence_and_provenance` | required |  | `evidence`, `source_provenance` | `episode360` (primary): subjects `entity`, `episode`, `journey`; `evidence`; `source360` (supporting): subjects none; `evidence`, `coverage` | Evidence and source provenance for retained history claims. |
| `measured_outcomes` | optional |  | `outcome_facts` | `outcome360` (primary): subjects `episode`; `outcomes`, `evidence` | Measured outcomes related to retained history. |
| `relationship_context` | optional |  | `relationship_facts` | `relationship360` (primary): subjects `entity`; `interactions`, `timeline`, `evidence` | Relationship context associated with the subject history. |
| `temporal_history` | required |  | `temporal_kernel`, `mutation_history`, `validity_state` | `temporal360` (primary): subjects `entity`; `summary`, `state`, `timeline`, `evidence` | Temporal state, validity, and mutation history. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `agent360` | `catalog_only` (supporting) | `in_flight` | `agent360.read`, `agent360.explore` |
| `episode360` | `catalog_only` (primary) | `in_flight` | `episode360.read`, `episode360.explore` |
| `outcome360` | `catalog_only` (primary) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `profile360` | `catalog_only` (primary) | `in_flight` | `profile360.read`, `profile360.explore` |
| `relationship360` | `catalog_only` (primary) | `in_flight` | `relationship360.read`, `relationship360.explore` |
| `source360` | `catalog_only` (supporting) | `in_flight` | `source360.read`, `source360.explore` |
| `temporal360` | `catalog_only` (primary) | `implemented` | `temporal360.read`, `temporal360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `agent_entity`, `agent_executions`, `episode_facts`, `events`, `evidence`, `identity`, `journeys`, `mutation_history`, `outcome_facts`, `relationship_facts`, `source_provenance`, `temporal_kernel`, `validity_state`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Profile 360

Product surface id: `profile360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `entity`, `agent`

Governed entity-level contextual frame combining identity, observations, relationships, evidence, and optional risk and value context.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `economic_value_context` | optional |  | `economic_facts`, `outcome_facts`, `ai_execution_facts` | `economic360` (primary): subjects `entity`, `agent`; `summary`, `evidence`, `outcomes`; `outcome360` (supporting): subjects none; `outcomes`, `evidence` | Economic facts and measured outcomes. |
| `entity_identity` | required |  | `identity`, `entity_registry` | `profile360` (primary): subjects `entity`, `agent`; `summary`, `state` | Resolved entity identity and registry context. |
| `evidence_and_limitations` | required |  | `evidence` | `profile360` (primary): subjects `entity`, `agent`; `evidence`, `findings` | Evidence supporting the displayed profile claims. |
| `observed_state_and_activity` | required |  | `observations`, `graph`, `temporal` | `profile360` (primary): subjects `entity`, `agent`; `state`, `timeline`, `interactions` | Observed state and temporal activity with explicit provenance. |
| `relationship_context` | optional |  | `relationship_facts` | `relationship360` (primary): subjects `entity`; `interactions`, `timeline`, `evidence` | Relationships around the entity. |
| `risk_context` | optional |  | `risk_outputs`, `model_governance` | `risk360` (primary): subjects `entity`; `summary`, `findings`, `evidence` | Governed risk and fraud context. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `economic360` | `catalog_only` (primary) | `implemented` | `economic360.read`, `economic360.explore` |
| `outcome360` | `catalog_only` (supporting) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `profile360` | `catalog_only` (primary) | `in_flight` | `profile360.read`, `profile360.explore` |
| `relationship360` | `catalog_only` (primary) | `in_flight` | `relationship360.read`, `relationship360.explore` |
| `risk360` | `catalog_only` (primary) | `implemented` | `risk360.read`, `risk360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `ai_execution_facts`, `economic_facts`, `entity_registry`, `evidence`, `graph`, `identity`, `model_governance`, `observations`, `outcome_facts`, `relationship_facts`, `risk_outputs`, `temporal`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Risk 360

Product surface id: `risk360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `entity`, `relationship`, `agent`, `cluster`

Governed view of risk findings, evidence, relationship and economic exposure, with explicit coverage and uncertainty.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `economic_exposure` | optional |  | `economic_facts`, `ai_execution_facts` | `economic360` (primary): subjects `entity`, `agent`; `summary`, `evidence`, `outcomes` | Economic facts associated with the risk subject and network. |
| `execution_exposure` | optional |  | `execution_facts` | `execution360` (primary): subjects `entity`, `agent`; `summary`, `timeline`, `evidence` | Execution facts associated with an agent or execution subject. |
| `fraud_and_social_patterns` | optional |  | `fraud_synthesis`, `graph_motifs`, `social_observations` | `fraud360` (primary): subjects `entity`, `relationship`, `agent`; `findings`, `evidence`, `health`; `social360` (supporting): subjects `entity`, `relationship`; `findings`, `evidence` | Fraud synthesis, graph motifs, and social observations. |
| `relationship_network_context` | required |  | `entity_graph`, `relationship_facts`, `graph` | `relationship360` (primary): subjects `agent`, `entity`, `relationship`; `summary`, `interactions`, `evidence`; `risk360` (supporting): subjects `entity`, `relationship`, `cluster`; `summary`, `evidence` | Entity graph and relationship evidence relevant to risk. |
| `risk_assessment_state` | required |  | `risk_outputs`, `model_governance` | `risk360` (primary): subjects `agent`, `entity`, `relationship`, `cluster`; `summary`, `state`, `findings`, `health` | Risk outputs, model governance context, and assessment state. |
| `risk_evidence_and_limitations` | required |  | `evidence` | `risk360` (primary): subjects `agent`, `entity`, `relationship`, `cluster`; `evidence`, `findings` | Evidence and limitations supporting risk findings. |

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

Canonical authorities: `ai_execution_facts`, `economic_facts`, `entity_graph`, `evidence`, `execution_facts`, `fraud_synthesis`, `graph`, `graph_motifs`, `model_governance`, `relationship_facts`, `risk_outputs`, `social_observations`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Signals 360

Product surface id: `signals360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `entity`, `agent`, `relationship`, `source`

Governed view of risk, fraud, source, social, and outcome signals with evidence and freshness status.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `fraud_and_network_signals` | optional |  | `fraud_synthesis`, `graph_motifs`, `social_observations`, `relationship_facts` | `fraud360` (primary): subjects `entity`, `agent`, `relationship`; `findings`, `evidence`, `health`; `social360` (supporting): subjects `entity`, `relationship`; `findings`, `evidence` | Fraud synthesis, motifs, social observations, and network context. |
| `measured_outcome_signals` | optional |  | `outcome_facts`, `measurement_contract` | `outcome360` (primary): subjects none; `summary`, `outcomes`, `findings` | Measured outcomes available as governed signal inputs. |
| `risk_signals` | required |  | `risk_outputs` | `risk360` (primary): subjects `agent`, `entity`, `relationship`, `source`; `summary`, `findings`, `evidence`, `health` | Risk outputs and signal findings. |
| `source_signals_and_coverage` | required |  | `source_provenance`, `source_coverage`, `ingestion_health` | `source360` (primary): subjects `agent`, `entity`, `source`; `summary`, `health`, `coverage`, `evidence`; `connection360` (supporting): subjects `source`; `state`, `evidence`, `coverage` | Source provenance and coverage of signal inputs. |
| `temporal_signal_context` | optional |  | `temporal_kernel` | `temporal360` (primary): subjects `entity`, `relationship`; `state`, `timeline`, `evidence` | Temporal context for signal observations. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `connection360` | `catalog_only` (supporting) | `in_flight` | `connection360.read`, `connection360.explore` |
| `fraud360` | `catalog_only` (primary) | `implemented` | `fraud360.read`, `fraud360.explore` |
| `outcome360` | `catalog_only` (primary) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `risk360` | `catalog_only` (primary) | `implemented` | `risk360.read`, `risk360.explore` |
| `social360` | `catalog_only` (supporting) | `in_flight` | `social360.read`, `social360.explore` |
| `source360` | `catalog_only` (primary) | `in_flight` | `source360.read`, `source360.explore` |
| `temporal360` | `catalog_only` (primary) | `implemented` | `temporal360.read`, `temporal360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `fraud_synthesis`, `graph_motifs`, `ingestion_health`, `measurement_contract`, `outcome_facts`, `relationship_facts`, `risk_outputs`, `social_observations`, `source_coverage`, `source_provenance`, `temporal_kernel`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Social 360

Product surface id: `social360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `entity`, `relationship`, `source`, `population`

Governed view of social observations, source-backed relationships, evidence, and optional population or geographic context.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `evidence_and_coverage` | required |  | `evidence`, `source_coverage`, `identity`, `cohort_membership` | `social360` (primary): subjects `entity`, `relationship`, `source`, `population`; `evidence`, `findings`; `source360` (supporting): subjects `source`; `evidence`, `coverage` | Evidence and source coverage for social claims. |
| `geographic_context` | optional |  | `geo_observations`, `locations` | `geographic360` (primary): subjects `entity`, `source`, `population`; `summary`, `timeline`, `evidence` | Location context for social observations. |
| `population_context` | optional |  | `population_definitions`, `cohort_membership` | `population360` (primary): subjects `entity`, `population`; `summary`, `state`, `evidence` | Population and cohort context for social observations. |
| `relationship_graph` | required |  | `relationship_facts`, `graph`, `identity`, `cohort_membership` | `relationship360` (primary): subjects `entity`, `relationship`, `source`, `population`; `summary`, `interactions`, `evidence` | Relationship facts and graph context. |
| `social_observations_and_sources` | required |  | `social_observations`, `source_facts`, `identity`, `cohort_membership` | `social360` (primary): subjects `entity`, `relationship`, `source`, `population`; `summary`, `timeline`, `interactions`, `evidence` | Social observations and their source facts. |

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

Canonical authorities: `cohort_membership`, `evidence`, `geo_observations`, `graph`, `identity`, `locations`, `population_definitions`, `relationship_facts`, `social_observations`, `source_coverage`, `source_facts`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Support 360

Product surface id: `support360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `entity`, `agent`, `episode`, `source`

Governed support context composed from communications, episodes and journeys, entity identity, and evidence.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `entity_and_agent_context` | required |  | `identity`, `agent_entity` | `profile360` (primary): subjects `entity`, `agent`; `summary`, `state`; `agent360` (supporting): subjects `entity`, `agent`; `summary`, `state`, `evidence` | Identity and agent context associated with support activity. |
| `measured_outcomes` | optional |  | `outcome_facts` | `outcome360` (primary): subjects `episode`; `outcomes`, `evidence` | Measured support outcomes where an authoritative provider exists. |
| `risk_context` | optional |  | `risk_outputs` | `risk360` (primary): subjects `entity`; `summary`, `findings`, `evidence` | Risk context from its governing projection, subject to policy. |
| `source_lineage_and_coverage` | required |  | `source_provenance`, `source_coverage` | `source360` (primary): subjects `source`; `evidence`, `coverage` | Source provenance and coverage for support context. |
| `support_communications` | required |  | `communication_facts`, `evidence` | `support360` (primary): subjects `entity`; `summary`, `state`, `timeline`, `evidence`, `interactions`, `outcomes` | Communication events and interaction evidence. |
| `support_episode_and_journey` | required |  | `episode_facts`, `journeys`, `events` | `episode360` (primary): subjects `entity`, `episode`; `summary`, `state`, `timeline`, `evidence` | Episode and journey context for support interactions. |

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

Canonical authorities: `agent_entity`, `communication_facts`, `episode_facts`, `events`, `evidence`, `identity`, `journeys`, `outcome_facts`, `risk_outputs`, `source_coverage`, `source_provenance`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Value 360

Product surface id: `value360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `campaign`, `episode`, `journey`

Governed view of economic facts, payment and commerce evidence, attribution, and measured outcomes; missing values remain explicit.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `campaign_and_attribution_context` | optional |  | `attribution_credits`, `campaign_facts` | `campaign360` (primary): subjects `campaign`, `episode`; `summary`, `evidence`, `outcomes` | Campaign facts and attribution credits associated with value. |
| `economic_facts_and_state` | required |  | `economic_facts`, `currency_value_normalization`, `ai_execution_facts` | `economic360` (primary): subjects `campaign`, `episode`, `journey`; `summary`, `state`, `evidence` | Economic facts and value state with currency normalization provenance. |
| `measured_outcomes` | required |  | `outcome_facts`, `measurement_contract` | `outcome360` (primary): subjects `campaign`, `episode`, `journey`; `summary`, `evidence`, `outcomes` | Measured outcome facts linked to economic value. |
| `payments_and_commerce_evidence` | required |  | `payments`, `commerce`, `ai_execution_facts` | `economic360` (primary): subjects `campaign`, `episode`, `journey`; `evidence`, `outcomes` | Payment and commerce evidence from the corresponding authorities. |
| `temporal_context` | optional |  | `temporal_kernel` | `temporal360` (primary): subjects none; `state`, `timeline` | Temporal context for value facts and comparisons. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `campaign360` | `catalog_only` (primary) | `in_flight` | `campaign360.read`, `campaign360.explore` |
| `economic360` | `catalog_only` (primary) | `implemented` | `economic360.read`, `economic360.explore` |
| `outcome360` | `catalog_only` (primary) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `temporal360` | `catalog_only` (primary) | `implemented` | `temporal360.read`, `temporal360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `ai_execution_facts`, `attribution_credits`, `campaign_facts`, `commerce`, `currency_value_normalization`, `economic_facts`, `measurement_contract`, `outcome_facts`, `payments`, `temporal_kernel`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.

## Workflow 360

Product surface id: `workflow360`
Contract status: `reconstructed_pending_source_alignment`
Subject kinds: `agent`, `episode`, `connection`

Governed operational view of agent executions, actions and tools, integration lifecycle, evidence, and optional outcomes.

### Domain slots

| Slot | Requirement | Required frame metadata | Canonical authority refs | Explicit projection section bindings | Description |
|---|---|---|---|---|---|
| `actors_actions_and_resources` | required |  | `agent_entities`, `agent_access`, `actions`, `tools`, `resources` | `execution360` (primary): subjects `agent`, `episode`; `interactions`, `evidence`; `agent360` (supporting): subjects `agent`; `state`, `evidence` | Agent actors, actions, tools, and resources participating in workflow activity. |
| `deployment_infrastructure_context` | optional |  | `deployments`, `infrastructure_facts`, `infrastructure_state` | `infrastructure360` (primary): subjects none; `deployments`, `evidence`, `findings` | Infrastructure and deployment context for workflows whose execution is associated with a registered deployment. |
| `evidence_and_source_lineage` | required |  | `evidence`, `source_coverage` | `source360` (primary): subjects `connection`; `evidence`, `coverage` | Evidence and source coverage for workflow state. |
| `integration_and_sync_context` | required |  | `managed_integration_lifecycle`, `connection_config`, `sync_state`, `provider_health` | `connection360` (primary): subjects `connection`; `summary`, `state`, `health`, `coverage` | Connection lifecycle and sync state for workflow integrations. |
| `workflow_execution_state` | required |  | `execution_facts`, `agent_executions` | `execution360` (primary): subjects `agent`, `episode`; `summary`, `state`, `timeline`; `agent360` (supporting): subjects `agent`; `timeline`, `evidence` | Execution facts and lifecycle state for workflow activity. |
| `workflow_outcomes` | optional |  | `outcome_facts` | `outcome360` (primary): subjects `episode`; `outcomes`, `evidence` | Measured outcomes associated with workflow execution. |

### Projection provider bindings

| Projection | Binding | Provider implementation metadata | Capability keys |
|---|---|---|---|
| `agent360` | `catalog_only` (supporting) | `in_flight` | `agent360.read`, `agent360.explore` |
| `connection360` | `catalog_only` (primary) | `in_flight` | `connection360.read`, `connection360.explore` |
| `execution360` | `catalog_only` (primary) | `in_flight` | `execution360.read`, `execution360.explore` |
| `infrastructure360` | `catalog_only` (primary) | `implemented` | `infrastructure360.read`, `infrastructure360.explore` |
| `outcome360` | `catalog_only` (primary) | `implemented` | `outcome360.read`, `outcome360.explore` |
| `source360` | `catalog_only` (primary) | `in_flight` | `source360.read`, `source360.explore` |

### Direct surface-provider bindings

| Provider class | Provider kind | Binding status | Subjects | Domain slots | Implementation | Frame-runtime call site |
|---|---|---|---|---|---|---|
| none declared | — | — | — | — | — | — |

### Authority and governance contract

Canonical authorities: `actions`, `agent_access`, `agent_entities`, `agent_executions`, `connection_config`, `deployments`, `evidence`, `execution_facts`, `infrastructure_facts`, `infrastructure_state`, `managed_integration_lifecycle`, `outcome_facts`, `provider_health`, `resources`, `source_coverage`, `sync_state`, `tools`.

The frame owns no canonical truth. It composes governed reads, preserves provider provenance, and cannot mutate the authorities listed above.

Freshness requirement: source timestamps `preserve`; missing timestamps become `unknown`; stale slots become `mark_affected_slots_stale`. Maximum age is unset pending authority-specific configuration.

Policy requirement: tenant scope `true`, authorization before read `true`, policy evaluation `per_projection_before_composition`, historical consent `required_when_applicable`, redaction `suppress_disallowed_slot_without_inference`.

Required backend capabilities: `experience360.frame.compose`, `experience360.tenant_scope.enforce`, `experience360.policy.evaluate`, `experience360.freshness.evaluate`, `experience360.evidence.provenance`.

Capability and provider status is contract metadata only: `registry_requirements_not_route_attestation`. Provider implementation states are copied from the technical registry and do not imply runtime readiness.

Lens alignment: expected count `None`; exact lens ids are pending source alignment.
