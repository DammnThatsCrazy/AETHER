"""Runtime IncentiveContext service facade (Social360 M5).

Thin async layer over the pure resolver that supplies the LIVE evidence:

- optionally resolves campaign evidence through ``services.campaign.resolver``
  (the repo's Campaign360 resolver) when a resolver is injected;
- normalizes a Campaign360 campaign row / Economic360 reward records into the
  resolver's evidence types;
- applies the rollout flag: with Social360 disabled (default) the facade returns
  ``None`` (no context is emitted — consumers treat the activity as NOT
  incentive-assessed, never as organic). The flag is read defensively: if the
  ``Social360Config`` flag does not exist in this environment it is treated as
  False.

The facade never changes the honesty rules — ``none_observed`` still requires a
bounded assessment and ``unknown`` stays ``unknown``.
"""

from __future__ import annotations

import os
from typing import Any, Optional, Protocol

from .models import IncentiveContext
from .resolver import (
    CampaignEvidence,
    IncentiveAssessment,
    IncentiveSignal,
    resolve_incentive_context,
)

__all__ = [
    "CampaignResolverLike",
    "IncentiveContextService",
    "campaign_evidence_from_record",
    "incentive_context_enabled",
    "social360_enabled",
]

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_INCENTIVE_FLAG_ENV = "AETHER_INCENTIVE_CONTEXT_ENABLED"
_SOCIAL_FLAG_ENV = "AETHER_SOCIAL360_ENABLED"


def social360_enabled() -> bool:
    """Fail-closed read of ``AETHER_SOCIAL360_ENABLED`` (False when unset).

    Env wins (live check); otherwise reads ``config.settings`` Social360Config
    defensively — any missing/import error is treated as False.
    """
    raw = os.environ.get(_SOCIAL_FLAG_ENV)
    if raw is not None:
        return raw.strip().lower() in _TRUE_VALUES
    try:
        from config import settings as _settings

        cfg = getattr(getattr(_settings, "settings", None), "social360", None)
        if cfg is not None:
            return bool(getattr(cfg, "social360_enabled", False))
        cls = getattr(_settings, "Social360Config", None)
        if cls is not None:
            return bool(getattr(cls(), "social360_enabled", False))
    except Exception:  # pragma: no cover - defensive; flag absent -> off
        return False
    return False


def incentive_context_enabled() -> bool:
    """M5 emission flag: OFF unless either rollout control is explicitly on.

    Honours both ``AETHER_SOCIAL360_ENABLED`` and the M5-specific
    ``AETHER_INCENTIVE_CONTEXT_ENABLED``; default False (fail-closed).
    """
    own = os.environ.get(_INCENTIVE_FLAG_ENV)
    if own is not None:
        return own.strip().lower() in _TRUE_VALUES
    return social360_enabled()


class _ResolutionResultLike(Protocol):
    status: str
    campaign_id: Any
    method: Optional[str]
    confidence: Any


class CampaignResolverLike(Protocol):
    """Duck-typed ``services.campaign.resolver.CampaignResolver.resolve_one``."""

    async def resolve_one(self, tenant_id: str, **kwargs: Any) -> _ResolutionResultLike:
        ...


def campaign_evidence_from_record(
    row: dict[str, Any],
    *,
    campaign_ref: str,
    resolution_method: Optional[str] = None,
    resolution_confidence: Optional[float] = None,
) -> CampaignEvidence:
    """Normalize a Campaign360 campaign row (repo ``get_by_id`` shape) to evidence.

    ``row`` is the dict a ``CampaignRegistryRepository`` lookup returns
    (``campaign_id`` / ``name`` / ``status`` / ``start_at`` / ``end_at`` /
    ``properties`` / ``origin``). ``reward_program`` is read from the row's
    ``properties`` only when the property is actually present; otherwise it stays
    ``None`` (unknown — never guessed).
    """
    props = row.get("properties") or {}
    reward_program: Optional[bool] = None
    if "reward_program" in props:
        reward_program = bool(props.get("reward_program"))
    reward_condition = props.get("reward_condition") or props.get("rewardCondition")
    sponsored = props.get("sponsored") or props.get("sponsored_declared")

    def _v(*keys: str) -> Optional[object]:
        for k in keys:
            if k in row and row[k] is not None:
                return row[k]
        return None

    return CampaignEvidence(
        campaign_ref=campaign_ref,
        name=_v("name"),
        status=_v("status"),
        start_at=_v("start_at", "startAt", "start_date"),
        end_at=_v("end_at", "endAt", "end_date"),
        zone_id=props.get("timezone") or props.get("tz") or props.get("zone_id"),
        reward_program=reward_program,
        sponsored_declared=bool(sponsored) if sponsored is not None else None,
        reward_condition=str(reward_condition) if reward_condition else None,
        eligibility_rule_ref=(
            str(props["eligibility_rule_ref"]) if props.get("eligibility_rule_ref") else None
        ),
        origin=_v("origin"),
        resolution_method=resolution_method,
        resolution_confidence=resolution_confidence,
        source_ref=_v("campaign_id"),
        note=props.get("note"),
    )


class IncentiveContextService:
    """Flag-gated runtime entrypoint for IncentiveContext resolution."""

    def __init__(
        self,
        campaign_resolver: Optional[CampaignResolverLike] = None,
        *,
        enabled: Optional[bool] = None,
    ) -> None:
        self._campaign_resolver = campaign_resolver
        self._enabled_override = enabled

    @property
    def enabled(self) -> bool:
        if self._enabled_override is not None:
            return self._enabled_override
        return incentive_context_enabled()

    async def resolve(
        self,
        tenant_id: str,
        *,
        evidence: dict[str, Any],
        campaign_record: Optional[dict[str, Any]] = None,
        assessment: Optional[IncentiveAssessment] = None,
        signals: list[IncentiveSignal] | tuple[IncentiveSignal, ...] = (),
        source_scope: Optional[str] = None,
        evidence_basis: Optional[str] = None,
        acquisition_mode: Optional[str] = None,
        timeline: list[Any] | tuple[Any, ...] = (),
        upstream_incentive_origins: list[str] | tuple[str, ...] = (),
        **resolver_kwargs: Any,
    ) -> Optional[IncentiveContext]:
        """Resolve one activity to an IncentiveContext, or ``None`` when disabled.

        When ``evidence`` carries resolvable campaign identifiers (utm / external
        campaign id) and a campaign resolver was injected, the canonical campaign
        is resolved first and its id becomes ``campaign_ref``.
        """
        if not self.enabled:
            return None

        campaign_ref = evidence.get("campaign_ref")
        resolution_method: Optional[str] = None
        resolution_confidence: Optional[float] = None
        if not campaign_ref and self._campaign_resolver is not None:
            resolved_ref, resolution_method, resolution_confidence = await self._resolve_campaign(
                tenant_id, evidence
            )
            campaign_ref = resolved_ref

        campaign = None
        if campaign_ref:
            if campaign_record is not None:
                campaign = campaign_evidence_from_record(
                    campaign_record,
                    campaign_ref=campaign_ref,
                    resolution_method=resolution_method,
                    resolution_confidence=resolution_confidence,
                )
            else:
                campaign = CampaignEvidence(campaign_ref=campaign_ref)

        kw = dict(resolver_kwargs)
        kw.setdefault("tenant_id", tenant_id)
        kw.setdefault("campaign_ref", campaign_ref)
        kw.setdefault("campaign", campaign)
        kw.setdefault("reward_ref", evidence.get("reward_ref"))
        kw.setdefault("economic_value_ref", evidence.get("economic_value_ref"))
        kw.setdefault("reward_condition", evidence.get("reward_condition"))
        kw.setdefault("eligibility_rule_ref", evidence.get("eligibility_rule_ref"))
        kw.setdefault("activity_occurred_at", evidence.get("occurred_at"))
        kw.setdefault("social_identity_ref", evidence.get("social_identity_ref"))
        kw.setdefault("content_ref", evidence.get("content_ref"))
        kw.setdefault("interaction_ref", evidence.get("interaction_ref"))
        kw.setdefault("subject_entity_ref", evidence.get("subject_entity_ref"))
        kw.setdefault("downstream_exposure", evidence.get("downstream_exposure"))
        kw.setdefault("contradictory_evidence_refs", evidence.get("contradictory_evidence_refs") or ())
        kw.setdefault("timeline", timeline)
        kw.setdefault("signals", list(signals))
        kw.setdefault("upstream_incentive_origins", list(upstream_incentive_origins))
        kw.setdefault("assessment", assessment)
        kw.setdefault("source_scope", source_scope or evidence.get("source_scope"))
        kw.setdefault("evidence_basis", evidence_basis or evidence.get("evidence_basis"))
        kw.setdefault("acquisition_mode", acquisition_mode or evidence.get("acquisition_mode"))

        return resolve_incentive_context(**kw)

    async def _resolve_campaign(
        self, tenant_id: str, evidence: dict[str, Any]
    ) -> tuple[Optional[str], Optional[str], Optional[float]]:
        resolver = self._campaign_resolver
        if resolver is None:
            return None, None, None
        kwargs: dict[str, Any] = {
            k: evidence[k]
            for k in (
                "canonical_campaign_id",
                "platform",
                "external_account_id",
                "external_campaign_id",
                "utm_id",
                "utm_source",
                "utm_medium",
                "utm_campaign",
                "utm_content",
                "utm_term",
                "referrer",
                "landing_url",
            )
            if evidence.get(k) is not None
        }
        kwargs["create_review_on_failure"] = False
        result = await resolver.resolve_one(tenant_id, **kwargs)
        if getattr(result, "status", None) != "resolved":
            return None, None, None
        campaign_id = getattr(result, "campaign_id", None)
        if campaign_id is None:
            return None, None, None
        confidence = getattr(result, "confidence", None)
        try:
            confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence = None
        return str(campaign_id), getattr(result, "method", None), confidence
