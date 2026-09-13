"""Tests for identity resolution repository — in-memory backend."""
from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.identity.repository import IdentityResolutionRepository

TENANT = "tenant_test"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


@pytest.fixture
def repo() -> IdentityResolutionRepository:
    return IdentityResolutionRepository()


# ── Subject (entity) creation ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_subject(repo):
    entity = await repo.create_subject(
        tenant_id=TENANT,
        canonical_entity_id="entity_1",
        entity_type="user",
    )
    assert entity["canonical_entity_id"] == "entity_1"
    assert entity["tenant_id"] == TENANT
    assert entity["status"] == "active"


@pytest.mark.asyncio
async def test_get_subject_by_entity_id(repo):
    await repo.create_subject(TENANT, "entity_1", "user")
    result = await repo.get_subject_by_entity_id(TENANT, "entity_1")
    assert result is not None
    assert result["canonical_entity_id"] == "entity_1"


@pytest.mark.asyncio
async def test_get_subject_tenant_isolated(repo):
    await repo.create_subject(TENANT, "entity_1", "user")
    result = await repo.get_subject_by_entity_id("other_tenant", "entity_1")
    assert result is None


# ── Alias upsert (idempotent) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_alias_creates(repo):
    alias = await repo.upsert_alias(
        tenant_id=TENANT,
        canonical_entity_id="entity_1",
        alias_type="user_id",
        alias_hash="hash_abc",
        alias_display_value_redacted="u_abc",
        source="sdk",
        confidence=1.0,
        confidence_tier="deterministic",
    )
    assert alias["alias_value_hash"] == "hash_abc"


@pytest.mark.asyncio
async def test_upsert_alias_idempotent(repo):
    kwargs = dict(
        tenant_id=TENANT,
        canonical_entity_id="entity_1",
        alias_type="user_id",
        alias_hash="hash_abc",
        alias_display_value_redacted="u_abc",
        source="sdk",
        confidence=1.0,
        confidence_tier="deterministic",
    )
    alias1 = await repo.upsert_alias(**kwargs)
    alias2 = await repo.upsert_alias(**kwargs)
    assert alias1["id"] == alias2["id"]


@pytest.mark.asyncio
async def test_alias_tenant_isolated(repo):
    await repo.upsert_alias(TENANT, "entity_1", "user_id", "hash_abc", "u", "sdk", 1.0, "deterministic")
    results = await repo.get_aliases_for_entity("other_tenant", "entity_1")
    assert results == []


@pytest.mark.asyncio
async def test_get_aliases_for_entity(repo):
    await repo.upsert_alias(TENANT, "entity_1", "user_id", "hash_abc", "u", "sdk", 1.0, "deterministic")
    await repo.upsert_alias(TENANT, "entity_1", "email_hash", "hash_email", "e", "sdk", 0.85, "strong")
    aliases = await repo.get_aliases_for_entity(TENANT, "entity_1")
    assert len(aliases) == 2


# ── Entity lookup by alias ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_entities_by_alias(repo):
    await repo.upsert_alias(TENANT, "entity_1", "user_id", "hash_abc", "u", "sdk", 1.0, "deterministic")
    entities = await repo.find_entities_by_alias(TENANT, "user_id", "hash_abc")
    assert "entity_1" in entities


@pytest.mark.asyncio
async def test_find_entities_by_alias_cross_tenant_empty(repo):
    await repo.upsert_alias(TENANT, "entity_1", "user_id", "hash_abc", "u", "sdk", 1.0, "deterministic")
    entities = await repo.find_entities_by_alias("other_tenant", "user_id", "hash_abc")
    assert entities == []


# ── Audit records (append-only) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_audit_record(repo):
    record = await repo.create_audit_record(
        tenant_id=TENANT,
        decision="merge",
        canonical_entity_id="entity_1",
        candidate_entity_ids=["entity_2"],
        confidence=1.0,
        confidence_tier="deterministic",
        reason_codes=["same_user_id"],
        source_event_ids=["evt_001"],
        policy_result="merge",
        consent_snapshot=None,
    )
    assert record["decision"] == "merge"
    assert record["tenant_id"] == TENANT


@pytest.mark.asyncio
async def test_get_audit_for_entity(repo):
    await repo.create_audit_record(TENANT, "merge", "entity_1", [], 1.0, "deterministic", [], [], "merge", None)
    records = await repo.get_audit_for_entity(TENANT, "entity_1")
    assert len(records) >= 1


# ── Conflict management ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_conflict(repo):
    conflict = await repo.create_conflict(
        tenant_id=TENANT,
        candidate_entity_ids=["entity_1", "entity_2"],
        candidate_aliases=[],
        conflict_type="ambiguous_match",
        confidence=0.7,
        reason_codes=["conflicting_alias"],
    )
    assert conflict["status"] == "open"


@pytest.mark.asyncio
async def test_get_open_conflicts(repo):
    await repo.create_conflict(TENANT, ["e1", "e2"], [], "ambiguous_match", 0.7, [])
    conflicts = await repo.get_conflicts(TENANT, status="open")
    assert len(conflicts) >= 1


@pytest.mark.asyncio
async def test_resolve_conflict(repo):
    conflict = await repo.create_conflict(TENANT, ["e1", "e2"], [], "ambiguous_match", 0.7, [])
    resolved = await repo.resolve_conflict(conflict["id"], "operator_x", TENANT)
    assert resolved is not None
    assert resolved["status"] == "resolved"


# ── Health aggregates ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_identity_health_returns_counts(repo):
    health = await repo.get_identity_health(TENANT)
    assert "total_entities" in health
    assert "total_aliases" in health
    assert "open_conflicts" in health
