"""WS-D Silver-boundary tests: items 5 (temporal), 7 (exact money), 3 (outcome
truth store) + flag-OFF byte parity.
"""

from __future__ import annotations

import pytest

# ── Item 7: Silver exact money ──────────────────────────────────────────────


def _event(event_type, properties, message_id="m-1"):
    return {
        "type": event_type,
        "messageId": message_id,
        "timestamp": "2026-09-06T00:00:00Z",
        "userId": "u-1",
        "context": {"tenantId": "tenant-a"},
        "properties": properties,
    }


def test_revenue_money_off_is_byte_parity(wsd_flags):
    from services.silver.projectors.revenue_projector import RevenueProjector

    wsd_flags()  # all WS-D flags OFF
    row = RevenueProjector().project(
        _event("order_completed", {})
    ).rows[0]
    # Historical collapse preserved byte-for-byte when the flag is OFF.
    assert row["amount"] == 0.0
    assert row["currency"] == "USD"
    assert "amount_exact" not in row and "currency_exact" not in row


def test_revenue_money_on_is_exact_and_never_fabricates(wsd_flags):
    from services.silver.projectors.revenue_projector import RevenueProjector

    wsd_flags(silver_exact_money_enabled=True)
    # Missing money -> typed absence, never 0.0/USD.
    missing = RevenueProjector().project(
        _event("order_completed", {})
    ).rows[0]
    assert missing["amount"] is None
    assert missing["currency"] is None
    assert missing["amount_exact"] is None
    assert missing["currency_exact"] is None

    # Present money -> exact decimal string + verbatim currency.
    present = RevenueProjector().project(
        _event("order_completed", {"amount": "12.5000", "currency": "EUR"})
    ).rows[0]
    assert present["amount_exact"] == "12.5000"
    assert present["currency_exact"] == "EUR"
    assert present["amount"] == 12.5


def test_outcome_money_off_on(wsd_flags):
    from services.silver.projectors.outcome_projector import OutcomeProjector

    wsd_flags()
    off = OutcomeProjector().project(
        _event("goal_achieved", {})
    ).rows[0]
    assert off["value_currency"] == "USD"
    assert "value_amount_exact" not in off

    wsd_flags(silver_exact_money_enabled=True)
    on = OutcomeProjector().project(
        _event("goal_achieved", {"value": "99.9900", "currency": "GBP"})
    ).rows[0]
    assert on["value_amount_exact"] == "99.9900"
    assert on["value_currency_exact"] == "GBP"
    assert on["value_currency"] == "GBP"

    missing = OutcomeProjector().project(
        _event("goal_achieved", {})
    ).rows[0]
    assert missing["value_amount_exact"] is None
    assert missing["value_currency_exact"] is None
    assert missing["value_currency"] is None


# ── Item 5: temporal envelope reaches Silver ────────────────────────────────


def test_silver_temporal_off_preserves_raw_timestamp(wsd_flags):
    from services.ingestion.workers import _apply_silver_temporal

    wsd_flags(silver_temporal_envelope_enabled=False)
    envelope = {"timestamp": "2026-09-06T00:00:00Z", "messageId": "m-1"}
    payload = {
        "temporal": {"occurred_at": "2026-09-06T12:34:56Z", "temporal_state": "valid"}
    }
    out = _apply_silver_temporal(payload, envelope)
    # Byte parity: timestamp untouched.
    assert out is envelope
    assert out["timestamp"] == "2026-09-06T00:00:00Z"
    assert "temporal" not in out


def test_silver_temporal_on_uses_server_occurred_at(wsd_flags):
    from services.ingestion.workers import _apply_silver_temporal

    wsd_flags(silver_temporal_envelope_enabled=True)
    envelope = {"timestamp": "2026-09-06T00:00:00Z", "messageId": "m-1"}
    payload = {
        "temporal": {
            "occurred_at": "2026-09-06T12:34:56.123+00:00",
            "temporal_state": "normalized",
            "reason_codes": ["timezone_normalized"],
        }
    }
    out = _apply_silver_temporal(payload, envelope)
    assert out["timestamp"] == "2026-09-06T12:34:56.123+00:00"
    assert out["temporal"]["temporal_state"] == "normalized"


def test_silver_temporal_on_without_payload_temporal_is_unchanged(wsd_flags):
    from services.ingestion.workers import _apply_silver_temporal

    wsd_flags(silver_temporal_envelope_enabled=True)
    envelope = {"timestamp": "2026-09-06T00:00:00Z"}
    assert _apply_silver_temporal({}, envelope) is envelope


@pytest.mark.asyncio
async def test_silver_fact_rows_carry_server_occurred_at(wsd_flags):
    """Temporal-integrity: a projector row's occurred_at follows the envelope."""
    from services.silver.projectors.revenue_projector import RevenueProjector

    wsd_flags(silver_temporal_envelope_enabled=True)
    env = _event("order_completed", {"amount": "10.00"})
    env["timestamp"] = "2026-09-06T12:34:56.123+00:00"
    env["temporal"] = {"occurred_at": "2026-09-06T12:34:56.123+00:00"}
    row = RevenueProjector().project(env).rows[0]
    assert row["occurred_at"] == "2026-09-06T12:34:56.123+00:00"


# ── Item 3: durable outcome-truth recorder + provider read ──────────────────


@pytest.mark.asyncio
async def test_outcome_truth_recorder_flag_off_is_noop(wsd_flags):
    from shared.backend_interpretation.primitives import OutcomeTruthRecord
    from services.measurement.outcome.truth_recorder import persist_outcome_truth

    wsd_flags()
    record = OutcomeTruthRecord(
        outcome_id="oc-1", tenant_id="tenant-a", definition_ref="goal_achieved",
        state="final", evidence_refs=[], source_event_ids=["e-1"],
    )
    assert await persist_outcome_truth(record) is None


@pytest.mark.asyncio
async def test_outcome_truth_recorder_retains_lineage(wsd_flags):
    from shared.store import reset_in_memory_stores
    from shared.backend_interpretation.stores import OutcomeTruthStore
    from services.measurement.outcome.truth_recorder import record_from_silver_outcome

    reset_in_memory_stores()
    wsd_flags(outcome_truth_store_enabled=True)
    row = {
        "outcome_type": "goal_achieved",
        "goal_id": "g-1",
        "occurred_at": "2026-09-06T00:00:00Z",
        "value_amount": "42.00",
        "value_currency": "USD",
        "user_id": "u-1",
    }
    recorded = await record_from_silver_outcome(
        tenant_id="tenant-a",
        row=row,
        event_id="evt-1",
        model_version="compiler-v1",
        policy_version="policy:v1",
    )
    assert recorded is not None
    loaded = await OutcomeTruthStore().get("tenant-a", recorded.outcome_id)
    assert loaded is not None
    # Evidence + model/policy lineage retained (the drop this item closes).
    assert [r.id for r in loaded.evidence_refs] == ["evt-1"]
    assert loaded.source_event_ids == ["evt-1"]
    assert loaded.model_version == "compiler-v1"
    assert loaded.policy_version == "policy:v1"
    assert loaded.state == "final"
    assert loaded.value_state == "present"


@pytest.mark.asyncio
async def test_outcome360_provider_reads_durable_truth(wsd_flags):
    from shared.store import reset_in_memory_stores
    from shared.intelligence_projections import (
        ProjectionContext,
        ProjectionRequest,
        ProjectionSubject,
    )
    from services.operational_intelligence.models import EntityRef
    from services.measurement.outcome.truth_recorder import record_from_silver_outcome
    from services.measurement.outcome.provider import Outcome360Provider

    reset_in_memory_stores()
    wsd_flags(outcome_truth_store_enabled=True)
    row = {
        "outcome_type": "goal_achieved",
        "goal_id": "g-1",
        "occurred_at": "2026-09-06T00:00:00Z",
        "value_amount": "42.00",
        "value_currency": "USD",
        "user_id": "u-1",
    }
    await record_from_silver_outcome(
        tenant_id="tenant-a", row=row, event_id="evt-1",
        model_version="compiler-v1",
        subject=EntityRef(kind="user", id="u-1"),
    )
    request = ProjectionRequest(
        projectionId="outcome360",
        tenantId="tenant-a",
        # Durable row subject kind is "user" (rich EntityRef); the projection
        # request addresses it with the coarse registry kind "entity" + same id.
        subject=ProjectionSubject(kind="entity", id="u-1"),
    )
    context = ProjectionContext(
        projectionId="outcome360", tenantId="tenant-a",
        registryState="in_flight", dependencyState=[], warnings=[],
    )
    result = await Outcome360Provider().project(request, context)
    by_id = {s.id: s for s in result.sections}
    assert by_id["outcomes"].state == "available"
    outcomes = by_id["outcomes"].content["outcomes"]
    assert len(outcomes) == 1
    assert outcomes[0]["definition_ref"] == "goal_achieved"
    assert result.claims and all(c.evidenceRefs for c in result.claims)
