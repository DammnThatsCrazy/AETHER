"""Fleet-health observability closure (agent 3B).

Pins the Phase-0 gap fix in
:func:`services.integrations.providers.payment_rails.kyber_aggregate.
build_fleet_health`: ``worker_heartbeat`` / ``last_successful_worker_cycle`` /
``outbox_lag`` / ``polling_cursor_age_seconds`` were hardcoded ``None``. These
tests assert they are now COMPUTED from live WorkerSupervisor state and the
durable receipt + provider-account ledgers — while the honest-unknown path (no
supervisor bound) still stays ``None``, never a fabricated 0.

Also covers the WorkerSupervisor → reliability heartbeat bridge
(:func:`services.reliability.service.bridge_worker_supervisor_heartbeats`).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from services.integrations.providers.payment_rails.kyber_aggregate import (  # noqa: E402
    build_fleet_health,
)
from services.integrations.providers.payment_rails.kyber_contract import (  # noqa: E402
    FleetHealthResponse,
)
from services.integrations.providers.payment_rails.receipts import (  # noqa: E402
    ReceiptStage,
)
from services.integrations.providers.payment_rails.repository import (  # noqa: E402
    PaymentRailsRepositories,
)
from services.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
)
from services.reliability.service import (  # noqa: E402
    bridge_worker_supervisor_heartbeats,
    worker_heartbeat_key,
)
from shared.store import (  # noqa: E402
    get_store,
    reset_in_memory_stores as reset_shared_stores,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_stores():
    """Empty both in-memory registries.

    ``build_fleet_health`` reads receipt + provider-account ledgers that live in
    ``shared.store``'s registry, while most repos live in
    ``repositories.repos``'s registry — an xdist worker runs many test files, so
    resetting only one lets payment-rail receipts seeded by earlier files leak
    into these counts. Same dual-reset convention as
    ``tests/payment_rails/test_rollout_and_readiness.py``.
    """
    reset_in_memory_stores()
    reset_shared_stores()
    yield
    reset_in_memory_stores()
    reset_shared_stores()


class _Producer:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)

    async def publish_batch(self, events):
        self.events.extend(events)


def _svc() -> PaymentRailsService:
    return PaymentRailsService(PaymentRailsRepositories(), producer=_Producer())


class _FakeSupervisor:
    """Minimal WorkerSupervisor stand-in exposing ``status()``."""

    def __init__(self, status_map: dict):
        self._status = status_map

    def status(self) -> dict:
        return dict(self._status)


def _worker_status(*, live: bool) -> dict:
    return {
        "state": "running" if live else "failed",
        "heartbeat_age_s": 2.0 if live else 600.0,
        "last_success_at": "2026-08-09T00:00:00Z" if live else None,
        "role": "payment_rails",
    }


async def _seed_outbox_receipt(svc, tenant: str, rid: str) -> None:
    receipt = await svc.repos.receipts.open(
        tenant, "moonpay", provider_event_id=f"evt-{rid}", body_hash=f"h-{rid}"
    )
    receipt["current_stage"] = ReceiptStage.OUTBOX_ENQUEUED
    receipt["outbox_publication_state"] = "enqueued"
    store = get_store("payment_provider_receipts")
    await store.set(f"{tenant}:{receipt['id']}", receipt)


async def test_fleet_health_values_are_computed_not_hardcoded_none():
    """worker_heartbeat / last_success / outbox_lag / cursor age come from real
    state — the Phase-0 hardcoded-None gap."""
    svc = _svc()
    tenant = f"t-{uuid.uuid4().hex[:8]}"

    # Two receipts parked at outbox_enqueued → durable outbox lag of 2.
    await _seed_outbox_receipt(svc, tenant, "r1")
    await _seed_outbox_receipt(svc, tenant, "r2")

    # A provider account with a fresh successful poll → fleet cursor age.
    # Relative to now so the expected age is deterministic, not wall-clock-tied.
    last_poll_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace(
        "+00:00", "Z"
    )
    await svc.repos.accounts.upsert(tenant, "moonpay", {
        "last_poll_at": last_poll_at,
        "provider_poll_health": "ok",
    })

    # A live supervisor: one worker running with a fresh heartbeat and a
    # recorded successful cycle.
    supervisor = _FakeSupervisor({
        "payment_rail_sync_worker": _worker_status(live=True),
        "payment_rail_repair_worker": _worker_status(live=False),
    })

    response = await build_fleet_health(svc, supervisor=supervisor)
    parsed = FleetHealthResponse.model_validate(response.model_dump(mode="json"))

    # Worker liveness is computed from the live supervisor (running + fresh
    # heartbeat), never None.
    assert parsed.totals.worker_heartbeat is True
    # The newest last_success_at across workers is folded through.
    assert parsed.totals.last_successful_worker_cycle == "2026-08-09T00:00:00Z"
    # Outbox lag is the computed receipt-ledger count, never None.
    assert parsed.totals.outbox_lag == 2

    # Fleet cursor age is derived from the account ledger for a polling adapter
    # (~10 minutes old, computed — never None, never a fabricated 0).
    moonpay = next(p for p in parsed.providers if p.provider == "moonpay")
    assert moonpay.polling_cursor_age_seconds is not None
    assert 480.0 <= moonpay.polling_cursor_age_seconds <= 1200.0

    # The fleet-health gauges are emitted (dashboard metric source). The
    # collector backs gauges in the histogram store; presence is enough here.
    from shared.logger.logger import metrics

    snap = metrics.snapshot()
    assert "kyber_fleet_worker_heartbeat" in snap.get("histograms", {})
    assert "kyber_fleet_outbox_lag" in snap.get("histograms", {})


async def test_fleet_health_unknown_when_no_supervisor():
    """No supervisor bound → worker liveness stays None (honest unknown), NOT
    a fabricated 0/False. The other ledgers still compute real values."""
    svc = _svc()
    await _seed_outbox_receipt(svc, f"t-{uuid.uuid4().hex[:8]}", "r1")

    response = await build_fleet_health(svc, supervisor=None)
    parsed = FleetHealthResponse.model_validate(response.model_dump(mode="json"))
    assert parsed.totals.worker_heartbeat is None
    assert parsed.totals.last_successful_worker_cycle is None
    # outbox lag remains computed even with no supervisor (ledger is readable).
    assert parsed.totals.outbox_lag == 1


async def test_fleet_health_liveness_false_when_workers_stale_or_failed():
    """Workers exist but none is live → worker_heartbeat is False (deliberately
    not healthy), still never None."""
    svc = _svc()
    supervisor = _FakeSupervisor({
        "payment_rail_sync_worker": _worker_status(live=False),
    })
    response = await build_fleet_health(svc, supervisor=supervisor)
    parsed = FleetHealthResponse.model_validate(response.model_dump(mode="json"))
    assert parsed.totals.worker_heartbeat is False
    assert parsed.totals.last_successful_worker_cycle is None


async def test_reliability_heartbeat_bridge_folds_supervisor_state():
    """WorkerSupervisor heartbeats land in the reliability registry with honest
    status verdicts (running→healthy, failed→critical) + last-success."""
    supervisor = _FakeSupervisor({
        "payment_rail_sync_worker": _worker_status(live=True),
        "payment_rail_repair_worker": _worker_status(live=False),
    })
    records = await bridge_worker_supervisor_heartbeats(supervisor)

    sync_key = worker_heartbeat_key("payment_rail_sync_worker", "payment_rails")
    repair_key = worker_heartbeat_key("payment_rail_repair_worker", "payment_rails")
    assert sync_key in records
    assert repair_key in records

    # The running worker certified healthy and its successful cycle is recorded.
    sync_record = records[sync_key]
    assert sync_record.get("status") == "healthy"
    assert sync_record.get("last_successful_job_at")
    # The failed worker is honestly critical — never a fabricated healthy.
    assert records[repair_key].get("status") == "critical"

    # No supervisor bound → silence, not an error.
    assert await bridge_worker_supervisor_heartbeats(None) == {}
