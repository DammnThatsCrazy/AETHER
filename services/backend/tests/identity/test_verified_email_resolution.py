"""Verified-email deterministic resolution invariants (Identity Assurance).

Covers the resolver-side semantics added for verified email ownership:
  * verified email MERGES previously-fragmented entities that share the email
    hash, choosing the OLDEST entity as survivor (blueprint §25);
  * a client-supplied ``email_verified`` flag is NOT trusted as proof (§11);
  * a contradictory deterministic identifier turns the merge into a CANDIDATE
    conflict rather than a silent merge (§24);
  * without identity-linking consent, verified email does NOT merge (§40);
  * a suppressed email identifier blocks the merge outright (§41).

The two-fragment precondition (two active entities that both carry the same
observed email alias) is constructed directly through the repository — the
deterministic, backend-owned state the verification pipeline later reconciles.
"""
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
from services.identity.models import (  # noqa: E402
    ConfidenceTier,
    EntityType,
    IdentitySignalType,
)
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.identity.resolution_replay import ResolutionReplayService  # noqa: E402
from services.identity.resolver import IdentityResolutionService  # noqa: E402
from services.identity.signals import extract_signals  # noqa: E402

TENANT = "tenant_verified_email"
LINK_CONSENT = {"purposes": {"identity": True}}


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


def _build_resolver() -> tuple[IdentityResolutionService, IdentityResolutionRepository]:
    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    resolver = IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
    )
    return resolver, repo


async def _set_first_seen(repo, tenant, entity_id, ts):
    row = await repo.get_subject_by_canonical_entity_id(tenant, entity_id)
    row["first_seen_at"] = ts
    row["created_at"] = ts
    await repo._subjects.update(row["id"], row)


async def _make_two_email_fragments(repo, tenant, email):
    """Two ACTIVE entities that both carry the same observed email alias.

    ``e1`` is made unambiguously older so survivor selection is deterministic.
    """
    email_hash = hash_email(email, tenant)
    e1 = str(uuid.uuid4())
    e2 = str(uuid.uuid4())
    await repo.create_subject(tenant, e1, EntityType.ANONYMOUS_VISITOR)
    await repo.create_subject(tenant, e2, EntityType.ANONYMOUS_VISITOR)
    await _set_first_seen(repo, tenant, e1, "2000-01-01T00:00:00+00:00")
    await _set_first_seen(repo, tenant, e2, "2030-01-01T00:00:00+00:00")
    await repo.upsert_alias(
        tenant, e1, IdentitySignalType.EMAIL_HASH, email_hash,
        confidence_tier=ConfidenceTier.STRONG,
    )
    await repo.upsert_alias(
        tenant, e2, IdentitySignalType.EMAIL_HASH, email_hash,
        confidence_tier=ConfidenceTier.STRONG,
    )
    return e1, e2, email_hash


async def _status(repo, tenant, entity_id) -> str:
    row = await repo.get_subject_by_canonical_entity_id(tenant, entity_id)
    return (row or {}).get("status", "")


# ── Core merge ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verified_email_merges_fragments_into_oldest_survivor():
    resolver, repo = _build_resolver()
    e1, e2, email_hash = await _make_two_email_fragments(repo, TENANT, "merge@example.com")

    replay = ResolutionReplayService(resolver=resolver, repo=repo)
    res = await replay.request_replay(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=email_hash,
        trigger_type="verification_evidence",
        trigger_id="ev-merge",
        consent_snapshot=LINK_CONSENT,
    )

    assert res["status"] == "complete"
    assert res["decision"] == "merge"
    # Oldest entity survives (blueprint §25); the newer one is tombstoned.
    assert res["canonical_entity_id"] == e1
    assert await _status(repo, TENANT, e1) == "active"
    assert await _status(repo, TENANT, e2) == "merged"
    assert await repo.resolve_surviving_canonical_entity_id(TENANT, e2) == e1

    # The survivor carries a resolution revision bump so downstream can restate.
    survivor = await repo.get_subject_by_canonical_entity_id(TENANT, e1)
    assert int(survivor.get("resolution_revision") or 0) >= 1


# ── Client claim is never trusted ─────────────────────────────────────────────

def test_client_email_verified_flag_is_not_trusted_as_proof():
    signals = extract_signals(
        {
            "event_id": "evt",
            "properties": {"email": "user@example.com", "email_verified": True},
        },
        TENANT,
    )
    types = {s.type for s in signals}
    assert IdentitySignalType.EMAIL_HASH in types
    # A client-asserted verified flag must never become verified evidence.
    assert IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED not in types


# ── Conflicting deterministic identity → candidate, not merge ────────────────

@pytest.mark.asyncio
async def test_verified_email_with_conflicting_user_ids_is_candidate():
    resolver, repo = _build_resolver()
    e1, e2, email_hash = await _make_two_email_fragments(repo, TENANT, "shared@example.com")
    # Contradictory deterministic identifiers: the mailbox maps to two users.
    await repo.upsert_alias(
        TENANT, e1, IdentitySignalType.USER_ID, "userhash-1",
        confidence_tier=ConfidenceTier.DETERMINISTIC,
    )
    await repo.upsert_alias(
        TENANT, e2, IdentitySignalType.USER_ID, "userhash-2",
        confidence_tier=ConfidenceTier.DETERMINISTIC,
    )

    replay = ResolutionReplayService(resolver=resolver, repo=repo)
    res = await replay.request_replay(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=email_hash,
        trigger_type="verification_evidence",
        trigger_id="ev-conflict",
        consent_snapshot=LINK_CONSENT,
    )

    assert res["decision"] == "candidate"
    assert "conflicting_verified_identifier" in res["reason_codes"]
    assert await _status(repo, TENANT, e1) == "active"
    assert await _status(repo, TENANT, e2) == "active"


# ── Consent gate ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verified_email_without_consent_does_not_merge():
    resolver, repo = _build_resolver()
    e1, e2, email_hash = await _make_two_email_fragments(repo, TENANT, "noconsent@example.com")

    replay = ResolutionReplayService(resolver=resolver, repo=repo)
    res = await replay.request_replay(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=email_hash,
        trigger_type="verification_evidence",
        trigger_id="ev-noconsent",
        consent_snapshot=None,
    )

    assert res["decision"] != "merge"
    assert await _status(repo, TENANT, e1) == "active"
    assert await _status(repo, TENANT, e2) == "active"


# ── Suppression overrides verification ────────────────────────────────────────

@pytest.mark.asyncio
async def test_suppressed_email_blocks_verified_merge():
    resolver, repo = _build_resolver()
    e1, e2, email_hash = await _make_two_email_fragments(repo, TENANT, "suppress@example.com")
    await repo.create_suppression_rule(
        tenant_id=TENANT,
        identifier_hash=email_hash,
        identifier_type=IdentitySignalType.EMAIL_HASH.value,
        reason="test suppression",
        created_by="operator",
    )

    replay = ResolutionReplayService(resolver=resolver, repo=repo)
    res = await replay.request_replay(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=email_hash,
        trigger_type="verification_evidence",
        trigger_id="ev-suppressed",
        consent_snapshot=LINK_CONSENT,
    )

    assert res["decision"] != "merge"
    assert await _status(repo, TENANT, e1) == "active"
    assert await _status(repo, TENANT, e2) == "active"
