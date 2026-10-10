"""Source Precedence Engine (prompt §3.4).

Different data sources carry different authority for different facts. A payment
provider webhook is authoritative for revenue; an SDK is authoritative for
campaign attribution but must never override a settled financial value. This
module encodes that as a machine-readable precedence matrix and a conflict
resolver that either picks the authoritative value *or*, when the evidence is
insufficient or two authoritative-level sources disagree, returns a conflict
record for manual review.

Fail-closed contract: :func:`resolve_conflict` never silently chooses between
disagreeing authoritative sources and never returns a value below the field's
``manual_review_threshold``. Any ambiguity yields ``resolved=False`` with
``requires_manual_review=True``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class Source(str, Enum):
    """Recognised ingestion sources, ordered loosely by base trust."""

    SDK = "sdk"
    CONNECTOR_PULL = "connector_pull"
    PROVIDER_WEBHOOK = "provider_webhook"
    AUTHENTICATED_WEBHOOK = "authenticated_webhook"
    EXTERNAL_API_FEED = "external_api_feed"
    INTERNAL_REPLAY = "internal_replay"
    OPERATOR_ACTION = "operator_action"


# Conflict-resolution rules a field may declare.
CONFLICT_RULE_AUTHORITATIVE_WINS = "authoritative_wins"
CONFLICT_RULE_AUTHORITATIVE_THEN_IDENTITY = "authoritative_then_identity_strength"
CONFLICT_RULE_LATEST_TIMESTAMP = "latest_timestamp_wins"
CONFLICT_RULE_HIGHEST_CONFIDENCE = "highest_confidence_wins"
CONFLICT_RULE_MANUAL_REVIEW = "manual_review"


def _s(source: Source) -> str:
    return source.value


# ── Precedence matrix ─────────────────────────────────────────────────────────
#
# One entry per entity/event fact. Each entry declares:
#   authoritative_source     – the single source of truth for the field
#   fallback_sources         – ordered weaker sources used when it is absent
#   timestamp_priority       – newer observations win among equal authority
#   identity_priority        – identity strength is used to break ties
#   conflict_rule            – how disagreements are adjudicated
#   manual_review_threshold  – min confidence to accept without review
#   tenant_override_allowed  – whether a tenant precedence override is permitted
#   audit_required           – whether resolution must be audited
PRECEDENCE_MATRIX: dict[str, dict[str, Any]] = {
    "identity": {
        "authoritative_source": _s(Source.OPERATOR_ACTION),
        "fallback_sources": [
            _s(Source.AUTHENTICATED_WEBHOOK),
            _s(Source.CONNECTOR_PULL),
            _s(Source.PROVIDER_WEBHOOK),
            _s(Source.SDK),
            _s(Source.EXTERNAL_API_FEED),
            _s(Source.INTERNAL_REPLAY),
        ],
        "timestamp_priority": False,
        "identity_priority": True,
        "conflict_rule": CONFLICT_RULE_AUTHORITATIVE_THEN_IDENTITY,
        "manual_review_threshold": 0.70,
        "tenant_override_allowed": True,
        "audit_required": True,
    },
    "revenue": {
        "authoritative_source": _s(Source.AUTHENTICATED_WEBHOOK),
        "fallback_sources": [
            _s(Source.PROVIDER_WEBHOOK),
            _s(Source.CONNECTOR_PULL),
            _s(Source.EXTERNAL_API_FEED),
            _s(Source.OPERATOR_ACTION),
            _s(Source.INTERNAL_REPLAY),
        ],
        "timestamp_priority": True,
        "identity_priority": False,
        "conflict_rule": CONFLICT_RULE_AUTHORITATIVE_WINS,
        "manual_review_threshold": 0.90,
        "tenant_override_allowed": False,
        "audit_required": True,
    },
    "conversion": {
        "authoritative_source": _s(Source.PROVIDER_WEBHOOK),
        "fallback_sources": [
            _s(Source.AUTHENTICATED_WEBHOOK),
            _s(Source.CONNECTOR_PULL),
            _s(Source.SDK),
            _s(Source.EXTERNAL_API_FEED),
            _s(Source.INTERNAL_REPLAY),
        ],
        "timestamp_priority": True,
        "identity_priority": False,
        "conflict_rule": CONFLICT_RULE_AUTHORITATIVE_WINS,
        "manual_review_threshold": 0.70,
        "tenant_override_allowed": True,
        "audit_required": True,
    },
    "wallet_linkage": {
        "authoritative_source": _s(Source.AUTHENTICATED_WEBHOOK),
        "fallback_sources": [
            _s(Source.OPERATOR_ACTION),
            _s(Source.CONNECTOR_PULL),
            _s(Source.PROVIDER_WEBHOOK),
            _s(Source.SDK),
            _s(Source.EXTERNAL_API_FEED),
            _s(Source.INTERNAL_REPLAY),
        ],
        "timestamp_priority": False,
        "identity_priority": True,
        "conflict_rule": CONFLICT_RULE_AUTHORITATIVE_THEN_IDENTITY,
        "manual_review_threshold": 0.85,
        "tenant_override_allowed": False,
        "audit_required": True,
    },
    "account_linkage": {
        "authoritative_source": _s(Source.CONNECTOR_PULL),
        "fallback_sources": [
            _s(Source.AUTHENTICATED_WEBHOOK),
            _s(Source.PROVIDER_WEBHOOK),
            _s(Source.OPERATOR_ACTION),
            _s(Source.SDK),
            _s(Source.EXTERNAL_API_FEED),
            _s(Source.INTERNAL_REPLAY),
        ],
        "timestamp_priority": False,
        "identity_priority": True,
        "conflict_rule": CONFLICT_RULE_AUTHORITATIVE_THEN_IDENTITY,
        "manual_review_threshold": 0.75,
        "tenant_override_allowed": True,
        "audit_required": True,
    },
    "payment_customer_linkage": {
        "authoritative_source": _s(Source.PROVIDER_WEBHOOK),
        "fallback_sources": [
            _s(Source.AUTHENTICATED_WEBHOOK),
            _s(Source.CONNECTOR_PULL),
            _s(Source.OPERATOR_ACTION),
            _s(Source.EXTERNAL_API_FEED),
            _s(Source.SDK),
            _s(Source.INTERNAL_REPLAY),
        ],
        "timestamp_priority": False,
        "identity_priority": True,
        "conflict_rule": CONFLICT_RULE_AUTHORITATIVE_WINS,
        "manual_review_threshold": 0.80,
        "tenant_override_allowed": False,
        "audit_required": True,
    },
    "agent_linkage": {
        "authoritative_source": _s(Source.CONNECTOR_PULL),
        "fallback_sources": [
            _s(Source.AUTHENTICATED_WEBHOOK),
            _s(Source.OPERATOR_ACTION),
            _s(Source.SDK),
            _s(Source.PROVIDER_WEBHOOK),
            _s(Source.EXTERNAL_API_FEED),
            _s(Source.INTERNAL_REPLAY),
        ],
        "timestamp_priority": False,
        "identity_priority": True,
        "conflict_rule": CONFLICT_RULE_AUTHORITATIVE_THEN_IDENTITY,
        "manual_review_threshold": 0.70,
        "tenant_override_allowed": True,
        "audit_required": True,
    },
    "campaign_linkage": {
        "authoritative_source": _s(Source.SDK),
        "fallback_sources": [
            _s(Source.CONNECTOR_PULL),
            _s(Source.EXTERNAL_API_FEED),
            _s(Source.PROVIDER_WEBHOOK),
            _s(Source.INTERNAL_REPLAY),
        ],
        "timestamp_priority": True,
        "identity_priority": False,
        "conflict_rule": CONFLICT_RULE_LATEST_TIMESTAMP,
        "manual_review_threshold": 0.30,
        "tenant_override_allowed": True,
        "audit_required": False,
    },
    "financial_value": {
        "authoritative_source": _s(Source.AUTHENTICATED_WEBHOOK),
        "fallback_sources": [
            _s(Source.PROVIDER_WEBHOOK),
            _s(Source.CONNECTOR_PULL),
            _s(Source.EXTERNAL_API_FEED),
            _s(Source.OPERATOR_ACTION),
            _s(Source.INTERNAL_REPLAY),
        ],
        "timestamp_priority": True,
        "identity_priority": False,
        "conflict_rule": CONFLICT_RULE_AUTHORITATIVE_WINS,
        "manual_review_threshold": 0.90,
        "tenant_override_allowed": False,
        "audit_required": True,
    },
    "reward_status": {
        "authoritative_source": _s(Source.PROVIDER_WEBHOOK),
        "fallback_sources": [
            _s(Source.AUTHENTICATED_WEBHOOK),
            _s(Source.CONNECTOR_PULL),
            _s(Source.OPERATOR_ACTION),
            _s(Source.EXTERNAL_API_FEED),
            _s(Source.SDK),
            _s(Source.INTERNAL_REPLAY),
        ],
        "timestamp_priority": True,
        "identity_priority": False,
        "conflict_rule": CONFLICT_RULE_AUTHORITATIVE_WINS,
        "manual_review_threshold": 0.80,
        "tenant_override_allowed": True,
        "audit_required": True,
    },
    "attribution_basis": {
        "authoritative_source": _s(Source.CONNECTOR_PULL),
        "fallback_sources": [
            _s(Source.SDK),
            _s(Source.EXTERNAL_API_FEED),
            _s(Source.PROVIDER_WEBHOOK),
            _s(Source.INTERNAL_REPLAY),
        ],
        "timestamp_priority": True,
        "identity_priority": False,
        "conflict_rule": CONFLICT_RULE_LATEST_TIMESTAMP,
        "manual_review_threshold": 0.40,
        "tenant_override_allowed": True,
        "audit_required": False,
    },
}


# Fail-closed default for unknown fields: nothing is authoritative, everything
# requires review, and no tenant override is permitted.
_UNKNOWN_FIELD_PRECEDENCE: dict[str, Any] = {
    "authoritative_source": _s(Source.OPERATOR_ACTION),
    "fallback_sources": [],
    "timestamp_priority": False,
    "identity_priority": False,
    "conflict_rule": CONFLICT_RULE_MANUAL_REVIEW,
    "manual_review_threshold": 1.0,
    "tenant_override_allowed": False,
    "audit_required": True,
    "unknown_field": True,
}


def precedence_for(field: str) -> dict[str, Any]:
    """Return the precedence entry for ``field`` (copy; fail-closed default)."""
    entry = PRECEDENCE_MATRIX.get(field)
    if entry is None:
        return dict(_UNKNOWN_FIELD_PRECEDENCE)
    # Return a shallow copy so callers cannot mutate the canonical matrix.
    copy = dict(entry)
    copy["fallback_sources"] = list(entry["fallback_sources"])
    return copy


def _authority_order(precedence: dict[str, Any]) -> list[str]:
    """Ordered authority list: authoritative source first, then fallbacks."""
    return [precedence["authoritative_source"], *precedence["fallback_sources"]]


def _rank(precedence: dict[str, Any], source: Any) -> int:
    """Precedence index of ``source`` (0 = authoritative; larger = weaker).

    Unknown sources rank below every declared source so they can never
    out-rank a recognised authority.
    """
    order = _authority_order(precedence)
    src = str(getattr(source, "value", source) or "")
    try:
        return order.index(src)
    except ValueError:
        return len(order) + 1


def _candidate_confidence(candidate: dict) -> float:
    # Absent confidence is treated as fully confident (a stated observation);
    # callers pass explicit low confidence to force review.
    try:
        return float(candidate.get("confidence", 1.0))
    except (TypeError, ValueError):
        return 0.0


def _conflict_record(
    field: str,
    precedence: dict[str, Any],
    reason: str,
    candidates: list[dict],
) -> dict[str, Any]:
    return {
        "field": field,
        "resolved": False,
        "conflict": True,
        "requires_manual_review": True,
        "reason": reason,
        "candidates": candidates,
        "authoritative_source": precedence["authoritative_source"],
        "conflict_rule": precedence["conflict_rule"],
        "manual_review_threshold": precedence["manual_review_threshold"],
        # A conflict is always worth auditing, even for otherwise low-audit
        # fields, because it will be adjudicated by a human.
        "audit_required": True,
    }


def _resolved_record(
    field: str,
    precedence: dict[str, Any],
    winner: dict,
    used_fallback: bool,
    tie_break: Optional[str],
    considered: int,
) -> dict[str, Any]:
    return {
        "field": field,
        "resolved": True,
        "conflict": False,
        "requires_manual_review": False,
        "value": winner.get("value"),
        "source": str(getattr(winner.get("source"), "value", winner.get("source"))),
        "confidence": _candidate_confidence(winner),
        "used_fallback": used_fallback,
        "tie_break": tie_break,
        "authoritative_source": precedence["authoritative_source"],
        "conflict_rule": precedence["conflict_rule"],
        "audit_required": precedence["audit_required"],
        "candidates_considered": considered,
    }


def _timestamp(candidate: dict) -> str:
    return str(candidate.get("timestamp") or candidate.get("observed_at") or "")


def _identity_confidence(candidate: dict) -> float:
    try:
        return float(candidate.get("identity_confidence", candidate.get("confidence", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def resolve_conflict(field: str, candidates: list[dict]) -> dict[str, Any]:
    """Resolve competing values for ``field`` using its precedence entry.

    ``candidates`` is a list of dicts, each carrying at least ``source`` and
    ``value`` and optionally ``confidence`` (default 1.0), ``timestamp`` /
    ``observed_at`` and ``identity_confidence``.

    Returns either a resolved record (``resolved=True``) or a conflict record
    (``resolved=False``, ``requires_manual_review=True``). The engine never
    silently chooses between disagreeing authoritative-level sources.
    """
    precedence = precedence_for(field)

    if not candidates:
        return _conflict_record(field, precedence, "no_candidates", [])

    # Rank candidates by source authority; the strongest present tier wins.
    ranked = sorted(candidates, key=lambda c: _rank(precedence, c.get("source")))
    top_rank = _rank(precedence, ranked[0].get("source"))

    # Unknown fields (or candidates whose source sits below every declared
    # source) can never be auto-resolved — fail closed to review.
    order_len = len(_authority_order(precedence))
    if top_rank > order_len:
        return _conflict_record(field, precedence, "unknown_source", ranked)

    top_tier = [c for c in ranked if _rank(precedence, c.get("source")) == top_rank]
    used_fallback = top_rank > 0
    threshold = float(precedence["manual_review_threshold"])

    # ── Single strongest-tier candidate ───────────────────────────────────────
    if len(top_tier) == 1:
        winner = top_tier[0]
        if _candidate_confidence(winner) < threshold:
            return _conflict_record(
                field, precedence, "insufficient_confidence", ranked
            )
        return _resolved_record(
            field, precedence, winner,
            used_fallback=used_fallback,
            tie_break="unique_authority" if not used_fallback else "unique_fallback",
            considered=len(candidates),
        )

    # ── Multiple candidates share the strongest tier ──────────────────────────
    distinct_values = {_normalize_value(c.get("value")) for c in top_tier}
    if len(distinct_values) == 1:
        # Same-tier sources agree — accept if the best of them clears review.
        winner = max(top_tier, key=_candidate_confidence)
        if _candidate_confidence(winner) < threshold:
            return _conflict_record(
                field, precedence, "insufficient_confidence", ranked
            )
        return _resolved_record(
            field, precedence, winner,
            used_fallback=used_fallback,
            tie_break="authoritative_agreement",
            considered=len(candidates),
        )

    # Same-tier sources DISAGREE. Only a timestamp rule may break the tie, and
    # only when the field opts into timestamp priority, timestamps are distinct
    # and the winner clears the review threshold. Everything else is a conflict.
    rule = precedence["conflict_rule"]
    if rule == CONFLICT_RULE_LATEST_TIMESTAMP and precedence["timestamp_priority"]:
        timestamps = [_timestamp(c) for c in top_tier]
        if all(timestamps) and len(set(timestamps)) == len(timestamps):
            winner = max(top_tier, key=_timestamp)
            if _candidate_confidence(winner) >= threshold:
                return _resolved_record(
                    field, precedence, winner,
                    used_fallback=used_fallback,
                    tie_break="latest_timestamp",
                    considered=len(candidates),
                )

    # authoritative_wins / identity-strength / insufficient tie-break data →
    # two authoritative-level sources disagree → manual review.
    return _conflict_record(
        field, precedence, "authoritative_sources_disagree", top_tier
    )


def _normalize_value(value: Any) -> Any:
    """Normalize a candidate value for equality comparison."""
    if isinstance(value, str):
        return value.strip().lower()
    return value
