"""Payment-rail DERIVED-condition alert evaluator (lightweight, in-process).

WHAT THIS IS
------------
A read-only classifier that turns the payment-rail plane's DURABLE state
(receipt ledger + reconciliation records) into a small set of severity-graded
``AlertCondition`` verdicts. It does NOT emit metrics, mutate any store, perform
network IO, or touch provider secrets — it only reads and classifies.

WHY IT WAS NEEDED (the gap this closes — the "alert-evaluator depth" piece)
---------------------------------------------------------------------------
The payment-rail plane already EMITS rich metrics (webhook handled/rejected,
sync/repair cycles, provider poll health/freshness, receipt/canonical backlogs,
oldest-incomplete-receipt age, dead-letters, worker heartbeats). ``alert_rules.yml``
turns most of those single-series signals into Prometheus alerts. But two classes
of condition have NO clean single-series PromQL expression, so nothing was
actually EVALUATING them:

1. **Reconciliation conflict backlog.** A ``conflict`` reconciliation record
   (SDK-observed truth disagreeing with provider truth on a funding session) is
   the most operationally important financial-integrity signal, yet the durable
   conflict/stale BACKLOG is never emitted as a gauge — only a per-transition
   counter (``payment_rail_sync_transitioned_total{state="conflict"}``) exists,
   which cannot express "how many sessions are conflicted right now". The only
   source of that truth is the durable reconciliation records themselves.
2. **Backlog / silence conditions that must distinguish "no data" from "0".**
   A provider that has never sent a webhook, or a plane with zero receipts, must
   read as UNKNOWN — not as a reassuring ``0`` age or ``0`` backlog. A gauge that
   is simply absent (never set) looks identical to a healthy zero in PromQL; the
   evaluator can tell them apart because it reads the underlying records.

This module fills that gap with an env-AWARE classifier. Every threshold is read
from :class:`config.settings.PaymentRailsConfig` (the ``alert_*`` fields this PR
added) so staging can run tight defaults while a production overlay loosens them
via env vars WITHOUT a code change. No threshold is hardcoded here.

DESIGN GUARANTEES
-----------------
* **Read-only.** Reads ``service.repos.receipts`` / ``service.repos.reconciliation``
  only; never writes, never emits a metric (reusing the plane's existing emitted
  names is fine, but this classifier deliberately emits nothing so it can be
  called cheaply from any surface — a Kyber ops view, a scheduled probe, a test).
* **No secrets.** Every ``AlertCondition.message`` is built from counts, ages, and
  stable keys only — never a provider payload, credential, or raw body. This
  mirrors the "no secrets in alert messages" rule the Prometheus rules follow.
* **"Unknown" is never "0".** ``classify_no_webhook`` returns ``UNKNOWN``
  (``observed=False``) when there is no webhook receipt at all, so a silent plane
  can never be rendered as a fresh 0-second age. This is the same fail-loud
  invariant the frontend enforces ("unknown must never render as a misleading 0").
* **Pure, testable core.** The ``classify_*`` functions are pure (value +
  thresholds → verdict) and unit-tested WITHOUT any store; the async
  :func:`evaluate_payment_rail_alerts` only wires durable reads into them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.temporal.instant import ensure_aware_utc

from services.integrations.providers.payment_rails.receipts import (
    COMPLETE_STAGES,
    TERMINAL_STATES,
    ReceiptState,
)


# ── Severity vocabulary ───────────────────────────────────────────────────────
class AlertSeverity:
    """Ordered severity tokens for a derived payment-rail condition.

    ``UNKNOWN`` is deliberately its own token, distinct from ``OK``: a condition
    the evaluator could not establish (no data) must never be silently reported as
    healthy. ``OK`` means "measured, and within tolerance"; ``UNKNOWN`` means
    "there was nothing to measure" — the two demand different operator responses.
    """

    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


# Severities that constitute a firing alert (an operator should look).
FIRING_SEVERITIES: frozenset[str] = frozenset({AlertSeverity.WARNING, AlertSeverity.CRITICAL})

# Best → worst ordering, used to roll many conditions into one overall verdict.
_SEVERITY_RANK: dict[str, int] = {
    AlertSeverity.OK: 0,
    AlertSeverity.UNKNOWN: 1,
    AlertSeverity.WARNING: 2,
    AlertSeverity.CRITICAL: 3,
}


@dataclass(frozen=True)
class AlertCondition:
    """One classified payment-rail condition.

    ``observed`` is ``False`` only when there was no underlying data to classify
    (the "unknown / no-data" case). ``value`` is the measured quantity (an age in
    seconds or a count) and ``threshold`` the boundary it was compared against —
    both are non-secret scalars safe to render or log. ``message`` never contains
    a secret or a provider payload.
    """

    key: str
    severity: str
    message: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    observed: bool = True
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def firing(self) -> bool:
        return self.severity in FIRING_SEVERITIES

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "severity": self.severity,
            "message": self.message,
            "value": self.value,
            "threshold": self.threshold,
            "observed": self.observed,
            "labels": dict(self.labels),
        }


@dataclass(frozen=True)
class AlertThresholds:
    """Env-aware thresholds for the derived conditions.

    Built from :class:`config.settings.PaymentRailsConfig` via
    :meth:`from_settings`, but every field is explicit so a test can construct a
    bespoke set without monkeypatching global settings. Ages are in seconds;
    everything else is a count.
    """

    no_webhook_seconds: float
    oldest_receipt_warn_seconds: float
    oldest_receipt_critical_seconds: float
    canonical_backlog_warn: float
    canonical_backlog_critical: float
    dead_letter_warn: float
    dead_letter_critical: float
    reconciliation_conflict_warn: float
    reconciliation_conflict_critical: float
    reconciliation_stale_warn: float
    verification_failure_window_seconds: float
    verification_failure_warn: float
    verification_failure_critical: float

    @classmethod
    def from_settings(cls, settings: Any = None) -> "AlertThresholds":
        """Read the ``alert_*`` fields off ``settings.payment_rails``.

        Imported lazily so this module stays import-cheap and so a test that has
        monkeypatched ``settings.payment_rails`` is honoured.
        """
        if settings is None:
            from config.settings import settings as _settings

            settings = _settings
        pr = settings.payment_rails
        return cls(
            no_webhook_seconds=float(pr.alert_no_webhook_seconds),
            oldest_receipt_warn_seconds=float(pr.alert_oldest_receipt_warn_seconds),
            oldest_receipt_critical_seconds=float(pr.alert_oldest_receipt_critical_seconds),
            canonical_backlog_warn=float(pr.alert_canonical_backlog_warn),
            canonical_backlog_critical=float(pr.alert_canonical_backlog_critical),
            dead_letter_warn=float(pr.alert_dead_letter_warn),
            dead_letter_critical=float(pr.alert_dead_letter_critical),
            reconciliation_conflict_warn=float(pr.alert_reconciliation_conflict_warn),
            reconciliation_conflict_critical=float(pr.alert_reconciliation_conflict_critical),
            reconciliation_stale_warn=float(pr.alert_reconciliation_stale_warn),
            verification_failure_window_seconds=float(
                pr.alert_webhook_verification_failure_window_seconds
            ),
            verification_failure_warn=float(pr.alert_webhook_verification_failure_warn),
            verification_failure_critical=float(pr.alert_webhook_verification_failure_critical),
        )


@dataclass(frozen=True)
class AlertReport:
    """The full set of classified conditions from one evaluation pass."""

    conditions: tuple[AlertCondition, ...]
    generated_at: str

    @property
    def firing(self) -> list[AlertCondition]:
        """Only the conditions an operator should act on (warning/critical)."""
        return [c for c in self.conditions if c.firing]

    @property
    def by_key(self) -> dict[str, AlertCondition]:
        return {c.key: c for c in self.conditions}

    @property
    def worst_severity(self) -> str:
        """The single worst severity across all conditions (OK if empty)."""
        worst = AlertSeverity.OK
        for c in self.conditions:
            if _SEVERITY_RANK.get(c.severity, 0) > _SEVERITY_RANK.get(worst, 0):
                worst = c.severity
        return worst

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "worst_severity": self.worst_severity,
            "firing": [c.key for c in self.firing],
            "conditions": [c.to_dict() for c in self.conditions],
        }


# ── Pure classification core (no IO — unit-tested directly) ───────────────────
def _ascending(
    value: float,
    warn: float,
    critical: float,
    *,
    key: str,
    unit: str,
    what: str,
    labels: Optional[dict[str, str]] = None,
) -> AlertCondition:
    """Classify a metric where LARGER is worse (ages and backlog counts).

    ``value >= critical`` → CRITICAL, ``value >= warn`` → WARNING, else OK. The
    message is built purely from the numeric value, the crossed threshold, and the
    caller-supplied ``what`` phrase — never any record content.
    """
    if value >= critical:
        sev, thr = AlertSeverity.CRITICAL, critical
    elif value >= warn:
        sev, thr = AlertSeverity.WARNING, warn
    else:
        sev, thr = AlertSeverity.OK, warn
    if sev == AlertSeverity.OK:
        message = f"{what} within tolerance ({value:g}{unit} < {warn:g}{unit})"
    else:
        message = f"{what} is {value:g}{unit} (>= {thr:g}{unit})"
    return AlertCondition(
        key=key, severity=sev, message=message, value=float(value),
        threshold=float(thr), observed=True, labels=labels or {},
    )


def classify_no_webhook(
    age_seconds: Optional[float], thresholds: AlertThresholds
) -> AlertCondition:
    """No-webhook-in-window.

    ``age_seconds`` is the age of the most recent verified webhook receipt, or
    ``None`` when the plane has NEVER recorded a webhook. The ``None`` case is the
    load-bearing guard: it is reported as ``UNKNOWN`` (``observed=False``,
    ``value=None``) — a silent plane must never be rendered as a fresh 0-second
    age. A measured age beyond the window fires WARNING (a webhook-capable
    provider has gone silent — rotated/misconfigured endpoint or provider outage).
    """
    if age_seconds is None:
        return AlertCondition(
            key="no_webhook_in_window",
            severity=AlertSeverity.UNKNOWN,
            message="no verified webhook has ever been observed — freshness is unknown, not zero",
            value=None,
            threshold=float(thresholds.no_webhook_seconds),
            observed=False,
        )
    if age_seconds > thresholds.no_webhook_seconds:
        return AlertCondition(
            key="no_webhook_in_window",
            severity=AlertSeverity.WARNING,
            message=(
                f"no verified webhook in {age_seconds:g}s "
                f"(> {thresholds.no_webhook_seconds:g}s window)"
            ),
            value=float(age_seconds),
            threshold=float(thresholds.no_webhook_seconds),
        )
    return AlertCondition(
        key="no_webhook_in_window",
        severity=AlertSeverity.OK,
        message=f"last verified webhook {age_seconds:g}s ago (within window)",
        value=float(age_seconds),
        threshold=float(thresholds.no_webhook_seconds),
    )


def classify_oldest_incomplete_receipt(
    age_seconds: Optional[float], thresholds: AlertThresholds
) -> AlertCondition:
    """Oldest incomplete-receipt age (a delivery stuck short of ``completed``).

    ``None`` means there are no incomplete receipts at all — genuinely healthy, so
    this reports OK with a measured value of ``0`` (unlike no-webhook, "nothing
    stuck" is a positive proof of health, not an absence of data).
    """
    if age_seconds is None:
        return AlertCondition(
            key="oldest_incomplete_receipt",
            severity=AlertSeverity.OK,
            message="no incomplete receipts",
            value=0.0,
            threshold=float(thresholds.oldest_receipt_warn_seconds),
        )
    return _ascending(
        age_seconds,
        thresholds.oldest_receipt_warn_seconds,
        thresholds.oldest_receipt_critical_seconds,
        key="oldest_incomplete_receipt",
        unit="s",
        what="oldest incomplete receipt age",
    )


def classify_canonical_backlog(count: int, thresholds: AlertThresholds) -> AlertCondition:
    """Canonical-delivery backlog: count of incomplete receipts."""
    return _ascending(
        float(count),
        thresholds.canonical_backlog_warn,
        thresholds.canonical_backlog_critical,
        key="canonical_backlog",
        unit="",
        what="canonical-delivery backlog",
    )


def classify_dead_letters(count: int, thresholds: AlertThresholds) -> AlertCondition:
    """Dead-letter backlog: receipts parked in ``dead_lettered`` (manual replay)."""
    return _ascending(
        float(count),
        thresholds.dead_letter_warn,
        thresholds.dead_letter_critical,
        key="dead_letter_backlog",
        unit="",
        what="dead-lettered receipts",
    )


def classify_reconciliation_conflicts(
    count: int, thresholds: AlertThresholds
) -> AlertCondition:
    """Reconciliation-conflict backlog: SDK vs provider-truth disagreements.

    This is the condition with no single-series PromQL equivalent — the durable
    conflict backlog is only knowable by reading reconciliation records. Any
    conflict is a financial-integrity discrepancy worth surfacing, so the default
    warn threshold is 1.
    """
    return _ascending(
        float(count),
        thresholds.reconciliation_conflict_warn,
        thresholds.reconciliation_conflict_critical,
        key="reconciliation_conflict",
        unit="",
        what="reconciliation conflicts",
    )


def classify_reconciliation_stale(count: int, thresholds: AlertThresholds) -> AlertCondition:
    """Stale reconciliation records: SDK-only sessions provider never confirmed.

    Single-threshold (warn only): a surge can mean a provider is silently dropping
    traffic, but a handful of stale SDK-only sessions is normal churn.
    """
    warn = thresholds.reconciliation_stale_warn
    sev = AlertSeverity.WARNING if count >= warn else AlertSeverity.OK
    message = (
        f"{count} stale (unconfirmed) reconciliation records (>= {warn:g})"
        if sev == AlertSeverity.WARNING
        else f"{count} stale reconciliation records (within tolerance)"
    )
    return AlertCondition(
        key="reconciliation_stale", severity=sev, message=message,
        value=float(count), threshold=float(warn),
    )


def classify_verification_failures(count: int, thresholds: AlertThresholds) -> AlertCondition:
    """Webhook signature/verification failures within the recent window.

    Repeated rejected/quarantined webhook receipts — a rotated/misconfigured
    signing secret or a probing caller. The COUNT is reported; the offending
    bodies are never referenced (they are quarantined metadata-only elsewhere).
    """
    return _ascending(
        float(count),
        thresholds.verification_failure_warn,
        thresholds.verification_failure_critical,
        key="webhook_verification_failures",
        unit="",
        what="recent webhook verification failures",
    )


# ── Durable-state helpers (read-only) ─────────────────────────────────────────
def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Best-effort parse of a stored ISO timestamp into an aware-UTC datetime.

    Uses the canonical ``shared.temporal.instant.ensure_aware_utc`` helper (the
    same one ``service.py``/``kyber_aggregate.py``/``repair_worker.py`` use) so a
    naive stored timestamp is normalized to UTC through the one shared code path
    rather than hand-setting the tzinfo attribute — this is what the temporal
    integrity gate enforces, and it keeps every payment-rail age computation on
    the identical instant semantics.
    """
    if not value:
        return None
    try:
        return ensure_aware_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (ValueError, TypeError):
        return None


def _is_incomplete(receipt: dict[str, Any]) -> bool:
    """A receipt short of a completion stage and not in a hard-terminal state.

    Mirrors the exact predicate the repair worker uses to compute
    ``payment_rail_canonical_backlog`` so the evaluator and the emitted gauge
    cannot disagree.
    """
    stage = receipt.get("current_stage")
    return stage not in COMPLETE_STAGES and stage not in TERMINAL_STATES


def _is_verification_failure(receipt: dict[str, Any]) -> bool:
    """A receipt that was rejected/quarantined at verification (denied webhook)."""
    return (
        receipt.get("current_stage") in (ReceiptState.REJECTED, ReceiptState.QUARANTINED)
        or receipt.get("verification_state") == "rejected"
    )


def _age_seconds(ts: Optional[str], now: datetime) -> Optional[float]:
    parsed = _parse_iso(ts)
    if parsed is None:
        return None
    return (now - parsed).total_seconds()


def _oldest_incomplete_age(receipts: list[dict[str, Any]], now: datetime) -> Optional[float]:
    """Age of the OLDEST incomplete receipt, or ``None`` when none are incomplete."""
    ages = [
        age
        for r in receipts
        if _is_incomplete(r)
        for age in (_age_seconds(r.get("received_at"), now),)
        if age is not None
    ]
    return max(ages) if ages else None


def _last_webhook_age(receipts: list[dict[str, Any]], now: datetime) -> Optional[float]:
    """Age of the MOST-RECENT webhook-sourced receipt, or ``None`` if there is none.

    ``None`` (no webhook receipt ever) is preserved all the way to
    ``classify_no_webhook`` so a silent plane classifies as UNKNOWN, never 0.
    """
    ages = [
        age
        for r in receipts
        if r.get("source") == "webhook"
        for age in (_age_seconds(r.get("received_at"), now),)
        if age is not None
    ]
    return min(ages) if ages else None


def _recent_verification_failures(
    receipts: list[dict[str, Any]], now: datetime, window_seconds: float
) -> int:
    """Count denied-webhook receipts whose last activity is within ``window``."""
    count = 0
    for r in receipts:
        if not _is_verification_failure(r):
            continue
        age = _age_seconds(r.get("last_attempted_at") or r.get("received_at"), now)
        if age is not None and age <= window_seconds:
            count += 1
    return count


# ── The async entry point (wires durable reads into the pure classifiers) ─────
async def evaluate_payment_rail_alerts(
    *,
    service: Any = None,
    now: Optional[datetime] = None,
    thresholds: Optional[AlertThresholds] = None,
) -> AlertReport:
    """Read the durable payment-rail state once and classify every derived alert.

    Read-only: enumerates the receipt ledger and reconciliation records
    cross-tenant (a control-plane view, never surfaced per-tenant), classifies
    each condition with env-aware thresholds, and returns an :class:`AlertReport`.
    Emits no metrics and mutates nothing. ``service`` / ``now`` / ``thresholds``
    are injectable so the wiring is testable against a seeded in-memory service
    with no global state.
    """
    if service is None:
        from services.integrations.providers.payment_rails.service import (
            get_payment_rails_service,
        )

        service = get_payment_rails_service()
    if thresholds is None:
        thresholds = AlertThresholds.from_settings()
    now = now or datetime.now(timezone.utc)

    receipts = await service.repos.receipts.list_all()
    reconciliation = await service.repos.reconciliation.list_all()

    backlog = sum(1 for r in receipts if _is_incomplete(r))
    dead = sum(1 for r in receipts if r.get("current_stage") == ReceiptState.DEAD_LETTERED)
    conflicts = sum(1 for r in reconciliation if r.get("state") == "conflict")
    stale = sum(1 for r in reconciliation if r.get("state") == "stale")

    conditions = (
        classify_no_webhook(_last_webhook_age(receipts, now), thresholds),
        classify_oldest_incomplete_receipt(_oldest_incomplete_age(receipts, now), thresholds),
        classify_canonical_backlog(backlog, thresholds),
        classify_dead_letters(dead, thresholds),
        classify_reconciliation_conflicts(conflicts, thresholds),
        classify_reconciliation_stale(stale, thresholds),
        classify_verification_failures(
            _recent_verification_failures(
                receipts, now, thresholds.verification_failure_window_seconds
            ),
            thresholds,
        ),
    )
    return AlertReport(conditions=conditions, generated_at=now.isoformat())


__all__ = [
    "AlertSeverity",
    "FIRING_SEVERITIES",
    "AlertCondition",
    "AlertThresholds",
    "AlertReport",
    "classify_no_webhook",
    "classify_oldest_incomplete_receipt",
    "classify_canonical_backlog",
    "classify_dead_letters",
    "classify_reconciliation_conflicts",
    "classify_reconciliation_stale",
    "classify_verification_failures",
    "evaluate_payment_rail_alerts",
]
