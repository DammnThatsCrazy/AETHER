"""Tenant and Kyber routes for Derivatives Intelligence PR4 product surfaces."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field, SecretStr

from shared.common.common import (
    APIResponse,
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from value.derivatives import counters
from value.derivatives.product import product_service

router = APIRouter(prefix="/v1/derivatives", tags=["Derivatives"])
kyber_router = APIRouter(prefix="/v1/admin/kyber/derivatives", tags=["Kyber Derivatives"])


class MeterUsageRequest(BaseModel):
    meter: str
    quantity: str = Field(..., description="Fixed-precision decimal quantity")


class OperatorActionRequest(BaseModel):
    tenant_id: str
    action: str
    scope: dict[str, Any] = Field(default_factory=dict)


def _tenant_id(request: Request) -> str:
    return request.state.tenant.tenant_id


def _require_derivatives_read(request: Request) -> None:
    tenant = request.state.tenant
    if hasattr(tenant, "require_permission"):
        tenant.require_permission("derivatives:read")


def _require_derivatives_export(request: Request) -> None:
    tenant = request.state.tenant
    if hasattr(tenant, "require_permission"):
        tenant.require_permission("derivatives:export")


from governance.security.request_context import is_kyber_operator as _is_kyber_operator


def _require_kyber_operator(request: Request) -> None:
    tenant = request.state.tenant
    # Canonical fail-closed operator check (replaces the never-set
    # is_platform_admin flag): only kyber:operator grant or the operator
    # tenant-id allowlist passes; Aether tenants (incl. Role.ADMIN) are denied.
    if not _is_kyber_operator(tenant):
        raise ForbiddenError("Kyber operator access required; Aether tenants may not access Kyber")
    if hasattr(tenant, "require_permission"):
        tenant.require_permission("derivatives:connector:admin")


@router.get("/overview")
async def derivatives_overview(request: Request) -> dict:
    _require_derivatives_read(request)
    return APIResponse(data=product_service.overview(_tenant_id(request))).to_dict()


@router.get("/accounts")
async def derivatives_accounts(request: Request) -> dict:
    _require_derivatives_read(request)
    return APIResponse(data={"items": product_service.accounts(_tenant_id(request))}).to_dict()


@router.get("/positions")
async def derivatives_positions(request: Request, status: str | None = Query(default=None)) -> dict:
    _require_derivatives_read(request)
    return APIResponse(data={"items": product_service.positions(_tenant_id(request), status=status)}).to_dict()


@router.get("/positions/{position_epoch_id}")
async def derivatives_position_detail(position_epoch_id: str, request: Request) -> dict:
    _require_derivatives_read(request)
    detail = product_service.position_detail(_tenant_id(request), position_epoch_id)
    if detail is None:
        raise NotFoundError("Derivatives position")
    return APIResponse(data=detail).to_dict()


@router.get("/behavior")
async def derivatives_behavior(request: Request, window: str = Query(default="lifetime")) -> dict:
    _require_derivatives_read(request)
    return APIResponse(data=product_service.behavior(_tenant_id(request), window=window)).to_dict()


@router.get("/realtime/topics")
async def derivatives_realtime_topics(request: Request) -> dict:
    _require_derivatives_read(request)
    return APIResponse(data=product_service.realtime_catalog(_tenant_id(request))).to_dict()


@router.get("/alerts/rules")
async def derivatives_alert_rules(request: Request) -> dict:
    _require_derivatives_read(request)
    return APIResponse(data=product_service.alert_catalog(_tenant_id(request))).to_dict()


@router.post("/usage")
async def derivatives_meter_usage(body: MeterUsageRequest, request: Request) -> dict:
    _require_derivatives_read(request)
    return APIResponse(data=product_service.meter_usage(_tenant_id(request), body.meter, Decimal(body.quantity))).to_dict()


@router.get("/export/evidence")
async def derivatives_export_evidence(request: Request) -> dict:
    _require_derivatives_export(request)
    tenant_id = _tenant_id(request)
    return APIResponse(data={
        "tenant_id": tenant_id,
        "export_type": "derivatives_evidence",
        "credential_material_included": False,
        "items": product_service.positions(tenant_id),
    }).to_dict()


@kyber_router.get("/fleet")
async def kyber_derivatives_fleet(request: Request) -> dict:
    _require_kyber_operator(request)
    operator = _tenant_id(request)
    computed = await counters.compute_kyber_fleet(operator_tenant_id=operator)
    # Counters computed from durable state win; fields only the product snapshot
    # model carries (e.g. backfill_state) are kept.
    return APIResponse(data={**product_service.kyber_fleet(operator), **computed}).to_dict()


@kyber_router.get("/data-quality")
async def kyber_derivatives_data_quality(request: Request) -> dict:
    _require_kyber_operator(request)
    operator = _tenant_id(request)
    computed = await counters.compute_kyber_data_quality(operator_tenant_id=operator)
    return APIResponse(data={**product_service.kyber_data_quality(operator), **computed}).to_dict()


@kyber_router.get("/reconciliation")
async def kyber_derivatives_reconciliation(request: Request, tenant_id: str | None = Query(default=None)) -> dict:
    _require_kyber_operator(request)
    return APIResponse(data=product_service.kyber_reconciliation(_tenant_id(request), tenant_id=tenant_id)).to_dict()


@kyber_router.get("/graph-quality")
async def kyber_derivatives_graph_quality(request: Request) -> dict:
    _require_kyber_operator(request)
    operator = _tenant_id(request)
    computed = await counters.compute_kyber_graph_quality(operator_tenant_id=operator)
    return APIResponse(data={**product_service.kyber_graph_quality(operator), **computed}).to_dict()


@kyber_router.get("/intelligence-quality")
async def kyber_derivatives_intelligence_quality(request: Request) -> dict:
    _require_kyber_operator(request)
    return APIResponse(data=product_service.kyber_intelligence_quality(_tenant_id(request))).to_dict()


@kyber_router.post("/operator-actions")
async def kyber_derivatives_operator_action(body: OperatorActionRequest, request: Request) -> dict:
    _require_kyber_operator(request)
    return APIResponse(data=product_service.record_operator_action(_tenant_id(request), body.tenant_id, body.action, body.scope)).to_dict()


# ── Tenant venue account links (flag-gated; AETHER_VENUE_ACCOUNT_LINKS_ENABLED) ──


class WalletLinkRequest(BaseModel):
    subject_id: str
    venue: str
    wallet_address: str
    chain_namespace: str = Field(..., description="CAIP-2 namespace used for the ownership proof")
    proof_evidence_id: str = Field(..., description="wallet_ownership_verified evidence id")
    consent_receipt_id: str


class TenantPushLinkRequest(BaseModel):
    subject_id: str
    venue: str
    account_ref: str
    consent_receipt_id: str


class CredentialLinkRequest(BaseModel):
    """A subject's read-only venue key. The secret is stored by the credential
    broker under the link's connection and never returned."""

    subject_id: str
    venue: str
    account_ref: str
    api_key: SecretStr
    api_secret: SecretStr | None = None
    passphrase: SecretStr | None = None
    scopes: list[str] = Field(..., min_length=1)
    consent_receipt_id: str


class RevokeLinkRequest(BaseModel):
    reason: str = ""


def _actor(request: Request) -> str:
    tenant = request.state.tenant
    return getattr(tenant, "user_id", None) or getattr(tenant, "tenant_id", None) or "system"


def _venue_credential(body: "CredentialLinkRequest"):
    from shared.credentials.types import (
        ApiKeyCredential,
        KeyIdSecretCredential,
        MultiCredential,
    )

    key = body.api_key.get_secret_value()
    if body.api_secret is None:
        primary = ApiKeyCredential(api_key=key)
    else:
        primary = KeyIdSecretCredential(key_id=key, secret=body.api_secret.get_secret_value())
    if body.passphrase is None:
        return primary
    return MultiCredential(credentials={
        "primary": primary,
        "passphrase": ApiKeyCredential(api_key=body.passphrase.get_secret_value()),
    })


def _require_account_links_enabled() -> None:
    from config.settings import settings

    if not settings.derivatives.venue_account_links_enabled:
        raise ServiceUnavailableError("Venue account links are disabled")


def _require_derivatives_connect(request: Request) -> None:
    tenant = request.state.tenant
    if hasattr(tenant, "require_permission"):
        tenant.require_permission("derivatives:connect")


def _link_service():
    from value.derivatives.account_links import VenueAccountLinkService

    return VenueAccountLinkService()


@router.get("/account-links")
async def list_venue_account_links(
    request: Request,
    venue: str | None = Query(default=None),
    subject_id: str | None = Query(default=None),
    include_revoked: bool = Query(default=False),
) -> dict:
    _require_account_links_enabled()
    _require_derivatives_read(request)
    from value.derivatives.account_links import LinkStatus

    links = await _link_service().list_links(
        _tenant_id(request), venue=venue, subject_id=subject_id, active_only=False,
    )
    if not include_revoked:
        links = [link for link in links if link.status is not LinkStatus.REVOKED]
    return APIResponse(data={"items": [link.to_record() for link in links]}).to_dict()


@router.post("/account-links/wallet")
async def create_wallet_account_link(body: WalletLinkRequest, request: Request) -> dict:
    from value.derivatives.account_links import AccountLinkError

    _require_account_links_enabled()
    _require_derivatives_connect(request)
    try:
        link = await _link_service().link_wallet(
            tenant_id=_tenant_id(request), actor=_actor(request), **body.model_dump(),
        )
    except AccountLinkError as exc:
        raise BadRequestError(exc.reason) from exc
    return APIResponse(data=link.to_record()).to_dict()


@router.post("/account-links/tenant-push")
async def create_tenant_push_account_link(body: TenantPushLinkRequest, request: Request) -> dict:
    from value.derivatives.account_links import AccountLinkError

    _require_account_links_enabled()
    _require_derivatives_connect(request)
    try:
        link = await _link_service().link_tenant_push(
            tenant_id=_tenant_id(request), actor=_actor(request), **body.model_dump(),
        )
    except AccountLinkError as exc:
        raise BadRequestError(exc.reason) from exc
    return APIResponse(data=link.to_record()).to_dict()


@router.post("/account-links/credential")
async def create_credential_account_link(body: CredentialLinkRequest, request: Request) -> dict:
    from value.derivatives.account_links import AccountLinkError, LinkMethod
    from value.derivatives.models import ReadOnlyCredentialError

    _require_account_links_enabled()
    _require_derivatives_connect(request)
    try:
        link = await _link_service().link_credential(
            tenant_id=_tenant_id(request),
            subject_id=body.subject_id,
            venue=body.venue,
            account_ref=body.account_ref,
            method=LinkMethod.READ_ONLY_API_KEY,
            credential=_venue_credential(body),
            scopes=body.scopes,
            consent_receipt_id=body.consent_receipt_id,
            actor=_actor(request),
        )
    except (AccountLinkError, ReadOnlyCredentialError) as exc:
        raise BadRequestError(getattr(exc, "reason", None) or str(exc)) from exc
    return APIResponse(data=link.to_record()).to_dict()


@router.post("/account-links/sync")
async def sync_venue_account_links(request: Request) -> dict:
    """Read every active governed link of this tenant through rights admission."""
    from value.derivatives.account_sync import VenueAccountSync

    _require_account_links_enabled()
    _require_derivatives_connect(request)
    result = await VenueAccountSync(link_service=_link_service()).sync_tenant(_tenant_id(request))
    return APIResponse(data=result.to_dict()).to_dict()


@router.post("/account-links/{link_id}/sync")
async def sync_venue_account_link(link_id: str, request: Request) -> dict:
    from value.derivatives.account_sync import VenueAccountSync

    _require_account_links_enabled()
    _require_derivatives_connect(request)
    service = _link_service()
    link = await service.get_link(_tenant_id(request), link_id)
    if link is None:
        raise NotFoundError("Venue account link")
    result = await VenueAccountSync(link_service=service).sync_link(link)
    return APIResponse(data=result.to_dict()).to_dict()


@router.post("/account-links/{link_id}/disconnect")
async def disconnect_venue_account_link(link_id: str, request: Request) -> dict:
    """Stop reading the account; its grant still governs admitted history."""
    _require_account_links_enabled()
    _require_derivatives_connect(request)
    link = await _link_service().disconnect(
        tenant_id=_tenant_id(request), link_id=link_id, actor=_actor(request),
    )
    if link is None:
        raise NotFoundError("Venue account link")
    return APIResponse(data=link.to_record()).to_dict()


@router.post("/account-links/{link_id}/revoke")
async def revoke_venue_account_link(link_id: str, body: RevokeLinkRequest, request: Request) -> dict:
    _require_account_links_enabled()
    _require_derivatives_connect(request)
    link = await _link_service().revoke(
        tenant_id=_tenant_id(request), link_id=link_id, reason=body.reason, actor=_actor(request),
    )
    if link is None:
        raise NotFoundError("Venue account link")
    return APIResponse(data=link.to_record()).to_dict()
