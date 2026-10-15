"""Resolution replay invariants (Identity Assurance).

Replay is a thin, idempotent wrapper over the EXISTING resolver: when verified
ownership evidence arrives it re-runs resolution for the affected identifier
component and (policy permitting) repairs historical fragmentation. These tests
assert the two properties that make replay safe to trigger from evidence:
  * it re-runs the resolver and reports the resulting decision + affected set;
  * it is idempotent — a duplicate trigger never double-merges or duplicates
    aliases (blueprint §31).
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
from identity.identity.audit import IdentityAuditWriter  # noqa: E402
from identity.identity.conflicts import IdentityConflictManager  # noqa: E402
from identity.identity.graph_writer import IdentityGraphWriter  # noqa: E402
from identity.identity.hashing import hash_email  # noqa: E402
from identity.identity.metrics import IdentityMetrics  # noqa: E402
from identity.identity.models import (  # noqa: E402
    ConfidenceTier,
    EntityType,
    IdentitySignalType,
    MergeDecision,
)
from identity.identity.repository import IdentityResolutionRepository  # noqa: E402
from identity.identity.resolution_replay import ResolutionReplayService  # noqa: E402
from identity.identity.decision_evidence import IdentityDecisionEvidenceRepository  # noqa: E402
from identity.identity.merge_policy import MergePolicyResult, evaluate  # noqa: E402
from identity.identity.resolver import IdentityResolutionService  # noqa: E402

TENANT = "tenant_replay"
LINK_CONSENT = {"purposes": {"identity": True}}


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


def _build_resolver():
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


async def _make_two_email_fragments(repo, tenant, email):
    email_hash = hash_email(email, tenant)
    e1 = str(uuid.uuid4())
    e2 = str(uuid.uuid4())
    await repo.create_subject(tenant, e1, EntityType.ANONYMOUS_VISITOR)
    await repo.create_subject(tenant, e2, EntityType.ANONYMOUS_VISITOR)
    for eid, ts in ((e1, "2000-01-01T00:00:00+00:00"), (e2, "2030-01-01T00:00:00+00:00")):
        row = await repo.get_subject_by_canonical_entity_id(tenant, eid)
        row["first_seen_at"] = ts
        row["created_at"] = ts
        await repo._subjects.update(row["id"], row)
    for eid in (e1, e2):
        await repo.upsert_alias(
            tenant, eid, IdentitySignalType.EMAIL_HASH, email_hash,
            confidence_tier=ConfidenceTier.STRONG,
        )
    return e1, e2, email_hash


@pytest.mark.asyncio
async def test_replay_reruns_resolver_and_reports_affected():
    resolver, repo = _build_resolver()
    e1, e2, email_hash = await _make_two_email_fragments(repo, TENANT, "replay@example.com")

    replay = ResolutionReplayService(resolver=resolver, repo=repo)
    res = await replay.request_replay(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=email_hash,
        trigger_type="verification_evidence",
        trigger_id="ev-1",
        consent_snapshot=LINK_CONSENT,
    )

    assert res["status"] == "complete"
    assert res["decision"] == "merge"
    assert set(res["affected"]) == {e1, e2}
    assert res["idempotent"] is False


@pytest.mark.asyncio
async def test_replay_is_idempotent_no_double_merge_or_duplicate_alias():
    resolver, repo = _build_resolver()
    e1, e2, email_hash = await _make_two_email_fragments(repo, TENANT, "idem@example.com")

    replay = ResolutionReplayService(resolver=resolver, repo=repo)
    first = await replay.request_replay(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=email_hash,
        trigger_type="verification_evidence",
        trigger_id="ev-idem",
        consent_snapshot=LINK_CONSENT,
    )
    assert first["decision"] == "merge"

    # Same trigger id + policy version → a completed job is never re-run.
    second = await replay.request_replay(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=email_hash,
        trigger_type="verification_evidence",
        trigger_id="ev-idem",
        consent_snapshot=LINK_CONSENT,
    )
    assert second["status"] == "noop"
    assert second["idempotent"] is True

    # Exactly one survivor; the other stays tombstoned once.
    assert (await repo.get_subject_by_canonical_entity_id(TENANT, e1))["status"] == "active"
    assert (await repo.get_subject_by_canonical_entity_id(TENANT, e2))["status"] == "merged"

    # No duplicate verified alias on the survivor.
    aliases = await repo.get_aliases_for_entity(TENANT, e1)
    verified = [
        a for a in aliases
        if a.get("alias_type") == IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED.value
        and not a.get("revoked_at")
    ]
    assert len(verified) == 1


@pytest.mark.asyncio
async def test_replay_unknown_identifier_type_errors_without_raising():
    resolver, repo = _build_resolver()
    replay = ResolutionReplayService(resolver=resolver, repo=repo)
    res = await replay.request_replay(
        tenant_id=TENANT,
        identifier_type="passport",
        identifier_hash="abc",
        trigger_type="verification_evidence",
        trigger_id="ev-bad",
        consent_snapshot=LINK_CONSENT,
    )
    assert res["status"] == "error"


@pytest.mark.asyncio
async def test_policy_version_is_executable_and_same_decision_does_not_restate_graph():
    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    evaluated_versions = []

    def v110_policy(ctx):
        evaluated_versions.append(list(ctx.existing_entity_ids))
        return evaluate(ctx)

    resolver = IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
        policy_evaluators={"1.1.0": v110_policy},
    )
    e1, e2, email_hash = await _make_two_email_fragments(repo, TENANT, "versioned@example.com")
    replay = ResolutionReplayService(resolver=resolver, repo=repo)

    first = await replay.request_replay(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=email_hash,
        trigger_type="verification_evidence",
        trigger_id="ev-policy-version",
        consent_snapshot=LINK_CONSENT,
        policy_version="1.0.0",
    )
    assert first["status"] == "complete"
    assert first["decision"] == "merge"

    subjects_before = {
        eid: await repo.get_subject_by_canonical_entity_id(TENANT, eid)
        for eid in (e1, e2)
    }
    edges_before = await repo.get_entity_graph(TENANT, e1)
    merge_rows_before = await repo._merges.find_many(filters={"tenant_id": TENANT}, limit=100)

    upgraded = await replay.request_replay(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=email_hash,
        trigger_type="verification_evidence",
        trigger_id="ev-policy-version",
        consent_snapshot=LINK_CONSENT,
        policy_version="1.1.0",
    )
    assert upgraded["status"] == "complete"
    assert upgraded["policy_version"] == "1.1.0"
    assert upgraded["restatement_status"] == "not_required"
    assert upgraded["restatement_job_id"] is None
    assert evaluated_versions  # the registered 1.1.0 evaluator ran
    assert subjects_before == {
        eid: await repo.get_subject_by_canonical_entity_id(TENANT, eid)
        for eid in (e1, e2)
    }
    assert edges_before == await repo.get_entity_graph(TENANT, e1)
    assert merge_rows_before == await repo._merges.find_many(filters={"tenant_id": TENANT}, limit=100)

    evidence = IdentityDecisionEvidenceRepository()
    rows = await evidence.list_for_entity(TENANT, e1)
    assert any(row.get("merge_policy_version") == "1.1.0" for row in rows)
    job = await replay._jobs.find_by_id(f"{TENANT}:ev-policy-version:1.1.0")
    assert job["policy_version"] == "1.1.0"
    assert job["summary"]["policy_version"] == "1.1.0"


@pytest.mark.asyncio
async def test_unknown_policy_version_fails_closed_without_mutating_graph():
    resolver, repo = _build_resolver()
    e1, e2, email_hash = await _make_two_email_fragments(repo, TENANT, "unknown-policy@example.com")
    replay = ResolutionReplayService(resolver=resolver, repo=repo)

    result = await replay.request_replay(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=email_hash,
        trigger_type="verification_evidence",
        trigger_id="ev-unsupported-policy",
        consent_snapshot=LINK_CONSENT,
        policy_version="9.9.9",
    )

    assert result["status"] == "error"
    assert "unsupported policy_version" in result["error"]
    assert (await repo.get_subject_by_canonical_entity_id(TENANT, e1))["status"] == "active"
    assert (await repo.get_subject_by_canonical_entity_id(TENANT, e2))["status"] == "active"
    assert not await repo._merges.find_many(filters={"tenant_id": TENANT}, limit=100)


@pytest.mark.asyncio
async def test_new_policy_version_applies_graph_change_only_when_its_decision_changes():
    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    decisions = []

    def review_policy(ctx):
        decisions.append("1.0.0")
        result = evaluate(ctx)
        return MergePolicyResult(
            decision=MergeDecision.CANDIDATE,
            confidence=result.confidence,
            confidence_tier=result.confidence_tier,
            reason_codes=[*result.reason_codes, "policy_requires_review"],
        )

    def merge_policy_v2(ctx):
        decisions.append("1.1.0")
        return evaluate(ctx)

    resolver = IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
        policy_evaluators={"1.0.0": review_policy, "1.1.0": merge_policy_v2},
    )
    e1, e2, email_hash = await _make_two_email_fragments(repo, TENANT, "policy-change@example.com")
    replay = ResolutionReplayService(resolver=resolver, repo=repo)
    base = await replay.request_replay(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=email_hash,
        trigger_type="verification_evidence",
        trigger_id="ev-policy-change",
        consent_snapshot=LINK_CONSENT,
        policy_version="1.0.0",
    )
    assert base["status"] == "complete"
    assert base["decision"] == "candidate"
    assert (await repo.get_subject_by_canonical_entity_id(TENANT, e1))["status"] == "active"
    assert (await repo.get_subject_by_canonical_entity_id(TENANT, e2))["status"] == "active"
    assert not await repo._merges.find_many(filters={"tenant_id": TENANT}, limit=100)

    changed = await replay.request_replay(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=email_hash,
        trigger_type="verification_evidence",
        trigger_id="ev-policy-change",
        consent_snapshot=LINK_CONSENT,
        policy_version="1.1.0",
    )
    assert changed["status"] == "complete"
    assert changed["decision"] == "merge"
    assert changed["restatement_status"] == "queued"
    assert changed["restatement_job_id"]
    assert decisions == ["1.0.0", "1.1.0"]
    assert (await repo.get_subject_by_canonical_entity_id(TENANT, e1))["status"] == "active"
    assert (await repo.get_subject_by_canonical_entity_id(TENANT, e2))["status"] == "merged"
    assert await repo._merges.find_many(filters={"tenant_id": TENANT}, limit=100)
    assert changed["policy_version"] == "1.1.0"


@pytest.mark.asyncio
async def test_replay_trigger_cannot_be_reused_for_different_evidence():
    resolver, repo = _build_resolver()
    _, _, email_hash = await _make_two_email_fragments(repo, TENANT, "bound-evidence@example.com")
    replay = ResolutionReplayService(resolver=resolver, repo=repo)
    args = dict(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=email_hash,
        trigger_type="verification_evidence",
        trigger_id="ev-bound-evidence",
        consent_snapshot=LINK_CONSENT,
    )
    first = await replay.request_replay(**args)
    assert first["status"] == "complete"

    second = await replay.request_replay(**{**args, "identifier_hash": "different-hash"})
    assert second["status"] == "error"
    assert second["error"] == "trigger_id_reused_with_different_evidence"
