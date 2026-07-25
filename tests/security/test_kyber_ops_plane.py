"""The exception queue and the incident correlator, one claim per test.

These two planes exist to make a single operator's attention survive contact
with a distributed system. Four properties carry that weight, and each is
falsifiable:

* **Compression.** An alert storm is one exception with a count, not a wall of
  duplicates. The migration's partial unique index says one open exception per
  ``dedupe_key``; this pins the read path that cooperates with it.
* **Ordering.** One potential cross-tenant leak outranks any volume of low-risk
  warnings. Volume is the metric easiest to accumulate and least correlated with
  consequence, so it is capped below every consequence term — and that has to be
  true of the *stored ranking*, not just of the weight table.
* **Attributed correlation.** Every signal attached to an incident records the
  basis that attached it, and deterministic bases are distinguishable from
  heuristic ones. A correlation you cannot interrogate is a correlation you
  cannot correct.
* **Resumability.** An operator who walks away mid-response comes back to a card
  that names the next action. An incident with no next action is an incident
  nobody can pick up.

Nothing here needs a database: the repositories fall back to shared in-memory
dicts under ``AETHER_ENV=local``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402

from services.kyber.ops.contracts import IncidentSignal, OperationalException  # noqa: E402
from services.kyber.ops.correlation import (  # noqa: E402
    ATTACHING_BASES,
    BASIS_ERROR_SIGNATURE,
    BASIS_RELEASE,
    IncidentCorrelator,
)
from services.kyber.ops.exceptions import ExceptionService  # noqa: E402
from services.kyber.ops.severity import VOLUME_WEIGHT  # noqa: E402

#: Big enough that a linear volume term would drown the leak, and cheap enough
#: to run in-process.
STORM_SIZE = 250


@pytest.fixture(autouse=True)
def clean_state():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


@pytest.fixture
def exceptions() -> ExceptionService:
    return ExceptionService()


@pytest.fixture
def correlator() -> IncidentCorrelator:
    return IncidentCorrelator()


# ── Compression ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_alert_storm_collapses_into_one_open_exception(exceptions: ExceptionService):
    """One row per ``dedupe_key``, carrying the count — not N rows."""
    stored = []
    for index in range(STORM_SIZE):
        stored.append(
            await exceptions.raise_exception(
                OperationalException(
                    title="connector timeout",
                    severity="low",
                    dedupe_key="connector:hubspot:timeout",
                    affected_services=["connector_hubspot"],
                    metadata={"attempt": index},
                )
            )
        )

    identities = {exc.exception_id for exc in stored}
    assert len(identities) == 1, "compression must land every occurrence on one row"

    queue = await exceptions.queue(limit=500)
    assert queue["total"] == 1
    only = queue["items"][0]
    assert only["signal_count"] == STORM_SIZE
    assert only["status"] == "open"


@pytest.mark.asyncio
async def test_a_resolved_exception_does_not_absorb_a_recurrence(exceptions: ExceptionService):
    """Compression follows status, not age: a recurrence after a fix is news."""
    first = await exceptions.raise_exception(
        OperationalException(title="connector timeout", dedupe_key="connector:hubspot:timeout")
    )
    await exceptions.resolve(first.exception_id, actor_id="op_1", note="connector redeployed")

    second = await exceptions.raise_exception(
        OperationalException(title="connector timeout", dedupe_key="connector:hubspot:timeout")
    )
    assert second.exception_id != first.exception_id
    assert second.signal_count == 1


# ── Ordering ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_security_exposure_outranks_a_storm_of_low_risk_warnings(
    exceptions: ExceptionService,
):
    """Consequence beats volume, in the stored ranking and not only in theory."""
    for index in range(STORM_SIZE):
        await exceptions.raise_exception(
            OperationalException(
                title="deprecated field in payload",
                severity="info",
                confidence=1.0,
                dedupe_key="schema:deprecated_field",
                metadata={"attempt": index},
            )
        )
    # A second, independent low-risk condition, so the queue holds volume in two
    # shapes: many occurrences of one thing and several distinct things.
    for index in range(20):
        await exceptions.raise_exception(
            OperationalException(
                title=f"slow query {index}",
                severity="low",
                confidence=1.0,
                dedupe_key=f"perf:slow_query:{index}",
            )
        )

    leak = await exceptions.raise_exception(
        OperationalException(
            title="tenant records visible to another tenant",
            severity="high",
            # Deliberately *less* certain than the noise, so the test proves
            # consequence wins rather than confidence winning.
            confidence=0.4,
            security_exposure=True,
            data_integrity_exposure=True,
            affected_tenants=["tenant_alpha"],
            dedupe_key="isolation:cross_tenant_read",
        )
    )

    queue = await exceptions.queue(limit=500)
    assert queue["items"][0]["exception_id"] == leak.exception_id
    assert queue["items"][0]["bucket"] == "critical_now"

    noise_scores = [
        item["priority_score"]
        for item in queue["items"]
        if item["exception_id"] != leak.exception_id
    ]
    assert noise_scores, "the storm must actually be in the queue"
    assert leak.priority_score > max(noise_scores)

    # And the mechanism, not just the outcome: the whole volume term is worth
    # less than the leak's margin, so no achievable count reverses this.
    assert VOLUME_WEIGHT < (leak.priority_score - max(noise_scores))
    assert "security_exposure" in leak.priority_inputs["dominant_terms"]


# ── Correlation ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_correlation_records_its_basis_and_separates_deterministic_from_heuristic(
    correlator: IncidentCorrelator,
):
    """Every attachment says *why*, and the why carries its own strength."""
    founding = IncidentSignal(
        source="ops_alert",
        signal_type="error_rate",
        service="ingest",
        release_id="rel_2026_07_25",
        error_signature="ValueError:offset_out_of_range",
        payload={"severity": "high"},
    )
    incident, created = await correlator.ingest_signal(founding)
    assert created is True

    # 1 — same release. Deterministic: one deploy, one cause.
    deterministic = IncidentSignal(
        source="reliability",
        signal_type="failed_events",
        service="projector",
        release_id="rel_2026_07_25",
    )
    same_incident, created = await correlator.ingest_signal(deterministic)
    assert created is False
    assert same_incident.incident_id == incident.incident_id

    # 2 — same error signature, no release and no service, so the stronger bases
    # cannot fire and the heuristic one is what is left.
    heuristic = IncidentSignal(
        source="connector",
        signal_type="warning",
        error_signature="ValueError:offset_out_of_range",
    )
    still_same, created = await correlator.ingest_signal(heuristic)
    assert created is False
    assert still_same.incident_id == incident.incident_id

    stored = {
        signal.signal_id: signal
        for signal in await correlator.signals_for(incident.incident_id)
    }
    recorded_deterministic = stored[deterministic.signal_id]
    recorded_heuristic = stored[heuristic.signal_id]

    assert recorded_deterministic.correlation_basis == BASIS_RELEASE
    assert recorded_deterministic.correlation_confidence == 1.0
    assert recorded_heuristic.correlation_basis == BASIS_ERROR_SIGNATURE
    assert recorded_heuristic.correlation_confidence == 0.7

    # The distinction is the point: a deterministic basis is strictly more
    # confident than a heuristic one, and both are strong enough to attach.
    assert (
        recorded_deterministic.correlation_confidence
        > recorded_heuristic.correlation_confidence
    )
    assert {recorded_deterministic.correlation_basis, recorded_heuristic.correlation_basis} <= (
        ATTACHING_BASES
    )

    refreshed = await correlator.get_incident(incident.incident_id)
    assert refreshed is not None
    bases = {entry["basis"] for entry in refreshed.metadata["correlations"]}
    assert {BASIS_RELEASE, BASIS_ERROR_SIGNATURE} <= bases


@pytest.mark.asyncio
async def test_time_proximity_alone_opens_a_second_incident_and_records_the_coincidence(
    correlator: IncidentCorrelator,
):
    """Over-merging hides a second failure, so a coincidence is not an attachment."""
    first, _ = await correlator.ingest_signal(
        IncidentSignal(source="ops_alert", signal_type="error_rate", service="ingest")
    )
    second, created = await correlator.ingest_signal(
        IncidentSignal(source="billing", signal_type="charge_failed", service="billing")
    )

    assert created is True
    assert second.incident_id != first.incident_id
    weak = second.metadata.get("weak_links") or []
    assert [entry["incident_id"] for entry in weak] == [first.incident_id]
    assert weak[0]["basis"] == "time_proximity"


# ── Resumability ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_resume_card_names_the_next_action(correlator: IncidentCorrelator):
    """An incident nobody can resume is an incident that stalls at a handover."""
    incident, _ = await correlator.ingest_signal(
        IncidentSignal(
            source="ops_alert",
            signal_type="error_rate",
            service="ingest",
            payload={"severity": "critical"},
        )
    )
    await correlator.update_incident(
        incident.incident_id,
        actor_id="op_1",
        status="mitigating",
        last_action="paused the hubspot connector",
        next_action="replay events 41200-41890 once the connector is healthy",
        blocked_by="waiting on connector health check",
        pending_verification=["job_enqueued", "customer_visible_parity"],
        note="handing over",
    )

    cards = await correlator.resume_cards()
    card = next(c for c in cards if c["incident_id"] == incident.incident_id)

    assert card["next_action"] == "replay events 41200-41890 once the connector is healthy"
    assert card["last_action"] == "paused the hubspot connector"
    assert card["blocked_by"] == "waiting on connector health check"
    assert card["pending_verification"] == ["job_enqueued", "customer_visible_parity"]
    assert card["status"] == "mitigating"


@pytest.mark.asyncio
async def test_resolving_an_incident_clears_the_next_action_it_no_longer_has(
    correlator: IncidentCorrelator,
):
    """A resolved incident must not keep advertising work nobody should do."""
    incident, _ = await correlator.ingest_signal(
        IncidentSignal(source="ops_alert", signal_type="error_rate", service="ingest")
    )
    await correlator.update_incident(
        incident.incident_id, actor_id="op_1", status="mitigating", next_action="replay the window"
    )
    resolved = await correlator.resolve_incident(
        incident.incident_id, actor_id="op_1", root_cause="offset regression in rel_2026_07_25"
    )

    assert resolved.next_action is None
    assert resolved.blocked_by is None
    assert resolved.root_cause == "offset regression in rel_2026_07_25"
    cards = await correlator.resume_cards()
    assert all(card["incident_id"] != incident.incident_id for card in cards)
