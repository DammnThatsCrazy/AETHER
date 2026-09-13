"""Tests for the payment-rail derived-condition alert evaluator.

WHY THIS FILE EXISTS
--------------------
It exercises ``services/integrations/providers/payment_rails/alert_eval.py`` — the
"alert-evaluator depth" gap. The plane emitted plenty of metrics but nothing
EVALUATED the derived conditions that have no clean single-series PromQL form,
above all the reconciliation-conflict backlog (which is only knowable from the
durable reconciliation records, never a counter).

Two guards these tests pin down explicitly:
* **"unknown must never render as 0".** A plane that has never seen a webhook must
  classify no-webhook as UNKNOWN with ``value=None`` — never a fresh 0-second age.
  ``test_no_webhook_none_is_unknown_never_zero`` and ``test_evaluate_empty_plane``
  lock this in.
* **"no secret in an alert".** ``test_evaluate_never_leaks_secret_material`` seeds
  receipt records carrying sentinel provider ids and asserts the sentinel never
  appears anywhere in the serialized report or any condition message.

The pure ``classify_*`` functions are tested with hand-built thresholds (no store,
no settings); the async ``evaluate_payment_rail_alerts`` is tested against a
seeded in-memory service so the durable-read wiring is covered end-to-end.
"""

from __future__ import annotations

import dataclasses
import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails.alert_eval import (  # noqa: E402
    AlertReport,
    AlertSeverity,
    AlertThresholds,
    classify_canonical_backlog,
    classify_dead_letters,
    classify_no_webhook,
    classify_oldest_incomplete_receipt,
    classify_reconciliation_conflicts,
    classify_reconciliation_stale,
    classify_verification_failures,
    evaluate_payment_rail_alerts,
)
from services.integrations.providers.payment_rails.receipts import (  # noqa: E402
    ReceiptStage,
    ReceiptState,
)
from services.integrations.providers.payment_rails.repository import (  # noqa: E402
    PaymentRailsRepositories,
)
from services.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
)

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _thresholds(**overrides) -> AlertThresholds:
    """A compact, explicit threshold set for the pure classifier tests."""
    base = dict(
        no_webhook_seconds=3600.0,
        oldest_receipt_warn_seconds=900.0,
        oldest_receipt_critical_seconds=3600.0,
        canonical_backlog_warn=50.0,
        canonical_backlog_critical=200.0,
        dead_letter_warn=1.0,
        dead_letter_critical=10.0,
        reconciliation_conflict_warn=1.0,
        reconciliation_conflict_critical=25.0,
        reconciliation_stale_warn=25.0,
        verification_failure_window_seconds=300.0,
        verification_failure_warn=5.0,
        verification_failure_critical=25.0,
    )
    base.update(overrides)
    return AlertThresholds(**base)


# ── Pure classifier: the "unknown is never 0" guard ───────────────────────────
def test_no_webhook_none_is_unknown_never_zero():
    """A plane that has never seen a webhook is UNKNOWN, not a fresh 0s age."""
    c = classify_no_webhook(None, _thresholds())
    assert c.severity == AlertSeverity.UNKNOWN
    assert c.observed is False
    assert c.value is None  # the load-bearing guard: never coerced to 0.0
    assert not c.firing


def test_no_webhook_fresh_is_ok_and_stale_warns():
    t = _thresholds(no_webhook_seconds=3600.0)
    ok = classify_no_webhook(120.0, t)
    assert ok.severity == AlertSeverity.OK and ok.value == 120.0
    warn = classify_no_webhook(7200.0, t)
    assert warn.severity == AlertSeverity.WARNING and warn.firing


# ── Pure classifier: oldest-incomplete-receipt ("none" means healthy 0) ───────
def test_oldest_incomplete_none_is_ok_zero():
    c = classify_oldest_incomplete_receipt(None, _thresholds())
    assert c.severity == AlertSeverity.OK and c.value == 0.0


def test_oldest_incomplete_warn_and_critical():
    t = _thresholds(oldest_receipt_warn_seconds=900.0, oldest_receipt_critical_seconds=3600.0)
    assert classify_oldest_incomplete_receipt(300.0, t).severity == AlertSeverity.OK
    assert classify_oldest_incomplete_receipt(1200.0, t).severity == AlertSeverity.WARNING
    crit = classify_oldest_incomplete_receipt(4000.0, t)
    assert crit.severity == AlertSeverity.CRITICAL and crit.threshold == 3600.0


# ── Pure classifier: backlog / dead-letters / conflicts / stale / verification ─
def test_canonical_backlog_ladder():
    t = _thresholds(canonical_backlog_warn=50.0, canonical_backlog_critical=200.0)
    assert classify_canonical_backlog(10, t).severity == AlertSeverity.OK
    assert classify_canonical_backlog(60, t).severity == AlertSeverity.WARNING
    assert classify_canonical_backlog(500, t).severity == AlertSeverity.CRITICAL


def test_dead_letters_any_warns_batch_critical():
    """A dead-letter must never be silent: one warns, a batch is critical."""
    t = _thresholds(dead_letter_warn=1.0, dead_letter_critical=10.0)
    assert classify_dead_letters(0, t).severity == AlertSeverity.OK
    assert classify_dead_letters(1, t).severity == AlertSeverity.WARNING
    assert classify_dead_letters(12, t).severity == AlertSeverity.CRITICAL


def test_reconciliation_conflicts_any_warns_burst_critical():
    """The genuinely-missing signal: any conflict warns, a burst is critical."""
    t = _thresholds(reconciliation_conflict_warn=1.0, reconciliation_conflict_critical=25.0)
    assert classify_reconciliation_conflicts(0, t).severity == AlertSeverity.OK
    assert classify_reconciliation_conflicts(1, t).severity == AlertSeverity.WARNING
    assert classify_reconciliation_conflicts(30, t).severity == AlertSeverity.CRITICAL


def test_reconciliation_stale_warn_only():
    t = _thresholds(reconciliation_stale_warn=25.0)
    assert classify_reconciliation_stale(10, t).severity == AlertSeverity.OK
    assert classify_reconciliation_stale(40, t).severity == AlertSeverity.WARNING


def test_verification_failures_ladder():
    t = _thresholds(verification_failure_warn=5.0, verification_failure_critical=25.0)
    assert classify_verification_failures(2, t).severity == AlertSeverity.OK
    assert classify_verification_failures(8, t).severity == AlertSeverity.WARNING
    assert classify_verification_failures(40, t).severity == AlertSeverity.CRITICAL


def test_classifier_messages_carry_no_record_content():
    """Messages are built from numbers/keys only — never record content."""
    t = _thresholds()
    for cond in (
        classify_no_webhook(None, t),
        classify_canonical_backlog(123, t),
        classify_reconciliation_conflicts(7, t),
        classify_dead_letters(3, t),
    ):
        # Only ASCII digits, the threshold phrasing, and stable words appear.
        assert "secret" not in cond.message.lower()
        assert "whsec" not in cond.message.lower()


# ── Env-aware threshold wiring ────────────────────────────────────────────────
def test_from_settings_is_env_aware(monkeypatch):
    """AlertThresholds.from_settings reflects settings.payment_rails (per-env)."""
    monkeypatch.setattr(
        settings,
        "payment_rails",
        dataclasses.replace(
            settings.payment_rails,
            alert_canonical_backlog_warn=7,
            alert_reconciliation_conflict_critical=99,
            alert_no_webhook_seconds=111,
        ),
    )
    t = AlertThresholds.from_settings()
    assert t.canonical_backlog_warn == 7.0
    assert t.reconciliation_conflict_critical == 99.0
    assert t.no_webhook_seconds == 111.0


# ── Async wiring: durable-state reads ─────────────────────────────────────────
def _svc() -> PaymentRailsService:
    class _NullProducer:
        async def publish(self, event):  # pragma: no cover - never called (read-only)
            return None

        async def publish_batch(self, events):  # pragma: no cover
            return None

    return PaymentRailsService(repositories=PaymentRailsRepositories(), producer=_NullProducer())


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
        {"id": fsid, "tenant_id": tenant, "funding_session_id": fsid,
         "provider": "moonpay", "state": state},
    )


@pytest.mark.asyncio
async def test_evaluate_empty_plane_is_unknown_not_healthy_zero():
    """No receipts/records: no-webhook is UNKNOWN (value None), the rest OK."""
    reset_in_memory_stores()
    report = await evaluate_payment_rail_alerts(service=_svc(), now=NOW, thresholds=_thresholds())
    assert isinstance(report, AlertReport)
    by = report.by_key
    assert by["no_webhook_in_window"].severity == AlertSeverity.UNKNOWN
    assert by["no_webhook_in_window"].value is None  # unknown, NOT zero
    assert by["oldest_incomplete_receipt"].severity == AlertSeverity.OK
    assert by["canonical_backlog"].severity == AlertSeverity.OK
    assert by["reconciliation_conflict"].severity == AlertSeverity.OK
    assert report.firing == []  # UNKNOWN is not a firing severity


@pytest.mark.asyncio
async def test_evaluate_reads_durable_state_and_classifies():
    """Seed a stuck receipt, a dead-letter, a fresh webhook, and a conflict."""
    reset_in_memory_stores()
    svc = _svc()
    # A healthy, recent, completed webhook receipt (proves no-webhook is fresh).
    await _put_receipt(svc, "t1", "r_ok", source="webhook",
                       current_stage=ReceiptStage.COMPLETED,
                       received_at="2026-01-01T11:59:00+00:00")
    # A delivery stuck short of completed for ~30m → incomplete, past warn (900s)
    # but under critical (3600s).
    await _put_receipt(svc, "t1", "r_stuck", source="polling",
                       current_stage=ReceiptStage.NORMALIZED,
                       received_at="2026-01-01T11:30:00+00:00")
    # A dead-lettered receipt (needs manual replay).
    await _put_receipt(svc, "t1", "r_dead", source="webhook",
                       current_stage=ReceiptState.DEAD_LETTERED,
                       received_at="2026-01-01T09:00:00+00:00")
    # A conflicted reconciliation record — the genuinely-missing signal.
    await _put_reconciliation(svc, "t1", "fs_conflict", "conflict")

    report = await evaluate_payment_rail_alerts(service=svc, now=NOW, thresholds=_thresholds())
    by = report.by_key

    assert by["no_webhook_in_window"].severity == AlertSeverity.OK  # r_ok is recent
    # canonical backlog = incomplete receipts only; the dead-lettered receipt is
    # in a hard-terminal state and is counted by dead_letter_backlog instead.
    assert by["canonical_backlog"].value == 1.0
    assert by["oldest_incomplete_receipt"].severity == AlertSeverity.WARNING  # ~30m: warn
    assert by["dead_letter_backlog"].severity == AlertSeverity.WARNING
    assert by["reconciliation_conflict"].severity == AlertSeverity.WARNING
    firing_keys = {c.key for c in report.firing}
    assert {"oldest_incomplete_receipt", "dead_letter_backlog", "reconciliation_conflict"} <= firing_keys


@pytest.mark.asyncio
async def test_recent_verification_failures_are_counted_within_window():
    reset_in_memory_stores()
    svc = _svc()
    # A quarantined webhook 1 minute ago → inside the 300s window.
    await _put_receipt(svc, "t1", "r_recent_bad", source="webhook",
                       current_stage=ReceiptState.QUARANTINED, verification_state="rejected",
                       received_at="2026-01-01T11:59:00+00:00",
                       last_attempted_at="2026-01-01T11:59:00+00:00")
    # A rejected webhook 1 hour ago → outside the window (not counted).
    await _put_receipt(svc, "t1", "r_old_bad", source="webhook",
                       current_stage=ReceiptState.REJECTED, verification_state="rejected",
                       received_at="2026-01-01T11:00:00+00:00",
                       last_attempted_at="2026-01-01T11:00:00+00:00")

    report = await evaluate_payment_rail_alerts(
        service=svc, now=NOW,
        thresholds=_thresholds(verification_failure_warn=1.0, verification_failure_critical=5.0),
    )
    cond = report.by_key["webhook_verification_failures"]
    assert cond.value == 1.0  # only the in-window failure
    assert cond.severity == AlertSeverity.WARNING


@pytest.mark.asyncio
async def test_evaluate_never_leaks_secret_material():
    """A provider id / body hash on a record must never surface in an alert."""
    reset_in_memory_stores()
    svc = _svc()
    sentinel = "whsec_SUPERSECRET_leak_canary"
    await _put_receipt(svc, "t1", sentinel, source="webhook",
                       current_stage=ReceiptStage.NORMALIZED,
                       received_at="2026-01-01T09:30:00+00:00")
    await _put_reconciliation(svc, "t1", sentinel, "conflict")

    report = await evaluate_payment_rail_alerts(service=svc, now=NOW, thresholds=_thresholds())
    serialized = repr(report.to_dict()) + " ".join(c.message for c in report.conditions)
    assert "SUPERSECRET" not in serialized
    assert sentinel not in serialized
