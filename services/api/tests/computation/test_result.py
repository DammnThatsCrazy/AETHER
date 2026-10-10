"""CanonicalResult value-invariant tests — the generalized 'unknown is never 0'
guarantee at the result envelope level."""

from __future__ import annotations

import pytest

from shared.computation import (
    CanonicalResult,
    MathType,
    ResultStatus,
    TypeContractError,
)


def _kwargs(**over):
    base = dict(
        definition_id="campaign.ctr",
        definition_version="1",
        tenant_id="t1",
        value_type=MathType.RATE,
        unit="ratio",
    )
    base.update(over)
    return base


def test_available_requires_value():
    with pytest.raises(TypeContractError):
        CanonicalResult(status=ResultStatus.AVAILABLE, value=None, **_kwargs())


@pytest.mark.parametrize(
    "status",
    [
        ResultStatus.MISSING_INPUTS,
        ResultStatus.UNAVAILABLE,
        ResultStatus.INSUFFICIENT_DATA,
        ResultStatus.NOT_APPLICABLE,
        ResultStatus.NOT_PROVISIONED,
        ResultStatus.SUPPRESSED,
        ResultStatus.PRIVACY_RESTRICTED,
        ResultStatus.FAILED,
    ],
)
def test_absence_statuses_forbid_a_value(status):
    # A value under an honest-absence status would let 'unknown' masquerade as a
    # real number (including 0).
    with pytest.raises(TypeContractError):
        CanonicalResult(status=status, value=0.0, **_kwargs())
    # ...but they construct fine with value=None.
    assert CanonicalResult(status=status, value=None, **_kwargs()).value is None


def test_money_result_requires_currency_when_valued():
    with pytest.raises(TypeContractError):
        CanonicalResult(
            status=ResultStatus.AVAILABLE,
            value=10.0,
            currency=None,
            **_kwargs(definition_id="campaign.media_spend", value_type=MathType.MONEY, unit="currency"),
        )
    ok = CanonicalResult(
        status=ResultStatus.AVAILABLE,
        value=10.0,
        currency="USD",
        **_kwargs(definition_id="campaign.media_spend", value_type=MathType.MONEY, unit="currency"),
    )
    assert ok.currency == "USD"


def test_available_zero_is_allowed_as_evidence_backed():
    # A genuine, evidence-backed 0 IS permitted under 'available'.
    r = CanonicalResult(status=ResultStatus.AVAILABLE, value=0.0, **_kwargs())
    assert r.value == 0.0
