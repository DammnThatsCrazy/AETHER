"""Task 2 — verification lifecycle events + durable replay worker + provenance.

Covers the three net-new behaviours added on top of the shipped verification
layer:

  * ``EvidenceService`` publishes ``IDENTITY_VERIFICATION_COMPLETED`` /
    ``IDENTITY_VERIFICATION_REVOKED`` and, when no inline replay service is
    injected, ``IDENTITY_RESOLUTION_REPLAY_REQUESTED`` (carrying verification
    provenance) instead of running replay on the request path.
  * ``IdentityReplayConsumer`` runs the replay from that event, raising on a
    replay error so the shared consumer retries and then dead-letters — and
    dropping a structurally invalid event without a pointless dead-letter.
  * A verified proof that drives a resolver decision stamps verification
    provenance (evidence id / method / issuer / policy version / resolution
    revision) onto the decision-evidence row (§14).
  * Concurrent replays for the SAME identifier serialize and never double-merge.
"""
from __future__ import annotations

import asyncio
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
from services.identity.decision_evidence import (  # noqa: E402
    IdentityDecisionEvidenceService,
)
from services.identity.evidence import EvidenceService  # noqa: E402
from services.identity.graph_writer import IdentityGraphWriter  # noqa: E402
from services.identity.hashing import hash_email  # noqa: E402
from services.identity.metrics import IdentityMetrics  # noqa: E402
from services.identity.models import (  # noqa: E402
    ConfidenceTier,
    EntityType,
    IdentitySignalType,
    VerificationEvidenceType,
)
from services.identity.replay_consumer import (  # noqa: E402
    IdentityReplayConsumer,
    IdentityReplayError,
)
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.identity.resolution_replay import ResolutionReplayService  # noqa: E402
from services.identity.resolver import IdentityResolutionService  # noqa: E402
from shared.events.events import Event, EventConsumer, Topic  # noqa: E402

TENANT = "tenant_events"
EMAIL = "events@example.com"
LINK_CONSENT = {"purposes": {"identity": True}}


@pytest.fixture(autouse=True)
def _reset():
    prev = os.environ.get("AETHER_ENV")
    os.environ["AETHER_ENV"] = "local"
    reset_in_memory_stores()
    yield
    if prev is None:
        os.environ.pop("AETHER_ENV", None)
    else:
        os.environ["AETHER_ENV"] = prev


class _FakeProducer:
    """Records published events so tests can assert lifecycle emission."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.events.append(event)

    def topics(self) -> list[Topic]:
        return [e.topic for e in self.events]


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
    for eid, ts in (
        (e1, "2000-01-01T00:00:00+00:00"),
        (e2, "2030-01-01T00:00:00+00:00"),
    ):
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


# ── Lifecycle event emission ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_issue_evidence_publishes_completed_and_replay_requested():
    producer = _FakeProducer()
    # No injected replay service → async worker path publishes the request.
    svc = EvidenceService(producer=producer)

    evidence = await svc.issue_evidence(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=hash_email(EMAIL, TENANT),
        verification_method="email_otp",
        evidence_type=VerificationEvidenceType.EMAIL_OWNERSHIP_VERIFIED.value,
        issuer="aether",
        consent_snapshot=LINK_CONSENT,
    )

    topics = producer.topics()
    assert Topic.IDENTITY_VERIFICATION_COMPLETED in topics
    assert Topic.IDENTITY_RESOLUTION_REPLAY_REQUESTED in topics

    completed = next(
        e for e in producer.events
        if e.topic == Topic.IDENTITY_VERIFICATION_COMPLETED
    )
    assert completed.payload["evidence_id"] == evidence.id
    assert completed.payload["verification_method"] == "email_otp"
    assert completed.payload["issuer"] == "aether"
    # The raw email must never appear in the payload — only its hash.
    assert EMAIL not in str(completed.payload)

    requested = next(
        e for e in producer.events
        if e.topic == Topic.IDENTITY_RESOLUTION_REPLAY_REQUESTED
    )
    prov = requested.payload["verification"]
    assert prov["evidence_id"] == evidence.id
    assert prov["method"] == "email_otp"
    assert requested.payload["trigger_id"] == evidence.id


@pytest.mark.asyncio
async def test_revoke_evidence_publishes_revoked():
    producer = _FakeProducer()
    svc = EvidenceService(producer=producer)
    evidence = await svc.issue_evidence(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=hash_email(EMAIL, TENANT),
        verification_method="email_otp",
        issuer="aether",
    )
    producer.events.clear()

    row = await svc.revoke_evidence(TENANT, evidence.id, reason="user_request")
    assert row is not None
    topics = producer.topics()
    assert Topic.IDENTITY_VERIFICATION_REVOKED in topics
    revoked = next(
        e for e in producer.events if e.topic == Topic.IDENTITY_VERIFICATION_REVOKED
    )
    assert revoked.payload["evidence_id"] == evidence.id
    assert revoked.payload["reason"] == "user_request"


@pytest.mark.asyncio
async def test_injected_replay_service_skips_event_and_runs_inline():
    """An injected replay service (the existing test seam) still runs inline and
    is not replaced by the async event path."""

    class _Recorder:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def request_replay(self, **kwargs):
            self.calls.append(kwargs)
            return {"status": "queued"}

    rec = _Recorder()
    producer = _FakeProducer()
    svc = EvidenceService(replay_service=rec, producer=producer)
    await svc.issue_evidence(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=hash_email(EMAIL, TENANT),
        verification_method="email_otp",
    )
    # Inline path fired, and no replay-requested event was published.
    assert len(rec.calls) == 1
    assert rec.calls[0]["verification"]["method"] == "email_otp"
    assert Topic.IDENTITY_RESOLUTION_REPLAY_REQUESTED not in producer.topics()


# ── Replay consumer: retry / dead-letter / invalid ──────────────────────────


@pytest.mark.asyncio
async def test_replay_consumer_runs_request_replay_on_success():
    class _OkReplay:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def request_replay(self, **kwargs):
            self.calls.append(kwargs)
            return {"status": "complete"}

    ok = _OkReplay()
    consumer = IdentityReplayConsumer(replay_service=ok)
    event = Event(
        topic=Topic.IDENTITY_RESOLUTION_REPLAY_REQUESTED,
        tenant_id=TENANT,
        payload={
            "tenant_id": TENANT,
            "identifier_type": "email",
            "identifier_hash": "h",
            "trigger_id": "ev-1",
            "verification": {"evidence_id": "ev-1", "method": "email_otp"},
        },
    )
    await consumer.on_replay_requested(event)  # must not raise
    assert ok.calls[0]["trigger_id"] == "ev-1"
    assert ok.calls[0]["verification"]["evidence_id"] == "ev-1"


@pytest.mark.asyncio
async def test_replay_consumer_raises_on_error_status():
    class _ErrReplay:
        async def request_replay(self, **kwargs):
            return {"status": "error", "error": "boom"}

    consumer = IdentityReplayConsumer(replay_service=_ErrReplay())
    event = Event(
        topic=Topic.IDENTITY_RESOLUTION_REPLAY_REQUESTED,
        tenant_id=TENANT,
        payload={
            "tenant_id": TENANT, "identifier_type": "email",
            "identifier_hash": "h", "trigger_id": "ev-1",
        },
    )
    with pytest.raises(IdentityReplayError):
        await consumer.on_replay_requested(event)


@pytest.mark.asyncio
async def test_replay_consumer_drops_invalid_event_without_raise():
    class _Spy:
        def __init__(self) -> None:
            self.called = False

        async def request_replay(self, **kwargs):
            self.called = True
            return {"status": "complete"}

    spy = _Spy()
    consumer = IdentityReplayConsumer(replay_service=spy)
    event = Event(
        topic=Topic.IDENTITY_RESOLUTION_REPLAY_REQUESTED,
        tenant_id=TENANT,
        payload={"identifier_type": "email"},  # missing identifier_hash + trigger_id
    )
    await consumer.on_replay_requested(event)  # returns, no raise
    assert spy.called is False


@pytest.mark.asyncio
async def test_replay_dead_letters_after_retry_budget():
    class _ErrReplay:
        async def request_replay(self, **kwargs):
            return {"status": "error", "error": "boom"}

    event_consumer = EventConsumer()
    event_consumer.MAX_HANDLER_RETRIES = 2
    IdentityReplayConsumer(replay_service=_ErrReplay()).register(event_consumer)

    event = Event(
        topic=Topic.IDENTITY_RESOLUTION_REPLAY_REQUESTED,
        tenant_id=TENANT,
        payload={
            "tenant_id": TENANT, "identifier_type": "email",
            "identifier_hash": "h", "trigger_id": "ev-1",
        },
    )
    await event_consumer._dispatch(event)
    assert len(event_consumer._dlq) == 1
    assert event_consumer._dlq[0].topic == Topic.DEAD_LETTER
    assert event_consumer._dlq[0].payload["original_topic"] == (
        Topic.IDENTITY_RESOLUTION_REPLAY_REQUESTED.value
    )


# ── Decision-evidence verification provenance (§14) ─────────────────────────


@pytest.mark.asyncio
async def test_verified_replay_stamps_decision_evidence_provenance():
    resolver, repo = _build_resolver()
    e1, e2, email_hash = await _make_two_email_fragments(repo, TENANT, EMAIL)

    replay = ResolutionReplayService(resolver=resolver, repo=repo)
    res = await replay.request_replay(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=email_hash,
        trigger_type="verification_evidence_issued",
        trigger_id="ev-1",
        consent_snapshot=LINK_CONSENT,
        verification={
            "evidence_id": "ev-1",
            "issuer": "aether",
            "method": "email_ownership_verified",
            "policy_version": "1.0.0",
        },
    )
    assert res["status"] == "complete"
    survivor = res["canonical_entity_id"]

    evidence_svc = IdentityDecisionEvidenceService()
    rows = await evidence_svc.list_for_entity(TENANT, survivor)
    stamped = [r for r in rows if r.get("verification_method")]
    assert stamped, "expected a decision-evidence row with verification provenance"
    row = stamped[0]
    assert row["verification_method"] == "email_ownership_verified"
    assert row["verification_evidence_id"] == "ev-1"
    assert row["verification_issuer"] == "aether"
    assert row["verification_policy_version"] == "1.0.0"
    assert int(row["resolution_revision"]) >= 1


@pytest.mark.asyncio
async def test_ordinary_decision_has_blank_verification_provenance():
    """A plain (non-verified) resolution leaves provenance empty / revision 0."""
    resolver, _repo = _build_resolver()
    decision = await resolver.resolve_event(
        {"event_id": "evt-plain", "user_id": "user_plain"}, TENANT,
    )
    assert decision.canonical_entity_id

    evidence_svc = IdentityDecisionEvidenceService()
    rows = await evidence_svc.list_for_entity(TENANT, decision.canonical_entity_id)
    assert rows, "expected at least one decision-evidence row"
    assert all(r.get("verification_method", "") == "" for r in rows)
    assert all(int(r.get("resolution_revision", 0)) == 0 for r in rows)


# ── Per-identifier serialization ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_replays_same_identifier_do_not_double_merge():
    resolver, repo = _build_resolver()
    e1, e2, email_hash = await _make_two_email_fragments(repo, TENANT, EMAIL)

    replay = ResolutionReplayService(resolver=resolver, repo=repo)
    results = await asyncio.gather(
        replay.request_replay(
            tenant_id=TENANT, identifier_type="email", identifier_hash=email_hash,
            trigger_type="verification_evidence_issued", trigger_id="ev-a",
            consent_snapshot=LINK_CONSENT,
        ),
        replay.request_replay(
            tenant_id=TENANT, identifier_type="email", identifier_hash=email_hash,
            trigger_type="verification_evidence_issued", trigger_id="ev-b",
            consent_snapshot=LINK_CONSENT,
        ),
    )
    assert all(r["status"] in ("complete", "noop") for r in results)
    # Both fragments must converge on exactly one survivor — no double-merge,
    # no split entity, no error.
    survivors = set()
    for eid in (e1, e2):
        row = await repo.get_subject_by_canonical_entity_id(TENANT, eid)
        survivors.add((row or {}).get("merged_into_entity_id") or eid)
    assert len(survivors) == 1
