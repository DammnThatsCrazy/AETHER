---
title: Source Relationship and Source Authority
slug: source-relationship-authority
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: "0.1.0"
---

# Source Relationship and Source Authority

Every governed source must answer six separate questions, owned by separate authorities.
None of them is a "connector type".

| Question | Authority | Location |
|---|---|---|
| What system is this? | Provider identity `family.product.capability` | `services/api/shared/integration_contracts/identity.py` |
| Which instance is connected? | `ProviderConnection` (technical only — no rights fields) | `services/api/connectors/provider_runtime/connection.py` |
| How did data enter? | `SourceBlock.source_type` | `services/api/shared/observation/envelope.py` |
| What relationship does the source have? | `SourceRelationship` (descriptive, never authorizing) | `services/api/shared/integration_contracts/source_relationship.py` |
| What may Aether do with it? | `DataRightsGrant` + consent + `EffectiveRightsResolver` → `RightsDecision` | `services/api/connectors/integrations/data_rights/`, `services/api/tenancy/rights_authority/` |
| What did it become? | Evidence → `MutationIntent` → `GraphMutationGateway` | `services/api/shared/graph/mutation_gateway.py` |

## Baseline inventory (2026-10-15)

| Intake path | Builds Envelope-B? | Rights admission | Notes |
|---|---|---|---|
| SDK `/v1/batch` (also Access Kit CLI/MCP observe) | yes (`services/api/ingestion/ingestion/observation_envelope.py`) | consent/site authority | flag-gated by `settings.observation_envelope.enabled` |
| Ingestion replay | yes (`services/api/ingestion/ingestion/adapters/replay.py`) | inherits original | rewrites `source_type="replay"` |
| Provider runtime webhook / pull / raw replay | no — flat Bronze rows via `services/api/connectors/provider_runtime/bridge.py` | `ProviderRawRightsAdmission` (tenant BYOD only at baseline) | #739 revocation fence |
| CSV import commit | no — Bronze rows with `rights_decision_refs` | `ImportRightsAdmission` (`tenant_lake`, `write_tenant_graph`, `tenant_insights`) | grants use `connector_class="tenant_import"` |
| Legacy connector webhooks, `/v1/ingest/feed` | no | none | remain `unclassified` until converged |

- PR #774: merged 2026-10-15 into Development. PR #775: merged 2026-10-15 into Development. #775 overlap is Access Kit only: it delegates source, rights, graph and action authority and owns none of them.
- No `SourceInstance` registry exists; `source_instance` stays a reference field.
- Provider manifest availability (`tenant_self_service`, `kyber_managed`, `olympus_system`) means provisioning availability only, never data ownership.

## Ownership boundaries

- `source_relationship` lives on the envelope `SourceBlock` (per observation) and on `DataRightsGrant` (per governed source). It is never added to `ProviderConnection` or to graph edges.
- Retention use is chosen from the grant's rights-source class (`connector_class`), never from the relationship. The relationship can only deny.
- Olympus-owned and Olympus-licensed sources are scoped to the reserved grant tenant `olympus`, which is never a customer tenant and never feeds the tenant pipeline.
