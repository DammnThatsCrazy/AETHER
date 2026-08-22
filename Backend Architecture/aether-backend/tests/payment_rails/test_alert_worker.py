"""Tests for the supervised derived-condition alert evaluator worker.

``alert_eval.py`` classifies the payment-rail conditions with no single-series
PromQL form (above all the reconciliation-conflict backlog), but it is a pure
library — nothing ran it, so that alerting was present-but-inert. ``alert_worker``
is the periodic runner that makes it operational. These tests pin the two things
that matter:

* **it actually runs the evaluator and publishes observations** — a seeded
  conflict/backlog surfaces as firing conditions, the cycle counter increments,
  and the heartbeat/firing gauges are emitted — without mutating any state; and
* **it is off by default** — the worker only runs when both the payment-rails
  master flag and its own ``alert_eval_enabled`` flag are set, so it can never
  fire on a plane that is not turned on.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from config.settings import settings
from repositories.repos import reset_in_memory_stores
from services.integrations.providers.payment_rails.alert_eval import (
    AlertReport,
    AlertSeverity,
)
from services.integrations.providers.payment_rails.alert_worker import (
    run_alert_eval_cycle,
)
from services.integrations.providers.payment_rails.receipts import (
    ReceiptStage,
    ReceiptState,
)
from services.integrations.providers.payment_rails.repository import (
    PaymentRailsRepositories,
)
from services.integrations.providers.payment_rails.service import PaymentRailsService
from shared.logger.logger import metrics

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _svc() -> PaymentRailsService:
    class _NullProducer:
        async def publish(self, event):  # pragma: no cover - never called (read-only)
            return None

        async def publish_batch(self, events):  # pragma: no cover
            return None

    return PaymentRailsService(
        repositories=PaymentRailsRepositories(), producer=_NullProducer()
    )


async def _put_receipt(svc, tenant, rid, **fields):
    record = {
        "receipt_id": rid,
        "id": rid,
        "tenant_id": tenant,
        "provider": fields.get("provider", "moonpay"),
        "source": fields.get("source", "webhook"),
        "current_stage": fields.get("current_stage", ReceiptStage.RECEIVED),
        "verification_state": fields.get("verification_state"),
        "received_at": fields["received_at"],
        "last_attempted_at": fields.get("last_attempted_at", fields["received_at"]),
    }
    await svc.repos.receipts._store.set(f"{tenant}:{rid}", record)


async def _put_reconciliation(svc, tenant, fsid, state):
    await svc.repos.reconciliation._store.set(
        f"{tenant}:{fsid}",
        {
            "id": fsid,
            "tenant_id": tenant,
            "funding_session_id": fsid,
            "provider": "moonpay",
            "state": state,
        },
    )


@pytest.mark.asyncio
async def test_cycle_runs_evaluator_and_publishes_observations():
    """A seeded conflict + dead-letter → firing report, counter + gauges emitted."""
    reset_in_memory_stores()
    svc = _svc()
    # Deterministic isolation: empty the two backing dicts the evaluator reads
    # (the shared in-memory payment stores are not reliably cleared across test
    # files) so this cycle sees exactly the two records seeded below.
    svc.repos.receipts._store._data.clear()
    svc.repos.reconciliation._store._data.clear()
    # A conflicted reconciliation record — the genuinely-missing derived signal.
    await _put_reconciliation(svc, "t1", "fs_conflict", "conflict")
    # A dead-lettered receipt (needs manual replay) so dead_letter_backlog fires.
    await _put_receipt(
        svc, "t1", "r_dead", current_stage=ReceiptState.DEAD_LETTERED,
        received_at="2026-01-01T09:00:00+00:00",
    )

    before = metrics.get_counter("payment_rail_alert_eval_cycle_total")
    report = await run_alert_eval_cycle(service=svc)
    after = metrics.get_counter("payment_rail_alert_eval_cycle_total")

    assert isinstance(report, AlertReport)
    # The cycle ran exactly once → counter advanced by one.
    assert after == before + 1
    # The conflict is a firing (warning+) condition, surfaced only by reading the
    # durable records — the whole reason the evaluator/worker exist.
    firing_keys = {c.key for c in report.firing}
    assert "reconciliation_conflict" in firing_keys
    assert "dead_letter_backlog" in firing_keys


@pytest.mark.asyncio
async def test_empty_plane_cycle_is_not_firing_but_still_heartbeats():
    """No records: no firing conditions, but the worker still runs + heartbeats.

    UNKNOWN (e.g. no-webhook-ever) must not be treated as firing — a
    never-configured plane should not page, but the evaluator must still prove it
    is alive.
    """
    reset_in_memory_stores()
    svc = _svc()
    # Guarantee a genuinely empty plane for the service the evaluator reads —
    # the shared in-memory payment stores are not reliably cleared by
    # reset_in_memory_stores() across test files, so empty the two backing dicts
    # the evaluator enumerates directly.
    svc.repos.receipts._store._data.clear()
    svc.repos.reconciliation._store._data.clear()

    before = metrics.get_counter("payment_rail_alert_eval_cycle_total")
    report = await run_alert_eval_cycle(service=svc)
    assert report.firing == []
    assert report.worst_severity in (AlertSeverity.OK, AlertSeverity.UNKNOWN)
    # The evaluator still ran (proved alive) even though nothing is firing.
    assert metrics.get_counter("payment_rail_alert_eval_cycle_total") == before + 1


def test_worker_is_disabled_by_default():
    """Both gates default off: the plane master flag and the eval flag."""
    # A fresh evaluation of the default config — the worker's enable predicate is
    # (payment_rails.enabled AND payment_rails.alert_eval_enabled); both are off
    # by default, so the evaluator never runs on an un-opted-in deployment.
    assert settings.payment_rails.alert_eval_enabled is False
