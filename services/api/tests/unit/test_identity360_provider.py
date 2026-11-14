"""Focused contracts for the read-only Identity360 surface service."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from identity.identity.identity360_provider import (
    Identity360Provider,
    IdentityBatchRead,
    IdentityProviderRegistryRead,
    IdentityRecordRead,
    RepositoryIdentity360Source,
)
from identity.identity.repository import IdentityResolutionRepository
from repositories.repos import reset_in_memory_stores


class FakeIdentity360Source:
    def __init__(self) -> None:
        self.entity: dict[str, Any] | None = {
            "entity_id": "entity-1",
            "tenant_id": "tenant-a",
            "entity_type": "human",
            "status": "active",
            "display_name": "Private Person Name",
            "created_at": "2026-10-01T00:00:00Z",
            "updated_at": "2026-10-15T00:00:00Z",
        }
        self.identity: dict[str, Any] | None = {
            "id": "identity-subject-1",
            "tenant_id": "tenant-a",
            "canonical_entity_id": "entity-1",
            "entity_type": "human",
            "status": "active",
            "first_seen_at": "2026-09-01T00:00:00Z",
            "last_seen_at": "2026-10-15T00:00:00Z",
        }
        self.source: dict[str, Any] | None = None
        self.source_rows: list[dict[str, Any]] = [
            {
                "id": "source-row-1",
                "tenant_id": "tenant-a",
                "source_kind": "connector",
                "source_namespace": "crm:customers",
                "canonical_entity_id": "entity-1",
                "status": "resolved",
                "external_id": "private-external-id",
                "user_id": "private-user-id",
                "device_id": "private-device-id",
                "session_id": "private-session-id",
                "first_seen_at": "2026-09-05T00:00:00Z",
                "last_seen_at": "2026-10-14T00:00:00Z",
            }
        ]
        self.claims: list[dict[str, Any]] = []
        self.aliases: list[dict[str, Any]] = [
            {
                "id": "alias-1",
                "tenant_id": "tenant-a",
                "canonical_entity_id": "entity-1",
                "alias_type": "email_hash",
                "alias_value_hash": "private-sha256-hash",
                "alias_display_value_redacted": "j***@example.test",
                "source": "identity_sdk",
                "source_platform": "web",
                "confidence": 0.97,
                "confidence_tier": "strong",
                "consent_snapshot": {"private": "consent-payload"},
                "first_seen_at": "2026-09-06T00:00:00Z",
                "last_seen_at": "2026-10-14T00:00:00Z",
            }
        ]
        self.edges: list[dict[str, Any]] = [
            {
                "id": "edge-1",
                "tenant_id": "tenant-a",
                "source_entity_id": "entity-1",
                "target_entity_id": "entity-2",
                "edge_type": "same_as",
                "confidence": 0.96,
                "confidence_tier": "strong",
                "reason_codes": ["same_verified_email"],
                "source_event_ids": ["private-event-id"],
                "consent_snapshot": {"private": "consent-payload"},
                "created_at": "2026-10-10T00:00:00Z",
            }
        ]
        self.decisions: list[dict[str, Any]] = [
            {
                "id": "decision-1",
                "tenant_id": "tenant-a",
                "entity_id": "entity-1",
                "decision_type": "auto_link",
                "confidence_score": 0.97,
                "confidence_tier": "strong",
                "review_status": "auto",
                "signals_used": ["private-signal-value"],
                "created_at": "2026-10-10T00:00:00Z",
                "merge_policy_version": "1.0.0",
            }
        ]
        self.verification: list[dict[str, Any]] = [
            {
                "id": "verification-1",
                "tenant_id": "tenant-a",
                "canonical_entity_id": "entity-1",
                "evidence_type": "email_ownership_verified",
                "identifier_type": "email",
                "identifier_hash": "private-verification-hash",
                "verification_method": "email_otp",
                "assurance_level": "verified",
                "issuer": "aether",
                "status": "active",
                "proof_reference": "private-proof-reference",
                "verified_at": "2026-10-11T00:00:00Z",
            }
        ]
        self.conflicts: list[dict[str, Any]] = [
            {
                "id": "conflict-1",
                "tenant_id": "tenant-a",
                "candidate_entity_ids": ["entity-1", "entity-2"],
                "candidate_aliases": [{"value": "private-conflict-value"}],
                "conflict_type": "ambiguous_match",
                "confidence": 0.72,
                "reason_codes": ["conflicting_verified_identifier"],
                "status": "open",
                "created_at": "2026-10-13T00:00:00Z",
            }
        ]
        self.force_truncate_aliases = False
        self.claim_read_called = False
        self.batch_reads: list[str] = []
        self.provider_registry_reads: list[str] = []
        self.provider_registry_entries: dict[str, dict[str, Any]] = {}

    async def canonical_entity(self, tenant_id: str, entity_id: str) -> IdentityRecordRead:
        return IdentityRecordRead(record=self.entity)

    async def identity_subject(self, tenant_id: str, entity_id: str) -> IdentityRecordRead:
        return IdentityRecordRead(record=self.identity)

    async def source_identity(self, tenant_id: str, source_identity_id: str) -> IdentityRecordRead:
        return IdentityRecordRead(record=self.source)

    async def provider_registry_entry(
        self, source_system_id: str
    ) -> IdentityProviderRegistryRead:
        self.provider_registry_reads.append(source_system_id)
        entry = self.provider_registry_entries.get(source_system_id)
        return IdentityProviderRegistryRead(
            entry=entry,
            reason=None if entry is not None else "provider_identity_not_registered",
        )

    async def source_identities_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead:
        self.batch_reads.append("source_identities")
        return IdentityBatchRead(rows=tuple(self.source_rows))

    async def source_claims(
        self, tenant_id: str, source_identity_id: str, *, limit: int
    ) -> IdentityBatchRead:
        self.batch_reads.append("source_claims")
        self.claim_read_called = True
        return IdentityBatchRead(rows=tuple(self.claims))

    async def aliases_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead:
        self.batch_reads.append("aliases")
        return IdentityBatchRead(rows=tuple(self.aliases), truncated=self.force_truncate_aliases)

    async def identity_edges_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead:
        self.batch_reads.append("identity_edges")
        return IdentityBatchRead(rows=tuple(self.edges))

    async def decisions_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead:
        self.batch_reads.append("decisions")
        return IdentityBatchRead(rows=tuple(self.decisions))

    async def conflicts_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead:
        self.batch_reads.append("conflicts")
        rows = [
            row
            for row in self.conflicts
            if row.get("tenant_id") == tenant_id and entity_id in row.get("candidate_entity_ids", [])
        ]
        return IdentityBatchRead(rows=tuple(rows[:limit]), truncated=len(rows) > limit)

    async def verification_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead:
        self.batch_reads.append("verification")
        return IdentityBatchRead(rows=tuple(self.verification))


def _payload(result: Any) -> dict[str, Any]:
    return {
        "state": result.state,
        "slots": [
            {
                "id": slot.id,
                "state": slot.state,
                "content": slot.content,
                "evidenceRefs": [ref.model_dump(mode="json") for ref in slot.evidence_refs],
            }
            for slot in result.slots
        ],
    }


@pytest.mark.asyncio
async def test_entity_identity_projects_scoped_evidence_without_sensitive_values() -> None:
    source = FakeIdentity360Source()
    result = await Identity360Provider(source).read("tenant-a", "entity", "entity-1")

    assert [slot.id for slot in result.slots] == [
        "identifier_inventory",
        "namespace_map",
        "match_evidence",
        "conflicts",
        "confidence",
        "aliases",
        "devices_sessions",
        "wallets",
        "policy_redactions",
        "evidence_trace",
    ]
    assert result.state == "degraded"
    assert result.slot("identifier_inventory").state == "available"
    assert result.slot("namespace_map").state == "partial"
    namespace_mapping = result.slot("namespace_map").content["mappings"][0]
    assert namespace_mapping["sourceIdentityId"] == "source-row-1"
    assert namespace_mapping["canonicalEntityId"] == "entity-1"
    assert namespace_mapping["evidenceRef"]["id"] == "source-row-1"
    assert namespace_mapping["evidenceRef"]["source"] == "identity_source_identities"
    assert result.slot("namespace_map").content["canonicalNamespaceRegistryJoin"]["state"] == "partial"
    assert result.slot("match_evidence").state == "available"
    assert result.slot("match_evidence").content["semantics"] == (
        "recorded_identity_resolution_evidence_only"
    )
    assert result.slot("conflicts").state == "available"
    assert result.slot("conflicts").content["items"][0]["type"] == "ambiguous_match"
    assert result.slot("confidence").state == "available"
    assert result.slot("confidence").content["compositeConfidence"] is None
    assert result.slot("aliases").state == "available"
    devices_sessions = result.slot("devices_sessions")
    assert devices_sessions.state == "partial"
    assert devices_sessions.content["inventoryState"] == "unknown"
    assert devices_sessions.content["observedIdentifierCount"] == 1
    assert devices_sessions.content["sourceIdentityObservations"] == [
        {
            "sourceIdentityId": "source-row-1",
            "identifierTypes": ["device_id", "session_id"],
            "firstSeenAt": "2026-09-05T00:00:00Z",
            "lastSeenAt": "2026-10-14T00:00:00Z",
            "evidenceRef": {
                "id": "source-row-1",
                "type": "annotation",
                "source": "identity_source_identities",
                "observedAt": "2026-10-14T00:00:00Z",
            },
        }
    ]
    inventory_item = result.slot("identifier_inventory").content["sourceIdentities"][0]
    assert inventory_item["id"] == "source-row-1"
    assert inventory_item["canonicalEntityId"] == "entity-1"
    assert inventory_item["evidenceRef"]["id"] == "source-row-1"
    alias_item = result.slot("aliases").content["items"][0]
    assert alias_item["evidenceRef"]["id"] == "alias-1"
    assert alias_item["evidenceRef"]["source"] == "identity_aliases"
    assert result.slot("wallets").state == "unknown"
    assert result.slot("policy_redactions").state == "degraded"
    assert result.slot("policy_redactions").content["projectionRedaction"]["state"] == "applied"
    assert result.slot("evidence_trace").state == "available"
    assert result.slot("match_evidence").content["freshness"]["state"] == "unknown"

    rendered = json.dumps(_payload(result), sort_keys=True)
    for private_value in (
        "Private Person Name",
        "private-external-id",
        "private-user-id",
        "private-sha256-hash",
        "private-signal-value",
        "private-event-id",
        "private-verification-hash",
        "private-proof-reference",
        "private-device-id",
        "private-session-id",
        "private-conflict-value",
        "consent-payload",
    ):
        assert private_value not in rendered

    assert "email_hash" in rendered
    assert "j***@example.test" in rendered
    assert "identity_source_identities" in rendered
    assert "identity_verification_evidence" in rendered
    assert "identity_conflicts" in rendered


@pytest.mark.asyncio
async def test_device_session_observations_require_exact_lineage_evidence() -> None:
    source = FakeIdentity360Source()
    source.source_rows = [
        {
            "tenant_id": "tenant-a",
            "source_kind": "sdk",
            "source_namespace": "sdk:web",
            "canonical_entity_id": "entity-1",
            "status": "resolved",
            "device_id": "private-device-id",
            "session_id": "private-session-id",
            "first_seen_at": "2026-09-05T00:00:00Z",
        }
    ]

    result = await Identity360Provider(source).read(
        "tenant-a", "entity", "entity-1", requested_slot_ids={"devices_sessions"}
    )

    devices_sessions = result.slot("devices_sessions")
    assert devices_sessions.state == "degraded"
    assert devices_sessions.reason == "identity_source_identities_evidence_ref_missing"
    assert devices_sessions.content["inventoryState"] == "unknown"
    assert devices_sessions.content["sourceIdentityObservations"] == []
    assert devices_sessions.evidence_refs == ()
    rendered = json.dumps(_payload(result), sort_keys=True)
    assert "private-device-id" not in rendered
    assert "private-session-id" not in rendered


@pytest.mark.asyncio
async def test_inventory_and_namespace_rows_require_record_level_provenance() -> None:
    source = FakeIdentity360Source()
    source.source_rows = [
        {
            "tenant_id": "tenant-a",
            "source_kind": "connector",
            "source_namespace": "crm:customers",
            "canonical_entity_id": "entity-1",
            "status": "resolved",
            "external_id": "unproven-private-identifier",
        }
    ]

    result = await Identity360Provider(source).read(
        "tenant-a",
        "entity",
        "entity-1",
        requested_slot_ids={"identifier_inventory", "namespace_map"},
    )

    inventory = result.slot("identifier_inventory")
    namespaces = result.slot("namespace_map")
    assert inventory.state == "degraded"
    assert namespaces.state == "degraded"
    assert inventory.content["sourceIdentities"] == []
    assert namespaces.content["mappings"] == []
    rendered = json.dumps(_payload(result), sort_keys=True)
    assert "unproven-private-identifier" not in rendered


@pytest.mark.asyncio
async def test_namespace_map_joins_only_exact_registered_source_system_identity() -> None:
    source = FakeIdentity360Source()
    source.source_rows[0]["source_system_id"] = "shopify.admin.orders_read"
    source.provider_registry_entries["shopify.admin.orders_read"] = {
        "identityKey": "shopify.admin.orders_read",
        "providerFamily": "shopify",
        "productId": "admin",
        "capabilityId": "orders_read",
        "displayName": "Shopify Admin Orders Read",
        "category": "commerce",
        "credentialSecret": "must-not-escape-provider-registry",
    }

    result = await Identity360Provider(source).read(
        "tenant-a", "entity", "entity-1", requested_slot_ids={"namespace_map"}
    )

    namespaces = result.slot("namespace_map")
    mapping = namespaces.content["mappings"][0]
    assert source.provider_registry_reads == ["shopify.admin.orders_read"]
    assert namespaces.state == "partial"
    assert mapping["sourceNamespace"] == "crm:customers"
    assert mapping["providerIdentity"] == "shopify.admin.orders_read"
    assert mapping["provider"]["providerFamily"] == "shopify"
    assert mapping["providerRegistryJoin"] == {"state": "resolved", "reason": None}
    assert mapping["evidenceRef"]["id"] == "source-row-1"
    summary = namespaces.content["canonicalNamespaceRegistryJoin"]
    assert summary["joinState"] == "resolved"
    assert summary["resolvedEntries"] == 1
    assert summary["freshness"]["state"] == "unknown"
    assert namespaces.reason == "provider_registry_freshness_unknown"
    assert "must-not-escape-provider-registry" not in json.dumps(_payload(result))

    # A namespace prefix that resembles a provider never substitutes for its
    # exact source_system_id foreign-key claim.
    source.source_rows[0]["source_system_id"] = "shopify"
    result = await Identity360Provider(source).read(
        "tenant-a", "entity", "entity-1", requested_slot_ids={"namespace_map"}
    )
    mapping = result.slot("namespace_map").content["mappings"][0]
    assert source.provider_registry_reads[-1] == "shopify"
    assert mapping["providerIdentity"] is None
    assert mapping["providerRegistryJoin"]["state"] == "unknown"
    assert result.slot("namespace_map").state == "partial"


@pytest.mark.asyncio
async def test_repository_identity_source_uses_exact_runtime_provider_key(monkeypatch) -> None:
    from types import SimpleNamespace

    from connectors.provider_runtime.registry import provider_registry

    exact_key = "shopify.admin.orders_read"
    plugin = SimpleNamespace(
        identity=lambda: SimpleNamespace(key=exact_key),
        manifest=lambda: SimpleNamespace(
            identity_key=exact_key,
            provider_family="shopify",
            product_id="admin",
            capability_id="orders_read",
            display_name="Shopify Admin Orders Read",
            category="commerce",
        ),
    )
    monkeypatch.setattr(
        provider_registry,
        "get",
        lambda requested: plugin if requested == exact_key else None,
    )

    source = RepositoryIdentity360Source(identity_repository=object())
    registered = await source.provider_registry_entry(exact_key)
    missing = await source.provider_registry_entry("shopify")

    assert registered.available is True
    assert registered.entry == {
        "identityKey": exact_key,
        "providerFamily": "shopify",
        "productId": "admin",
        "capabilityId": "orders_read",
        "displayName": "Shopify Admin Orders Read",
        "category": "commerce",
    }
    assert missing.available is True
    assert missing.entry is None
    assert missing.reason == "provider_identity_not_registered"


@pytest.mark.asyncio
async def test_namespace_provider_registry_is_not_read_when_slot_is_not_requested() -> None:
    source = FakeIdentity360Source()
    source.source_rows[0]["source_system_id"] = "shopify.admin.orders_read"

    result = await Identity360Provider(source).read(
        "tenant-a", "entity", "entity-1", requested_slot_ids={"identifier_inventory"}
    )

    assert result.slot("namespace_map").state == "unknown"
    assert result.slot("namespace_map").reason == "identity_slot_not_requested"
    assert source.provider_registry_reads == []


@pytest.mark.asyncio
async def test_namespace_map_does_not_join_provider_for_cross_tenant_identity_row() -> None:
    source = FakeIdentity360Source()
    source.source_rows[0]["tenant_id"] = "tenant-b"
    source.source_rows[0]["source_system_id"] = "shopify.admin.orders_read"
    source.provider_registry_entries["shopify.admin.orders_read"] = {
        "identityKey": "shopify.admin.orders_read",
        "providerFamily": "shopify",
    }

    result = await Identity360Provider(source).read(
        "tenant-a", "entity", "entity-1", requested_slot_ids={"namespace_map"}
    )

    namespaces = result.slot("namespace_map")
    assert namespaces.state == "degraded"
    assert namespaces.content["mappings"] == []
    assert source.provider_registry_reads == []
    assert namespaces.reason == "identity_row_tenant_mismatch"


@pytest.mark.asyncio
async def test_alias_records_require_their_own_evidence_reference() -> None:
    source = FakeIdentity360Source()
    source.aliases = [
        {
            "tenant_id": "tenant-a",
            "canonical_entity_id": "entity-1",
            "alias_type": "email_hash",
            "alias_display_value_redacted": "j***@example.test",
        }
    ]

    result = await Identity360Provider(source).read(
        "tenant-a", "entity", "entity-1", requested_slot_ids={"aliases"}
    )

    aliases = result.slot("aliases")
    assert aliases.state == "degraded"
    assert aliases.reason == "identity_aliases_evidence_ref_missing"
    assert aliases.content["items"] == []
    assert aliases.evidence_refs == ()


@pytest.mark.asyncio
async def test_missing_device_session_observations_remain_unknown_not_empty() -> None:
    source = FakeIdentity360Source()
    source.source_rows = [
        {
            "id": "source-row-without-device-session",
            "tenant_id": "tenant-a",
            "source_kind": "connector",
            "source_namespace": "crm:customers",
            "canonical_entity_id": "entity-1",
            "status": "resolved",
            "external_id": "private-external-id",
        }
    ]

    result = await Identity360Provider(source).read(
        "tenant-a", "entity", "entity-1", requested_slot_ids={"devices_sessions"}
    )

    devices_sessions = result.slot("devices_sessions")
    assert devices_sessions.state == "unknown"
    assert devices_sessions.content["inventoryState"] == "unknown"
    assert devices_sessions.content["sourceIdentityObservations"] == []
    assert devices_sessions.reason == "device_session_inventory_authority_not_joined"
    assert "private-external-id" not in json.dumps(_payload(result), sort_keys=True)


@pytest.mark.asyncio
async def test_requested_slot_scope_skips_identity_authorities_for_unrequested_slots() -> None:
    source = FakeIdentity360Source()
    result = await Identity360Provider(source).read(
        "tenant-a",
        "entity",
        "entity-1",
        requested_slot_ids={"identifier_inventory"},
    )

    assert result.slot("identifier_inventory").state == "available"
    assert source.batch_reads == ["source_identities"]
    assert result.slot("match_evidence").state == "unknown"
    assert result.slot("match_evidence").reason == "identity_slot_not_requested"


@pytest.mark.asyncio
async def test_source_subject_uses_exact_tenant_scoped_record_and_sanitized_claims() -> None:
    source = FakeIdentity360Source()
    source.source = {
        "id": "source-1",
        "tenant_id": "tenant-a",
        "source_kind": "sdk",
        "source_namespace": "sdk:web",
        "status": "unresolved",
        "external_id": "private-source-identifier",
        "canonical_entity_id": None,
        "first_seen_at": "2026-10-12T00:00:00Z",
    }
    source.claims = [
        {
            "id": "claim-1",
            "tenant_id": "tenant-a",
            "source_identity_id": "source-1",
            "claim_type": "email",
            "normalized_value": "private-normalized-email",
            "raw_value": "private-raw-email",
            "verification_status": "observed",
            "confidence_hint": 0.5,
            "pii_classification": "direct_identifier",
            "status": "active",
            "ingested_at": "2026-10-12T00:00:00Z",
        }
    ]

    result = await Identity360Provider(source).read("tenant-a", "source", "source-1")

    inventory = result.slot("identifier_inventory")
    namespaces = result.slot("namespace_map")
    evidence = result.slot("evidence_trace")
    assert inventory.state == "available"
    assert namespaces.state == "partial"
    assert namespaces.content["canonicalNamespaceRegistryJoin"]["state"] == "partial"
    assert "source_system_id_not_recorded" in result.warnings
    assert inventory.content["sourceIdentities"][0]["identifierTypes"] == ["external_id"]
    assert inventory.content["claims"][0]["claimType"] == "email"
    assert inventory.content["claims"][0]["evidenceRef"]["id"] == "claim-1"
    assert inventory.content["sourceIdentities"][0]["id"] == "source-1"
    assert inventory.content["sourceIdentities"][0]["canonicalEntityId"] is None
    assert inventory.content["sourceIdentities"][0]["evidenceRef"]["id"] == "source-1"
    assert evidence.state == "available"
    assert result.slot("match_evidence").state == "unknown"
    assert result.slot("aliases").state == "unknown"

    rendered = json.dumps(_payload(result), sort_keys=True)
    for private_value in (
        "private-source-identifier",
        "private-normalized-email",
        "private-raw-email",
        "private-source-identifier",
    ):
        assert private_value not in rendered


@pytest.mark.asyncio
async def test_resolved_source_identity_joins_canonical_match_evidence() -> None:
    source = FakeIdentity360Source()
    source.source = {
        "id": "source-1",
        "tenant_id": "tenant-a",
        "source_kind": "connector",
        "source_namespace": "crm:customers",
        "status": "resolved",
        "external_id": "private-source-identifier",
        "canonical_entity_id": "entity-1",
    }

    result = await Identity360Provider(source).read("tenant-a", "source", "source-1")

    assert result.slot("match_evidence").state == "available"
    assert result.slot("match_evidence").content["subjectResolution"]["state"] == "resolved"
    assert result.slot("aliases").state == "available"
    assert "aliases" in source.batch_reads
    source_inventory_item = result.slot("identifier_inventory").content["sourceIdentities"][0]
    assert source_inventory_item["id"] == "source-1"
    assert source_inventory_item["canonicalEntityId"] == "entity-1"
    assert source_inventory_item["evidenceRef"]["id"] == "source-1"
    rendered = json.dumps(_payload(result), sort_keys=True)
    assert "private-source-identifier" not in rendered


@pytest.mark.asyncio
async def test_claim_records_without_record_evidence_degrade_inventory() -> None:
    source = FakeIdentity360Source()
    source.source = {
        "id": "source-1",
        "tenant_id": "tenant-a",
        "source_kind": "sdk",
        "source_namespace": "sdk:web",
        "status": "unresolved",
        "external_id": "private-source-identifier",
    }
    source.claims = [
        {
            "tenant_id": "tenant-a",
            "source_identity_id": "source-1",
            "claim_type": "email",
            "raw_value": "private-claim-value",
        }
    ]

    result = await Identity360Provider(source).read(
        "tenant-a", "source", "source-1", requested_slot_ids={"identifier_inventory"}
    )

    inventory = result.slot("identifier_inventory")
    assert inventory.state == "degraded"
    assert inventory.content["claims"] == []
    assert inventory.reason == "identity_claims_evidence_ref_missing"
    rendered = json.dumps(_payload(result), sort_keys=True)
    assert "private-claim-value" not in rendered


@pytest.mark.asyncio
async def test_unresolved_source_link_does_not_become_canonical_subject() -> None:
    source = FakeIdentity360Source()
    source.source = {
        "id": "source-1",
        "tenant_id": "tenant-a",
        "source_kind": "sdk",
        "source_namespace": "sdk:web",
        "status": "unresolved",
        "external_id": "private-source-identifier",
        # A stale or untrusted link alone must not bind downstream projections.
        "canonical_entity_id": "entity-1",
    }

    result = await Identity360Provider(source).read(
        "tenant-a",
        "source",
        "source-1",
        requested_slot_ids={"match_evidence"},
    )

    identity = result.slot("match_evidence")
    assert identity.state == "unknown"
    assert identity.content["subjectResolution"]["canonicalEntity"] is None
    assert identity.content["subjectResolution"]["state"] == "unknown"
    assert "source_identity_not_resolved" in result.warnings


@pytest.mark.asyncio
async def test_repository_source_identity_query_is_tenant_bound_before_identity360_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_in_memory_stores()


    repository = IdentityResolutionRepository()
    source_identity_id = "shared-source-record-id"
    foreign_row = {
        "id": source_identity_id,
        "tenant_id": "tenant-b",
        "source_kind": "connector",
        "source_namespace": "foreign-private-namespace",
        "status": "resolved",
        "external_id": "foreign-private-identifier",
        "canonical_entity_id": "foreign-entity-id",
    }
    await repository._source_identities.insert(source_identity_id, dict(foreign_row))
    # Preserve the existing globally unique-ID method for legacy callers; the
    # new tenant-bound seam must exclude this same-id foreign row in its query.
    assert (await repository.get_source_identity(source_identity_id))["tenant_id"] == "tenant-b"

    store = repository._source_identities
    original_find_many = store.find_many
    query_filters: list[dict[str, Any]] = []

    async def recording_find_many(
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str | None = None,
        sort_order: str = "desc",
    ) -> list[dict[str, Any]]:
        query_filters.append(dict(filters or {}))
        return await original_find_many(
            filters=filters,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    monkeypatch.setattr(store, "find_many", recording_find_many)
    source = RepositoryIdentity360Source(identity_repository=repository)

    source_read = await source.source_identity("tenant-a", source_identity_id)
    assert source_read.record is None
    assert query_filters == [{"tenant_id": "tenant-a", "id": source_identity_id}]

    result = await Identity360Provider(source).read("tenant-a", "source", source_identity_id)
    assert result.state == "degraded"
    assert result.slot("identifier_inventory").content["sourceIdentities"] == []
    assert result.slot("evidence_trace").content["evidenceRefs"] == []
    assert all(
        filters == {"tenant_id": "tenant-a", "id": source_identity_id} for filters in query_filters
    )
    rendered = json.dumps(_payload(result), sort_keys=True)
    for foreign_value in (
        "foreign-private-namespace",
        "foreign-private-identifier",
        "foreign-entity-id",
    ):
        assert foreign_value not in rendered
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_repository_conflicts_are_tenant_and_entity_scoped() -> None:
    reset_in_memory_stores()
    repository = IdentityResolutionRepository()
    await repository.create_conflict(
        "tenant-a", ["entity-1", "entity-2"], [], "ambiguous_match", 0.7, ["review"]
    )
    await repository.create_conflict(
        "tenant-b", ["entity-1", "entity-foreign"], [], "foreign_match", 0.9, ["private"]
    )

    source = RepositoryIdentity360Source(identity_repository=repository)
    read = await source.conflicts_for_entity("tenant-a", "entity-1", limit=10)

    assert read.available is True
    assert read.truncated is False
    assert len(read.rows) == 1
    assert read.rows[0]["tenant_id"] == "tenant-a"
    assert read.rows[0]["candidate_entity_ids"] == ["entity-1", "entity-2"]
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_cross_tenant_entity_and_evidence_are_not_projected() -> None:
    source = FakeIdentity360Source()
    source.entity = {
        "entity_id": "entity-1",
        "tenant_id": "tenant-b",
        "entity_type": "human",
        "display_name": "Cross Tenant Private Name",
    }
    source.identity = {
        "id": "identity-subject-1",
        "tenant_id": "tenant-b",
        "canonical_entity_id": "entity-1",
        "entity_type": "human",
        "status": "active",
    }

    result = await Identity360Provider(source).read("tenant-a", "entity", "entity-1")

    assert result.state == "degraded"
    assert result.slot("match_evidence").state == "unknown"
    assert result.slot("aliases").state == "unknown"
    assert result.slot("aliases").content["items"] == []
    assert "Cross Tenant Private Name" not in json.dumps(_payload(result))


@pytest.mark.asyncio
async def test_tenant_mismatched_rows_fail_closed_and_truncation_is_preserved() -> None:
    source = FakeIdentity360Source()
    source.aliases = [
        {
            "id": "foreign-alias",
            "tenant_id": "tenant-b",
            "canonical_entity_id": "entity-1",
            "alias_type": "email_hash",
            "alias_value_hash": "must-not-leak",
        }
    ]
    source.force_truncate_aliases = True

    result = await Identity360Provider(source).read("tenant-a", "entity", "entity-1")

    evidence = result.slot("aliases")
    assert evidence.state == "degraded"
    assert evidence.content["items"] == []
    assert "must-not-leak" not in json.dumps(_payload(result))

    source.aliases = []
    source.force_truncate_aliases = True
    result = await Identity360Provider(source).read("tenant-a", "entity", "entity-1")
    assert result.slot("aliases").state == "truncated"
    assert result.slot("aliases").truncated is True


@pytest.mark.asyncio
async def test_agent_subject_requires_canonical_agent_entity_type() -> None:
    source = FakeIdentity360Source()
    source.entity = {**source.entity, "entity_type": "human"}

    result = await Identity360Provider(source).read("tenant-a", "agent", "entity-1")

    assert result.slot("match_evidence").state == "unknown"
    assert result.slot("wallets").state == "unknown"


@pytest.mark.asyncio
async def test_wallet_source_candidate_does_not_claim_wallet_ownership() -> None:
    source = FakeIdentity360Source()
    source.source_rows = [
        {
            "id": "wallet-source-row",
            "tenant_id": "tenant-a",
            "source_kind": "sdk_wallet",
            "source_namespace": "tenant:tenant-a:wallet:eip155:1",
            "canonical_entity_id": "entity-1",
            "status": "unresolved",
            "external_id": "private-wallet-hash",
        }
    ]

    result = await Identity360Provider(source).read(
        "tenant-a", "entity", "entity-1", requested_slot_ids={"wallets"}
    )

    wallets = result.slot("wallets")
    assert wallets.state == "unknown"
    assert wallets.content["ownershipState"] == "unknown"
    assert wallets.content["observedSourceCandidates"][0]["sourceKind"] == "sdk_wallet"
    assert wallets.content["ownershipProofs"] == []
    assert "verification" in source.batch_reads
    rendered = json.dumps(_payload(result), sort_keys=True)
    assert "private-wallet-hash" not in rendered


@pytest.mark.asyncio
async def test_wallet_slot_reads_exact_entity_bound_proof_without_identifier_values() -> None:
    source = FakeIdentity360Source()
    source.verification = [
        {
            "id": "wallet-proof-1",
            "tenant_id": "tenant-a",
            "canonical_entity_id": "entity-1",
            "evidence_type": "wallet_ownership_verified",
            "identifier_type": "wallet",
            "identifier_hash": "private-wallet-identifier-hash",
            "verification_method": "wallet_signature",
            "assurance_level": "verified",
            "issuer": "aether",
            "status": "active",
            "proof_reference": "private-wallet-proof-reference",
            "proof_digest": "private-wallet-proof-digest",
            "subject_hint_ciphertext": "private-wallet-subject-ciphertext",
            "metadata": {
                "chain_namespace": "eip155:1",
                "private_value": "private-wallet-metadata",
            },
            "verified_at": "2026-10-11T00:00:00Z",
        }
    ]

    result = await Identity360Provider(source).read(
        "tenant-a", "entity", "entity-1", requested_slot_ids={"wallets"}
    )

    wallets = result.slot("wallets")
    assert wallets.state == "partial"
    assert wallets.content["ownershipState"] == "unknown"
    assert wallets.content["currentControl"] == "unknown"
    assert wallets.content["ownershipProofs"] == [
        {
            "id": "wallet-proof-1",
            "evidenceType": "wallet_ownership_verified",
            "identifierType": "wallet",
            "chainNamespace": "eip155:1",
            "verificationMethod": "wallet_signature",
            "assuranceLevel": "verified",
            "issuer": "aether",
            "status": "active",
            "verifiedAt": "2026-10-11T00:00:00Z",
            "expiresAt": None,
            "revokedAt": None,
        }
    ]
    assert [(ref.source, ref.id) for ref in wallets.evidence_refs] == [
        ("identity_verification_evidence", "wallet-proof-1")
    ]
    rendered = json.dumps(_payload(result), sort_keys=True)
    for private_value in (
        "private-wallet-identifier-hash",
        "private-wallet-proof-reference",
        "private-wallet-proof-digest",
        "private-wallet-subject-ciphertext",
        "private-wallet-metadata",
    ):
        assert private_value not in rendered


@pytest.mark.asyncio
async def test_wallet_slot_joins_exact_tenant_inventory_without_echoing_wallet_identifiers() -> None:
    source = FakeIdentity360Source()
    source.wallet_inventory_for_entity = _wallet_inventory_reader(
        [
            {
                "id": "0xprivate-wallet-address",
                "wallet_id": "0xprivate-wallet-address",
                "owner_entity_id": "entity-1",
                "tenant_id": "tenant-a",
                "chain": "eip155:1",
                "address": "0xprivate-wallet-address",
                "linked_at": "2026-10-12T00:00:00Z",
            }
        ]
    )

    result = await Identity360Provider(source).read(
        "tenant-a", "entity", "entity-1", requested_slot_ids={"wallets"}
    )

    wallets = result.slot("wallets")
    assert wallets.state == "partial"
    assert wallets.content["inventoryState"] == "available"
    assert wallets.content["ownershipState"] == "unknown"
    assert wallets.content["currentControl"] == "unknown"
    assert wallets.content["linkedWallets"][0]["chain"] == "eip155:1"
    assert wallets.content["linkedWallets"][0]["linkedAt"] == "2026-10-12T00:00:00Z"
    assert wallets.evidence_refs[0].source == "entity_wallets"
    assert wallets.evidence_refs[0].id.startswith("wallet-link:")
    assert "0xprivate-wallet-address" not in json.dumps(_payload(result), sort_keys=True)


@pytest.mark.asyncio
async def test_wallet_slot_rejects_cross_tenant_inventory_rows() -> None:
    source = FakeIdentity360Source()
    source.wallet_inventory_for_entity = _wallet_inventory_reader(
        [
            {
                "id": "foreign-wallet-record",
                "owner_entity_id": "entity-1",
                "tenant_id": "tenant-b",
                "chain": "eip155:1",
                "linked_at": "2026-10-12T00:00:00Z",
            }
        ]
    )

    result = await Identity360Provider(source).read(
        "tenant-a", "entity", "entity-1", requested_slot_ids={"wallets"}
    )

    wallets = result.slot("wallets")
    assert wallets.state == "degraded"
    assert wallets.content["linkedWallets"] == []
    assert wallets.reason == "identity_row_tenant_mismatch"
    assert "foreign-wallet-record" not in json.dumps(_payload(result), sort_keys=True)


@pytest.mark.asyncio
async def test_repository_identity_source_reads_wallet_links_by_tenant_and_owner_entity() -> None:
    class _WalletRepository:
        def __init__(self) -> None:
            self.calls: list[tuple[dict[str, str], int]] = []

        async def find_many(self, *, filters, limit):
            self.calls.append((filters, limit))
            return [
                {
                    "id": "wallet-link-record",
                    "tenant_id": "tenant-a",
                    "owner_entity_id": "entity-1",
                    "wallet_id": "private-wallet-id",
                    "chain": "eip155:1",
                    "address": "private-wallet-address",
                    "linked_at": "2026-10-12T00:00:00Z",
                }
            ]

    wallet_repository = _WalletRepository()
    source = RepositoryIdentity360Source(wallet_repository=wallet_repository)

    result = await source.wallet_inventory_for_entity(
        "tenant-a", "entity-1", limit=17
    )

    assert wallet_repository.calls == [
        ({"tenant_id": "tenant-a", "owner_entity_id": "entity-1"}, 18)
    ]
    assert result.available is True
    assert result.truncated is False
    assert result.rows[0]["owner_entity_id"] == "entity-1"


def _wallet_inventory_reader(rows: list[dict[str, Any]]):
    async def read(tenant_id: str, entity_id: str, *, limit: int) -> IdentityBatchRead:
        assert tenant_id == "tenant-a"
        assert entity_id == "entity-1"
        return IdentityBatchRead(rows=tuple(rows[:limit]), truncated=len(rows) > limit)

    return read


@pytest.mark.asyncio
async def test_wallet_slot_rejects_cross_tenant_verification_evidence() -> None:
    source = FakeIdentity360Source()
    source.verification = [
        {
            "id": "foreign-wallet-proof",
            "tenant_id": "tenant-b",
            "canonical_entity_id": "entity-1",
            "evidence_type": "wallet_ownership_verified",
            "identifier_type": "wallet",
            "identifier_hash": "private-wallet-identifier-hash",
            "status": "active",
        }
    ]

    result = await Identity360Provider(source).read(
        "tenant-a", "entity", "entity-1", requested_slot_ids={"wallets"}
    )

    wallets = result.slot("wallets")
    assert wallets.state == "degraded"
    assert wallets.content["ownershipProofs"] == []
    assert wallets.reason == "identity_row_tenant_mismatch"
    assert "private-wallet-identifier-hash" not in json.dumps(_payload(result), sort_keys=True)


@pytest.mark.asyncio
async def test_suppressed_source_identity_does_not_read_or_project_claims() -> None:
    source = FakeIdentity360Source()
    source.source = {
        "id": "source-1",
        "tenant_id": "tenant-a",
        "source_kind": "sdk",
        "source_namespace": "private-namespace",
        "status": "suppressed",
        "external_id": "private-source-identifier",
    }
    source.claims = [
        {
            "id": "claim-1",
            "tenant_id": "tenant-a",
            "source_identity_id": "source-1",
            "claim_type": "email",
            "raw_value": "private-raw-email",
        }
    ]

    result = await Identity360Provider(source).read("tenant-a", "source", "source-1")

    assert not source.claim_read_called
    assert result.slot("identifier_inventory").state == "suppressed"
    assert result.slot("namespace_map").state == "suppressed"
    rendered = json.dumps(_payload(result), sort_keys=True)
    for private_value in (
        "private-namespace",
        "private-source-identifier",
        "private-raw-email",
    ):
        assert private_value not in rendered


@pytest.mark.asyncio
async def test_repository_failure_is_reported_as_degraded_without_exception_text() -> None:
    class FailingSource(FakeIdentity360Source):
        async def canonical_entity(self, tenant_id: str, entity_id: str) -> IdentityRecordRead:
            raise RuntimeError("private backend endpoint")

    result = await Identity360Provider(FailingSource()).read("tenant-a", "entity", "entity-1")

    resolved = result.slot("match_evidence")
    assert resolved.state == "degraded"
    assert "RuntimeError" in " ".join(result.warnings)
    assert "private backend endpoint" not in json.dumps(_payload(result))


@pytest.mark.asyncio
async def test_provider_rejects_empty_scope_and_unsupported_subjects() -> None:
    provider = Identity360Provider(FakeIdentity360Source())
    with pytest.raises(ValueError):
        await provider.read("", "entity", "entity-1")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await provider.read("tenant-a", "campaign", "campaign-1")  # type: ignore[arg-type]
