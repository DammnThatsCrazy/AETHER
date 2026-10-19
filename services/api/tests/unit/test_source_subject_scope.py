from __future__ import annotations

import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from identity.identity.identity360_provider import Identity360Provider, IdentityRecordRead
from identity.identity.source_subject_scope import RepositorySourceSubjectScopeReader


class _IdentitySource:
    def __init__(self, *, source_tenant: str = "tenant-a", status: str = "resolved") -> None:
        self.source = {
            "id": "source-1",
            "tenant_id": source_tenant,
            "source_kind": "connector",
            "source_namespace": "crm:contacts",
            "canonical_entity_id": "entity-1",
            "status": status,
            "external_id": "sensitive-source-id",
        }
        self.calls: list[str] = []

    async def source_identity(self, tenant_id: str, source_identity_id: str):
        self.calls.append("source")
        if source_identity_id != "source-1":
            return IdentityRecordRead(record=None)
        return IdentityRecordRead(record=self.source)

    async def canonical_entity(self, tenant_id: str, entity_id: str):
        self.calls.append("entity")
        return IdentityRecordRead(
            record={
                "entity_id": entity_id,
                "tenant_id": "tenant-a",
                "entity_type": "human",
                "status": "active",
            }
        )

    async def identity_subject(self, tenant_id: str, entity_id: str):
        self.calls.append("identity_subject")
        return IdentityRecordRead(
            record={
                "id": "identity-subject-1",
                "tenant_id": "tenant-a",
                "canonical_entity_id": entity_id,
                "entity_type": "human",
                "status": "active",
            }
        )


@pytest.mark.asyncio
async def test_source_scope_requires_resolved_exact_identity360_join() -> None:
    source = _IdentitySource()
    scope = await RepositorySourceSubjectScopeReader(Identity360Provider(source)).resolve(
        "tenant-a", "source-1"
    )

    assert scope.state == "available"
    assert scope.canonical_entity_id == "entity-1"
    assert scope.tenant_id == "tenant-a"
    assert scope.source_identity_id == "source-1"
    assert {ref.source for ref in scope.evidence_refs} >= {
        "identity_source_identities",
        "entity_registry",
        "identity_subjects",
    }
    assert "sensitive-source-id" not in repr(scope)


@pytest.mark.asyncio
async def test_source_scope_rejects_unresolved_link_even_when_entity_id_is_present() -> None:
    source = _IdentitySource(status="provisional")
    scope = await RepositorySourceSubjectScopeReader(Identity360Provider(source)).resolve(
        "tenant-a", "source-1"
    )

    assert scope.state == "unknown"
    assert scope.canonical_entity_id is None
    assert "entity" not in source.calls


@pytest.mark.asyncio
async def test_source_scope_rejects_cross_tenant_record_before_join() -> None:
    source = _IdentitySource(source_tenant="tenant-b")
    scope = await RepositorySourceSubjectScopeReader(Identity360Provider(source)).resolve(
        "tenant-a", "source-1"
    )

    assert scope.state == "unknown"
    assert scope.canonical_entity_id is None
    assert source.calls == ["source"]
