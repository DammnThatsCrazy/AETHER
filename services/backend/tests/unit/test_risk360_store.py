"""Risk360 Phase-3 storage tests — tenant-scoped JSONB repositories.

Under ``AETHER_ENV=local`` ``get_pool()`` returns None, so these exercise the
in-memory BaseRepository backend with the same semantics the SQL path
implements: tenant-qualified ids, tenant-checked reads, and no cross-tenant
leak. No Alembic migration is required (BaseRepository owns the schema).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.risk360.contracts import (  # noqa: E402
    EntityRef,
    EpistemicStatus,
    EvidenceRef,
    ExposureAssessment,
    GraphSnapshotRef,
    MonetaryAmount,
    RiskAssessment,
    RiskComponent,
    RiskSignal,
    RiskVector,
    ValueState,
)
from services.risk360.store import (  # noqa: E402
    RiskAssessmentRepository,
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
