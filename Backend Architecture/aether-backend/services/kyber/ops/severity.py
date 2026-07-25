"""Explainable exception priority.

An operator queue is only useful if its order can be defended. This module
turns the exposure fields on :class:`OperationalException` into a single score
*and* the term-by-term arithmetic that produced it, so the answer to "why is
this at the top" is a stored record rather than a guess.

The ordering property that drives the weights
---------------------------------------------
One potential cross-tenant leak must outrank any volume of low-risk warnings.
Volume is the metric that is easiest to accumulate and least correlated with
consequence: a retry loop can emit five hundred informational exceptions in a
minute, and if count carried linear weight it would bury the single row that
means customer data crossed a tenant boundary. So:

* ``security_exposure`` and ``data_integrity_exposure`` carry the two largest
  weights, and together they are treated as the cross-tenant-leak signature —
  they force ``critical_now`` outright;
* ``signal_count`` enters **logarithmically and capped** at
  :data:`VOLUME_WEIGHT`, which is smaller than every consequence term. Five
  hundred repetitions of a harmless warning can therefore never reach a single
  leak, because the whole volume term is worth less than a tenth of the leak
  terms;
* ``confidence`` damps rather than gates. A half-confident leak is still a
  leak, so the damping factor floors at :data:`MIN_CONFIDENCE_FACTOR` instead
  of scaling to zero — otherwise a low-confidence security finding would sort
  below a certain typo.

Scores are normalised to 0–100 against the maximum reachable raw total, so the
bucket thresholds mean the same thing after a weight is retuned.
"""
from __future__ import annotations

import math
from typing import Any

from .contracts import ExceptionBucket, OperationalException, Severity, now_iso

# ── Weights ──────────────────────────────────────────────────────────────────
#
# Consequence first, then reach, then urgency, then volume. Every value is the
# maximum contribution of its term; each term's normalised value is in [0, 1].

SECURITY_WEIGHT = 30.0
DATA_INTEGRITY_WEIGHT = 26.0
CUSTOMER_VISIBLE_WEIGHT = 12.0
FINANCIAL_WEIGHT = 10.0
TENANT_REACH_WEIGHT = 10.0
IRREVERSIBILITY_WEIGHT = 9.0
TIME_TO_BREACH_WEIGHT = 8.0
SLA_WEIGHT = 8.0
SEVERITY_WEIGHT = 6.0
#: Deliberately the smallest weight in the table. See the module docstring.
VOLUME_WEIGHT = 4.0

MAX_RAW_SCORE = (
    SECURITY_WEIGHT + DATA_INTEGRITY_WEIGHT + CUSTOMER_VISIBLE_WEIGHT
    + FINANCIAL_WEIGHT + TENANT_REACH_WEIGHT + IRREVERSIBILITY_WEIGHT
    + TIME_TO_BREACH_WEIGHT + SLA_WEIGHT + SEVERITY_WEIGHT + VOLUME_WEIGHT
)

#: Confidence scales the total into [MIN_CONFIDENCE_FACTOR, 1.0] rather than
#: [0, 1]: uncertainty should discount a finding, never erase it.
MIN_CONFIDENCE_FACTOR = 0.5

#: Reach saturates here — beyond this many tenants the difference stops being
#: decision-relevant, it is already "the fleet".
TENANT_REACH_SATURATION = 25
#: A single named tenant scores a small non-zero reach. An empty
#: ``affected_tenants`` means "reach unknown", and unknown must not be worth
#: more than one confirmed tenant.
SINGLE_TENANT_REACH = 0.15
#: Volume saturates here, and even at saturation is worth VOLUME_WEIGHT.
VOLUME_SATURATION = 1000
#: Time-to-breach urgency saturates at one minute and decays to zero over a day.
TIME_TO_BREACH_FLOOR_SECONDS = 60
TIME_TO_BREACH_HORIZON_SECONDS = 86_400

#: Ordered worst-first; used for the severity term and for escalate-only merges.
SEVERITY_ORDER: tuple[Severity, ...] = ("critical", "high", "medium", "low", "info")

_SEVERITY_VALUE: dict[str, float] = {
    "critical": 1.0,
    "high": 0.75,
    "medium": 0.5,
    "low": 0.25,
    "info": 0.0,
}

# ── Bucket thresholds (on the normalised 0–100 scale) ────────────────────────

CRITICAL_NOW_THRESHOLD = 28.0
NEEDS_ACTION_THRESHOLD = 14.0
WATCH_THRESHOLD = 5.0

#: Bucket order the queue is read in. First is what an operator does now.
BUCKET_ORDER: tuple[ExceptionBucket, ...] = (
    "critical_now", "needs_action", "watch", "informational",
)

_BUCKET_RANK: dict[str, int] = {bucket: index for index, bucket in enumerate(BUCKET_ORDER)}


def severity_rank(severity: str) -> int:
    """Position in :data:`SEVERITY_ORDER`; lower is worse.

    Unknown values sort last, which keeps a typo from silently outranking a
    real ``critical``.
    """
    try:
        return SEVERITY_ORDER.index(severity)  # type: ignore[arg-type]
    except ValueError:
        return len(SEVERITY_ORDER)


def bucket_rank(bucket: str) -> int:
    """Position in :data:`BUCKET_ORDER`; lower is more urgent."""
    return _BUCKET_RANK.get(bucket, len(BUCKET_ORDER))


def escalate_severity(current: str, incoming: str) -> Severity:
    """The worse of two severities.

    Compression must never quiet an exception down: the same ``dedupe_key``
    arriving with a lower severity means one of the occurrences was mild, not
    that the problem shrank. Mirrors ``services/agent/ops_alerts.record_alert``.
    """
    if severity_rank(incoming) < severity_rank(current):
        return incoming  # type: ignore[return-value]
    return current  # type: ignore[return-value]


def _log_saturating(value: float, saturation: int) -> float:
    """Normalise a count into [0, 1] logarithmically.

    ``1`` maps to ``0.0`` and ``saturation`` maps to ``1.0``. Log rather than
    linear so an order-of-magnitude more repetitions is worth one more step,
    not ten times the score.
    """
    if value <= 1 or saturation <= 1:
        return 0.0
    return min(1.0, math.log10(value) / math.log10(saturation))


def _time_to_breach_value(seconds: int | None) -> float:
    """Urgency from a deadline: 1.0 inside a minute, 0.0 beyond a day.

    ``None`` means "no known deadline", which scores ``0.0`` — absence of a
    deadline is not urgency, and it is also not safety, which is why nothing
    else in the table is allowed to depend on this term.
    """
    if seconds is None:
        return 0.0
    if seconds <= TIME_TO_BREACH_FLOOR_SECONDS:
        return 1.0
    if seconds >= TIME_TO_BREACH_HORIZON_SECONDS:
        return 0.0
    span = TIME_TO_BREACH_HORIZON_SECONDS - TIME_TO_BREACH_FLOOR_SECONDS
    return 1.0 - ((seconds - TIME_TO_BREACH_FLOOR_SECONDS) / span)


def _term(value: Any, normalized: float, weight: float) -> dict[str, Any]:
    return {
        "value": value,
        "normalized": round(normalized, 6),
        "weight": weight,
        "contribution": round(normalized * weight, 6),
    }


def score_exception(exc: OperationalException) -> tuple[float, dict[str, Any]]:
    """Score one exception and return the arithmetic that produced the score.

    Args:
        exc: The exception to rank. Only its exposure fields are read; the
            existing ``priority_score`` is ignored so re-scoring is idempotent.

    Returns:
        ``(score, inputs)`` where ``score`` is on a 0–100 scale and ``inputs``
        is the explainability record to store in ``priority_inputs``: every
        term with its raw value, normalised value, weight and contribution,
        plus the confidence factor, the raw subtotal and the terms that
        dominated.
    """
    tenant_count = len(exc.affected_tenants or [])
    terms: dict[str, dict[str, Any]] = {
        "security_exposure": _term(
            exc.security_exposure, 1.0 if exc.security_exposure else 0.0, SECURITY_WEIGHT
        ),
        "data_integrity_exposure": _term(
            exc.data_integrity_exposure,
            1.0 if exc.data_integrity_exposure else 0.0,
            DATA_INTEGRITY_WEIGHT,
        ),
        "customer_visible": _term(
            exc.customer_visible, 1.0 if exc.customer_visible else 0.0, CUSTOMER_VISIBLE_WEIGHT
        ),
        "financial_exposure": _term(
            exc.financial_exposure, 1.0 if exc.financial_exposure else 0.0, FINANCIAL_WEIGHT
        ),
        "tenant_reach": _term(
            tenant_count,
            _log_saturating(tenant_count, TENANT_REACH_SATURATION) if tenant_count > 1
            else (SINGLE_TENANT_REACH if tenant_count == 1 else 0.0),
            TENANT_REACH_WEIGHT,
        ),
        "irreversibility": _term(
            not exc.reversible, 0.0 if exc.reversible else 1.0, IRREVERSIBILITY_WEIGHT
        ),
        "time_to_breach": _term(
            exc.time_to_breach_seconds,
            _time_to_breach_value(exc.time_to_breach_seconds),
            TIME_TO_BREACH_WEIGHT,
        ),
        "sla_impact": _term(exc.sla_impact, 1.0 if exc.sla_impact else 0.0, SLA_WEIGHT),
        "severity": _term(
            exc.severity, _SEVERITY_VALUE.get(exc.severity, 0.5), SEVERITY_WEIGHT
        ),
        "volume": _term(
            exc.signal_count,
            _log_saturating(float(exc.signal_count or 1), VOLUME_SATURATION),
            VOLUME_WEIGHT,
        ),
    }

    raw_subtotal = sum(term["contribution"] for term in terms.values())
    confidence = min(1.0, max(0.0, float(exc.confidence)))
    confidence_factor = MIN_CONFIDENCE_FACTOR + (1.0 - MIN_CONFIDENCE_FACTOR) * confidence
    score = round(100.0 * raw_subtotal * confidence_factor / MAX_RAW_SCORE, 4)

    dominant = [
        name for name, term in sorted(
            terms.items(), key=lambda item: item[1]["contribution"], reverse=True
        )
        if term["contribution"] > 0
    ][:3]

    inputs: dict[str, Any] = {
        "terms": terms,
        "weights": {name: term["weight"] for name, term in terms.items()},
        "raw_subtotal": round(raw_subtotal, 6),
        "max_raw_score": MAX_RAW_SCORE,
        "confidence": confidence,
        "confidence_factor": round(confidence_factor, 6),
        "score": score,
        "dominant_terms": dominant,
        "scale": "0-100",
        "scored_at": now_iso(),
    }
    return score, inputs


def bucket_for(score: float, exc: OperationalException) -> ExceptionBucket:
    """Which bucket an exception belongs in — what to *do*, not how bad it looks.

    Thresholds on the normalised score decide the ordinary case. Three floors
    override them upward, because some conditions must not be able to sort
    themselves into ``watch`` through low confidence or a missing field:

    * ``security_exposure and data_integrity_exposure`` — the cross-tenant leak
      signature — is always ``critical_now``;
    * ``severity == "critical"`` is always ``critical_now``;
    * either exposure flag alone, an irreversible exception, or a deadline
      inside an hour is at least ``needs_action``.

    Floors only ever raise the bucket. Nothing here can lower one.
    """
    if exc.security_exposure and exc.data_integrity_exposure:
        return "critical_now"
    if exc.severity == "critical":
        return "critical_now"

    if score >= CRITICAL_NOW_THRESHOLD:
        bucket: ExceptionBucket = "critical_now"
    elif score >= NEEDS_ACTION_THRESHOLD:
        bucket = "needs_action"
    elif score >= WATCH_THRESHOLD:
        bucket = "watch"
    else:
        bucket = "informational"

    needs_action_floor = (
        exc.security_exposure
        or exc.data_integrity_exposure
        or not exc.reversible
        or (exc.time_to_breach_seconds is not None and exc.time_to_breach_seconds <= 3600)
    )
    if needs_action_floor and bucket_rank(bucket) > bucket_rank("needs_action"):
        return "needs_action"
    return bucket


def apply_priority(exc: OperationalException) -> OperationalException:
    """Recompute ``priority_score``, ``priority_inputs`` and ``bucket`` in place.

    Every mutation path — first raise, compression, re-score after a severity
    escalation — goes through this one function so a ranking never drifts from
    the inputs stored beside it.
    """
    score, inputs = score_exception(exc)
    exc.priority_score = score
    exc.priority_inputs = inputs
    exc.bucket = bucket_for(score, exc)
    return exc


__all__ = [
    "BUCKET_ORDER",
    "CRITICAL_NOW_THRESHOLD",
    "MAX_RAW_SCORE",
    "NEEDS_ACTION_THRESHOLD",
    "SEVERITY_ORDER",
    "WATCH_THRESHOLD",
    "apply_priority",
    "bucket_for",
    "bucket_rank",
    "escalate_severity",
    "score_exception",
    "severity_rank",
]
