<!-- DO NOT EDIT — generated from packages/shared/contracts/intelligence-projection-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Intelligence Projection Registry

Contract version: `1.0.0`

A 360 is an intelligence projection over canonical Aether truth — never a competing system of record. `implementationState` is repo metadata, NOT readiness.

## Projection kinds

`agentic_360`, `context_360`, `entity_360`, `measurement_360`, `operational_workbench`, `relationship_360`, `risk_360`, `sequence_360`

## Implementation states

`deprecated`, `implemented`, `in_flight`, `registered`

## Section states

`available`, `degraded`, `empty`, `missing`, `not_applicable`, `unknown`

## Graph mutation policies

`canonical_gateway_only`, `read_only`

## Projections

| Projection | Kind | State | Hard spines | Projection deps | Surfaces | Capability keys | Graph policy | Authorities | Legacy routes | Blueprint |
|---|---|---|---|---|---|---|---|---|---|---|
| `agent360` | agentic_360 | in_flight | `agentic_runtime_access`, `contract_spine`, `identity_resolution`, `temporal_kernel` | `profile360`, `economic360`(opt), `outcome360`(opt) | `profile360` | `agent360.explore`, `agent360.read` | read_only | `agent_access`, `agent_entity`, `agent_executions`, `economic_facts`, `evidence`, `graph`, `identity`, `outcome_facts` | `/v1/agent`, `/v1/agents`, `/v1/profile360` | `docs/blueprints/agent360.md` |
| `campaign360` | measurement_360 | in_flight | `attribution_architecture`, `contract_spine`, `measurement_outcome_contract` | `communication360`, `economic360`, `episode360`, `outcome360`, `population360` | `campaign360`, `comparison_workbench` | `campaign360.explore`, `campaign360.read` | canonical_gateway_only | `attribution_credits`, `campaign_facts`, `communication`, `economic`, `journeys`, `outcomes`, `population`, `touchpoints` | `/v1/campaign-quality`, `/v1/campaign-sources`, `/v1/campaigns`, `/v1/mapping-review` | `docs/blueprints/campaign360.md` |
| `cluster360` | operational_workbench | in_flight | `computation_substrate`, `exploration_fabric` | `population360` | `cluster360`, `graph` | `cluster360.explore`, `cluster360.read` | read_only | `cluster_definitions`, `cluster_membership`, `computation`, `graph`, `population` | `/v1/clusters` | `docs/blueprints/cluster360.md` |
| `communication360` | sequence_360 | in_flight | `contract_spine`, `temporal_kernel` | `episode360`, `outcome360`, `profile360`, `relationship360` | `profile360`, `timeline` | `communication360.explore`, `communication360.read` | read_only | `campaign_touchpoints`, `communication_facts`, `entities`, `evidence`, `outcomes` | `/v1/comms`, `/v1/contact`, `/v1/delivery`, `/v1/notifications` | `docs/blueprints/communication360.md` |
| `connection360` | operational_workbench | in_flight | `reconciled_control_plane`, `upr` | `source360` | `connection360` | `connection360.explore`, `connection360.read` | canonical_gateway_only | `connection_config`, `connection_permissions`, `credential_readiness`, `managed_integration_lifecycle`, `provider_health`, `source_coverage`, `sync_state` | `/v1/client-sync`, `/v1/integrations`, `/v1/provider-connections` | `docs/blueprints/connection360.md` |
| `economic360` | measurement_360 | in_flight | `measurement_outcome_contract`, `temporal_kernel` | `outcome360`, `profile360`, `relationship360` | `campaign360`, `economic360`, `product_intelligence` | `economic360.explore`, `economic360.read` | read_only | `commerce`, `currency_value_normalization`, `economic_facts`, `graph`, `outcome_facts`, `payments` | `/v1/economic`, `/v1/profile` | `docs/blueprints/economic360.md` |
| `episode360` | sequence_360 | in_flight | `contract_spine`, `journey_continuity`, `temporal_kernel` | `profile360`, `relationship360` | `journeys`, `timeline` | `episode360.explore`, `episode360.read` | read_only | `episode_facts`, `events`, `evidence`, `graph`, `journeys`, `temporal` | `/v1/events`, `/v1/journeys` | `docs/blueprints/episode360.md` |
| `execution360` | sequence_360 | in_flight | `agentic_runtime_access`, `temporal_kernel` | `agent360`, `episode360`, `outcome360`, `temporal360` | `timeline` | `execution360.explore`, `execution360.read` | read_only | `actions`, `agent_entities`, `economic_facts`, `evidence`, `execution_facts`, `graph`, `outcome_facts`, `resources`, `tools` | `/v1/agent`, `/v1/agents`, `/v1/computations`, `/v1/flows`, `/v1/jobs` | `docs/blueprints/execution360.md` |
| `fraud360` | risk_360 | in_flight | `evidence_provenance`, `model_governance` | `profile360`, `risk360` | `graph` | `fraud360.explore`, `fraud360.read` | read_only | `economic_facts`, `evidence`, `execution_facts`, `fraud_synthesis`, `graph_motifs`, `identity`, `relationship_facts`, `risk_outputs`, `social_observations` | `/v1/fraud` | `docs/blueprints/fraud360.md` |
| `geographic360` | context_360 | in_flight | `context_capsule_semantics`, `temporal_kernel` | `profile360`, `temporal360` | `geo` | `geographic360.explore`, `geographic360.read` | read_only | `context_capsules`, `entity_graph`, `geo_observations`, `locations`, `temporal` | `/v1/geo` | `docs/blueprints/geographic360.md` |
| `outcome360` | measurement_360 | in_flight | `measurement_outcome_contract`, `temporal_kernel` | `temporal360` | `campaign360`, `outcome360` | `outcome360.explore`, `outcome360.read` | read_only | `evidence`, `graph`, `measurement_contract`, `outcome_facts` | `/v1/attribution`, `/v1/conversions`, `/v1/journeys`, `/v1/measurement`, `/v1/resolution`, `/v1/spend` | `docs/blueprints/outcome360.md` |
| `population360` | context_360 | in_flight | `contract_spine`, `grouping_membership` | `profile360`, `relationship360`, `temporal360` | `cluster360`, `comparison_workbench` | `population360.explore`, `population360.read` | read_only | `cluster_definitions`, `cohort_membership`, `entities`, `evidence`, `population_definitions`, `temporal` | `/v1/population` | `docs/blueprints/population360.md` |
| `profile360` | entity_360 | in_flight | `contract_spine`, `evidence_provenance`, `identity_resolution`, `temporal_kernel` | `risk360`(opt) | `profile360` | `profile360.explore`, `profile360.read` | read_only | `entity_registry`, `evidence`, `graph`, `identity`, `observations`, `temporal` | `/v1/profile`, `/v1/profile360` | `docs/blueprints/profile360.md` |
| `relationship360` | relationship_360 | in_flight | `identity_resolution`, `relationship_fidelity`, `temporal_kernel` | `profile360`, `temporal360`, `communication360`(opt), `economic360`(opt), `risk360`(opt), `social360`(opt) | `graph`, `profile360` | `relationship360.explore`, `relationship360.read` | read_only | `evidence`, `graph`, `identity`, `relationship_facts`, `temporal` | `/v1/entities`, `/v1/graph`, `/v1/semantic` | `docs/blueprints/relationship360.md` |
| `risk360` | risk_360 | in_flight | `computation_substrate`, `evidence_provenance`, `model_governance` | `cluster360`, `economic360`, `profile360` | `comparison_workbench`, `graph` | `risk360.explore`, `risk360.read` | read_only | `cluster_membership`, `economic_facts`, `entity_graph`, `evidence`, `model_governance`, `risk_outputs` | `/v1/capability-risk`, `/v1/risk-overlays` | `docs/blueprints/risk360.md` |
| `social360` | relationship_360 | in_flight | `relationship_fidelity`, `temporal_kernel`, `upr` | `profile360`, `relationship360` | `profile360` | `social360.explore`, `social360.read` | read_only | `evidence`, `graph`, `relationship_facts`, `social_observations`, `source_facts` | `/v1/profile` | `docs/blueprints/social360.md` |
| `source360` | operational_workbench | in_flight | `upr` |  | `campaign360` | `source360.explore`, `source360.read` | read_only | `evidence`, `ingestion_health`, `provider_registry`, `source_coverage`, `source_provenance`, `source_schema` | `/v1/imports`, `/v1/kyber`, `/v1/providers` | `docs/blueprints/source360.md` |
| `temporal360` | context_360 | in_flight | `contract_spine`, `graph_history_replay` |  | `temporal_observatory`, `timeline` | `temporal360.explore`, `temporal360.read` | read_only | `graph_snapshots`, `mutation_history`, `temporal_kernel`, `validity_state` | `/v1/graph`, `/v1/preferences` | `docs/blueprints/temporal360.md` |
