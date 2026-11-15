"""Apple Ads attribution-token exchange (user-level iOS install attribution).

iOS gives apps exactly one user-level, platform-verified ad attribution signal
that needs no App Tracking Transparency consent: the AdServices attribution
token (``AAAttribution.attributionToken()``, iOS 14.3+). It covers Apple Ads
(Apple Search Ads) campaigns only. Installs from other ad networks stay
Direct / Unknown at user level; their campaign-level evidence is the separate
AdAttributionKit / SKAdNetwork postback path (``value/attribution/apple_postbacks.py``).

Flow: the iOS SDK reads the token and posts it here with its anonymous ID. The
backend exchanges it with Apple (``POST https://api-adservices.apple.com/api/v1/``,
body = the raw token). Apple's answer is the verification, so the result is
recorded SERVER-SIDE as a touchpoint and a canonical activity with
``entry_method = "ios_apple_ads_attribution"`` and ``proof_level =
"platform_verified"``. The client never asserts the evidence: a forged event
carrying the same entry method cannot write this activity.

Replay safety: the canonical activity's idempotency key is the SHA-256 of the
token, so a token resolves for the first anonymous ID that presented it and is
refused for any other. Only the hash is stored, never the token.

Apple returns 404 while the attribution record is not ready yet; that maps to
``{"resolved": false, "status": "pending", "retry_after_seconds": 5}`` so the
SDK retries (Apple recommends up to three attempts five seconds apart) instead
of the request blocking.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from config.settings import settings
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.traffic.apple_ads_attribution")

router = APIRouter(prefix="/v1/attribution/apple-ads", tags=["apple-ads-attribution"])

APPLE_ADS_ATTRIBUTION_URL = os.getenv(
    "AETHER_APPLE_ADS_ATTRIBUTION_URL", "https://api-adservices.apple.com/api/v1/"
)
ENTRY_METHOD = "ios_apple_ads_attribution"
PROOF_LEVEL = "platform_verified"
TOUCHPOINT_TABLE = "silver_campaign_touchpoint_facts"
_MAX_TOKEN_LENGTH = 8192
_RETRY_AFTER_SECONDS = 5
_TIMEOUT_SECONDS = 10.0

# Fields of Apple's response that become evidence. Everything else is dropped.
_APPLE_FIELDS = ("orgId", "campaignId", "adGroupId", "keywordId", "adId", "creativeSetId",
                 "conversionType", "claimType", "countryOrRegion", "clickDate")


class AppleAdsResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=_MAX_TOKEN_LENGTH)
    anonymous_id: str = Field(min_length=1, max_length=256)
    session_id: Optional[str] = Field(default=None, max_length=256)
    install_id: Optional[str] = Field(default=None, max_length=256)

    @field_validator("token", "anonymous_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class AppleExchangeResult(BaseModel):
    status: str  # "attributed" | "not_attributed" | "pending" | "invalid" | "unavailable"
    payload: dict[str, Any] = Field(default_factory=dict)


async def exchange_token(token: str) -> AppleExchangeResult:
    """Exchange an attribution token with Apple. Never raises for Apple errors."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                APPLE_ADS_ATTRIBUTION_URL, content=token.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
            )
    except httpx.HTTPError as exc:
        logger.warning("apple ads exchange transport error: %s", type(exc).__name__)
        return AppleExchangeResult(status="unavailable")
    if response.status_code == 404:
        return AppleExchangeResult(status="pending")
    if response.status_code == 400:
        return AppleExchangeResult(status="invalid")
    if response.status_code != 200:
        return AppleExchangeResult(status="unavailable")
    try:
        body = response.json()
    except ValueError:
        return AppleExchangeResult(status="unavailable")
    if not isinstance(body, dict):
        return AppleExchangeResult(status="unavailable")
    if body.get("attribution") is not True:
        return AppleExchangeResult(status="not_attributed")
    return AppleExchangeResult(
        status="attributed",
        payload={k: body[k] for k in _APPLE_FIELDS if body.get(k) is not None},
    )


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _evidence(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_method": ENTRY_METHOD,
        "proof_level": PROOF_LEVEL,
        "source": "apple_search_ads",
        "medium": "cpc",
        "source_class": "paid_search",
        "channel_family": "search",
        "economic_class": "paid",
        "traffic_origin": "app_store",
        "attribution_provider": "apple_adservices",
        "campaign_id": str(payload["campaignId"]) if payload.get("campaignId") is not None else None,
        "ad_group_id": str(payload["adGroupId"]) if payload.get("adGroupId") is not None else None,
        "keyword_id": str(payload["keywordId"]) if payload.get("keywordId") is not None else None,
        "ad_id": str(payload["adId"]) if payload.get("adId") is not None else None,
        "org_id": str(payload["orgId"]) if payload.get("orgId") is not None else None,
        "conversion_type": payload.get("conversionType"),
        "claim_type": payload.get("claimType"),
        "country_or_region": payload.get("countryOrRegion"),
        "click_date": payload.get("clickDate"),
    }


async def record_attribution(
    tenant_id: str, body: AppleAdsResolve, evidence: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Persist the verified attribution. Returns (accepted, activity_row).

    ``accepted`` is False when the token was already bound to a different
    anonymous ID; nothing new is written in that case.
    """
    from journeys.measurement.repositories.activity_repo import ActivityRepository
    from journeys.measurement.repositories.touchpoint_repo import TouchpointRepository

    digest = token_hash(body.token)
    key = f"apple_ads:{digest}"
    # One deterministic touchpoint ID per token, written on both the touchpoint
    # and the canonical activity (silver_table / silver_fact_id), so the journey
    # compiler lists it in touchpoint_ids and attribution can credit it.
    touchpoint_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aether:apple_ads:{tenant_id}:{digest}"))
    occurred_at = evidence.get("click_date") or datetime.now(timezone.utc).isoformat()
    activity = await ActivityRepository().upsert({
        "tenant_id": tenant_id,
        "idempotency_key": key,
        "anonymous_id": body.anonymous_id,
        "session_id": body.session_id,
        "install_id": body.install_id,
        "activity_family": "campaign",
        "activity_type": "app_install_attributed",
        "actor_type": "human",
        "activity_status": "observed",
        "channel": "paid_search",
        "source": evidence["source"],
        "medium": evidence["medium"],
        "platform": "ios",
        "source_class": evidence["source_class"],
        "traffic_origin": evidence["traffic_origin"],
        "economic_class": evidence["economic_class"],
        "channel_family": evidence["channel_family"],
        "entry_method": ENTRY_METHOD,
        "proof_level": PROOF_LEVEL,
        "verification_level": "platform_verified",
        # Apple's campaign ID is external; Aether's campaign_id stays unset
        # until campaign resolution maps it (evidence keeps the external ID).
        "attribution_eligible": True,
        "occurred_at": occurred_at,
        "server_received_at": datetime.now(timezone.utc).isoformat(),
        "source_system": "apple_adservices",
        "silver_table": TOUCHPOINT_TABLE,
        "silver_fact_id": touchpoint_id,
        "privacy_class": "behavioral",
    })
    if activity.get("anonymous_id") != body.anonymous_id:
        return False, activity
    await TouchpointRepository().upsert({
        "touchpoint_id": touchpoint_id,
        "tenant_id": tenant_id,
        "idempotency_key": key,
        "anonymous_id": body.anonymous_id,
        "session_id": body.session_id,
        "external_campaign_id": evidence.get("campaign_id"),
        "external_account_id": evidence.get("org_id"),
        "campaign_resolution_status": "unresolved",
        "ad_group_id": evidence.get("ad_group_id"),
        "keyword_id": evidence.get("keyword_id"),
        "ad_id": evidence.get("ad_id"),
        "channel": "paid_search",
        "source": evidence["source"],
        "medium": evidence["medium"],
        "platform": "apple_search_ads",
        "traffic_origin": evidence["traffic_origin"],
        "economic_class": evidence["economic_class"],
        "channel_family": evidence["channel_family"],
        "verification_level": "platform_verified",
        "attribution_eligible": True,
        "touchpoint_type": "click" if evidence.get("claim_type") != "Impression" else "impression",
        "is_click_through": evidence.get("claim_type") != "Impression",
        "is_view_through": evidence.get("claim_type") == "Impression",
        "source_class": evidence["source_class"],
        "entry_method": ENTRY_METHOD,
        "proof_level": PROOF_LEVEL,
        "occurred_at": occurred_at,
        "properties": {k: v for k, v in evidence.items() if v is not None},
    })
    await _request_journey_rebuild(tenant_id, activity, touchpoint_id)
    return True, activity


async def _request_journey_rebuild(tenant_id: str, activity: dict[str, Any], touchpoint_id: str) -> str:
    """Recompile the journey that now carries the verified acquisition touchpoint.

    Both upserts above are storage-only: the activity-driven rebuild hook runs in
    the silver projectors, which this endpoint bypasses, and the iOS resolver
    emits no further event. Attribution often resolves after the install's
    ordinary activity was already compiled, so without this a user who does
    nothing else keeps a journey missing its acquisition touchpoint.

    Uses the debounced activity rebuild when that is enabled, otherwise the
    touchpoint rebuild path directly. Best-effort: the attribution is already
    durable, and compilation is an idempotent recomputation from those facts.
    Returns how the rebuild was requested, for observability and tests.
    """
    try:
        from journeys.measurement.activity_rebuild import request_for_activities

        if await request_for_activities([activity]):
            return "activity_rebuild_queued"
        from journeys.measurement.engine.journey_compiler import JourneyCompiler

        rebuilt = await JourneyCompiler().rebuild_affected_by_touchpoint(tenant_id, touchpoint_id)
        return "touchpoint_rebuilt" if rebuilt else "no_journey_identity"
    except Exception as exc:  # noqa: BLE001 - the stored attribution is the source of truth
        logger.warning("apple_ads.journey_rebuild_failed",
                       extra={"tenant_id": tenant_id, "error_type": type(exc).__name__})
        return "rebuild_failed"


def _require_enabled() -> None:
    if not settings.mobile.apple_ads_attribution_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


@router.post("/resolve")
async def resolve_apple_ads_attribution(body: AppleAdsResolve, request: Request) -> dict[str, Any]:
    """SDK-facing: exchange the token and record verified Apple Ads attribution."""
    _require_enabled()
    from journeys.traffic.deferred_attribution import _tenant_id_from_request

    tenant_id = _tenant_id_from_request(request)
    result = await exchange_token(body.token)
    metrics.increment("apple_ads_attribution_exchange_total", labels={"status": result.status})
    if result.status == "pending":
        return {"resolved": False, "status": "pending", "retry_after_seconds": _RETRY_AFTER_SECONDS}
    if result.status != "attributed":
        # not_attributed / invalid / unavailable: the install stays Direct / Unknown.
        return {"resolved": False, "status": result.status}
    evidence = _evidence(result.payload)
    accepted, _ = await record_attribution(tenant_id, body, evidence)
    if not accepted:
        metrics.increment("apple_ads_attribution_replay_rejected_total")
        return {"resolved": False, "status": "token_already_bound"}
    return {
        "resolved": True,
        "status": "attributed",
        "evidence": {k: v for k, v in evidence.items() if v is not None},
    }
