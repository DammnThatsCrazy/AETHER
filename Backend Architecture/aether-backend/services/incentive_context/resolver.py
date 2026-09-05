"""IncentiveContext resolution — runtime evidence → context (Social360 M5).

Turns campaign / economic / temporal evidence into a first-class, temporal,
provenance-bearing :class:`IncentiveContext` conforming to the M1
``incentive-context.schema.json`` (blueprint §§30-33). The resolver is a pure,
deterministic function of its evidence inputs plus an explicit *assessment
scope* — it never queries, so it is unit-testable without a store; the async
service facade (:mod:`services.incentive_context.service`) supplies the live
Campaign360/Economic360 lookups.

Honesty doctrine (release-blocking, §3.4 / §31):

- incentive exposure is CONTEXT, not disqualification: a detected incentive
  never erases the fact the activity occurred;
- absence of a detected incentive is NEVER automatically ``none_observed`` —
  that status requires a bounded assessment scope proving the incentive-source
  space was actually enumerated;
- ``unknown`` stays ``unknown``: with only a partial assessment, nothing-found
  resolves to ``unknown``, never to ``organic`` and never to ``none_observed``;
- every context traces to evidence: ``evidence_refs``, ``source_scope`` /
  ``evidence_basis``, ``policy_ref`` and ``computed_at`` are populated from the
  actual inputs, and a context whose evidence cannot be scoped is refused
  (:class:`UnscopedEvidenceError`) rather than guessed.

The direct-vs-upstream split follows §33: a context resolves the DIRECT
incentive to the subject/actor. Downstream exposure is recorded as
``upstream_incentive_origin`` provenance on the context — the cascade is never
flattened into a single paid/organic label.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence

from services.value.models import to_decimal_string

from .canonical import (
    EVIDENCE_BASIS,
    EVIDENCE_BASIS_BY_ACQUISITION_MODE,
    INCENTIVE_STATUSES,
    POLICY_REF,
    SOURCE_SCOPES,
    SOURCE_SCOPE_BY_ACQUISITION_MODE,
)
from .models import IncentiveContext, TemporalSegment
from .segments import (
    campaign_window_utc,
    parse_boundary,
    segment_timeline,
    timeline_overlaps_window,
)

__all__ = [
    "AssessmentScope",
    "CampaignEvidence",
    "IncentiveAssessment",
    "IncentiveSignal",
    "UnscopedEvidenceError",
    "build_context_id",
    "campaign_incentive_bearing",
    "resolve_incentive_context",
    "resolve_provenance",
    "to_observation_flags",
]

_UTC = timezone.utc

# Signal kinds the resolver recognises. Each maps to a declared status strength.
INCENTIVE_SIGNAL_KINDS: tuple[str, ...] = (
    "economic_transfer_verified",   # verified economic value moved to the subject
    "sponsorship_declared",         # content/activity explicitly labelled sponsored
    "reward_program_observed",      # a concrete reward-program/offer record observed
    "eligibility_observed",         # a reward eligibility rule matched the subject
)
_SIGNAL_STRENGTH_BY_KIND: dict[str, str] = {
    "economic_transfer_verified": "verified",
    "sponsorship_declared": "declared",
    "reward_program_observed": "observed",
    "eligibility_observed": "observed",
}
_STRENGTH_RANK: dict[str, int] = {"verified": 3, "declared": 2, "observed": 1}

AssessmentScope = str  # one of "bounded_enumeration" | "window_bounded" | "partial" | "not_applicable"
_ASSESSMENT_SCOPES: frozenset[str] = frozenset(
    {"bounded_enumeration", "window_bounded", "partial", "not_applicable"}
)

_POSITIVE_STATUSES: frozenset[str] = frozenset(
    {"verified", "declared", "observed", "suspected"}
)


class UnscopedEvidenceError(ValueError):
    """Raised when evidence cannot be attributed to a canonical source scope.

    The schema requires ``source_scope`` (which has no ``unknown`` member), so
    a context is NEVER emitted with a guessed scope. Callers must supply an
    explicit canonical scope or a provider acquisition mode.
    """


@dataclass(frozen=True)
class IncentiveSignal:
    """One concrete, direct incentive evidence item bound to the subject.

    ``subject_bound`` is always True for items in the resolver's signal list
    (upstream provenance travels separately as ``upstream_incentive_origins``),
    so a signal present here is positive evidence of a DIRECT incentive.
    """

    kind: str
    ref: str                       # evidence reference (campaign/reward/economic row)
    occurred_at: Optional[str] = None
    amount_usd: Optional[str] = None
    provider_ref: Optional[str] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in INCENTIVE_SIGNAL_KINDS:
            raise ValueError(
                f"signal kind must be one of {INCENTIVE_SIGNAL_KINDS}, got {self.kind!r}"
            )
        if not self.ref:
            raise ValueError("incentive signal ref must be non-empty")

    @property
    def strength(self) -> str:
        return _SIGNAL_STRENGTH_BY_KIND[self.kind]

    @property
    def normalized_amount(self) -> Optional[str]:
        """Decimal-string USD normalization via services/value machinery.

        ``None`` when no amount (or an amount that does not parse) — never 0.
        """
        if not self.amount_usd:
            return None
        return to_decimal_string(self.amount_usd)


@dataclass(frozen=True)
class CampaignEvidence:
    """A campaign the activity is attributed to (Campaign360 record + resolution)."""

    campaign_ref: str
    name: Optional[str] = None
    status: Optional[str] = None
    start_at: Optional[object] = None      # aware UTC | naive local (+zone_id) | date | ISO str
    end_at: Optional[object] = None        # exclusive (half-open window)
    zone_id: Optional[str] = None          # IANA zone when start/end are LOCAL
    reward_program: Optional[bool] = None  # None = unknown (never guessed)
    sponsored_declared: Optional[bool] = None
    reward_condition: Optional[str] = None
    eligibility_rule_ref: Optional[str] = None
    origin: Optional[str] = None
    resolution_method: Optional[str] = None
    resolution_confidence: Optional[float] = None
    source_ref: Optional[str] = None       # underlying evidence/registry record ref
    provider_ref: Optional[str] = None
    note: Optional[str] = None


def campaign_incentive_bearing(campaign: Optional[CampaignEvidence]) -> Optional[bool]:
    """Is the campaign positive evidence of an incentive program?

    True only on POSITIVE markers (declared sponsorship, a reward program flag,
    or a declared reward condition). False only when the campaign is positively
    known non-reward. None = unknown — incentive exposure is not asserted from
    unknown (blueprint: unknown never coerced).
    """
    if campaign is None:
        return None
    if campaign.sponsored_declared is True:
        return True
    if campaign.reward_program is True:
        return True
    if campaign.reward_condition:
        return True
    if campaign.reward_program is False and not campaign.reward_condition:
        return False
    return None


@dataclass(frozen=True)
class IncentiveAssessment:
    """How complete the incentive-source enumeration was (honesty control).

    ``none_observed`` is ONLY reachable with ``scope`` in
    ``bounded_enumeration`` / ``window_bounded``; anything else yields
    ``unknown`` for nothing-found (absence of a detected incentive is never
    automatically organic). ``not_applicable`` asserts the activity is outside
    incentive scope — an explicit claim, never inferred.
    """

    scope: AssessmentScope = "partial"
    source_refs: tuple[str, ...] = ()
    horizon_start: Optional[object] = None   # activity horizon actually scanned
    horizon_end: Optional[object] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if self.scope not in _ASSESSMENT_SCOPES:
            raise ValueError(
                f"assessment.scope must be one of {sorted(_ASSESSMENT_SCOPES)}, "
                f"got {self.scope!r}"
            )


def build_context_id(*parts: Optional[object]) -> str:
    """Deterministic, content-addressed context id from the evidence anchors."""
    if not any(p is not None and str(p) != "" for p in parts):
        raise ValueError(
            "cannot build an IncentiveContext id with no subject/campaign anchor"
        )
    key = "|".join("" if p is None else str(p) for p in parts)
    return f"ic-{uuid.uuid5(uuid.NAMESPACE_URL, key).hex}"


def resolve_provenance(
    *,
    source_scope: Optional[str] = None,
    evidence_basis: Optional[str] = None,
    acquisition_mode: Optional[str] = None,
    campaign: Optional[CampaignEvidence] = None,
) -> tuple[str, str]:
    """Canonical sourceScope / evidenceBasis for the context (never guessed).

    Explicit canonical stamps win; then the 1:1 acquisition-mode derivation;
    then the campaign's own scope when it carries one. If source_scope cannot be
    attributed there is NO ``unknown`` member to fall back on — the resolver
    raises :class:`UnscopedEvidenceError` rather than emit a non-conforming
    context.
    """
    if source_scope not in SOURCE_SCOPES:
        source_scope = SOURCE_SCOPE_BY_ACQUISITION_MODE.get(acquisition_mode or "")
    if source_scope not in SOURCE_SCOPES:
        raise UnscopedEvidenceError(
            "cannot attribute evidence to a canonical source_scope; supply an "
            "explicit source_scope or provider acquisition_mode (sourceScope has "
            "no 'unknown' member — the context is refused rather than guessed)"
        )
    if evidence_basis not in EVIDENCE_BASIS:
        evidence_basis = (
            EVIDENCE_BASIS_BY_ACQUISITION_MODE.get(acquisition_mode or "")
            or "unknown"
        )
    return source_scope, evidence_basis


def to_observation_flags(context: IncentiveContext) -> tuple[bool, bool]:
    """Map a resolved context to ``(incentive_context, incentive_assessed)``.

    The pair is what M6/M7 observation accounting consumes
    (``shared/relationship_fidelity/evidence.py``). Mapping is monotone and
    honest:

    - verified/declared/observed/suspected → (True, True)  assessed & present
    - none_observed → (False, True)                        assessed, not present
    - not_applicable → (False, False)   structurally outside incentive scope —
      excluded from both the present numerator and the assessed denominator
    - unknown → (False, False)          NOT assessed — never counted as absent

    ``unknown`` therefore never contributes to an exposure ratio and never reads
    as organic. ``suspected`` is assessed-present (a context flag, not proof);
    consumers must not elevate it to a verified incentive claim.
    """
    status = context.status
    if status in ("verified", "declared", "observed", "suspected"):
        return True, True
    if status == "none_observed":
        return False, True
    # not_applicable and unknown: not assessed as either present or absent.
    return False, False


def _resolved_window(
    campaign: Optional[CampaignEvidence],
) -> tuple[Optional[datetime], Optional[datetime]]:
    if campaign is None:
        return None, None
    return campaign_window_utc(campaign.start_at, campaign.end_at, zone_id=campaign.zone_id)


def _select_status(
    *,
    best_strength: Optional[str],
    campaign_bound: bool,
    activity_occurred_at: Optional[object],
    campaign: Optional[CampaignEvidence],
    allow_temporal_suspicion: bool,
    assessment: IncentiveAssessment,
) -> tuple[str, str]:
    """Deterministic status + confidence_kind selection (documented ladder).

    1. a subject-bound signal's strength wins (verified > declared > observed);
    2. else an activity directly attributed to a positively incentive-bearing
       campaign resolves ``observed`` (unless it is provably OUTSIDE the
       campaign window — then assessment applies);
    3. else, only if ``allow_temporal_suspicion``, an in-window-but-unattributed
       activity is ``suspected`` (pure context, no direct claim);
    4. else ``not_applicable`` (explicit), else ``none_observed`` (bounded
       assessment only), else ``unknown``.
    """
    if best_strength is not None:
        return best_strength, "provider_declared"

    bearing = campaign_incentive_bearing(campaign)
    start, end = _resolved_window(campaign) if campaign is not None else (None, None)

    if campaign_bound and bearing is True:
        overlap = timeline_overlaps_window(activity_occurred_at, start, end)
        if overlap != "out":
            # Directly attributed to an incentive-bearing program. Even when the
            # window bounds are unknown we cannot PROVE the activity is outside,
            # and the attribution itself is incentive evidence; observed, derived
            # (not provider-declared: no single provider record says "paid").
            return "observed", "derived"

    if (
        allow_temporal_suspicion
        and bearing is True
        and not campaign_bound
        and timeline_overlaps_window(activity_occurred_at, start, end) == "in"
    ):
        return "suspected", "derived"

    if assessment.scope == "not_applicable":
        return "not_applicable", "derived"

    if assessment.scope in ("bounded_enumeration", "window_bounded"):
        return "none_observed", "derived"

    return "unknown", "unknown"


def resolve_incentive_context(
    *,
    tenant_id: Optional[str] = None,
    subject_entity_ref: Optional[str] = None,
    social_identity_ref: Optional[str] = None,
    content_ref: Optional[str] = None,
    interaction_ref: Optional[str] = None,
    campaign_ref: Optional[str] = None,
    reward_ref: Optional[str] = None,
    economic_value_ref: Optional[str] = None,
    activity_occurred_at: Optional[object] = None,
    campaign: Optional[CampaignEvidence] = None,
    signals: Sequence[IncentiveSignal] = (),
    upstream_incentive_origins: Sequence[str] = (),
    downstream_exposure: Optional[bool] = None,
    timeline: Sequence[object] = (),
    assessment: Optional[IncentiveAssessment] = None,
    source_scope: Optional[str] = None,
    evidence_basis: Optional[str] = None,
    acquisition_mode: Optional[str] = None,
    reward_condition: Optional[str] = None,
    eligibility_rule_ref: Optional[str] = None,
    contradictory_evidence_refs: Sequence[str] = (),
    confidence_value: Optional[float] = None,
    context_id: Optional[str] = None,
    computed_at: Optional[object] = None,
    policy_ref: str = POLICY_REF,
    allow_temporal_suspicion: bool = False,
    limitations: Sequence[str] = (),
) -> IncentiveContext:
    """Resolve one activity/subject to a schema-conformant IncentiveContext.

    Pure and deterministic given identical inputs. Returns a fully-populated
    :class:`IncentiveContext`; raises :class:`UnscopedEvidenceError` when the
    evidence cannot be attributed to a canonical source scope.
    """
    assessment = assessment or IncentiveAssessment()
    computed_dt = parse_boundary(computed_at) or datetime.now(_UTC)
    assert computed_dt is not None and computed_dt.tzinfo is not None

    # ── anchors ─────────────────────────────────────────────────────────────
    campaign_bound = bool(campaign_ref) and campaign is not None
    if campaign is not None and campaign_ref is None:
        campaign_ref = campaign.campaign_ref

    # reward/economy refs: explicit params win, else derive from direct signals.
    if reward_ref is None:
        for sig in signals:
            if sig.kind in ("reward_program_observed", "eligibility_observed"):
                reward_ref = sig.ref
                break
    if economic_value_ref is None:
        for sig in signals:
            if sig.kind == "economic_transfer_verified":
                economic_value_ref = sig.ref
                break

    # ── provenance (never guessed; refuses on un-scopable evidence) ──────────
    resolved_scope, resolved_basis = resolve_provenance(
        source_scope=source_scope,
        evidence_basis=evidence_basis,
        acquisition_mode=acquisition_mode,
        campaign=campaign,
    )

    # ── status ladder ────────────────────────────────────────────────────────
    strengths = [sig.strength for sig in signals]
    best_strength = None
    for s in strengths:
        if best_strength is None or _STRENGTH_RANK[s] > _STRENGTH_RANK[best_strength]:
            best_strength = s
    status, confidence_kind = _select_status(
        best_strength=best_strength,
        campaign_bound=campaign_bound,
        activity_occurred_at=activity_occurred_at,
        campaign=campaign,
        allow_temporal_suspicion=allow_temporal_suspicion,
        assessment=assessment,
    )

    # ── direct vs upstream semantics (§33) ───────────────────────────────────
    direct_incentive = status in ("verified", "declared", "observed")
    origins = [r for r in upstream_incentive_origins if r]
    upstream_origin = origins[0] if origins else None

    # ── exposure window + temporal segmentation (§32) ───────────────────────
    # The exposure window is stamped from the campaign ONLY when the activity is
    # not provably outside it. A verified/declared signal whose activity falls
    # outside the campaign window is NOT given that window as its exposure
    # window (the campaign window would then contradict the activity's own time).
    exposure_started_at: Optional[datetime] = None
    exposure_ended_at: Optional[datetime] = None
    segments: list[TemporalSegment] = []
    if status in _POSITIVE_STATUSES and campaign is not None:
        win_start, win_end = _resolved_window(campaign)
        overlap = timeline_overlaps_window(activity_occurred_at, win_start, win_end)
        if overlap != "out":
            exposure_started_at, exposure_ended_at = win_start, win_end
            if (
                exposure_started_at is not None
                and exposure_ended_at is not None
                and timeline
            ):
                try:
                    obs = [parse_boundary(t) for t in timeline]
                except (TypeError, ValueError):
                    obs = []
                obs = [o for o in obs if o is not None]
                segments = segment_timeline(
                    exposure_started_at,
                    exposure_ended_at,
                    obs,
                )

    # ── evidence refs / limitations ──────────────────────────────────────────
    evidence_refs: list[str] = []
    for sig in signals:
        if sig.ref:
            evidence_refs.append(sig.ref)
    if campaign is not None:
        for ref in (campaign.source_ref, campaign.provider_ref, campaign.campaign_ref):
            if ref:
                evidence_refs.append(ref)
    if reward_ref:
        evidence_refs.append(reward_ref)
    if economic_value_ref:
        evidence_refs.append(economic_value_ref)
    for ref in assessment.source_refs:
        evidence_refs.append(ref)
    evidence_refs.extend(origins)
    evidence_refs.extend(contradictory_evidence_refs)

    contradictory: list[str] = list(contradictory_evidence_refs)
    if (
        status in _POSITIVE_STATUSES
        and campaign is not None
        and campaign_incentive_bearing(campaign) is False
        and campaign.source_ref
    ):
        # The campaign is positively known non-reward yet another record claims
        # an incentive — surface the contradiction, do not hide it.
        contradictory.append(campaign.source_ref)

    limitations_out = [str(l) for l in limitations]
    if origins and status not in ("verified", "declared", "observed"):
        limitations_out.append(
            "activity is downstream of an incentive-originated item "
            f"(upstream ref: {origins[0]}); this context records the DIRECT "
            "incentive only and is not an organic/paid flattening of the cascade"
        )
    if status in ("verified", "declared", "observed") and campaign is not None \
            and campaign_incentive_bearing(campaign) is True \
            and not any(sig.kind == "economic_transfer_verified" for sig in signals):
        limitations_out.append(
            "incentive inferred from campaign attribution / declared program; "
            "no direct economic-transfer record in this context"
        )
    if confidence_kind == "unknown":
        limitations_out.append(
            "incentive presence could not be bounded by an assessment (scope "
            "partial/absent); status is unknown, never organic, never "
            "none_observed"
        )
    if exposure_started_at is None and status in _POSITIVE_STATUSES:
        limitations_out.append(
            "no campaign window bound recorded; exposure window not segmented"
        )

    if confidence_value is None and campaign is not None and status == "observed" \
            and campaign.resolution_confidence is not None:
        confidence_value = campaign.resolution_confidence

    if context_id is None:
        context_id = build_context_id(
            tenant_id,
            subject_entity_ref,
            social_identity_ref,
            content_ref,
            interaction_ref,
            campaign_ref,
            reward_ref,
            economic_value_ref,
            activity_occurred_at,
        )

    return IncentiveContext(
        incentive_context_id=context_id,
        subject_entity_ref=subject_entity_ref,
        social_identity_ref=social_identity_ref,
        content_ref=content_ref,
        interaction_ref=interaction_ref,
        campaign_ref=campaign_ref,
        reward_ref=reward_ref,
        economic_value_ref=economic_value_ref,
        status=status,  # type: ignore[arg-type]
        reward_condition=reward_condition
        or (campaign.reward_condition if campaign is not None else None),
        eligibility_rule_ref=eligibility_rule_ref
        or (campaign.eligibility_rule_ref if campaign is not None else None),
        exposure_started_at=exposure_started_at,
        exposure_ended_at=exposure_ended_at,
        direct_incentive=direct_incentive,
        upstream_incentive_origin=upstream_origin,
        downstream_exposure=downstream_exposure,
        temporal_segments=segments,
        evidence_refs=evidence_refs,
        contradictory_evidence_refs=contradictory,
        source_scope=resolved_scope,  # type: ignore[arg-type]
        evidence_basis=resolved_basis,  # type: ignore[arg-type]
        confidence_kind=confidence_kind,  # type: ignore[arg-type]
        confidence_value=confidence_value,
        policy_ref=policy_ref,
        computed_at=computed_dt,
        limitations=limitations_out,
    )
