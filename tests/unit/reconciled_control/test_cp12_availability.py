"""CP-12 typed-availability helpers — distinctness + no fabrication.

Blueprint CP-12: ``missing``, ``empty``, ``zero``, ``degraded`` and
``not_applicable`` remain distinct, and no operator health surface may fabricate
``zero``/``empty`` to represent missing evidence. These tests pin the helper
contracts in ``services/managed_integrations/availability.py`` and the value
vocabulary in ``contracts.py``.
"""

from __future__ import annotations

import pytest

from services.managed_integrations.availability import (
    assert_availability,
    availability_from_presence,
    availability_from_readiness,
    is_availability,
)
from services.managed_integrations.contracts import (
    INTEGRATION_AVAILABILITY_VALUES,
    RECONCILE_RESULT_VALUES,
)


def test_vocabulary_has_exactly_six_distinct_cp12_labels() -> None:
    assert set(INTEGRATION_AVAILABILITY_VALUES) == {
        "available", "empty", "missing", "degraded", "not_applicable", "unknown",
    }
    # missing/empty/degraded/not_applicable are genuinely distinct values.
    assert len(INTEGRATION_AVAILABILITY_VALUES) == len(
        set(INTEGRATION_AVAILABILITY_VALUES)
    )


def test_is_availability_and_assert() -> None:
    assert is_availability("missing")
    assert is_availability("empty")
    assert is_availability("not_applicable")
    assert not is_availability("unavailable")
    assert not is_availability("zero")  # zero is not an emitted CP-12 label
    assert_availability("degraded")
    with pytest.raises(ValueError):
        assert_availability("zero")


def test_availability_from_presence_true_is_available() -> None:
    assert availability_from_presence(True) == "available"


def test_availability_from_presence_false_is_missing_by_default() -> None:
    # Absence defaults to `missing`, never fabricated as `empty`.
    assert availability_from_presence(False) == "missing"


def test_availability_from_presence_explicit_empty_is_allowed() -> None:
    # A caller that truly means "the surface exists but has no rows" must ask.
    assert availability_from_presence(False, absent="empty") == "empty"


def test_availability_from_presence_none_is_unknown() -> None:
    # The authority gave no signal -> unknown (not missing, not empty).
    assert availability_from_presence(None) == "unknown"


def test_availability_from_presence_rejects_bogus_absent() -> None:
    with pytest.raises(ValueError):
        availability_from_presence(False, absent="zero")


def test_readiness_validated_is_available() -> None:
    for state in ("connection_validated", "sandbox_validated", "partner_live"):
        assert availability_from_readiness(state) == "available"


def test_readiness_supplied_is_degraded_not_missing() -> None:
    # A supplied-but-unvalidated credential is evidence that is partial, not
    # absent — degrading rather than fabricating `missing`.
    for state in ("credential_supplied", "degraded", "suspended"):
        assert availability_from_readiness(state) == "degraded"


def test_readiness_waiting_or_revoked_is_missing_not_empty() -> None:
    for state in ("scaffolded", "credential_waiting", "revoked", "disabled"):
        assert availability_from_readiness(state) == "missing"


def test_readiness_unknown_state_is_unknown() -> None:
    assert availability_from_readiness("weird_state") == "unknown"


def test_readiness_absent_is_missing_never_empty() -> None:
    assert availability_from_readiness(None) == "missing"
    assert availability_from_readiness("") == "missing"


def test_reconcile_result_vocabulary_is_the_five_s32_labels() -> None:
    assert set(RECONCILE_RESULT_VALUES) == {
        "match", "acceptable_drift", "actionable_drift", "blocked", "unknown",
    }
