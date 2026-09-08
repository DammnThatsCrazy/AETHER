"""Aether — Rights Authority: retention executor SEAM (blueprint §9 / §10).

This module exposes the *retention execution seam* for the ``rights_irrl``
authority: given an effective :class:`RightsDecision` /
:class:`~services.rights_authority.lifecycle.LifecycleResolution` (or an explicit
retention window / expiry) and a tenant/artifact, it computes a retention
expiry and produces/persists **pending retention impact items** through the
existing impact machinery (``RightsImpactItem`` / ``persist_impact_items``).

Doctrine (fail-closed, blueprint §9 / §10 "no fake completion"):

- A **known window/expiry** produces one pending ``delete_at_expiry`` impact item
  so the scheduled deletion is durable + surfaced; nothing is executed here.
- An explicit **preserve/hold** decision schedules no deletion (there is nothing
  to remediate) and returns ``state="preserve"``.
- An explicit **delete-now** lifecycle decision (delete/hard_delete/tombstone)
  produces one pending deletion impact item.
- A retention signal that is **unknown** (no window, no expiry, no decisive
  lifecycle action) NEVER becomes a silent no-op that implies retention: it
  produces one pending ``retention_review`` impact item. Retention is only ever
  implied by an explicit decision, never by absence of one.

All timestamps are aware UTC. This module never calls the stdlib naive clock
directly; it uses ``shared.common.common.utc_now`` and
``shared.common.common.parse_event_time`` and refuses naive ``datetime`` input
rather than guessing a zone.

Integration boundary (REMAINING SEAM, deliberately not implemented here): the
seam does NOT talk to any real artifact store. Wiring the artifact-store
deletion adapter (and the trigger that fires when ``expiry`` passes) is the
remaining integration. Until then every scheduled/unknown outcome stays a
``pending`` impact item surfaced through the existing ``rights_impacts`` store.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, Field

from shared.common.common import parse_event_time, utc_now
from shared.logger.logger import get_logger
from services.rights_authority.impact import RightsImpactItem, persist_impact_items

logger = get_logger("aether.rights_irrl.retention")

# Seam-specific required-action tokens used on pending impact items.
RETENTION_REVIEW_ACTION = "retention_review"            # window unknown → human/adapter review
RETENTION_SCHEDULED_DELETE_ACTION = "delete_at_expiry"  # window known → delete after expiry

# Lifecycle/deletion tokens that mean "retain indefinitely; do NOT schedule a
# deletion". Only unambiguous indefinite-retain / hold verbs qualify. Governed /
# per-policy labels (``governed``, ``per_policy``, profile presets) are NOT here:
# they carry no expiry and must not silently imply retention → they fall through
# to a pending retention review until a real window is supplied.
PRESERVE_ACTION_TOKENS: frozenset[str] = frozenset({
    "preserve",
    "preserve_forever",
    "legal_hold",
    "retain",
    "retain_as_required",
    "retain_if_independently_qualified",
    "retain_if_generalization_passed",
    "retain_if_non_reconstructable_and_permitted",
    "tenant_retains",
    "quarantine",
    "suppress",
})

# Lifecycle tokens that mean deletion is ordered NOW (no retention window).
DELETE_NOW_ACTION_TOKENS: frozenset[str] = frozenset({
    "delete",
    "hard_delete",
    "tombstone",
})

# Retention resolution outcome states.
RETENTION_STATES: tuple[str, ...] = (
    "explicit_expiry",   # an absolute expires_at resolved to a deletion deadline
    "known_window",      # anchor + retention window resolved to a deletion deadline
    "delete_immediate",  # lifecycle orders deletion now
    "preserve",          # explicit retain/hold → no deletion scheduled
    "unknown_retention", # no window / no decisive signal → pending retention review
)


@dataclass(frozen=True)
class RetentionWindow:
    """A parsed retention window: calendar (years/months) + elapsed units.

    Only ``years``, ``months``, ``days`` and ``hours`` are materialised; weeks
    fold into days and ISO time components below an hour are not supported
    (retention windows are expressed at day granularity or coarser).
    """

    years: int = 0
    months: int = 0
    days: int = 0
    hours: int = 0

    @property
    def iso(self) -> str:
        """Lossy-ish ISO-8601 duration rendering (for logs/impact reasons)."""
        parts = ["P"]
        if self.years:
            parts.append(f"{self.years}Y")
        if self.months:
            parts.append(f"{self.months}M")
        if self.days:
            parts.append(f"{self.days}D")
        if self.hours:
            parts.append(f"T{self.hours}H")
        if len(parts) == 1:
            return "P0D"
        return "".join(parts)


# ISO-8601 duration subset: P[n]Y[n]M[n]W[n]D[ T[n]H ]  (no minutes/seconds).
_ISO_WINDOW_RE = re.compile(
    r"^P(?=[0-9T])(?:(?P<years>[0-9]+)Y)?(?:(?P<months>[0-9]+)M)?"
    r"(?:(?P<weeks>[0-9]+)W)?(?:(?P<days>[0-9]+)D)?(?:T(?:(?P<hours>[0-9]+)H)?)?$"
)
# Token form: "<amount><unit>" with unit in d/w/m/y/h (lower/upper).
_TOKEN_WINDOW_RE = re.compile(r"^(?P<amount>[0-9]+)\s*(?P<unit>[a-zA-Z]+)$")
_UNIT_TO_FIELD = {
    "d": "days",
    "day": "days",
    "days": "days",
    "w": "weeks",
    "week": "weeks",
    "weeks": "weeks",
    "m": "months",
    "month": "months",
    "months": "months",
    "y": "years",
    "year": "years",
    "years": "years",
    "h": "hours",
    "hour": "hours",
    "hours": "hours",
}


def _iso_parts(match: re.Match[str]) -> RetentionWindow:
    def _num(key: str) -> int:
        raw = match.group(key)
        return int(raw) if raw else 0

    return RetentionWindow(
        years=_num("years"),
        months=_num("months"),
        days=_num("days") + _num("weeks") * 7,
        hours=_num("hours"),
    )


def parse_retention_window(value: Any) -> Optional[RetentionWindow]:
    """Parse a retention window spec, or ``None`` when it cannot be understood.

    Accepted forms (documented contract for callers/integration):
    - integer day count: ``90``
    - token duration: ``"90d"``, ``"12w"``, ``"24M"``, ``"2y"``, ``"48h"``
      (d=days, w=weeks, m/M=months, y/Y=years, h=hours; spaces optional)
    - ISO-8601 duration subset: ``"P90D"``, ``"P2W"``, ``"P6M"``, ``"P1Y"``,
      ``"P1Y6M10D"``, ``"PT24H"``

    An unrecognised value returns ``None`` (fail closed: a caller must not
    invent a window from a value it cannot parse).
    """
    if isinstance(value, RetentionWindow):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if value <= 0:
            return None
        return RetentionWindow(days=value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    iso_match = _ISO_WINDOW_RE.match(text)
    if iso_match is not None:
        if not any(iso_match.group(g) for g in ("years", "months", "weeks", "days", "hours")):
            return None  # bare "P"/"PT" carries no window
        window = _iso_parts(iso_match)
        return _require_positive(window)
    token_match = _TOKEN_WINDOW_RE.match(text)
    if token_match is None:
        return None
    amount = int(token_match.group("amount"))
    unit = _UNIT_TO_FIELD.get(token_match.group("unit").lower())
    if unit is None or amount <= 0:
        return None
    if unit == "weeks":
        return _require_positive(RetentionWindow(days=amount * 7))
    return _require_positive(RetentionWindow(**{unit: amount}))


def _require_positive(window: RetentionWindow) -> Optional[RetentionWindow]:
    """Reject a zero-duration window (a degenerate/ambiguous retention signal)."""
    if not (window.years or window.months or window.days or window.hours):
        return None
    return window


def _add_months(anchor: datetime, months: int) -> datetime:
    """Calendar-aware month arithmetic (clamps day-of-month at month ends)."""
    month_index = anchor.year * 12 + (anchor.month - 1) + months
    year, month0 = divmod(month_index, 12)
    month = month0 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return anchor.replace(year=year, month=month, day=day)


def add_retention_window(anchor: datetime, window: RetentionWindow) -> datetime:
    """Add a parsed :class:`RetentionWindow` to an aware UTC ``anchor``."""
    date_part = _add_months(anchor, window.years * 12 + window.months)
    return date_part + timedelta(days=window.days, hours=window.hours)


def _coerce_instant(value: Any) -> Optional[datetime]:
    """Aware UTC instant from a datetime/ISO string; ``None`` when unusable.

    Naive ``datetime`` input is REFUSED (never guessed into a zone); strings go
    through ``parse_event_time``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value
    return parse_event_time(value)


# ═══════════════════════════════════════════════════════════════════════════
# Resolution
# ═══════════════════════════════════════════════════════════════════════════

def _pick(obj: Any, *keys: str) -> Any:
    """Read the first present attribute/key from a dict or object."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        for key in keys:
            if obj.get(key) is not None:
                return obj.get(key)
        return None
    for key in keys:
        try:
            value = getattr(obj, key, None)
        except Exception:  # pragma: no cover — defensive against proxy objects
            value = None
        if value is not None:
            return value
    return None


def _tokenize(value: Any) -> str:
    """Canonical lowercase token of an action/label value."""
    if value is None:
        return ""
    if hasattr(value, "value"):
        value = value.value
    return str(value).strip().lower()


def _decision_lifecycle_token(decision: Any, lifecycle: Any) -> str:
    """Dominant lifecycle token from lifecycle → decision deletion → retention."""
    action = _pick(lifecycle, "action", "lifecycle_action")
    if action is not None:
        return _tokenize(action)
    deletion = _pick(decision, "deletion", "deletion_action", "lifecycle_action")
    if deletion is not None:
        return _tokenize(deletion)
    return _tokenize(_pick(decision, "retention", "retention_action"))


class RetentionResolution(BaseModel):
    """Outcome of evaluating retention for one governed tenant/artifact."""

    tenant_id: str
    artifact_ref: Optional[str] = None
    grant_id: Optional[str] = None
    decision_ref: Optional[str] = None
    state: str = "unknown_retention"
    action: str = ""                      # lifecycle/deletion token that applies
    basis: str = ""
    retention_label: Optional[str] = None  # decision.retention raw value if any
    window: Optional[str] = None
    anchor: Optional[str] = None          # ISO aware UTC anchor used
    expiry: Optional[str] = None          # ISO aware UTC deletion deadline, if any
    impact_items: list[RightsImpactItem] = Field(default_factory=list)
    impact_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def remediates(self) -> bool:
        """Whether this resolution carries pending impact items to execute."""
        return bool(self.impact_items)


def evaluate_retention(
    *,
    tenant_id: str,
    artifact_ref: Optional[str] = None,
    decision: Any = None,
    lifecycle: Any = None,
    grant_id: Optional[str] = None,
    retention_window: Any = None,
    expires_at: Any = None,
    anchor: Any = None,
    component_type: str = "raw_object",
    now: Any = None,
) -> RetentionResolution:
    """Evaluate retention for one artifact and build pending impact items (no I/O).

    Outcomes (see :data:`RETENTION_STATES`):

    - ``expires_at`` supplied  → ``explicit_expiry`` + pending ``delete_at_expiry``.
    - ``retention_window`` supplied (with an anchor) → ``known_window`` + pending
      ``delete_at_expiry``. Anchor defaults to the decision's effective/evaluated
      time, else ``now`` (aware UTC).
    - No window/expiry and a decisive preserve/hold token → ``preserve``; no item.
    - No window/expiry and a decisive delete-now token → ``delete_immediate`` +
      pending deletion item.
    - No window/expiry and no decisive signal (or an unparseable one) →
      ``unknown_retention`` + pending ``retention_review`` item (fail closed).

    ``component_type`` must be one of the ``RightsImpactItem`` cascade dimensions
    (default ``raw_object``); the caller knows the governed object's kind.
    """
    if now is None:
        now = utc_now()
    now_aware = _coerce_instant(now) or utc_now()

    decision_ref = _pick(decision, "decision_id") or _pick(lifecycle, "decision_ref")
    retention_label = _tokenize(_pick(decision, "retention")) or None
    lifecycle_token = _decision_lifecycle_token(decision, lifecycle)

    resolution = RetentionResolution(
        tenant_id=tenant_id,
        artifact_ref=artifact_ref,
        grant_id=grant_id,
        decision_ref=decision_ref,
        retention_label=retention_label,
    )

    # ── Explicit expiry / window ─────────────────────────────────────────────
    if expires_at is not None or retention_window is not None:
        anchor_instant = (
            _coerce_instant(anchor)
            or _coerce_instant(_pick(decision, "effective_as_of", "evaluated_at"))
            or now_aware
        )
        expiry_instant = _coerce_instant(expires_at) if expires_at is not None else None
        if expiry_instant is not None:
            resolution.state = "explicit_expiry"
            resolution.basis = "explicit_expires_at"
            resolution.anchor = anchor_instant.isoformat()
            resolution.expiry = expiry_instant.isoformat()
            resolution.action = RETENTION_SCHEDULED_DELETE_ACTION
            resolution.impact_items.append(_scheduled_delete_item(
                tenant_id=tenant_id,
                artifact_ref=artifact_ref,
                grant_id=grant_id,
                decision_ref=decision_ref,
                component_type=component_type,
                expiry_iso=expiry_instant.isoformat(),
                basis=resolution.basis,
            ))
            return resolution

        # A supplied-but-unparseable absolute expiry is malformed → review.
        if expires_at is not None:
            resolution.state = "unknown_retention"
            resolution.basis = "unparseable_expires_at"
            resolution.action = RETENTION_REVIEW_ACTION
            resolution.impact_items.append(_review_item(
                tenant_id=tenant_id,
                artifact_ref=artifact_ref,
                grant_id=grant_id,
                decision_ref=decision_ref,
                component_type=component_type,
                signal=expires_at,
            ))
            resolution.notes.append(
                "expires_at could not be parsed — pending retention review (fail closed)"
            )
            return resolution

        window_obj = parse_retention_window(retention_window)
        if window_obj is not None and anchor_instant is not None:
            expiry_instant = add_retention_window(anchor_instant, window_obj)
            resolution.state = "known_window"
            resolution.basis = f"retention_window:{window_obj.iso}"
            resolution.window = window_obj.iso
            resolution.anchor = anchor_instant.isoformat()
            resolution.expiry = expiry_instant.isoformat()
            resolution.action = RETENTION_SCHEDULED_DELETE_ACTION
            resolution.impact_items.append(_scheduled_delete_item(
                tenant_id=tenant_id,
                artifact_ref=artifact_ref,
                grant_id=grant_id,
                decision_ref=decision_ref,
                component_type=component_type,
                expiry_iso=expiry_instant.isoformat(),
                basis=resolution.basis,
            ))
            return resolution

        # Window given but unparseable, or no anchor resolvable → review.
        resolution.state = "unknown_retention"
        resolution.basis = "unknown_retention_window"
        resolution.action = RETENTION_REVIEW_ACTION
        resolution.impact_items.append(_review_item(
            tenant_id=tenant_id,
            artifact_ref=artifact_ref,
            grant_id=grant_id,
            decision_ref=decision_ref,
            component_type=component_type,
            signal=retention_window,
        ))
        resolution.notes.append(
            "retention window could not be resolved — pending retention review (fail closed)"
        )
        return resolution

    # ── No window/expiry: interpret the effective lifecycle signal ──────────
    token = lifecycle_token or (retention_label or "")

    if token in PRESERVE_ACTION_TOKENS:
        resolution.state = "preserve"
        resolution.action = token or "preserve"
        resolution.basis = "preserve_explicit"
        resolution.notes.append(
            f"effective lifecycle token {token!r} retains — no deletion scheduled"
        )
        return resolution

    if token in DELETE_NOW_ACTION_TOKENS:
        resolution.state = "delete_immediate"
        resolution.action = token
        resolution.basis = "delete_now"
        resolution.impact_items.append(
            RightsImpactItem(
                tenant_id=tenant_id,
                grant_id=grant_id,
                artifact_ref=artifact_ref,
                component_type=component_type,  # type: ignore[arg-type]
                required_action=token,
                remediation_state="pending",
                reason=(
                    f"effective lifecycle action {token!r} orders deletion of "
                    f"{artifact_ref or '?'} — pending deletion execution "
                    f"(decision {decision_ref or '?'})"
                ),
            )
        )
        resolution.notes.append(
            f"effective lifecycle action {token!r} orders deletion — pending delete item"
        )
        return resolution

    # Unknown signal → pending retention review, never silent retention.
    resolution.state = "unknown_retention"
    resolution.action = RETENTION_REVIEW_ACTION
    resolution.basis = "unknown_retention_signal"
    resolution.impact_items.append(_review_item(
        tenant_id=tenant_id,
        artifact_ref=artifact_ref,
        grant_id=grant_id,
        decision_ref=decision_ref,
        component_type=component_type,
        signal=token or retention_label,
    ))
    resolution.notes.append(
        "no retention window/expiry and no decisive lifecycle action — "
        "pending retention review; this never implies retention"
    )
    return resolution


def _review_item(
    *,
    tenant_id: str,
    artifact_ref: Optional[str],
    grant_id: Optional[str],
    decision_ref: Optional[str],
    component_type: str,
    signal: Any,
) -> RightsImpactItem:
    signal_text = "none" if signal in (None, "") else repr(signal)
    return RightsImpactItem(
        tenant_id=tenant_id,
        grant_id=grant_id,
        artifact_ref=artifact_ref,
        component_type=component_type,  # type: ignore[arg-type]
        required_action=RETENTION_REVIEW_ACTION,
        remediation_state="pending",
        reason=(
            f"retention unknown for {artifact_ref or '?'} "
            f"(signal {signal_text}, decision {decision_ref or '?'}) — pending "
            f"retention review; nothing implies retention (fail closed)"
        ),
    )


def _scheduled_delete_item(
    *,
    tenant_id: str,
    artifact_ref: Optional[str],
    grant_id: Optional[str],
    decision_ref: Optional[str],
    component_type: str,
    expiry_iso: str,
    basis: str,
) -> RightsImpactItem:
    return RightsImpactItem(
        tenant_id=tenant_id,
        grant_id=grant_id,
        artifact_ref=artifact_ref,
        component_type=component_type,  # type: ignore[arg-type]
        required_action=RETENTION_SCHEDULED_DELETE_ACTION,
        remediation_state="pending",
        reason=(
            f"retention expiry {expiry_iso} for {artifact_ref or '?'} "
            f"({basis}, decision {decision_ref or '?'}) — deletion pending after "
            f"expiry; artifact-store adapter integration required"
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════════════════

async def schedule_retention(**kwargs: Any) -> RetentionResolution:
    """Evaluate retention and persist any pending impact items (no fake completion).

    Persists every item produced by :func:`evaluate_retention` through
    ``services.rights_authority.impact.persist_impact_items`` and records the
    returned impact ids on the resolution. Nothing is executed — deletion stays
    ``pending`` until an artifact-store adapter acts on it.
    """
    resolution = evaluate_retention(**kwargs)
    if not resolution.impact_items:
        return resolution
    resolution.impact_ids = await persist_impact_items(resolution.impact_items)
    return resolution


__all__ = [
    "DELETE_NOW_ACTION_TOKENS",
    "PRESERVE_ACTION_TOKENS",
    "RETENTION_REVIEW_ACTION",
    "RETENTION_SCHEDULED_DELETE_ACTION",
    "RETENTION_STATES",
    "RetentionResolution",
    "RetentionWindow",
    "add_retention_window",
    "evaluate_retention",
    "parse_retention_window",
    "schedule_retention",
]
