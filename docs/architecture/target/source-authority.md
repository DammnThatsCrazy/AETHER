---
title: Source Relationship and Source Authority
slug: source-relationship-authority
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
source_files: [services/api/shared/integration_contracts/source_relationship.py, services/api/connectors/provider_runtime/rights_admission.py, services/api/connectors/integrations/data_rights/service.py, services/api/tenancy/rights_authority/source_lineage.py]
since_version: "0.1.0"
source_hashes:
  "services/api/connectors/integrations/data_rights/service.py": "sha256:c214d8359695bb39295853149666e6b38f6c68dc1e3c983ce5935d35ab5a5ed0"
  "services/api/connectors/provider_runtime/rights_admission.py": "sha256:2f73758b8ac901b65c5d63b311ab4f3017be6070fcd509bc127386023ca64cb5"
  "services/api/shared/integration_contracts/source_relationship.py": "sha256:9dce3c9e3424b976f4edea041ae39eedd82c9e8a7a25b57da20aa340c0d241f1"
  "services/api/tenancy/rights_authority/source_lineage.py": "sha256:4224f6a22e5d7b58925329370fcbfff1d4537e88fd71f6c1a9264fc0eba1a252"
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
- Olympus-owned and Olympus-licensed sources are scoped to the reserved grant tenant `olympus`, which is never a customer tenant and never feeds the tenant pipeline. Every `olympus_provider` grant, whatever its relationship, must use that scope.

## Relationship to owner to rights class

A grant is created only when its `source_relationship`, curated `raw_data_owner` and `connector_class` agree. `relationship_consistent` is deny-only: a consistent pairing authorizes nothing, the grant, consent and `RightsDecision` still decide.

| Relationship | Required `raw_data_owner` | Compatible `connector_class` values | Created by |
|---|---|---|---|
| `personal_account` | `subject` | `tenant_byod_data`, `tenant_import`, `byok_gateway`, `action_notifier`, `dual_role` | tenant |
| `organization_system` | `tenant` | `tenant_byod_data`, `tenant_import`, `byok_gateway`, `action_notifier`, `dual_role` | tenant |
| `first_party_application` | `tenant` | `tenant_byod_data` | server-stamped on SDK envelopes, no grant route |
| `partner_feed` | `partner` | `partner_feed` | operator |
| `olympus_source` | `olympus_labs` | `olympus_provider` | operator |
| `public_reference` | `public` | `olympus_provider`, `tenant_byod_data` | operator |
| `internal_system` | `olympus_labs` | `olympus_provider` | operator |
| `unclassified` (legacy rows) | none | `tenant_byod_data` only | not creatable |

An `olympus_provider` grant is refused with `olympus_scope_required` unless its tenant is the reserved `olympus` scope, so a `public_reference` grant on that class cannot sit under a customer tenant.

## Raw retention by rights-source class

Provider raw admission picks the retention use from the grant's `connector_class`. The relationship is only checked for consistency.

| Grant `connector_class` | Retention use (`requested_use` and destination) | Notes |
|---|---|---|
| `tenant_byod_data` | `tenant_lake` | the only class admitted before classification existed; legacy `unclassified` grants stay here |
| `olympus_provider` | `olympus_baseline` when the grant tenant is `olympus`, otherwise none: denied | a stored `olympus_provider` grant under a customer tenant retains nothing |
| `partner_feed` | `olympus_baseline` when the grant tenant is `olympus`, otherwise `tenant_lake` | a tenant partner grant never licenses another tenant |
| `tenant_import`, `byok_gateway`, `action_notifier`, `dual_role` | none: denied | `tenant_import` is admitted only by the import path |

Olympus scope: grants and connections for Olympus-owned and Olympus-licensed sources use the reserved tenant `OLYMPUS_SOURCE_TENANT_ID = "olympus"`, never a customer tenant. `olympus_baseline` is only ever chosen under that scope, and the provider event bridge refuses to forward batches under that tenant into the tenant pipeline (a replay dry run counts them as not admitted), so Olympus-scope raw evidence stays available for governed replay only. The revocation fence applies to every class.

## Who may create which grant

| Route | Caller | Accepted `source_relationship` | Refusals |
|---|---|---|---|
| `POST /v1/integrations/data-rights/grants` | tenant admin | `personal_account`, `organization_system` | `403` for any operator relationship; the `olympus` scope is refused (`403` from another tenant, otherwise `400` `tenant_scope_required`); `400` for a failed classification (owner or class mismatch) |
| `POST /v1/admin/kyber/data-rights/grants` | Kyber operator | `partner_feed`, `olympus_source`, `public_reference`, `internal_system` | `403` for a non-operator or any relationship outside the operator set (tenant relationships, `first_party_application`, `unclassified`); `400` for a failed classification, including `olympus_scope_required` |

`source_relationship` and a curated `raw_data_owner` are required on creation; the creation audit event records the relationship. There is no Olympus superuser path: operator grants still pass the same resolver.

## Source scopes

A grant governs one source scope. Provider raw records resolve to exactly one of:

- `provider-account:<connection_id>:<account_id>` when the record names an account.
- `provider-stream:<connection_id>:<stream_id>` for accountless records, only when the capability manifest declares `stream_id`.

There is no connection-wide scope, and a record-supplied stream id alone never creates one.

## Invariants

Each invariant names the tests that pin it. Test names are relative to `services/api/tests` unless prefixed `tests/`.

| # | Invariant | Pinned by |
|---|---|---|
| 1 | Tenant identifiers are server resolved | `provider_runtime/test_rights_admission.py::test_cross_tenant_grant_lookup_denies_even_when_reference_matches`; `tests/unit/test_ingestion_v2.py::test_v1_and_v2_stamp_credential_platform_and_namespace_on_sdk_source` |
| 2 | Source relationships are server stamped | `tests/unit/observation/test_observation_envelope.py::test_client_supplied_source_claims_are_ignored`, `::test_sdk_envelope_is_first_party_with_server_provider_and_instance`; `unit/test_auth_credential_platform.py` |
| 3 | Clients cannot submit authoritative RightsDecision references | not pinned |
| 4 | Provider adapters cannot authorize their own data use | `provider_runtime/test_rights_admission_classes.py::test_relationship_never_turns_a_denied_use_into_an_allow`; `provider_runtime/test_rights_admission.py::test_injected_adapters_cannot_bypass_production_durable_store_gate` |
| 5 | A valid credential does not imply retention rights | `provider_runtime/test_rights_admission.py::test_absent_grant_denies_before_raw_admission`; `provider_runtime/test_rights_admission_classes.py::test_denials_fail_closed` |
| 6 | BYOK does not imply data rights | `provider_runtime/test_rights_admission.py::test_byok_or_mismatched_source_grant_cannot_admit_tenant_raw_data` |
| 7 | `olympus_source` does not provide an Olympus bypass | `unit/test_data_rights_grant_routes.py::test_tenant_cannot_claim_the_olympus_scope`; `unit/test_data_rights_source_relationship.py::test_invalid_pairings_are_rejected`; `provider_runtime/test_rights_admission_classes.py::test_denials_fail_closed`, `::test_olympus_class_grant_under_customer_tenant_has_no_retention_use`, `::test_retention_use_table`; `provider_runtime/test_bridge.py::test_olympus_scope_events_never_enter_the_tenant_pipeline`; `provider_runtime/test_replay.py::test_dry_run_does_not_count_olympus_scope_events_as_admitted` |
| 8 | `partner_feed` does not imply cross-tenant reuse | `provider_runtime/test_rights_admission_classes.py::test_wrong_tenant_and_wrong_source_deny`; `ingestion/test_import_source_relationship.py::test_non_tenant_grant_cannot_admit_an_import` |
| 9 | `public_reference` does not imply unrestricted commercial reuse | not pinned |
| 10 | Revoked grants block subsequent provider raw writes | `provider_runtime/test_rights_admission.py::test_expired_or_revoked_grant_denies_admission`; `provider_runtime/test_rights_revocation_fence.py`; `tests/prod_equivalent/test_real_stack_rights_revocation_fence.py::test_a_write_after_a_committed_revocation_is_denied` |
| 11 | One tenant's connection cannot bind another tenant's account | `provider_runtime/test_shop_account_binding.py::test_shop_held_by_another_tenant_is_rejected` |
| 12 | Public reference data does not auto-merge with tenant-private identity | not pinned |
| 13 | Weak identity evidence cannot silently merge distinct profiles | `identity/test_blueprint_18_5_invariants.py::test_generated_weak_or_context_only_evidence_never_auto_merges`; `identity/test_sdk_legacy_resolve_late_binding.py::test_weak_fingerprint_claim_never_links_or_returns_authoritative_resolution` |
| 14 | Graph writes remain Gateway-governed | `rights_authority/test_source_lineage.py::test_graph_decision_traces_to_relationship_and_grant` (lineage only); gateway enforcement is pinned by the existing graph gateway suites, not by a test on this program |
| 15 | Access Kit transport cannot circumvent intake, tenant, consent or rights authorities | not pinned |
| 16 | Replays preserve original source provenance | `tests/unit/observation/test_replay_adapter.py::test_replay_preserves_source_relationship_and_rights_references`; `provider_runtime/test_provider_source_scope.py::test_replayed_record_resolves_the_same_source_id` |
| 17 | Operator access remains purpose/governance constrained | `unit/test_data_rights_grant_routes.py::test_non_operator_is_refused`, `::test_operator_cannot_mint_non_operator_relationships`; `rights_authority/test_olympus_internal.py::test_unknown_purpose_denied` |
| 18 | A `source_relationship` never contributes to an allow decision | `integration_contracts/test_source_relationship.py::test_relationship_consistency_matrix`; `provider_runtime/test_rights_admission_classes.py::test_relationship_never_turns_a_denied_use_into_an_allow` |
| 19 | `provider-stream` scopes resolve only to manifest-declared streams | `provider_runtime/test_provider_source_scope.py::test_undeclared_or_missing_stream_denies`, `::test_no_connection_wide_fallback` |
