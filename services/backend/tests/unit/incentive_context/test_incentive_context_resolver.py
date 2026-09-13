"""IncentiveContext resolver honesty + lineage tests (M5 release-blocking).

Covers the doctrine: incentive exposure is context not disqualification; absence
of a detected incentive is NEVER automatically ``none_observed`` (or organic);
``unknown`` stays ``unknown``; ``not_applicable`` is never inferred; each
resolved context traces to evidence (provenance, refs, policy, computed_at);
and the §33 cascade is never flattened into a paid/organic label.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.incentive_context.canonical import (  # noqa: E402
    INCENTIVE_STATUSES,
    POLICY_REF,
)
from services.incentive_context.models import IncentiveContext  # noqa: E402
from services.incentive_context.resolver import (  # noqa: E402
    CampaignEvidence,
    IncentiveAssessment,
    IncentiveSignal,
    UnscopedEvidenceError,
    build_context_id,
    resolve_incentive_context,
    to_observation_flags,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)

_REWARD_CAMPAIGN = CampaignEvidence(
    campaign_ref="cmp-1",
    reward_program=True,
    start_at="2026-04-01T00:00:00+00:00",
    end_at="2026-06-01T00:00:00+00:00",
    source_ref="cmp-row-1",
)
_NON_REWARD_CAMPAIGN = CampaignEvidence(
    campaign_ref="cmp-0",
    reward_program=False,
    start_at="2026-04-01T00:00:00+00:00",
    end_at="2026-06-01T00:00:00+00:00",
    source_ref="cmp-row-0",
)


def _resolve(**overrides):
    kwargs = dict(
        tenant_id="ten-1",
        social_identity_ref="si-1",
        interaction_ref="in-1",
        source_scope="tenant_connected",
        evidence_basis="provider_api",
        computed_at=NOW,
    )
    kwargs.update(overrides)
    return resolve_incentive_context(**kwargs)


# ── Absence-of-detection honesty ────────────────────────────────────────────


def test_no_signal_and_no_assessment_is_unknown_not_none_observed() -> None:
    ctx = _resolve()
    assert ctx.status == "unknown"
    assert ctx.direct_incentive is False
    # Absence of a detected incentive must not even LOOK like none_observed.
    assert ctx.status != "none_observed"
    assert ctx.status != "not_applicable"


def test_absence_of_detected_incentive_is_never_automatically_none_observed() -> None:
    # No positive signal + partial/absent assessment must stay unknown, even when
    # a campaign exists that the activity is attributed to but whose incentive
    # bearing is UNKNOWN (None). Unknown reward-bearing is not an incentive claim.
    unknown_bearing = CampaignEvidence(campaign_ref="cmp-?")
    ctx = _resolve(
        campaign_ref="cmp-?",
        campaign=unknown_bearing,
        activity_occurred_at="2026-05-01T00:00:00Z",
    )
    assert ctx.status == "unknown"
    assert ctx.status != "none_observed"


def test_none_observed_requires_bounded_assessment() -> None:
    # window_bounded over a single known non-reward/out-of-window campaign is a
    # real assessment => none_observed is honest here.
    ctx = _resolve(
        activity_occurred_at="2026-03-01T00:00:00Z",  # before the reward window
        campaign=_REWARD_CAMPAIGN,
        assessment=IncentiveAssessment(
            scope="window_bounded", source_refs=("cmp-row-1",)
        ),
    )
    assert ctx.status == "none_observed"
    assert ctx.direct_incentive is False
    # lineage: the assessment enumeration is traceable
    assert "cmp-row-1" in ctx.evidence_refs


def test_bounded_empty_enumeration_is_none_observed_with_evidence() -> None:
    ctx = _resolve(
        assessment=IncentiveAssessment(
            scope="bounded_enumeration", source_refs=("reg://campaigns", "reg://rewards")
        )
    )
    assert ctx.status == "none_observed"
    assert "reg://campaigns" in ctx.evidence_refs
    assert "reg://rewards" in ctx.evidence_refs


def test_unknown_never_coerced_to_organic_or_none_observed() -> None:
    assert "organic" not in INCENTIVE_STATUSES
    for scope in (None, IncentiveAssessment(scope="partial")):
        kw = {} if scope is None else {"assessment": scope}
        ctx = _resolve(**kw)
        assert ctx.status == "unknown"


def test_not_applicable_requires_explicit_scope() -> None:
    # Never inferred from missing incentive evidence.
    assert _resolve().status != "not_applicable"
    ctx = _resolve(assessment=IncentiveAssessment(scope="not_applicable"))
    assert ctx.status == "not_applicable"


def test_unscoped_evidence_is_refused_not_guessed() -> None:
    with pytest.raises(UnscopedEvidenceError):
        resolve_incentive_context(
            tenant_id="ten-1", social_identity_ref="si-1", computed_at=NOW
        )
    # Even with signals, no scope => refuse.
    with pytest.raises(UnscopedEvidenceError):
        resolve_incentive_context(
            tenant_id="ten-1",
            social_identity_ref="si-1",
            signals=[IncentiveSignal(kind="sponsorship_declared", ref="spo-x")],
            computed_at=NOW,
        )


def test_scoped_by_acquisition_mode() -> None:
    ctx = resolve_incentive_context(
        tenant_id="ten-1",
        social_identity_ref="si-1",
        acquisition_mode="poll",
        computed_at=NOW,
    )
    assert ctx.source_scope == "tenant_connected"
    assert ctx.evidence_basis == "provider_api"


# ── Status derivation ladder ────────────────────────────────────────────────


def test_economic_transfer_verifies() -> None:
    ctx = _resolve(
        interaction_ref="in-v",
        signals=[IncentiveSignal(kind="economic_transfer_verified", ref="econ-v")],
    )
    assert ctx.status == "verified"
    assert ctx.direct_incentive is True
    assert ctx.confidence_kind == "provider_declared"
    assert ctx.economic_value_ref == "econ-v"


def test_declared_sponsorship() -> None:
    ctx = _resolve(
        interaction_ref="in-d",
        signals=[IncentiveSignal(kind="sponsorship_declared", ref="spo-d")],
    )
    assert ctx.status == "declared"
    assert ctx.direct_incentive is True


def test_bound_reward_campaign_in_window_is_observed() -> None:
    ctx = _resolve(
        interaction_ref="in-o",
        campaign_ref="cmp-1",
        campaign=_REWARD_CAMPAIGN,
        activity_occurred_at="2026-05-01T00:00:00Z",
    )
    assert ctx.status == "observed"
    assert ctx.direct_incentive is True
    assert ctx.confidence_kind == "derived"
    assert ctx.campaign_ref == "cmp-1"
    assert ctx.exposure_started_at == datetime(2026, 4, 1, tzinfo=UTC)


def test_bound_non_reward_campaign_is_not_incentive() -> None:
    # Attribution to a positively-known NON-reward campaign is not incentive;
    # with only a partial assessment this must stay unknown, not none_observed.
    ctx = _resolve(
        interaction_ref="in-x",
        campaign_ref="cmp-0",
        campaign=_NON_REWARD_CAMPAIGN,
        activity_occurred_at="2026-05-01T00:00:00Z",
    )
    assert ctx.status != "observed"
    assert ctx.direct_incentive is False


def test_suspected_requires_opt_in_and_window_context() -> None:
    # Default: pure temporal coincidence is not even suspected.
    default_ctx = _resolve(
        interaction_ref="in-s",
        campaign=_REWARD_CAMPAIGN,
        activity_occurred_at="2026-05-01T00:00:00Z",
    )
    assert default_ctx.status not in ("suspected", "observed")
    assert default_ctx.status == "unknown"

    # Opt-in temporal suspicion is context, and direct_incentive stays False
    # (unconfirmed), while the exposure window is recorded.
    ctx = _resolve(
        interaction_ref="in-s",
        campaign=_REWARD_CAMPAIGN,
        activity_occurred_at="2026-05-01T00:00:00Z",
        allow_temporal_suspicion=True,
    )
    assert ctx.status == "suspected"
    assert ctx.direct_incentive is False
    assert ctx.exposure_started_at is not None


def test_observed_never_becomes_a_disqualification() -> None:
    # Incentive exposure is context: an observed incentive still yields a
    # context; it is not a verdict that the activity did not happen.
    ctx = _resolve(
        interaction_ref="in-o2",
        campaign_ref="cmp-1",
        campaign=_REWARD_CAMPAIGN,
        activity_occurred_at="2026-05-01T00:00:00Z",
    )
    assert ctx.status == "observed"
    assert ctx.interaction_ref == "in-o2"


# ── §33 cascade: never flattened to paid/organic ────────────────────────────


def test_downstream_actor_direct_assessment_keeps_upstream_provenance() -> None:
    # B reposts Creator A's incentivized content. B's direct assessment finds
    # nothing (bounded) => none_observed, but the context MUST carry the upstream
    # incentive origin so nothing downstream reads B's act as clean "organic".
    ctx = _resolve(
        interaction_ref="in-b",
        upstream_incentive_origins=("content-ref-A",),
        assessment=IncentiveAssessment(
            scope="bounded_enumeration", source_refs=("reg://rewards",)
        ),
    )
    assert ctx.status == "none_observed"
    assert ctx.direct_incentive is False
    assert ctx.upstream_incentive_origin == "content-ref-A"
    assert any("upstream" in lim for lim in ctx.limitations)


def test_upstream_origin_never_sets_direct_incentive() -> None:
    ctx = _resolve(
        interaction_ref="in-b2",
        upstream_incentive_origins=("content-ref-A",),
    )
    # B's direct incentive unassessed => unknown; the cascade is not flattened.
    assert ctx.status == "unknown"
    assert ctx.direct_incentive is False
    assert ctx.upstream_incentive_origin == "content-ref-A"


def test_direct_verified_does_not_carry_upstream_when_none() -> None:
    ctx = _resolve(
        interaction_ref="in-v",
        signals=[IncentiveSignal(kind="economic_transfer_verified", ref="econ-v")],
    )
    assert ctx.upstream_incentive_origin is None
    assert ctx.direct_incentive is True


def test_verified_outside_campaign_window_gets_no_contradicting_window() -> None:
    # A verified economic transfer in March, while the reward campaign window is
    # Apr-Jun: the campaign window is NOT stamped as the exposure window (it
    # would contradict the activity's own timestamp). Segments stay empty.
    ctx = _resolve(
        interaction_ref="in-vpre",
        campaign_ref="cmp-1",
        campaign=_REWARD_CAMPAIGN,
        activity_occurred_at="2026-03-01T00:00:00Z",
        signals=[IncentiveSignal(kind="economic_transfer_verified", ref="econ-pre")],
    )
    assert ctx.status == "verified"
    assert ctx.exposure_started_at is None
    assert ctx.exposure_ended_at is None
    assert ctx.temporal_segments == []
    assert any("not segmented" in lim for lim in ctx.limitations)


# ── Lineage / provenance ────────────────────────────────────────────────────


def test_every_context_traces_to_policy_and_time() -> None:
    ctx = _resolve()
    assert ctx.policy_ref == POLICY_REF
    assert ctx.computed_at.tzinfo is not None
    assert ctx.schema_version == "1.0.0"


def test_evidence_refs_collected_from_all_sources() -> None:
    ctx = _resolve(
        campaign_ref="cmp-1",
        campaign=_REWARD_CAMPAIGN,
        activity_occurred_at="2026-05-01T00:00:00Z",
        signals=[IncentiveSignal(kind="reward_program_observed", ref="rw-9")],
        assessment=IncentiveAssessment(
            scope="window_bounded", source_refs=("reg://campaigns",)
        ),
    )
    for ref in ("rw-9", "cmp-row-1", "cmp-1", "reg://campaigns"):
        assert ref in ctx.evidence_refs
    assert len(ctx.evidence_refs) == len(set(ctx.evidence_refs))  # deduped


def test_reward_ref_and_condition_carry_through() -> None:
    ctx = _resolve(
        campaign_ref="cmp-1",
        campaign=CampaignEvidence(
            campaign_ref="cmp-1",
            reward_program=True,
            reward_condition="per_qualified_interaction",
            eligibility_rule_ref="rule-7",
            start_at="2026-04-01T00:00:00+00:00",
            end_at="2026-06-01T00:00:00+00:00",
            source_ref="cmp-row-1",
        ),
        signals=[IncentiveSignal(kind="reward_program_observed", ref="rw-9")],
    )
    assert ctx.status == "observed"
    assert ctx.reward_condition == "per_qualified_interaction"
    assert ctx.eligibility_rule_ref == "rule-7"
    assert ctx.reward_ref == "rw-9"


def test_contradiction_surfaced_when_non_reward_campaign_conflicts() -> None:
    # Positive signal + positively-known non-reward campaign = contradiction is
    # recorded, never hidden.
    ctx = _resolve(
        campaign_ref="cmp-0",
        campaign=_NON_REWARD_CAMPAIGN,
        activity_occurred_at="2026-05-01T00:00:00Z",
        signals=[IncentiveSignal(kind="economic_transfer_verified", ref="econ-c")],
    )
    assert ctx.status == "verified"  # the economic record is stronger evidence
    assert "cmp-row-0" in ctx.contradictory_evidence_refs


# ── Determinism / observation-flag mapping ──────────────────────────────────


def test_context_id_is_deterministic_and_content_addressed() -> None:
    a = _resolve(interaction_ref="in-det")
    b = _resolve(interaction_ref="in-det")
    c = _resolve(interaction_ref="in-other")
    assert a.incentive_context_id == b.incentive_context_id
    assert a.incentive_context_id != c.incentive_context_id


def test_build_context_id_requires_an_anchor() -> None:
    with pytest.raises(ValueError):
        build_context_id(None, "", None)


def test_observation_flags_mapping_is_honest() -> None:
    positive = ("verified", "declared", "observed", "suspected")
    for status in positive:
        assert to_observation_flags(_make(status)) == (True, True), status
    assert to_observation_flags(_make("none_observed")) == (False, True)
    # unknown and not_applicable are NOT assessed as present or absent.
    assert to_observation_flags(_make("unknown")) == (False, False)
    assert to_observation_flags(_make("not_applicable")) == (False, False)


def _make(status: str) -> IncentiveContext:
    if status == "verified":
        return _resolve(
            interaction_ref=f"in-{status}",
            signals=[IncentiveSignal(kind="economic_transfer_verified", ref=f"econ-{status}")],
        )
    if status == "declared":
        return _resolve(
            interaction_ref=f"in-{status}",
            signals=[IncentiveSignal(kind="sponsorship_declared", ref=f"spo-{status}")],
        )
    if status == "observed":
        return _resolve(
            interaction_ref=f"in-{status}",
            campaign_ref="cmp-1",
            campaign=_REWARD_CAMPAIGN,
            activity_occurred_at="2026-05-01T00:00:00Z",
        )
    if status == "suspected":
        return _resolve(
            interaction_ref=f"in-{status}",
            campaign=_REWARD_CAMPAIGN,
            activity_occurred_at="2026-05-01T00:00:00Z",
            allow_temporal_suspicion=True,
        )
    if status == "none_observed":
        return _resolve(
            interaction_ref=f"in-{status}",
            assessment=IncentiveAssessment(
                scope="bounded_enumeration", source_refs=("reg://campaigns",)
            ),
        )
    if status == "unknown":
        return _resolve(interaction_ref=f"in-{status}")
    if status == "not_applicable":
        return _resolve(
            interaction_ref=f"in-{status}",
            assessment=IncentiveAssessment(scope="not_applicable"),
        )
    raise AssertionError(f"unhandled status {status}")
