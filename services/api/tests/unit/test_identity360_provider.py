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
        self.force_truncate_aliases = False
        self.claim_read_called = False
        self.batch_reads: list[str] = []

    async def canonical_entity(self, tenant_id: str, entity_id: str) -> IdentityRecordRead:
        return IdentityRecordRead(record=self.entity)

    async def identity_subject(self, tenant_id: str, entity_id: str) -> IdentityRecordRead:
        return IdentityRecordRead(record=self.identity)

    async def source_identity(self, tenant_id: str, source_identity_id: str) -> IdentityRecordRead:
        return IdentityRecordRead(record=self.source)

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

    assert result.state == "available"
    assert result.slot("resolved_subject_identity").state == "available"
    assert result.slot("source_identifier_lineage").state == "available"
    assert result.slot("identity_evidence").state == "available"
    assert result.slot("relationship_identity_context").content["semantics"] == (
        "identity_resolution_edges_only"
    )
    assert result.slot("actor_and_agent_binding").state == "unknown"
    assert result.slot("identity_evidence").content["freshness"]["state"] == "unknown"

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
        "consent-payload",
    ):
        assert private_value not in rendered

    assert "email_hash" in rendered
    assert "j***@example.test" in rendered
    assert "identity_source_identities" in rendered
    assert "identity_verification_evidence" in rendered


@pytest.mark.asyncio
async def test_requested_slot_scope_skips_identity_authorities_for_unrequested_slots() -> None:
    source = FakeIdentity360Source()
    result = await Identity360Provider(source).read(
        "tenant-a",
        "entity",
        "entity-1",
        requested_slot_ids={"resolved_subject_identity"},
    )

    assert result.slot("resolved_subject_identity").state == "available"
    assert set(result.slot("resolved_subject_identity").content["resolution"]) == {
        "state",
        "authority",
        "exactIdMatch",
    }
    assert source.batch_reads == []
    assert result.slot("identity_evidence").state == "unknown"
    assert result.slot("identity_evidence").reason == "identity_slot_not_requested"


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

    lineage = result.slot("source_identifier_lineage")
    evidence = result.slot("identity_evidence")
    assert lineage.state == "degraded"
    assert lineage.reason == "source_provider_registry_join_not_performed"
    assert "source_provider_registry_join_not_performed" in result.warnings
    assert lineage.content["sourceIdentities"][0]["identifierTypes"] == ["external_id"]
    assert lineage.content["claims"][0]["claimType"] == "email"
    assert evidence.content["sourceClaims"][0]["verificationStatus"] == "observed"
    assert result.slot("resolved_subject_identity").state == "unknown"
    assert result.slot("relationship_identity_context").state == "unknown"

    rendered = json.dumps(_payload(result), sort_keys=True)
    for private_value in (
        "private-source-identifier",
        "private-normalized-email",
        "private-raw-email",
    ):
        assert private_value not in rendered


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
        requested_slot_ids={"resolved_subject_identity"},
    )

    identity = result.slot("resolved_subject_identity")
    assert identity.state == "unknown"
    assert identity.content["canonicalEntity"] is None
    assert identity.content["resolution"]["state"] == "unknown"
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
    assert result.state == "unknown"
    assert result.slot("source_identifier_lineage").content["sourceIdentities"] == []
    assert result.slot("identity_evidence").content["sourceClaims"] == []
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

    assert result.state == "unknown"
    assert result.slot("resolved_subject_identity").state == "unknown"
    assert result.slot("identity_evidence").state == "unknown"
    assert result.slot("identity_evidence").content["aliases"] == []
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

    evidence = result.slot("identity_evidence")
    assert evidence.state == "degraded"
    assert evidence.content["aliases"] == []
    assert "must-not-leak" not in json.dumps(_payload(result))

    source.aliases = []
    source.force_truncate_aliases = True
    result = await Identity360Provider(source).read("tenant-a", "entity", "entity-1")
    assert result.slot("identity_evidence").state == "truncated"
    assert result.slot("identity_evidence").truncated is True


@pytest.mark.asyncio
async def test_agent_subject_requires_canonical_agent_entity_type() -> None:
    source = FakeIdentity360Source()
    source.entity = {**source.entity, "entity_type": "human"}

    result = await Identity360Provider(source).read("tenant-a", "agent", "entity-1")

    assert result.slot("resolved_subject_identity").state == "unknown"
    assert result.slot("actor_and_agent_binding").content["state"] == "unknown"


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
    assert result.slot("source_identifier_lineage").state == "suppressed"
    assert result.slot("identity_evidence").state == "suppressed"
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

    resolved = result.slot("resolved_subject_identity")
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
