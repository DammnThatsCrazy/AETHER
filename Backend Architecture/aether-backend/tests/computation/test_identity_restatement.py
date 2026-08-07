"""Section 17 — identity merge restatement + evidence semantics.

Two properties are proven here:

1. The AUTOMATIC in-line resolver merge (services/identity/resolver.py, the
   step-10 merge execution reached during ingestion) now publishes
   ``Topic.IDENTITY_MERGED`` — the same event the operator merge route
   (services/identity/routes.py::merge_identities) emits — so the downstream
   measurement + semantic restatement consumers fire for auto-merges too.
   Previously step 10 recorded the merge but published nothing, so automatic
   deterministic auto-merges silently skipped restatement.

2. The composite identity confidence exposed by services/identity/confidence.py
   is explicitly marked as an evidence-weighted MATCH score, NOT a calibrated
   probability (``score_kind`` / ``calibrated=False``), while still unpacking as
   the historical ``(score, tier, reason_codes)`` 3-tuple.
"""
from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("AETHER_CREDENTIAL_BACKEND", "in_memory")

# Make backend packages importable when this suite is run in isolation.
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.audit import IdentityAuditWriter  # noqa: E402
from services.identity.conflicts import IdentityConflictManager  # noqa: E402
from services.identity.confidence import (  # noqa: E402
    CALIBRATED,
    MatchScore,
    SCORE_KIND,
    identity_match_score,
    score_signals,
)
from services.identity.graph_writer import IdentityGraphWriter  # noqa: E402
from services.identity.merge_policy import MergePolicyResult  # noqa: E402
from services.identity.metrics import IdentityMetrics  # noqa: E402
from services.identity.models import (  # noqa: E402
    ConfidenceTier,
    IdentitySignalType,
    MergeDecision,
)
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.identity.resolver import IdentityResolutionService  # noqa: E402
from shared.events.events import Event, Topic  # noqa: E402

TENANT = "tenant_restatement"
ENTITY_SURVIVOR = "entity_survivor"
ENTITY_CONSUMED = "entity_consumed"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


class _FakeProducer:
    """Records every published event so the test can assert on topic + payload."""

    def __init__(self, *, boom: bool = False) -> None:
        self.published: list[Event] = []
        self._boom = boom

    async def publish(self, event: Event) -> None:
        self.published.append(event)
        if self._boom:
            raise RuntimeError("event bus unavailable")


def _build_resolver(producer: _FakeProducer) -> IdentityResolutionService:
    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    return IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
        producer=producer,  # type: ignore[arg-type]
    )


async def _force_auto_merge(resolver: IdentityResolutionService, monkeypatch) -> None:
    """Wire an in-line auto-merge of ENTITY_CONSUMED -> ENTITY_SURVIVOR.

    The real merge policy never yields a step-10 merge with a from-entity
    distinct from the survivor, so the resolver-execution path is exercised by
    (a) making the alias lookup report two pre-existing entities and (b) forcing
    the policy to decide MERGE with the survivor as the target. The publish
    behaviour under test is independent of *which* policy produced the MERGE.
    """
    # Two pre-existing subjects the incoming signal maps to.
    await resolver._repo.create_subject(TENANT, ENTITY_SURVIVOR)
    await resolver._repo.create_subject(TENANT, ENTITY_CONSUMED)

    async def _fake_find_subjects_by_alias(tenant_id, sig_type, sig_hash):
        return [ENTITY_SURVIVOR, ENTITY_CONSUMED]

    monkeypatch.setattr(
        resolver._repo, "find_subjects_by_alias", _fake_find_subjects_by_alias
    )

    def _fake_evaluate(ctx):
        return MergePolicyResult(
            decision=MergeDecision.MERGE,
            confidence=0.99,
            confidence_tier=ConfidenceTier.DETERMINISTIC,
            reason_codes=["same_user_id"],
            merge_target_entity_id=ENTITY_SURVIVOR,
        )

    monkeypatch.setattr("services.identity.resolver.evaluate", _fake_evaluate)


# ── 1. Automatic resolver merge publishes IDENTITY_MERGED ──────────────────────


@pytest.mark.asyncio
async def test_auto_merge_publishes_identity_merged(monkeypatch):
    producer = _FakeProducer()
    resolver = _build_resolver(producer)
    await _force_auto_merge(resolver, monkeypatch)

    decision = await resolver.resolve_event(
        {"event_id": "evt_merge", "user_id": "u_shared"}, TENANT,
    )
    assert decision.decision == MergeDecision.MERGE
    assert decision.canonical_entity_id == ENTITY_SURVIVOR

    merged_events = [
        e for e in producer.published if e.topic == Topic.IDENTITY_MERGED
    ]
    assert len(merged_events) == 1, "auto-merge must publish exactly one IDENTITY_MERGED"

    event = merged_events[0]
    assert event.topic == Topic.IDENTITY_MERGED
    assert event.tenant_id == TENANT
    assert event.source_service == "identity"
    payload = event.payload
    # Survivor / consumed keys match what the measurement + semantic restatement
    # consumers read (primary_entity_id = survivor, secondary_entity_id = consumed).
    assert payload["primary_entity_id"] == ENTITY_SURVIVOR
    assert payload["secondary_entity_id"] == ENTITY_CONSUMED
    assert payload["canonical_entity_id"] == ENTITY_SURVIVOR
    assert payload["auto_merge"] is True


@pytest.mark.asyncio
async def test_auto_merge_publish_failure_does_not_break_resolution(monkeypatch):
    # A bus failure while publishing IDENTITY_MERGED must never discard the
    # resolution decision (the merge is already durably recorded by then).
    producer = _FakeProducer(boom=True)
    resolver = _build_resolver(producer)
    await _force_auto_merge(resolver, monkeypatch)

    decision = await resolver.resolve_event(
        {"event_id": "evt_merge_boom", "user_id": "u_shared"}, TENANT,
    )
    assert decision.decision == MergeDecision.MERGE
    assert decision.canonical_entity_id == ENTITY_SURVIVOR
    assert "internal_error" not in decision.reason_codes
    # The publish was still attempted.
    assert any(e.topic == Topic.IDENTITY_MERGED for e in producer.published)


@pytest.mark.asyncio
async def test_non_merge_resolution_publishes_nothing(monkeypatch):
    # A plain CREATE (brand-new entity) is not a merge and must not emit
    # IDENTITY_MERGED — guards against over-publishing.
    producer = _FakeProducer()
    resolver = _build_resolver(producer)

    decision = await resolver.resolve_event(
        {"event_id": "evt_create", "user_id": "u_brand_new"}, TENANT,
    )
    assert decision.decision != MergeDecision.MERGE
    assert not [e for e in producer.published if e.topic == Topic.IDENTITY_MERGED]


# ── 2. Confidence is an uncalibrated identity MATCH score ───────────────────────


def test_confidence_result_carries_uncalibrated_marker():
    result = score_signals(
        matching_signal_types=[IdentitySignalType.USER_ID],
        consent_snapshot={"purposes": {"analytics": True}},
        source_tenant_id=TENANT,
        target_tenant_id=TENANT,
    )
    # The result is explicitly marked as a match score, NOT a probability.
    assert isinstance(result, MatchScore)
    assert result.calibrated is False
    assert result.score_kind == SCORE_KIND == "identity_match_score"
    # Module-level marker is likewise uncalibrated.
    assert CALIBRATED is False


def test_match_score_still_unpacks_as_legacy_tuple():
    result = score_signals(
        matching_signal_types=[IdentitySignalType.EMAIL_HASH],
        consent_snapshot={"purposes": {"analytics": True}},
        source_tenant_id=TENANT,
        target_tenant_id=TENANT,
    )
    # Backward compatibility: existing callers unpack a 3-tuple unchanged.
    score, tier, reason_codes = result
    assert 0.0 <= score <= 1.0
    assert isinstance(tier, ConfidenceTier)
    assert isinstance(reason_codes, list)
    # Property accessors mirror the tuple positions.
    assert result.score == score
    assert result.tier == tier
    # identity_match_score is the clearly-named alias for the same function.
    assert identity_match_score is score_signals


def test_blocked_result_is_also_marked_uncalibrated():
    # Even the early blocking returns carry the marker.
    result = score_signals(
        matching_signal_types=[IdentitySignalType.USER_ID],
        consent_snapshot=None,
        source_tenant_id="tenant_a",
        target_tenant_id="tenant_b",  # cross-tenant → BLOCKED
    )
    assert result.tier == ConfidenceTier.BLOCKED
    assert result.calibrated is False
    assert result.score_kind == "identity_match_score"
