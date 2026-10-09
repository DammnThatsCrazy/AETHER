"""Phase 9 recovery proofs for identity split and suppressed evidence.

These tests exercise the real repository, resolver, graph writer, audit writer,
restatement queue and source-identity registry. They prove durable outcomes;
they do not substitute policy stubs for identity state transitions.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.audit import IdentityAuditWriter  # noqa: E402
from services.identity.conflicts import IdentityConflictManager  # noqa: E402
from services.identity.graph_writer import IdentityGraphWriter  # noqa: E402
from services.identity.hashing import hash_email  # noqa: E402
from services.identity.import_candidate_adapter import ImportIdentityCandidateAdapter  # noqa: E402
from services.identity.metrics import IdentityMetrics  # noqa: E402
from services.identity.models import ConfidenceTier, IdentitySignalType  # noqa: E402
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.identity.resolver import IdentityResolutionService  # noqa: E402
from services.identity.source_identity_registry import SourceIdentityRegistry  # noqa: E402

TENANT = "tenant_phase9_recovery"
FIXTURES = Path(__file__).resolve().parents[4] / "packages/proof-fixtures/fixtures/identity"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


def _resolver(repo: IdentityResolutionRepository) -> IdentityResolutionService:
    metrics = IdentityMetrics()
    return IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
    )


def _fixture(name: str) -> dict:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert data["_fixture_version"] == 1
    return data


@pytest.mark.asyncio
async def test_bad_merge_split_restores_fragment_and_queues_restatement():
    """A real merge can be repaired while retaining evidence and audit lineage."""
    fixture = _fixture("scenario_c_bad_merge_split.json")
    tenant_id = TENANT
    repo = IdentityResolutionRepository()
    resolver = _resolver(repo)
    survivor = f"survivor-{uuid.uuid4().hex}"
    merged_fragment = f"fragment-{uuid.uuid4().hex}"
    email_hash = hash_email(f"split-{uuid.uuid4().hex}@example.test", tenant_id)
    await repo.create_subject(tenant_id, survivor)
    await repo.create_subject(tenant_id, merged_fragment)
    alias = await repo.upsert_alias(
        tenant_id=tenant_id,
        canonical_entity_id=survivor,
        alias_type=IdentitySignalType.EMAIL_HASH,
        alias_value_hash=email_hash,
        alias_display_value_redacted="[REDACTED:email]",
        confidence_tier=ConfidenceTier.STRONG,
        source="proof_fixture",
        source_event_id="historical-fragment-event",
    )

    merge = await resolver.operator_merge(
        tenant_id=tenant_id,
        primary_entity_id=survivor,
        secondary_entity_id=merged_fragment,
        actor_id="phase9-proof-operator",
        reason="proof fixture: intentionally incorrect historical merge",
    )
    assert merge.decision.value == "merge"
    assert (await repo.get_subject_by_canonical_entity_id(tenant_id, merged_fragment))["status"] == "merged"
    merge_rows = await repo.get_merge_history(tenant_id, survivor)
    merge_row = next(row for row in merge_rows if row["from_entity_id"] == merged_fragment)

    split = await resolver.fragment_split(
        tenant_id=tenant_id,
        entity_id=survivor,
        fragments={"alias_ids": [alias["id"]], "observation_ids": []},
        mode="restore_pre_merge_entity",
        actor_id="phase9-proof-operator",
        reason="repair bad merge from fixture scenario C",
        source_merge_event_id=merge_row["id"],
    )

    assert split["allowed"] is True
    assert split["resulting_entity_id"] == merged_fragment
    assert split["moved_alias_ids"]
    assert split["restatement_status"] == "queued"
    assert split["restatement_job_id"]
    restored = await repo.get_subject_by_canonical_entity_id(tenant_id, merged_fragment)
    assert restored["status"] == "active"
    assert restored.get("merged_into_entity_id") is None
    assert await repo.resolve_surviving_canonical_entity_id(tenant_id, merged_fragment) == merged_fragment

    source_aliases = await repo.find_aliases_by_signal(tenant_id, IdentitySignalType.EMAIL_HASH, email_hash)
    live_aliases = [row for row in source_aliases if not row.get("revoked_at")]
    assert len(live_aliases) == 1
    assert live_aliases[0]["canonical_entity_id"] == merged_fragment
    split_rows = await repo.get_split_history(tenant_id, survivor)
    assert len(split_rows) == 1
    assert split_rows[0]["source_merge_event_id"] == merge_row["id"]
    assert split_rows[0]["fragment"]["alias_ids"] == [alias["id"]]
    from services.jobs.service import get_jobs_service

    queued = await get_jobs_service().get_job(tenant_id, split["restatement_job_id"])
    assert queued and queued["tenant_id"] == tenant_id and queued["status"] == "queued"
    assert fixture["expected"]["raw_records_preserved"] is True


@pytest.mark.asyncio
async def test_suppressed_import_evidence_cannot_be_reactivated_or_candidate_bound():
    """Reimport/lookup of a suppressed source never revives its identity claim."""
    fixture = _fixture("scenario_deleted_identity_suppression.json")
    repo = IdentityResolutionRepository()
    registry = SourceIdentityRegistry(repo)
    resolver = _resolver(repo)
    raw_email = f"suppressed-{uuid.uuid4().hex}@example.test"
    source = await registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="csv_import",
        source_kind="csv",
        source_namespace="csv:contacts",
        external_id=f"row-{uuid.uuid4().hex}",
    )
    deleted_profile_id = await registry.ensure_provisional_profile(
        tenant_id=TENANT, source_identity_id=source.id
    )
    await registry.upsert_identity_claim(
        tenant_id=TENANT,
        source_identity_id=source.id,
        claim_type="email",
        raw_value=raw_email,
        verification_status="observed",
    )
    await registry.mark_suppressed(source.id, reason="data subject deletion")
    email_digest = hash_email(raw_email, TENANT)
    assert await repo.check_suppression(
        TENANT, IdentitySignalType.EMAIL_HASH.value, email_digest
    )

    # The idempotent source registration path returns the same row and must
    # preserve suppression. Claim capture can be retried by an import worker,
    # but the candidate adapter must continue to ignore the suppressed source.
    same_source = await registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="csv_import",
        source_kind="csv",
        source_namespace="csv:contacts",
        external_id=source.external_id,
    )
    assert same_source.id == source.id
    assert same_source.status == "suppressed"
    await registry.upsert_identity_claim(
        tenant_id=TENANT,
        source_identity_id=source.id,
        claim_type="email",
        raw_value=raw_email,
        verification_status="observed",
    )
    claims = await repo.get_claims_for_source(source.id)
    assert claims and all(claim["status"] == "suppressed" for claim in claims)

    candidate = await ImportIdentityCandidateAdapter(repo).evaluate(
        tenant_id=TENANT, claims={"email": raw_email}
    )
    assert candidate.outcome == "no_match"
    assert candidate.candidate_source_identity_ids == []

    # A fresh live event carrying the suppressed identifier may create an
    # isolated entity, but it cannot bind to the deleted imported profile or
    # restore an alias that suppression revoked.
    result = await resolver.resolve_event({
        "event_id": f"post-delete-{uuid.uuid4().hex}",
        "user_id": f"sdk-user-{uuid.uuid4().hex}",
        "properties": {"email": raw_email},
        "context": {"consent": {"purposes": {"identity": True}}},
    }, TENANT)
    assert result.canonical_entity_id
    assert result.canonical_entity_id != deleted_profile_id
    assert result.decision.value in {"create", "blocked", "candidate"}
    email_aliases = await repo.find_aliases_by_signal(
        TENANT, IdentitySignalType.EMAIL_HASH, email_digest
    )
    assert not [row for row in email_aliases if not row.get("revoked_at")]
    assert await repo.check_suppression(
        TENANT, IdentitySignalType.EMAIL_HASH.value, email_digest
    )
    assert fixture["expected"]["source_stays_suppressed"] is True
    assert fixture["expected"]["claims_stay_suppressed"] is True
    assert fixture["expected"]["suppression_blocks_alias_resurrection"] is True
