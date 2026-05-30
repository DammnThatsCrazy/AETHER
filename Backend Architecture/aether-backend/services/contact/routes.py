"""
Aether Service — Enterprise Contact

Accepts inbound enterprise inquiries from authenticated tenants and routes them
to the internal sales team via logged notification. Falls back gracefully when
the email delivery layer is unavailable.

Endpoints:
    POST /v1/contact/enterprise   Submit an enterprise inquiry
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.contact")
router = APIRouter(prefix="/v1/contact", tags=["Contact"])

_VALID_COMPANY_TYPES = {"startup", "smb", "enterprise", "government", "nonprofit"}


def _require_tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        from shared.common.common import UnauthorizedError
        raise UnauthorizedError("Authentication required")
    return tenant


class EnterpriseContactRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=3, max_length=320)
    company_name: str = Field(..., min_length=1, max_length=200)
    company_type: str = Field(..., description="startup | smb | enterprise | government | nonprofit")
    message: str = Field(..., min_length=1, max_length=500)


@router.post("/enterprise")
async def contact_enterprise(body: EnterpriseContactRequest, request: Request):
    """Accept an enterprise inquiry from an authenticated tenant.

    Logs the submission for internal review and attempts to deliver an email
    notification to the sales team. The response is always 200 as long as the
    payload is valid — delivery failure is non-fatal.
    """
    tenant = _require_tenant(request)

    if body.company_type.lower() not in _VALID_COMPANY_TYPES:
        raise BadRequestError(
            f"Invalid company_type '{body.company_type}'. "
            f"Valid values: {sorted(_VALID_COMPANY_TYPES)}"
        )

    logger.info(
        "enterprise_contact_received",
        extra={
            "tenant_id": tenant.tenant_id,
            "name": body.name,
            "email": body.email,
            "company_name": body.company_name,
            "company_type": body.company_type,
            "message_length": len(body.message),
        },
    )
    metrics.increment("contact_enterprise_submitted")

    # Best-effort internal notification — failure is non-fatal.
    try:
        await _notify_sales_team(tenant.tenant_id, body)
    except Exception as exc:
        logger.warning(f"Sales notification delivery failed (non-fatal): {exc}")

    return APIResponse(data={
        "received": True,
        "message": "Thank you — our team will respond within 2 business days.",
    }).to_dict()


async def _notify_sales_team(tenant_id: str, body: EnterpriseContactRequest) -> None:
    """Attempt to deliver an internal notification to the sales team."""
    try:
        from shared.notification.email import send_internal_email
        subject = f"[Enterprise Inquiry] {body.company_name} ({body.company_type})"
        content = (
            f"Tenant: {tenant_id}\n"
            f"Name: {body.name}\n"
            f"Email: {body.email}\n"
            f"Company: {body.company_name} ({body.company_type})\n\n"
            f"Message:\n{body.message}"
        )
        await send_internal_email(subject=subject, body=content, tag="enterprise_inquiry")
    except ImportError:
        # Email module not available in this deployment — log only.
        logger.info(
            "enterprise_contact_logged_only",
            extra={
                "tenant_id": tenant_id,
                "company_name": body.company_name,
                "email": body.email,
            },
        )
