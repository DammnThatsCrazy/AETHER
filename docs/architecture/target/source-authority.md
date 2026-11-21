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
  "services/api/connectors/integrations/data_rights/service.py": "sha256:329e509fb684a110fbfe212df329c2b6f06acc644849d70b2373bc06eaacf2e9"
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
| 3 | Clients cannot submit authoritative RightsDecision references | `tests/unit/derivatives/test_account_sync.py::test_client_cannot_forge_governance_refs`; `unit/test_source_authority_invariants.py::test_sdk_events_cannot_carry_rights_references`, `::test_feed_requests_cannot_set_source_rights`, `::test_provider_events_cannot_carry_rights_references`; `provider_runtime/test_bridge.py::test_relationship_never_comes_from_the_event_payload` |
| 4 | Provider adapters cannot authorize their own data use | `provider_runtime/test_rights_admission_classes.py::test_relationship_never_turns_a_denied_use_into_an_allow`; `provider_runtime/test_rights_admission.py::test_injected_adapters_cannot_bypass_production_durable_store_gate` |
| 5 | A valid credential does not imply retention rights | `provider_runtime/test_rights_admission.py::test_absent_grant_denies_before_raw_admission`; `provider_runtime/test_rights_admission_classes.py::test_denials_fail_closed` |
| 6 | BYOK does not imply data rights | `provider_runtime/test_rights_admission.py::test_byok_or_mismatched_source_grant_cannot_admit_tenant_raw_data` |
| 7 | `olympus_source` does not provide an Olympus bypass | `unit/test_data_rights_grant_routes.py::test_tenant_cannot_claim_the_olympus_scope`; `unit/test_data_rights_source_relationship.py::test_invalid_pairings_are_rejected`; `provider_runtime/test_rights_admission_classes.py::test_denials_fail_closed`, `::test_olympus_class_grant_under_customer_tenant_has_no_retention_use`, `::test_retention_use_table`; `provider_runtime/test_bridge.py::test_olympus_scope_events_never_enter_the_tenant_pipeline`; `provider_runtime/test_replay.py::test_dry_run_does_not_count_olympus_scope_events_as_admitted` |
| 8 | `partner_feed` does not imply cross-tenant reuse | `provider_runtime/test_rights_admission_classes.py::test_wrong_tenant_and_wrong_source_deny`; `ingestion/test_import_source_relationship.py::test_non_tenant_grant_cannot_admit_an_import` |
| 9 | `public_reference` does not imply unrestricted commercial reuse | `tests/unit/derivatives/test_market_reference.py::test_olympus_source_is_a_public_reference_grant_without_tenant_rights`; `unit/test_native_capabilities.py::test_public_reference_grants_cannot_allow_reuse`, `::test_an_olympus_grant_must_carry_the_catalog_relationship` |
| 10 | Revoked grants block subsequent provider raw writes | `provider_runtime/test_rights_admission.py::test_expired_or_revoked_grant_denies_admission`; `provider_runtime/test_rights_revocation_fence.py`; `tests/prod_equivalent/test_real_stack_rights_revocation_fence.py::test_a_write_after_a_committed_revocation_is_denied` |
| 11 | One tenant's connection cannot bind another tenant's account | `provider_runtime/test_shop_account_binding.py::test_shop_held_by_another_tenant_is_rejected` |
| 12 | Public reference data does not auto-merge with tenant-private identity | `unit/test_source_authority_invariants.py::test_olympus_scope_records_never_become_tenant_identity_evidence`; `provider_runtime/test_bridge.py::test_olympus_scope_events_never_enter_the_tenant_pipeline` |
| 13 | Weak identity evidence cannot silently merge distinct profiles | `identity/test_blueprint_18_5_invariants.py::test_generated_weak_or_context_only_evidence_never_auto_merges`; `identity/test_sdk_legacy_resolve_late_binding.py::test_weak_fingerprint_claim_never_links_or_returns_authoritative_resolution` |
| 14 | Graph writes remain Gateway-governed | `rights_authority/test_source_lineage.py::test_graph_decision_traces_to_relationship_and_grant` (lineage only); gateway enforcement is pinned by the existing graph gateway suites, not by a test on this program |
| 15 | Access Kit transport cannot circumvent intake, tenant, consent or rights authorities | `unit/test_source_authority_invariants.py::test_delegated_mcp_tokens_reach_only_reads_and_never_source_or_rights_routes`, `::test_access_kit_writes_observations_only_through_canonical_batch_intake` |
| 16 | Replays preserve original source provenance | `tests/unit/observation/test_replay_adapter.py::test_replay_preserves_source_relationship_and_rights_references`; `provider_runtime/test_provider_source_scope.py::test_replayed_record_resolves_the_same_source_id` |
| 17 | Operator access remains purpose/governance constrained | `unit/test_data_rights_grant_routes.py::test_non_operator_is_refused`, `::test_operator_cannot_mint_non_operator_relationships`; `rights_authority/test_olympus_internal.py::test_unknown_purpose_denied` |
| 18 | A `source_relationship` never contributes to an allow decision | `integration_contracts/test_source_relationship.py::test_relationship_consistency_matrix`; `provider_runtime/test_rights_admission_classes.py::test_relationship_never_turns_a_denied_use_into_an_allow` |
| 19 | `provider-stream` scopes resolve only to manifest-declared streams | `provider_runtime/test_provider_source_scope.py::test_undeclared_or_missing_stream_denies`, `::test_no_connection_wide_fallback` |
| 20 | A venue account link cannot exist without a grant for its source scope | `unit/test_venue_account_links.py::test_wallet_link_is_a_personal_account_source`, `::test_tenant_push_is_an_organization_system_source`, `::test_backfill_governs_links_created_before_sources` |
| 21 | The reserved `olympus` scope cannot hold a tenant venue link | `unit/test_venue_account_links.py::test_olympus_scope_cannot_hold_a_venue_link` |
| 22 | Propagation uses only fills admitted under a grant | `propagation/test_propagation_service.py::test_service_builds_tenant_run_from_repository_sources`; `tests/unit/derivatives/test_account_sync.py::test_sync_admits_raw_records_and_writes_governed_fills` |
| 23 | Revoking a venue link (or its grant) blocks the next raw write for that account | `unit/test_venue_account_links.py::test_linked_account_raw_records_are_admitted_until_revoked`; `tests/unit/derivatives/test_account_sync.py::test_grant_revoked_behind_an_active_link_denies_and_keeps_the_checkpoint` |

## Intake paths and their source stamp

Every intake path writes server-owned source provenance; nothing in a request
body can set it.

| Path | Source relationship | Rights references | Where |
|---|---|---|---|
| SDK `/v1/batch` | `first_party_application` | none (consent-governed) | `ingestion/ingestion/observation_envelope.py` |
| Provider pulls and webhooks | from the grant that admitted the raw record | source id, grant ref and `rdec_` decision from `metadata.aether_rights_admission` | `ProviderIngressAdapter` (`ingestion/ingestion/adapters/provider.py`), attached by `connectors/provider_runtime/bridge.py` as `observation_envelope` |
| Server feed `/v1/ingest/feed` | from the grant for `feed:<source>` | `source_rights` on the Bronze row | `ingestion/ingestion/feed_rights.py` |
| Imports | from the import grant | grant ref | `ingestion/imports` |
| Replay | the original row's | the original row's | `ReplayIngressAdapter` |

The server feed requires an active grant allowing the tenant lake for the first
use of a source (`FEED_SOURCE_GRANT_REQUIRED`, default on). A source a tenant
already fed keeps working, stamped `unclassified` and `lake_scope:
tenant_only`, until a grant converges it.

Selecting an account on a tenant's own provider connection
(`POST /v1/provider-connections/{id}/accounts/select`) creates the
`organization_system` grant for `provider-account:<connection>:<account>`
(`tenant_byod_data`, owner `tenant`, contract basis, tenant lake, graph and
insights only) unless one is already active
(`connectors/provider_runtime/organization_grants.py`). Shopify is the
reference path. The reserved `olympus` scope never gets one.

## Native capabilities

The Olympus provider catalog (`connectors/provider_catalog/catalog.py`) declares
the relationship an Olympus grant for each provider must carry, and whether a
tenant can also connect it with its own credentials (`tenant_connectable`).
`validate_grant_classification` enforces both: an Olympus-scope grant for a
catalogued provider must use the declared relationship, and a
`public_reference` grant can never allow commercial reuse, model training or
cross-tenant aggregation.

| Provider | Olympus relationship | Tenant use |
|---|---|---|
| Dune (`dune_api`, `dune_datashare`, `dune_sim`) | `olympus_source` | yes: the tenant's own `organization_system` grant in its scope |
| CoinGecko, CoinMarketCap | `public_reference` | no |
| Public exchange market data (Coinbase Exchange, Binance, Kraken, OKX, Bybit, CCXT) | `public_reference` | no |

The Dune feeder applies this per ingest (`connectors/dune_feeder/service.py`):
a global ingest lands under the `olympus` scope and needs an Olympus grant for
`dune:<source_tag>` (Olympus baseline use); a tenant ingest needs that tenant's
grant (tenant lake use). Each row records `owner_scope`, `source_rights` and a
matching `license_status`. A source already fed in a scope stays legacy
(`unclassified`, tenant-lake-only); first use without a grant is refused
(`DUNE_SOURCE_GRANT_REQUIRED`, default on).

Coinbase is three separate capabilities: the payment rail (`payment_rails/coinbase.py`,
the tenant's own payments account), the Coinbase Financial Markets futures venue
(`coinbase_futures`, a member's linked account) and Coinbase Exchange public
market data (`coinbase_exchange`, Olympus `public_reference`).

## Source lifecycle

| Operation | Acquisition | Credential | Grant | Raw and derived data | Replay |
|---|---|---|---|---|---|
| Disconnect | stops (connection disabled) | deleted | kept active | kept | allowed |
| Reconnect | resumes on the same connection | new credential stored | the existing grant | kept | allowed |
| Rotate credential | continues | replaced, same ref | unchanged | kept | allowed |
| Revoke | stops | deleted | revoked; the next raw write is denied (revocation fence) | kept; no new writes | denied |
| Erase (link deletion, DSR) | stops | deleted | revoked | deleted through the DSR plane | denied |
| Tenant offboarding | stops for every source | deleted | revoked | per retention policy, then deleted | denied |

## Derivatives venue sources

Venue account links (`services/api/value/derivatives/account_links.py`) sit on
these authorities rather than beside them. Each link provisions a
`ProviderConnection` for `<venue>.account.<capability>` and a grant for
`provider-account:<connection_id>:<account_ref>` (`venue_sources.py`):
wallet, key and OAuth links are `personal_account` (owner `subject`, with the
consent receipt as `consent_basis`); tenant push is `organization_system`
(owner `tenant`). All use `tenant_byod_data`. Account sync and tenant-pushed
fills go through `ProviderRawRightsAdmission`. Venue market data is a separate
`<venue>.markets.market_data` capability for the `olympus` reference scope and
never becomes tenant evidence: `market_reference.py` admits public market
records under an operator-provisioned `public_reference` grant and writes only
the global market registry that tenant fills reference. Disconnect stops acquisition and keeps the
grant; revoke ends the grant; erasure revokes and deletes.

Venue OAuth (`venue_oauth.py`) draws the same line: the OAuth application is an
Olympus credential under the reserved `olympus` scope, set by a Kyber operator;
the tokens a member grants are the member's account access, stored per link
under the tenant behind the link's connection, and refused unless every granted
scope is read-only.

