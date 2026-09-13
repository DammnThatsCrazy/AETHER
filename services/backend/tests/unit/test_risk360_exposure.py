"""Risk360 Phase-5 exposure builder tests (exposure.py).

Covers building an :class:`ExposureAssessment` from a ``safe_rollup`` economic
snapshot and revenue-adjustment netting, the unpriced honesty contract (a USD
figure is never fabricated), and the economic360 reader seam path (including
honest degradation when the backing source fails).
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.risk360.contracts import EpistemicStatus  # noqa: E402
from services.risk360.exposure import (  # noqa: E402
    exposure_from_rollup,
    subject_exposure,
)

SUBJ = dict(tenant_id="ten_1", subject_kind="entity", subject_id="ent_1")


def test_priced_rollup_yields_derived_usd_exposure():
    exposure = exposure_from_rollup(
        rollup={"total_usd": "500.00", "rollup_status": "complete", "unpriced_count": 0},
        **SUBJ,
    )
    assert exposure.economic_value.usd_value == Decimal("500.00")
    assert exposure.claim_state == EpistemicStatus.DERIVED
    assert exposure.evidence_refs[0].source == "economic.safe_rollup"


def test_revenue_adjustment_nets_exposure_and_floors_at_zero():
    exposure = exposure_from_rollup(
        rollup={"total_usd": "100.00", "rollup_status": "complete", "unpriced_count": 0},
        net_adjustment_usd=Decimal("-40.00"),
        **SUBJ,
    )
    assert exposure.economic_value.usd_value == Decimal("60.00")
    assert "revenue_adjustments" in exposure.exposed_outcome_labels

    fully_refunded = exposure_from_rollup(
        rollup={"total_usd": "10.00", "rollup_status": "complete", "unpriced_count": 0},
        net_adjustment_usd=Decimal("-50.00"),
        **SUBJ,
    )
    assert fully_refunded.economic_value.usd_value == Decimal("0.00")


def test_unpriced_rollup_never_becomes_a_number():
    exposure = exposure_from_rollup(
        rollup={
            "total_usd": None,
            "rollup_status": "unavailable",
            "unpriced_count": 2,
        },
        net_adjustment_usd=Decimal("-40.00"),
        **SUBJ,
    )
    # netting an unpriced gross must NOT fabricate a magnitude
    assert exposure.economic_value.usd_value is None
    assert exposure.claim_state == EpistemicStatus.UNKNOWN
    assert "unpriced_economic_value" in exposure.exposed_outcome_labels


class _StubReader:
    """Duck-typed EconomicSourceReader seam."""

    def __init__(self, records, error=False):
        self._records = records
        self._error = error

    async def records(self, *, tenant_id, subject):
        if self._error:
            raise RuntimeError("economic source down")
        return self._records


@pytest.mark.asyncio
async def test_subject_exposure_reads_economic_seam_and_rolls_up():
    reader = _StubReader(
        [
            {"amount": "100.00", "currency": "USD", "value_usd": "100.00"},
            {"amount": "50.00", "currency": "USD", "value_usd": "50.00"},
        ]
    )
    exposure = await subject_exposure(reader, **SUBJ)
    assert exposure.economic_value.usd_value == Decimal("150.00")
    assert exposure.claim_state == EpistemicStatus.DERIVED


@pytest.mark.asyncio
async def test_subject_exposure_degrades_honestly_on_reader_failure():
    reader = _StubReader([], error=True)
    exposure = await subject_exposure(reader, **SUBJ)
    # a backing-source failure is NOT a fabricated 0 exposure
    assert exposure.economic_value.usd_value is None
    assert exposure.claim_state == EpistemicStatus.UNKNOWN
