"""
Aether Service — SDK Distribution Routes

The customer-facing half of SDK distribution: where a property is registered,
where the install snippet comes from, and where an operator can see whether the
install actually came up.

Endpoints:
    GET    /v1/sdk/sites                      List the tenant's sites
    POST   /v1/sdk/sites                      Register a site
    GET    /v1/sdk/sites/{site_id}            One site + its install state
    PATCH  /v1/sdk/sites/{site_id}            Rename / re-scope / revoke
    DELETE /v1/sdk/sites/{site_id}            Remove, if nothing is bound to it
    GET    /v1/sdk/sites/{site_id}/install    Snippet + bound keys (the install page)
    POST   /v1/sdk/sites/{site_id}/keys       Mint a publishable key for this site

The install page is deliberately one endpoint returning both the snippet and
the keys already bound to the site. A snippet is only pasteable with a key, and
a key is only readable once — at mint time — so an install page that fetched
them separately would send operators hunting for a credential the platform
cannot show them again.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.auth.auth import KEY_CLASS_PUBLISHABLE
from shared.common.common import (
    APIResponse,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from shared.logger.logger import get_logger, metrics
from shared.observability import trace_request, emit_latency

from services.me.key_issuance import mint_api_key
from services.sdk_distribution.control_plane import register_site_install
from services.sdk_distribution.install_verifier import (
    FIRST_SIGNAL_WINDOW_SECONDS,
    SIGNAL_ORDER,
    STATE_LIVE,
    describe_site_install,
)
from services.sdk_distribution.sites import (
    STATUS_ACTIVE,
    STATUS_REVOKED,
    SDKSiteRepository,
    SiteOriginError,
    new_site_id,
    normalize_origins,
)
from services.sdk_distribution.snippet import LOADER_URL, build_snippet

logger = get_logger("aether.service.sdk_distribution.routes")
router = APIRouter(prefix="/v1/sdk", tags=["SDK — Distribution"])

_sites = SDKSiteRepository()


class SiteCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    origins: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Origins the snippet is installed on, e.g. "
        "['https://example.com', 'www.example.com']. Bare hosts are read as "
        "https; wildcards are refused (list each subdomain).",
    )
    environment: str = Field(
        default="production",
        pattern="^(production|staging|development)$",
        description="Which of the operator's own environments this site is.",
    )


class SiteUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    origins: Optional[list[str]] = Field(default=None, min_length=1, max_length=50)
    environment: Optional[str] = Field(
        default=None, pattern="^(production|staging|development)$"
    )
    status: Optional[str] = Field(
        default=None,
        pattern=f"^({STATUS_ACTIVE}|{STATUS_REVOKED})$",
        description="Revoking stops the site being handed out for new installs. "
        "It does not by itself invalidate keys already bound to it — revoke "
        "those explicitly so nothing is left relying on a site that is gone.",
    )


class SiteKeyCreateRequest(BaseModel):
    name: str = Field(default="Install key", min_length=1, max_length=100)


def _tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        from shared.common.common import UnauthorizedError

        raise UnauthorizedError("Authentication required")
    return tenant


def _require_operator(request: Request):
    """Site changes mint install credentials, so they are an operator action.

    Reading is left to any authenticated tenant member; writing is not. A
    publishable key is public the moment it is issued, and the site is the only
    thing scoping it, so registering or re-scoping one is a credential decision
    rather than a preference.
    """
    tenant = _tenant(request)
    tenant.require_permission("write")
    return tenant


async def _load_site(tenant_id: str, site_id: str) -> dict:
    record = await _sites.get(tenant_id, site_id)
    if record is None:
        raise NotFoundError(f"Site {site_id}")
    return record


async def _site_install(tenant_id: str, site_id: str) -> dict:
    """The site's install record, read through the verifier's own view.

    A site that was registered but never installed has no record; that is a
    normal answer rather than an error, so the reader gets the same shape
    either way and does not have to special-case the absence.
    """
    from repositories.sdk_repos import SDKInstallationRepository

    record = await SDKInstallationRepository().get(tenant_id, site_id)
    return describe_site_install(record)


async def _keys_bound_to(tenant_id: str, site_id: str) -> list[dict]:
    """Publishable keys whose site binding includes ``site_id``.

    The binding is a JSONB list, which ``find_many``'s text-equality filters
    cannot match against, so the tenant's keys are read and filtered here.
    """
    from repositories.repos import APIKeyRepository

    keys = await APIKeyRepository().find_many(
        filters={"tenant_id": tenant_id}, limit=1000
    )
    bound = []
    for key in keys:
        if key.get("key_class") != KEY_CLASS_PUBLISHABLE:
            continue
        if site_id in (key.get("site_ids") or []):
            bound.append({
                "id": key.get("id"),
                "name": key.get("name"),
                "created_at": key.get("created_at"),
                "last_used_at": key.get("last_used_at"),
            })
    return bound


@router.get("/sites")
async def list_sites(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    include_revoked: bool = Query(default=False),
):
    """List the calling tenant's sites."""
    ctx = trace_request(request, service="sdk_distribution")
    tenant = _tenant(request)
    records = await _sites.list_for_tenant(
        tenant.tenant_id, limit=limit, include_revoked=include_revoked
    )
    emit_latency("sdk_sites_listed", ctx.elapsed_ms())
    return APIResponse(data={
        "sites": records,
        "count": len(records),
        "installable": sum(1 for r in records if r.get("status") == STATUS_ACTIVE),
    }).to_dict()


@router.post("/sites")
async def create_site(body: SiteCreateRequest, request: Request):
    """Register a site the SDK will be installed on."""
    ctx = trace_request(request, service="sdk_distribution")
    tenant = _require_operator(request)

    try:
        origins = normalize_origins(body.origins)
    except SiteOriginError as exc:
        raise BadRequestError(str(exc)) from exc

    from shared.common.common import utc_now

    now = utc_now().isoformat()
    record = await _sites.insert(new_site_id(), {
        "tenant_id": tenant.tenant_id,
        "name": body.name,
        "origins": origins,
        "environment": body.environment,
        "status": STATUS_ACTIVE,
        "created_by": getattr(tenant, "user_id", None) or tenant.tenant_id,
        "created_at": now,
        "updated_at": now,
    })

    metrics.increment("sdk_sites_registered")
    logger.info(
        f"SDK site registered: tenant={tenant.tenant_id} site={record['id']}"
    )
    # Hand the site to the Reconciled Control Plane, when the plane is on. A
    # site is registered here rather than on its first install signal because
    # the site that never installs is the one worth seeing: a site with no
    # handshake has nothing to project, so registering at first signal would
    # leave exactly the broken installs outside the plane's view. Never raises,
    # and returns None with the plane off (the default), so site creation does
    # not depend on a plane this deploy may not run.
    await register_site_install(record)
    emit_latency("sdk_site_registered", ctx.elapsed_ms())
    return APIResponse(data={"site": record}).to_dict()


@router.get("/sites/{site_id}")
async def get_site(site_id: str, request: Request):
    """Return one site, its install state and anything bound to it."""
    ctx = trace_request(request, service="sdk_distribution")
    tenant = _tenant(request)
    record = await _load_site(tenant.tenant_id, site_id)

    bound = await _keys_bound_to(tenant.tenant_id, site_id)
    emit_latency("sdk_site_fetched", ctx.elapsed_ms())
    return APIResponse(data={
        "site": record,
        "bound_keys": bound,
        "install": {
            "loader_url": LOADER_URL,
            "install_url": f"/v1/sdk/sites/{site_id}/install",
            "ready": record.get("status") == STATUS_ACTIVE and bool(bound),
            "blocked_reason": (
                "site is revoked" if record.get("status") != STATUS_ACTIVE
                else None if bound
                else "no publishable key is bound to this site yet"
            ),
        },
    }).to_dict()


@router.patch("/sites/{site_id}")
async def update_site(site_id: str, body: SiteUpdateRequest, request: Request):
    """Rename a site, change its origins, or revoke it."""
    ctx = trace_request(request, service="sdk_distribution")
    tenant = _require_operator(request)
    record = await _load_site(tenant.tenant_id, site_id)

    changes: dict = {}
    if body.name is not None:
        changes["name"] = body.name
    if body.origins is not None:
        try:
            changes["origins"] = normalize_origins(body.origins)
        except SiteOriginError as exc:
            raise BadRequestError(str(exc)) from exc
    if body.environment is not None:
        changes["environment"] = body.environment
    if body.status is not None:
        changes["status"] = body.status

    if not changes:
        raise BadRequestError("No updatable fields supplied")

    from shared.common.common import utc_now

    changes["updated_at"] = utc_now().isoformat()
    updated = await _sites.update(site_id, changes)

    warnings: list[str] = []
    if changes.get("status") == STATUS_REVOKED:
        bound = await _keys_bound_to(tenant.tenant_id, site_id)
        if bound:
            # Revoking the site does not un-issue the keys that name it, and
            # pretending otherwise would leave live publishable credentials in
            # customer HTML that the operator believes they retired.
            warnings.append(
                f"{len(bound)} publishable key(s) still bound to this site; "
                "revoke them via DELETE /v1/me/api-keys/{id} to stop them working"
            )
    if "origins" in changes:
        warnings.append(
            "origin changes apply to new installs; already-installed snippets "
            "keep working from the origins they were served on"
        )

    metrics.increment("sdk_sites_updated")
    emit_latency("sdk_site_updated", ctx.elapsed_ms())
    return APIResponse(data={
        "site": updated or record,
        "warnings": warnings,
    }).to_dict()


@router.delete("/sites/{site_id}")
async def delete_site(site_id: str, request: Request):
    """Delete a site — refused while a publishable key is still bound to it."""
    ctx = trace_request(request, service="sdk_distribution")
    tenant = _require_operator(request)
    await _load_site(tenant.tenant_id, site_id)

    bound = await _keys_bound_to(tenant.tenant_id, site_id)
    if bound:
        raise ConflictError(
            f"{len(bound)} publishable key(s) are still bound to site {site_id}; "
            "revoke them first, or PATCH the site to status=revoked to keep it "
            "for history without handing it out for new installs"
        )

    await _sites.delete(site_id)
    metrics.increment("sdk_sites_deleted")
    emit_latency("sdk_site_deleted", ctx.elapsed_ms())
    return APIResponse(data={"deleted": True, "id": site_id}).to_dict()


@router.get("/sites/{site_id}/install")
async def get_install(site_id: str, request: Request):
    """The install page: snippet template, bound keys, and what to expect next.

    The snippet carries a placeholder rather than a key. The platform stores
    only a key's hash, so a key that has already been issued cannot be shown
    again — an install page that printed one would be printing something it
    does not have. Minting returns the real snippet instead.
    """
    ctx = trace_request(request, service="sdk_distribution")
    tenant = _tenant(request)
    record = await _load_site(tenant.tenant_id, site_id)
    bound = await _keys_bound_to(tenant.tenant_id, site_id)

    emit_latency("sdk_install_page_fetched", ctx.elapsed_ms())
    return APIResponse(data={
        "site_id": site_id,
        "site_name": record.get("name"),
        "status": record.get("status"),
        "loader_url": LOADER_URL,
        "snippet": build_snippet(
            site_id=site_id,
            api_key="pk_your_publishable_key",
        ),
        "bound_keys": bound,
        "mint_url": f"/v1/sdk/sites/{site_id}/keys",
        "verify": {
            "endpoint": f"/v1/sdk/sites/{site_id}/heartbeat",
            "live_endpoint": f"/v1/sdk/sites/{site_id}/live",
            "expect_first_signal_within_seconds": FIRST_SIGNAL_WINDOW_SECONDS,
            "signals": list(SIGNAL_ORDER),
        },
    }).to_dict()


@router.get("/sites/{site_id}/heartbeat")
async def get_site_heartbeat(site_id: str, request: Request):
    """Has this site's snippet actually come up? The install verifier.

    The answer is derived from the loader's own milestone events, accepted
    through the ordinary ingestion path — never from a separate "did you
    install it" endpoint, which would report success on evidence ingestion
    never saw.

    A site with no signals is reported as ``awaiting_first_signal``, not as
    failed: "we have not seen it yet" and "we saw it break" are different
    facts, and only the second one means the operator has something to fix.
    """
    ctx = trace_request(request, service="sdk_distribution")
    tenant = _tenant(request)
    record = await _load_site(tenant.tenant_id, site_id)
    install = await _site_install(tenant.tenant_id, site_id)

    emit_latency("sdk_site_heartbeat_fetched", ctx.elapsed_ms())
    return APIResponse(data={
        "site_id": site_id,
        "site_name": record.get("name"),
        "site_status": record.get("status"),
        "install": install,
        "loader_url": LOADER_URL,
        "expect_first_signal_within_seconds": FIRST_SIGNAL_WINDOW_SECONDS,
        "signals": list(SIGNAL_ORDER),
    }).to_dict()


@router.get("/sites/{site_id}/live")
async def get_site_live(site_id: str, request: Request):
    """The cheap liveness read for a polling dashboard.

    Separate from ``/heartbeat`` because the two are read at different rates:
    a dashboard polls this one and renders a badge, and a human opens the
    other when the badge is wrong. Keeping the poll small is the whole point of
    the split.
    """
    ctx = trace_request(request, service="sdk_distribution")
    tenant = _tenant(request)
    record = await _load_site(tenant.tenant_id, site_id)
    install = await _site_install(tenant.tenant_id, site_id)

    emit_latency("sdk_site_live_fetched", ctx.elapsed_ms())
    return APIResponse(data={
        "site_id": site_id,
        "live": install["state"] == STATE_LIVE,
        "state": install["state"],
        "last_signal": install["last_signal"],
        "last_signal_at": install["last_signal_at"],
        "age_seconds": install["age_seconds"],
        "site_status": record.get("status"),
    }).to_dict()


@router.post("/sites/{site_id}/keys")
async def create_site_key(site_id: str, body: SiteKeyCreateRequest, request: Request):
    """Mint a publishable key bound to exactly this site, with its snippet.

    This is the only response that will ever contain the raw key, so it is also
    the only one that can contain a pasteable snippet.
    """
    ctx = trace_request(request, service="sdk_distribution")
    tenant = _require_operator(request)
    record = await _load_site(tenant.tenant_id, site_id)

    if record.get("status") != STATUS_ACTIVE:
        raise ForbiddenError(
            f"Site {site_id} is {record.get('status')}; activate it before "
            "issuing install keys"
        )

    issued = await mint_api_key(
        tenant=tenant,
        name=body.name,
        key_class=KEY_CLASS_PUBLISHABLE,
        requested_permissions=[],
        # Bound to this one site, and to no other: the key is public, and the
        # site is the only thing that confines it.
        site_ids=[site_id],
        platform="web",
        source="sdk_install",
    )

    metrics.increment("sdk_site_keys_issued")
    emit_latency("sdk_site_key_issued", ctx.elapsed_ms())
    return APIResponse(data={
        "api_key": issued["raw_key"],
        "id": issued["record"]["id"],
        "key_class": KEY_CLASS_PUBLISHABLE,
        "site_id": site_id,
        "permissions": issued["permissions"],
        "snippet": build_snippet(site_id=site_id, api_key=issued["raw_key"]),
        "message": (
            "Paste the snippet into the site's HTML. Store the key separately — "
            "it is publishable, so it will be visible in the page, but it is "
            "still the credential that authorises this site's ingestion."
        ),
    }).to_dict()
