"""Journey handoff routes: issue (source device), redeem (destination), read (tenant)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from config.settings import settings
from shared.common.common import BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics

from .service import issue_handoff, list_handoffs, peek_handoff_source, redeem_handoff

logger = get_logger("aether.service.journey_handoff")
router = APIRouter(prefix="/sdk/journey-handoff", tags=["SDK Journey Handoff"])


def _strip_required(value: str) -> str:
    """Identifiers are trimmed before the length check, so a blank value is a
    422 from request validation rather than a service-level ValueError (500)."""
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


class IssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    journey_id: str = Field(..., min_length=1, max_length=256)
    session_id: str = Field(..., min_length=1, max_length=256)
    anonymous_id: str = Field(..., min_length=1, max_length=256)
    platform: Optional[str] = Field(default=None, max_length=32)
    ttl_seconds: int = Field(default=600, ge=30, le=900)
    tenant_app_key: Optional[str] = None

    _strip_ids = field_validator("journey_id", "session_id", "anonymous_id")(_strip_required)


class RedeemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(..., min_length=8, max_length=256)
    session_id: str = Field(..., min_length=1, max_length=256)
    anonymous_id: str = Field(..., min_length=1, max_length=256)
    platform: Optional[str] = Field(default=None, max_length=32)
    tenant_app_key: Optional[str] = None

    _strip_ids = field_validator("session_id", "anonymous_id")(_strip_required)


def _require_enabled() -> None:
    if not settings.identity_continuity.journey_handoff_enabled:
        raise NotFoundError("journey handoff (feature not enabled)")


async def _require_link_consent(tenant_id: str, anonymous_id: str) -> None:
    """Both ends must have granted identity-link consent; fail closed."""
    from governance.consent.authority import evaluate_identity_link_consent

    try:
        allowed, reason, _ctx = await evaluate_identity_link_consent(tenant_id, anonymous_id)
    except Exception as exc:
        logger.warning(
            "journey_handoff.consent_lookup_failed",
            extra={"tenant_id": tenant_id, "error_type": type(exc).__name__},
        )
        raise BadRequestError("identity_link_consent_lookup_failed")
    if not allowed:
        raise BadRequestError(reason or "identity_link_consent_required")


def _scope(request: Request, requested_app: Optional[str]) -> tuple[str, str]:
    from ingestion.sdk.routes import _authenticated_app_scope

    namespace, error = _authenticated_app_scope(request, requested_app)
    if error or not namespace:
        raise BadRequestError(error or "sdk_app_scope_unavailable")
    return str(request.state.tenant.tenant_id), namespace


@router.post("")
async def issue(body: IssueRequest, request: Request) -> dict:
    _require_enabled()
    tenant_id, namespace = _scope(request, body.tenant_app_key)
    await _require_link_consent(tenant_id, body.anonymous_id)
    issued = await issue_handoff(
        tenant_id=tenant_id, app_namespace=namespace, journey_id=body.journey_id,
        session_id=body.session_id, anonymous_id=body.anonymous_id,
        platform=body.platform or "unknown", ttl_seconds=body.ttl_seconds,
    )
    metrics.increment("journey_handoff_issued_total")
    return {"data": issued}


@router.post("/redeem")
async def redeem(body: RedeemRequest, request: Request) -> dict:
    _require_enabled()
    tenant_id, namespace = _scope(request, body.tenant_app_key)
    await _require_link_consent(tenant_id, body.anonymous_id)
    # The source subject's consent can lapse between issuance and redemption, and
    # redemption creates an explicit cross-session link carrying its identifiers,
    # so re-evaluate it now (the contract requires consent at both ends). A
    # revoked source answers exactly like an unknown token.
    source_anonymous_id = await peek_handoff_source(
        tenant_id=tenant_id, app_namespace=namespace, token=body.token,
    )
    if source_anonymous_id is not None:
        try:
            await _require_link_consent(tenant_id, source_anonymous_id)
        except BadRequestError:
            metrics.increment(
                "journey_handoff_rejected_total", labels={"reason": "source_consent"}
            )
            raise NotFoundError("handoff token")
    link, reason = await redeem_handoff(
        tenant_id=tenant_id, app_namespace=namespace, token=body.token,
        session_id=body.session_id, anonymous_id=body.anonymous_id,
        platform=body.platform or "unknown",
    )
    if link is None:
        # One uniform answer: do not reveal whether a token exists, expired, or
        # belongs to another tenant/app.
        metrics.increment("journey_handoff_rejected_total", labels={"reason": reason})
        raise NotFoundError("handoff token")
    metrics.increment("journey_handoff_redeemed_total")
    return {"data": link}


@router.get("/journeys/{journey_id}")
async def journey_handoffs(journey_id: str, request: Request) -> dict:
    """Tenant read: the explicit handoffs recorded for one journey."""
    _require_enabled()
    tenant = request.state.tenant
    tenant.require_permission("read")
    items = await list_handoffs(str(tenant.tenant_id), journey_id)
    return {"data": {"journey_id": journey_id, "items": items, "count": len(items)}}
