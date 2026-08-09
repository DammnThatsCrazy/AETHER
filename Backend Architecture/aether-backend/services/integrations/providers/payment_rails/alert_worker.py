"""Payment Rail Observability — supervised derived-condition alert evaluator.

The Prometheus rules in ``deploy/observability/prometheus/alert_rules.yml`` cover
the payment-rail conditions expressible as a single-series PromQL threshold. But
several operationally critical signals have **no** clean single-series form —
above all the reconciliation-conflict backlog (an SDK-vs-provider truth
disagreement piling up), which is not emitted as a counter and can only be known
by reading the durable reconciliation records. ``alert_eval.py`` classifies those
derived conditions, but it is a pure library: **nothing runs it**. Without this
worker the derived alerting is present-but-inert — an operator would discover a
degrading delivery plane during an incident instead of being paged.

This supervised worker closes that gap. Each cycle it runs
:func:`evaluate_payment_rail_alerts` (read-only), then publishes, for every
classified condition, a labelled severity gauge (``ok=0 unknown=1 warning=2
critical=3`` so Prometheus/dashboards can alert on and graph each condition
independently), a firing-count gauge, a worst-severity gauge, and a heartbeat;
and it logs every *firing* (warning/critical) condition. The evaluator guarantees
no secret or provider payload ever appears in a condition message, so the logs
and metrics are safe.

Gated behind ``AETHER_PAYMENT_ALERT_EVAL_ENABLED`` (default off) **and** the
payment-rails master flag, so it never runs when the plane is off. Read-only and
idempotent by construction: it emits observations, never mutates state. Aether
observes; this worker never executes, settles, or custodies.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics

from services.integrations.providers.payment_rails.alert_eval import (
    AlertReport,
    AlertSeverity,
    evaluate_payment_rail_alerts,
)
from services.integrations.providers.payment_rails.lifecycle import (
    rollout_control_permitted,
)
from services.integrations.providers.payment_rails.models import utc_now_iso

logger = get_logger("aether.payment_rails.alert_worker")

# Default cadence. The evaluator is a cheap read of the receipt/reconciliation
# ledgers; a sweep every few minutes surfaces a degrading plane well inside any
# human response window without hammering the stores.
PAYMENT_RAIL_ALERT_EVAL_INTERVAL_SECONDS = 5 * 60

# Gauge encoding for a condition's severity. Ordered so a dashboard threshold can
# fire at >=2 (warning) and a value of 1 (unknown) is visibly distinct from 0
# (ok) — the whole point of the evaluator is that "no data" is not "healthy".
_SEVERITY_GAUGE_RANK: dict[str, float] = {
    AlertSeverity.OK: 0.0,
    AlertSeverity.UNKNOWN: 1.0,
    AlertSeverity.WARNING: 2.0,
    AlertSeverity.CRITICAL: 3.0,
}


async def run_alert_eval_cycle(*, service: Optional[Any] = None) -> AlertReport:
    """Run one evaluation pass and publish its observations.

    Returns the :class:`AlertReport` so callers/tests can assert on it. Emits
    only metrics + logs; never mutates payment state. ``service`` is injectable
    so tests exercise this against a seeded in-memory service with no globals.
    """
    # Lifecycle gate: the derived-condition evaluator is a rollout control. It
    # may only emit when its flag is on AND the payment-rails capability
    # lifecycle stage is at/above the control's minimum. When the stage is not
    # declared the gate fails open to the flag, so an un-declared deployment is
    # byte-for-byte unchanged. Blocked → emit an empty report (never run the
    # evaluator): observability must not silently go dark when demoted, it must
    # report "no data".
    if not await rollout_control_permitted("derived_alert_evaluator"):
        return AlertReport(conditions=(), generated_at=utc_now_iso())

    report = await evaluate_payment_rail_alerts(service=service)

    # One labelled gauge per condition so each derived signal is independently
    # graphable/alertable (e.g. the reconciliation-conflict backlog stands on its
    # own even though no counter exists for it).
    for condition in report.conditions:
        metrics.gauge(
            "payment_rail_alert_condition_severity",
            _SEVERITY_GAUGE_RANK.get(condition.severity, 0.0),
            labels={"condition": condition.key},
        )
    metrics.gauge("payment_rail_alerts_firing", float(len(report.firing)))
    metrics.gauge(
        "payment_rail_alert_worst_severity",
        _SEVERITY_GAUGE_RANK.get(report.worst_severity, 0.0),
    )
    metrics.gauge("payment_rail_alert_eval_heartbeat", 1.0)
    metrics.increment("payment_rail_alert_eval_cycle_total")

    # Log every firing (warning/critical) condition. The evaluator contractually
    # keeps secrets/payloads out of the message, so verbatim logging is safe.
    for condition in report.firing:
        logger.warning(
            "payment_rail_alert firing key=%s severity=%s value=%s threshold=%s: %s",
            condition.key,
            condition.severity,
            condition.value,
            condition.threshold,
            condition.message,
        )
    return report


async def run_payment_alert_eval_loop(
    interval_seconds: int = PAYMENT_RAIL_ALERT_EVAL_INTERVAL_SECONDS,
) -> None:
    """Supervised periodic derived-condition evaluation sweep."""
    while True:
        try:
            await run_alert_eval_cycle()
        except Exception as exc:  # pragma: no cover — supervisor also guards
            logger.warning("payment_rail_alert_eval cycle failed: %s", exc)
            metrics.increment(
                "payment_rail_alert_eval_error_total", labels={"stage": "cycle"}
            )
        await asyncio.sleep(interval_seconds)


def build_payment_alert_eval_coro():
    """Fresh coroutine for the WorkerSupervisor (one per (re)start).

    Reads the cadence from settings so it is per-environment tunable via
    ``AETHER_PAYMENT_ALERT_EVAL_INTERVAL_SECONDS`` without a code change.
    """
    from config.settings import settings

    return run_payment_alert_eval_loop(
        interval_seconds=int(settings.payment_rails.alert_eval_interval_seconds)
    )
