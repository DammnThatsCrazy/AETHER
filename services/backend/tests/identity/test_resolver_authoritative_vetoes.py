"""Resolver hard vetoes are populated from tenant-owned candidate state."""

from __future__ import annotations

import os
import sys
import uuid

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.audit import IdentityAuditWriter  # noqa: E402
from services.identity.conflicts import IdentityConflictManager  # noqa: E402
from services.identity.graph_writer import IdentityGraphWriter  # noqa: E402
from services.identity.hashing import hash_email  # noqa: E402
from services.identity.metrics import IdentityMetrics  # noqa: E402
from services.identity.models import ConfidenceTier, EntityType, IdentitySignalType  # noqa: E402
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.identity.resolver import IdentityResolutionService  # noqa: E402


TENANT = "tenant_resolver_authoritative_vetoes"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


def _build_resolver():
    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    service = IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
    )
    return service, repo


async def _candidate(repo, *, email: str, entity_type: EntityType, status: str = "active") -> str:
    canonical_id = str(uuid.uuid4())
    row = await repo.create_subject(TENANT, canonical_id, entity_type)
    if status != "active":
        row["status"] = status
        await repo._subjects.update(row["id"], row)
    await repo.upsert_alias(
        TENANT,
        canonical_id,
        IdentitySignalType.EMAIL_HASH,
        hash_email(email, TENANT),
        confidence_tier=ConfidenceTier.STRONG,
        consent_snapshot={"purposes": {"identity": True}},
    )
    return canonical_id


def _event(email: str, *, event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "user_id": "sdk-person-user",
        # This caller field must not override candidate entity kind.
        "entity_type": "person",
        "properties": {"email": email},
        "context": {"consent": {"purposes": {"identity": True}}},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["deleted", "suppressed"])
async def test_resolver_blocks_authoritative_deleted_or_suppressed_subject(status):
    resolver, repo = _build_resolver()
    candidate_id = await _candidate(
        repo, email=f"{status}@example.com", entity_type=EntityType.HUMAN, status=status,
    )

    result = await resolver.resolve_event(_event(f"{status}@example.com"), TENANT)

    assert result.decision.value == "blocked"
    assert "veto_blocked" in result.reason_codes
    assert result.canonical_entity_id == candidate_id
    assert await repo._merges.find_many(filters={"tenant_id": TENANT}, limit=10) == []


@pytest.mark.asyncio
async def test_resolver_blocks_person_signal_matching_agent_subject():
    resolver, repo = _build_resolver()
    agent_id = await _candidate(
        repo, email="agent-mailbox@example.com", entity_type=EntityType.AGENT,
    )

    result = await resolver.resolve_event(_event("agent-mailbox@example.com"), TENANT)

    assert result.decision.value == "blocked"
    assert "veto_blocked" in result.reason_codes
    assert result.canonical_entity_id == agent_id
    assert await repo._merges.find_many(filters={"tenant_id": TENANT}, limit=10) == []


@pytest.mark.asyncio
async def test_resolver_fails_closed_when_candidate_alias_state_lookup_fails(monkeypatch):
    resolver, repo = _build_resolver()
    candidate_id = await _candidate(
        repo, email="lookup-failure@example.com", entity_type=EntityType.HUMAN,
    )

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("repository unavailable")

    monkeypatch.setattr(repo, "get_aliases_for_entity", unavailable)
    result = await resolver.resolve_event(_event("lookup-failure@example.com"), TENANT)

    assert result.decision.value == "blocked"
    assert "candidate_state_unavailable" in result.reason_codes
    assert result.canonical_entity_id == candidate_id
    assert await repo._merges.find_many(filters={"tenant_id": TENANT}, limit=10) == []


@pytest.mark.asyncio
async def test_resolver_detects_revoked_alias_even_without_an_active_candidate():
    resolver, repo = _build_resolver()
    candidate_id = await _candidate(
        repo, email="revoked-alias@example.com", entity_type=EntityType.HUMAN,
    )
    aliases = await repo.get_aliases_for_entity(TENANT, candidate_id)
    assert len(aliases) == 1
    await repo.revoke_alias(aliases[0]["id"])

    result = await resolver.resolve_event(_event("revoked-alias@example.com"), TENANT)

    assert result.decision.value == "blocked"
    assert "veto_blocked" in result.reason_codes
    assert "revoked_alias" in result.reason_codes
    assert await repo._merges.find_many(filters={"tenant_id": TENANT}, limit=10) == []
