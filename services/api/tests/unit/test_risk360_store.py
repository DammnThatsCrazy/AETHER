"""Risk360 evidence storage tests — tenant-scoped JSONB repository records.

Under ``AETHER_ENV=local`` ``get_pool()`` returns None, so these exercise the
in-memory repository backend with the same semantics the SQL path implements:
tenant-qualified ids, tenant-checked reads, and no cross-tenant leak. The
production risk-poisoning authority is declared in its Alembic migration.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from intelligence.risk360.contracts import (  # noqa: E402
    EntityRef,
    EpistemicStatus,
    EvidenceRef,
    ExposureAssessment,
    GraphSnapshotRef,
    MonetaryAmount,
    RiskAssessment,
    RiskComponent,
    RiskPoisoningEvidence,
    RiskSignal,
    RiskVector,
    ValueState,
)
from intelligence.risk360.store import (  # noqa: E402
    RiskAssessmentRepository,
    RiskPoisoningEvidenceConflict,
    RiskPoisoningEvidenceRepository,
    RiskSignalRepository,
)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


@pytest.fixture(autouse=True)
def _reset_stores() -> None:
    reset_in_memory_stores()


def _signal(signal_id: str, tenant_id: str, *, subject_id: str = "usr_1") -> RiskSignal:
    return RiskSignal(
        signal_id=signal_id,
        tenant_id=tenant_id,
        subject_kind="entity",
        subject_id=subject_id,
        risk_dimension="payment",
        source="fraud.signals",
        detector_version="2.1.0",
        claim_state=EpistemicStatus.INFERRED,
        confidence=0.7,
        evidence_refs=[EvidenceRef(id=f"ev-{signal_id}", type="transaction", source="ledger")],
        score=0.3,
    )


def _assessment(assessment_id: str, tenant_id: str) -> RiskAssessment:
    return RiskAssessment(
        assessment_id=assessment_id,
        tenant_id=tenant_id,
        subject_kind="entity",
        subject_id="usr_1",
        subject_ref=EntityRef(kind="user", id="usr_1"),
        policy_id="policy_payment_authorization",
        policy_version="3",
        dimensions=["economic"],
        vector=RiskVector(
            components=[
                RiskComponent(
                    dimension="economic",
                    state=ValueState.OBSERVED,
                    score=0.4,
                    claim_state=EpistemicStatus.OBSERVED,
                )
            ]
        ),
        exposure=ExposureAssessment(
            tenant_id=tenant_id,
            subject_kind="entity",
            subject_id="usr_1",
            subject_ref=EntityRef(kind="user", id="usr_1"),
            exposed_asset_labels=["wallet"],
            economic_value=MonetaryAmount(amount="120.00", currency="USD"),
        ),
        claim_state=EpistemicStatus.DERIVED,
        confidence=0.55,
        snapshot=GraphSnapshotRef(graph_snapshot_id=f"gs-{assessment_id}"),
    )


def _poisoning_evidence(
    evidence_id: str,
    tenant_id: str = TENANT_A,
    *,
    source_id: str = "provider:crm",
    subject_kind: str = "agent",
    subject_id: str = "agent-1",
    now: datetime | None = None,
    first_seen_at: datetime | None = None,
    version: int = 1,
    supersedes_evidence_id: str | None = None,
    restatement_reason: str | None = None,
) -> RiskPoisoningEvidence:
    observed = now or datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    return RiskPoisoningEvidence(
        evidence_id=evidence_id,
        tenant_id=tenant_id,
        source_id=source_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        poisoning_type="agent_trace_tampering",
        signal_strength=0.82,
        confidence="high",
        claim_state=EpistemicStatus.INFERRED,
        detector_id="agent-trace-integrity",
        detector_version="2.4.1",
        source_record_id=f"trace-record-{evidence_id}",
        evidence_refs=[
            EvidenceRef(id=f"trace-{evidence_id}", type="event", source="agent-traces")
        ],
        first_seen_at=first_seen_at or observed - timedelta(minutes=4),
        last_seen_at=observed,
        recorded_at=observed,
        version=version,
        supersedes_evidence_id=supersedes_evidence_id,
        restatement_reason=restatement_reason,
    )


@pytest.mark.asyncio
async def test_risk_signal_repository_round_trip_tenant_scoped() -> None:
    repo = RiskSignalRepository()
    signal = _signal("sig-1", TENANT_A)
    payload = signal.model_dump(mode="json")

    stored = await repo.upsert_scoped(TENANT_A, "sig-1", payload)
    assert stored["signal_id"] == "sig-1"

    got = await repo.get_scoped(TENANT_A, "sig-1")
    assert got is not None
    assert got == payload
    assert got["tenant_id"] == TENANT_A


@pytest.mark.asyncio
async def test_risk_signal_repository_no_cross_tenant_read() -> None:
    repo = RiskSignalRepository()
    await repo.upsert_scoped(TENANT_A, "sig-1", _signal("sig-1", TENANT_A).model_dump(mode="json"))

    # Same natural id from another tenant is absent — never a cross-tenant leak.
    assert await repo.get_scoped(TENANT_B, "sig-1") is None
    assert await repo.list_scoped(TENANT_B) == []
    assert await repo.update_scoped(TENANT_B, "sig-1", {"score": 0.99}) is None
    assert await repo.delete_scoped(TENANT_B, "sig-1") is False
    # Tenant A still owns the row, untouched.
    assert (await repo.get_scoped(TENANT_A, "sig-1"))["score"] == 0.3


@pytest.mark.asyncio
async def test_risk_signal_repository_list_and_list_by_subject() -> None:
    repo = RiskSignalRepository()
    await repo.upsert_scoped(TENANT_A, "sig-1", _signal("sig-1", TENANT_A).model_dump(mode="json"))
    await repo.upsert_scoped(TENANT_A, "sig-2", _signal("sig-2", TENANT_A).model_dump(mode="json"))
    await repo.upsert_scoped(TENANT_B, "sig-3", _signal("sig-3", TENANT_B).model_dump(mode="json"))

    rows_a = await repo.list_scoped(TENANT_A)
    assert {r["signal_id"] for r in rows_a} == {"sig-1", "sig-2"}
    assert all(r["tenant_id"] == TENANT_A for r in rows_a)

    # Subject-scoped list filters to one tenant's subject only.
    subj = await repo.list_by_subject(TENANT_A, "entity", "usr_1")
    assert {r["signal_id"] for r in subj} == {"sig-1", "sig-2"}

    dim = await repo.list_by_dimension(TENANT_A, "payment")
    assert {r["signal_id"] for r in dim} == {"sig-1", "sig-2"}


@pytest.mark.asyncio
async def test_risk_assessment_repository_round_trip_tenant_scoped() -> None:
    repo = RiskAssessmentRepository()
    assessment = _assessment("a-1", TENANT_A)
    payload = assessment.model_dump(mode="json")

    stored = await repo.upsert_scoped(TENANT_A, "a-1", payload)
    assert stored["assessment_id"] == "a-1"

    got = await repo.get_scoped(TENANT_A, "a-1")
    assert got is not None
    assert got == payload
    assert got["policy_id"] == "policy_payment_authorization"
    assert got["vector"]["components"][0]["dimension"] == "economic"
    assert got["exposure"]["economic_value"]["amount"] == "120.00"


@pytest.mark.asyncio
async def test_risk_assessment_repository_no_cross_tenant_read_and_list() -> None:
    repo = RiskAssessmentRepository()
    await repo.upsert_scoped(TENANT_A, "a-1", _assessment("a-1", TENANT_A).model_dump(mode="json"))
    await repo.upsert_scoped(TENANT_A, "a-2", _assessment("a-2", TENANT_A).model_dump(mode="json"))
    await repo.upsert_scoped(TENANT_B, "a-9", _assessment("a-9", TENANT_B).model_dump(mode="json"))

    assert await repo.get_scoped(TENANT_B, "a-1") is None
    rows_a = await repo.list_scoped(TENANT_A)
    assert {r["assessment_id"] for r in rows_a} == {"a-1", "a-2"}
    assert all(r["tenant_id"] == TENANT_A for r in rows_a)

    by_subject = await repo.list_by_subject(TENANT_A, "entity", "usr_1")
    assert {r["assessment_id"] for r in by_subject} == {"a-1", "a-2"}


@pytest.mark.asyncio
async def test_risk_assessment_repository_update_and_delete() -> None:
    repo = RiskAssessmentRepository()
    await repo.upsert_scoped(TENANT_A, "a-1", _assessment("a-1", TENANT_A).model_dump(mode="json"))

    updated = await repo.update_scoped(TENANT_A, "a-1", {"confidence": 0.8})
    assert updated is not None
    assert updated["confidence"] == 0.8

    assert await repo.delete_scoped(TENANT_A, "a-1") is True
    assert await repo.get_scoped(TENANT_A, "a-1") is None
    # Deleting an absent/foreign row is a no-op.
    assert await repo.delete_scoped(TENANT_A, "a-1") is False


@pytest.mark.asyncio
async def test_identical_natural_ids_across_tenants_do_not_collide() -> None:
    signal_repo = RiskSignalRepository()
    await signal_repo.upsert_scoped(
        TENANT_A, "sig-1", _signal("sig-1", TENANT_A).model_dump(mode="json")
    )
    await signal_repo.upsert_scoped(
        TENANT_B, "sig-1", _signal("sig-1", TENANT_B).model_dump(mode="json")
    )

    got_a = await signal_repo.get_scoped(TENANT_A, "sig-1")
    got_b = await signal_repo.get_scoped(TENANT_B, "sig-1")
    assert got_a is not None and got_b is not None
    assert got_a["signal_id"] == got_b["signal_id"] == "sig-1"
    assert got_a["tenant_id"] == TENANT_A
    assert got_b["tenant_id"] == TENANT_B


@pytest.mark.asyncio
async def test_poisoning_evidence_repository_enforces_exact_tenant_source_and_subject() -> None:
    repo = RiskPoisoningEvidenceRepository()
    await repo.create(_poisoning_evidence("p-1", source_id="source-a"))
    await repo.create(_poisoning_evidence("p-2", source_id="source-b"))
    await repo.create(_poisoning_evidence("p-3", TENANT_B, source_id="source-a"))
    await repo.create(
        _poisoning_evidence("p-4", subject_kind="entity", subject_id="entity-1")
    )

    exact = await repo.list_for_subject(
        TENANT_A,
        "agent",
        "agent-1",
        source_id="source-a",
    )
    assert exact.complete is True
    assert [record.evidence_id for record in exact.records] == ["p-1"]
    assert await repo.get(TENANT_B, "p-1") is None
    assert await repo.get(TENANT_A, "p-1") is not None

    other_source = await repo.list_for_subject(TENANT_A, "agent", "agent-1")
    assert {record.source_id for record in other_source.records} == {"source-a", "source-b"}
    other_subject = await repo.list_for_subject(TENANT_A, "entity", "entity-1")
    assert [record.evidence_id for record in other_subject.records] == ["p-4"]


@pytest.mark.asyncio
async def test_poisoning_evidence_repository_reports_bounded_truncation() -> None:
    repo = RiskPoisoningEvidenceRepository()
    base = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    await repo.create(_poisoning_evidence("p-1", now=base))
    await repo.create(_poisoning_evidence("p-2", now=base + timedelta(seconds=1)))

    read = await repo.list_for_subject(TENANT_A, "agent", "agent-1", limit=1)
    assert read.complete is False
    assert read.reason == "poisoning_evidence_scan_truncated"
    assert len(read.records) == 1
    assert read.records[0].evidence_id == "p-2"


@pytest.mark.asyncio
async def test_poisoning_evidence_lifecycle_and_restatement_are_auditable_and_temporal() -> None:
    repo = RiskPoisoningEvidenceRepository()
    now = datetime.now(timezone.utc)
    initial = _poisoning_evidence("p-v1", now=now - timedelta(minutes=2))
    await repo.create(initial)

    acknowledged = await repo.transition_status(
        TENANT_A,
        "p-v1",
        "acknowledged",
        actor_id="operator-7",
        reason="review started",
        evidence_refs=[EvidenceRef(id="review-1", type="event", source="risk-review")],
    )
    assert acknowledged is not None
    assert acknowledged.status == "acknowledged"
    assert acknowledged.lifecycle_events[-1].actor_id == "operator-7"
    assert acknowledged.lifecycle_events[-1].from_status == "open"
    with pytest.raises(RiskPoisoningEvidenceConflict):
        await repo.transition_status(
            TENANT_A,
            "p-v1",
            "superseded",
            actor_id="operator-8",
        )

    transition_at = acknowledged.lifecycle_events[-1].occurred_at
    before_restatement = transition_at + timedelta(microseconds=1)
    successor_recorded_at = transition_at + timedelta(microseconds=2)
    replacement = _poisoning_evidence(
        "p-v2",
        now=successor_recorded_at,
        first_seen_at=initial.first_seen_at,
        version=2,
        supersedes_evidence_id="p-v1",
        restatement_reason="detector model corrected source attribution",
    )
    await repo.restate(
        TENANT_A,
        "p-v1",
        replacement,
        actor_id="detector-release-2.4.2",
        reason="detector model corrected source attribution",
    )

    predecessor = await repo.get(TENANT_A, "p-v1")
    successor = await repo.get(TENANT_A, "p-v2")
    assert predecessor is not None and successor is not None
    assert predecessor.status == "superseded"
    assert predecessor.superseded_by_evidence_id == "p-v2"
    assert successor.supersedes_evidence_id == "p-v1"
    assert successor.version == 2

    historical = await repo.list_for_subject(
        TENANT_A,
        "agent",
        "agent-1",
        as_of=before_restatement,
    )
    assert [record.evidence_id for record in historical.records] == ["p-v1"]
    assert historical.records[0].status == "acknowledged"
    assert historical.records[0].superseded_by_evidence_id is None
    assert historical.records[0].lifecycle_events[-1].to_status == "acknowledged"

    current = await repo.list_for_subject(
        TENANT_A,
        "agent",
        "agent-1",
    )
    assert {record.evidence_id: record.status for record in current.records} == {
        "p-v1": "superseded",
        "p-v2": "open",
    }


@pytest.mark.asyncio
async def test_poisoning_evidence_restatement_rejects_cross_scope_and_forks() -> None:
    repo = RiskPoisoningEvidenceRepository()
    initial = _poisoning_evidence("p-v1")
    await repo.create(initial)

    mismatch = _poisoning_evidence(
        "p-v2",
        source_id="different-source",
        version=2,
        supersedes_evidence_id="p-v1",
        restatement_reason="corrected",
    )
    with pytest.raises(RiskPoisoningEvidenceConflict):
        await repo.restate(
            TENANT_A,
            "p-v1",
            mismatch,
            actor_id="detector",
            reason="corrected",
        )

    replacement = _poisoning_evidence(
        "p-v2",
        now=initial.recorded_at + timedelta(minutes=1),
        first_seen_at=initial.first_seen_at,
        version=2,
        supersedes_evidence_id="p-v1",
        restatement_reason="corrected",
    )
    await repo.restate(
        TENANT_A,
        "p-v1",
        replacement,
        actor_id="detector",
        reason="corrected",
    )
    with pytest.raises(RiskPoisoningEvidenceConflict):
        await repo.restate(
            TENANT_A,
            "p-v1",
            _poisoning_evidence(
                "p-v3",
                now=initial.recorded_at + timedelta(minutes=2),
                first_seen_at=initial.first_seen_at,
                version=2,
                supersedes_evidence_id="p-v1",
                restatement_reason="another correction",
            ),
            actor_id="detector",
            reason="another correction",
        )
