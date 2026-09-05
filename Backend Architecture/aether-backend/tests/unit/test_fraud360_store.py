"""Fraud360 FraudHypothesis JSONB store tests (Phase 3).

Tenant-scoped round-trip over the ``BaseRepository`` JSONB pattern (table
``fraud_hypotheses``). In ``AETHER_ENV=local`` the store is in-memory and shared
per table; tests reset the backing stores for isolation. The repository
re-checks the tenant on every read and enforces the hypothesis state machine at
the storage boundary (no silent escalation into ``confirmed``).
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

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.economic.economic360_contracts import MonetaryAmount  # noqa: E402
from services.fraud360.contracts import (  # noqa: E402
    ConfirmationRequiresFactualClaimError,
    EpistemicStatus,
    FraudHypothesis,
    FraudHypothesisState,
    IllegalTransitionError,
    RejectionRequiresEvidenceError,
)
from services.fraud360.store import FraudHypothesisRepository  # noqa: E402
from services.operational_intelligence.models import (  # noqa: E402
    EvidenceRef,
    GraphSnapshotRef,
)


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _sample(tenant_id: str, hypothesis_id: str = "hyp-1") -> FraudHypothesis:
    return FraudHypothesis(
        hypothesis_id=hypothesis_id,
        tenant_id=tenant_id,
        subject_kind="entity",
        subject_id="ent_123",
        state=FraudHypothesisState.UNDER_EVALUATION,
        claim_state=EpistemicStatus.DERIVED,
        confidence=0.7,
        matched_pattern_ids=["synthetic_identity"],
        materiality=0.6,
        exposure=MonetaryAmount(amount="1000.00", currency="USD", usd_value="1000.00"),
        evidence_refs=[
            EvidenceRef(id="ev_1", type="transaction", source="fraud360/test")
        ],
        contradictory_evidence_refs=[
            EvidenceRef(id="ev_2", type="annotation", source="fraud360/test")
        ],
        risk_assessment_ids=["ra_1"],
        network_ids=["net_1"],
        flow_trace_ids=["ft_1"],
        decision_ids=["dec_1"],
        snapshot=GraphSnapshotRef(graph_snapshot_id="snap_1"),
        run_id="run_abc",
    )


async def test_create_and_get_round_trip():
    repo = FraudHypothesisRepository()
    original = _sample("tenant-a")
    stored = await repo.create("tenant-a", original)
    assert stored.hypothesis_id == "hyp-1"
    assert stored.created_at is not None  # envelope timestamp persisted

    fetched = await repo.get("tenant-a", "hyp-1")
    assert fetched is not None
    # created_at/updated_at are persistence-owned; everything else round-trips.
    assert fetched.model_dump(exclude={"created_at", "updated_at"}) == original.model_dump(
        exclude={"created_at", "updated_at"}
    )
    assert fetched.exposure == original.exposure
    assert fetched.snapshot == original.snapshot


async def test_create_rejects_mismatched_tenant_scope():
    repo = FraudHypothesisRepository()
    with pytest.raises(ValueError):
        await repo.create("tenant-a", _sample("tenant-B"))


async def test_tenant_isolation_on_read_and_list():
    repo = FraudHypothesisRepository()
    await repo.create("tenant-a", _sample("tenant-a", "hyp-a"))
    await repo.create("tenant-b", _sample("tenant-b", "hyp-b"))

    # Cross-tenant get is None even though the qualified id differs.
    assert await repo.get("tenant-a", "hyp-b") is None
    assert await repo.get("tenant-b", "hyp-a") is None
    assert (await repo.get("tenant-a", "hyp-a")) is not None

    tenant_a_rows = await repo.list("tenant-a")
    assert [h.hypothesis_id for h in tenant_a_rows] == ["hyp-a"]
    tenant_b_rows = await repo.list("tenant-b")
    assert [h.hypothesis_id for h in tenant_b_rows] == ["hyp-b"]

    # A state filter scopes within the tenant.
    under_eval = await repo.list(
        "tenant-a", state=FraudHypothesisState.UNDER_EVALUATION
    )
    assert [h.hypothesis_id for h in under_eval] == ["hyp-a"]


async def test_update_state_walks_legal_lifecycle():
    repo = FraudHypothesisRepository()
    await repo.create("tenant-a", _sample("tenant-a"))

    promoted = await repo.update_state("tenant-a", "hyp-1", "supported")
    assert promoted is not None and promoted.state is FraudHypothesisState.SUPPORTED

    fetched = await repo.get("tenant-a", "hyp-1")
    assert fetched.state is FraudHypothesisState.SUPPORTED


async def test_update_state_denies_illegal_edge():
    repo = FraudHypothesisRepository()
    await repo.create("tenant-a", _sample("tenant-a"))
    with pytest.raises(IllegalTransitionError):
        await repo.update_state("tenant-a", "hyp-1", "candidate")


async def test_update_state_rejected_requires_evidence():
    repo = FraudHypothesisRepository()
    await repo.create("tenant-a", _sample("tenant-a"))
    with pytest.raises(RejectionRequiresEvidenceError):
        await repo.update_state("tenant-a", "hyp-1", "rejected")
    rejected = await repo.update_state(
        "tenant-a", "hyp-1", "rejected", evidence_refs=[{"id": "ev_reject"}]
    )
    assert rejected.state is FraudHypothesisState.REJECTED


async def test_update_state_confirmed_requires_factual_claim():
    repo = FraudHypothesisRepository()
    # Promote hyp-1 to investigating, then attempt confirm under a suspicion
    # claim — the no-silent-escalation rule denies it at the storage boundary.
    await repo.create("tenant-a", _sample("tenant-a"))
    await repo.update_state("tenant-a", "hyp-1", "supported")
    await repo.update_state("tenant-a", "hyp-1", "material")
    await repo.update_state("tenant-a", "hyp-1", "investigating")
    with pytest.raises(ConfirmationRequiresFactualClaimError):
        await repo.update_state(
            "tenant-a", "hyp-1", "confirmed", claim_state=EpistemicStatus.DERIVED
        )

    # A hypothesis that is already under investigation with a factual claim
    # may transition to confirmed.
    investigating = _sample("tenant-a", "hyp-2")
    investigating.state = FraudHypothesisState.INVESTIGATING
    investigating.claim_state = EpistemicStatus.VERIFIED
    await repo.create("tenant-a", investigating)
    confirmed = await repo.update_state(
        "tenant-a", "hyp-2", "confirmed", claim_state=EpistemicStatus.VERIFIED
    )
    assert confirmed.state is FraudHypothesisState.CONFIRMED


async def test_update_state_missing_or_other_tenant_returns_none():
    repo = FraudHypothesisRepository()
    await repo.create("tenant-a", _sample("tenant-a"))
    assert await repo.update_state("tenant-a", "nope", "supported") is None
    assert await repo.update_state("tenant-b", "hyp-1", "supported") is None
