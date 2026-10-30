"""Surface attribution + sequence_key flow: envelope → silver row → activity.

The canonical envelope context v1 stamps ``context.surface`` and
``context.sequence.event`` on every SDK event. These tests pin the consumption
path: BaseProjector._base_row reads both into the silver row (surface verbatim;
the sequence counter zero-padded to a 12-digit sequence_key so lexicographic
TEXT ordering equals numeric ordering), the silver adapters carry them into
the canonical activity dict, and the CanonicalActivity contract accepts them.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from journeys.measurement.contracts import CanonicalActivity  # noqa: E402
from journeys.measurement.silver_adapters import adapt_from_silver  # noqa: E402
from ingestion.silver.projectors.base import BaseProjector  # noqa: E402
from ingestion.silver.projectors.outcome_projector import OutcomeProjector  # noqa: E402


def _bronze_event(context_extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    context: dict[str, Any] = {
        "tenantId": "tenant-a",
        "consentSnapshotId": "consent-1",
        "surface": "web",
        "sequence": {"event": 42},
    }
    context.update(context_extra or {})
    return {
        "type": "goal_achieved",
        "messageId": "evt-1",
        "userId": "user-1",
        "anonymousId": "anon-1",
        "timestamp": "2026-07-23T12:00:00+00:00",
        "properties": {"goalId": "goal-1", "value": 10, "currency": "USD"},
        "context": context,
    }


# ── BaseProjector._base_row ───────────────────────────────────────────────────


def test_base_row_reads_surface_and_sequence_key_from_context():
    row = BaseProjector()._base_row(_bronze_event())
    assert row["surface"] == "web"
    assert row["sequence_key"] == "000000000042"


def test_sequence_key_is_zero_padded_for_lexicographic_ordering():
    low = BaseProjector()._base_row(_bronze_event({"sequence": {"event": 9}}))
    high = BaseProjector()._base_row(_bronze_event({"sequence": {"event": 100}}))
    assert low["sequence_key"] == "000000000009"
    assert high["sequence_key"] == "000000000100"
    # The whole point of the padding: TEXT sort order == numeric order.
    assert low["sequence_key"] < high["sequence_key"]


def test_base_row_without_envelope_fields_stays_null():
    row = BaseProjector()._base_row(_bronze_event({"surface": None, "sequence": None}))
    assert row["surface"] is None
    assert row["sequence_key"] is None


def test_sequence_key_rejects_non_integral_counters():
    projector = BaseProjector()
    for bad_sequence in ({"event": "42"}, {"event": True}, {"event": 1.5},
                         {"event": -1}, {}, "not-a-dict"):
        row = projector._base_row(_bronze_event({"sequence": bad_sequence}))
        assert row["sequence_key"] is None, bad_sequence


# ── Silver adapters + CanonicalActivity contract ──────────────────────────────


def test_adapter_emits_surface_and_sequence_key_into_canonical_activity():
    silver_row = {
        "tenant_id": "tenant-a",
        "fact_id": "0d4f2c9a-58f5-4a41-b0f8-2b8b7c1e9d10",
        "source_event_id": "evt-1",
        "occurred_at": "2026-07-23T12:00:00+00:00",
        "surface": "server",
        "sequence_key": "000000000007",
        "outcome_type": "goal_achieved",
        "succeeded": True,
        "user_id": "user-1",
    }
    activity = adapt_from_silver("silver_outcome_facts", silver_row)
    assert activity is not None
    assert activity["surface"] == "server"
    assert activity["sequence_key"] == "000000000007"


def test_projector_row_flows_surface_and_sequence_to_activity_end_to_end():
    """Bronze event → OutcomeProjector row → adapter → CanonicalActivity."""
    result = OutcomeProjector().project(_bronze_event())
    assert result is not None and not result.skipped
    silver_row = result.rows[0]
    assert silver_row["surface"] == "web"
    assert silver_row["sequence_key"] == "000000000042"

    activity = adapt_from_silver(result.table, silver_row)
    assert activity is not None
    assert activity["surface"] == "web"
    assert activity["sequence_key"] == "000000000042"

    # The contract accepts both fields — surface near platform, sequence_key
    # in the ordering/replay block.
    contract = CanonicalActivity(**activity)
    assert contract.surface == "web"
    assert contract.sequence_key == "000000000042"
    assert contract.consent_snapshot_id == "consent-1"


def test_outcome_projector_preserves_only_explicit_prediction_adjudication_refs():
    event = _bronze_event()
    event["properties"].update({
        "predictionId": "ppout_prediction-7",
        "predictionLabelContractVersion": "profile-outcome-labels.v1",
    })
    result = OutcomeProjector().project(event)
    assert result is not None
    row = result.rows[0]
    assert row["prediction_id"] == "ppout_prediction-7"
    assert row["prediction_label_contract_version"] == "profile-outcome-labels.v1"

    # Matching only the entity and timestamp cannot create adjudication refs.
    implicit = OutcomeProjector().project(_bronze_event())
    assert implicit is not None
    assert implicit.rows[0]["prediction_id"] is None
    assert implicit.rows[0]["prediction_label_contract_version"] is None


def test_outcome_projector_discards_malformed_adjudication_refs():
    event = _bronze_event()
    event["properties"].update({
        "predictionId": ["prediction-1"],
        "predictionLabelContractVersion": " " + "x" * 130,
    })
    result = OutcomeProjector().project(event)
    assert result is not None
    assert result.rows[0]["prediction_id"] is None
    assert result.rows[0]["prediction_label_contract_version"] is None


@pytest.mark.asyncio
async def test_outcome_truth_recorder_preserves_explicit_prediction_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import journeys.measurement.outcome.truth_recorder as recorder

    captured = {}

    async def capture(record, store=None, *, register_correlation=True):
        captured["record"] = record
        return record

    monkeypatch.setattr(recorder, "outcome_truth_store_enabled", lambda: True)
    monkeypatch.setattr(recorder, "persist_outcome_truth", capture)
    result = OutcomeProjector().project(_bronze_event())
    assert result is not None
    row = result.rows[0] | {
        "prediction_id": "ppout_explicit-1",
        "prediction_label_contract_version": "profile-outcome-labels.v1",
    }

    await recorder.record_from_silver_outcome(
        tenant_id="tenant-a", row=row, event_id="evt-1"
    )

    assert captured["record"].prediction_id == "ppout_explicit-1"
    assert (
        captured["record"].prediction_label_contract_version
        == "profile-outcome-labels.v1"
    )


def test_adapter_base_defaults_surface_and_sequence_key_to_none():
    silver_row = {
        "tenant_id": "tenant-a",
        "fact_id": "0d4f2c9a-58f5-4a41-b0f8-2b8b7c1e9d10",
        "source_event_id": "evt-2",
        "occurred_at": "2026-07-23T12:00:00+00:00",
        "outcome_type": "goal_achieved",
    }
    activity = adapt_from_silver("silver_outcome_facts", silver_row)
    assert activity is not None
    assert activity["surface"] is None
    assert activity["sequence_key"] is None
