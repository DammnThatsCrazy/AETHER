"""
Aether Service — Enterprise Contact

Accepts inbound enterprise inquiries from authenticated tenants, persists them
durably, and notifies the internal sales team by email. The persisted row is the
source of truth — email delivery is best-effort and never loses an inquiry.
Inquiry PII (name/email/company/message) is written only to the database, never
to application logs.

Endpoints:
    POST /v1/contact/enterprise   Submit an enterprise inquiry
"""

from __future__ import annotations

import uuid
from html import escape

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from repositories.repos import EnterpriseInquiryRepository
from shared.common.common import APIResponse, BadRequestError, ServiceUnavailableError
from shared.email import email_service
from shared.email.templates import _base
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


_enterprise_inquiries = EnterpriseInquiryRepository()


@router.post("/enterprise")
async def contact_enterprise(body: EnterpriseContactRequest, request: Request):
    """Accept an enterprise inquiry from an authenticated tenant.

    Persists the inquiry as the durable record, then attempts an email
    notification to the sales team. If persistence fails the request fails
    (no fake success); email delivery failure is non-fatal and the inquiry is
    retained with a ``status`` marker.
    """
    tenant = _require_tenant(request)

    if body.company_type.lower() not in _VALID_COMPANY_TYPES:
        raise BadRequestError(
            f"Invalid company_type '{body.company_type}'. "
            f"Valid values: {sorted(_VALID_COMPANY_TYPES)}"
        )

    inquiry_id = str(uuid.uuid4())
    try:
        await _enterprise_inquiries.insert(inquiry_id, {
            "tenant_id": tenant.tenant_id,
            "name": body.name,
            "email": body.email,
            "company_name": body.company_name,
            "company_type": body.company_type,
            "message": body.message,
            "status": "received",
        })
    except Exception as exc:
        logger.error(
            "enterprise_contact_persist_failed",
            extra={"tenant_id": tenant.tenant_id, "inquiry_id": inquiry_id, "error": str(exc)},
        )
        raise ServiceUnavailableError("enterprise inquiry storage") from exc

    logger.info(
        "enterprise_contact_received",
        extra={
            "tenant_id": tenant.tenant_id,
            "inquiry_id": inquiry_id,
            "company_type": body.company_type,
            "message_length": len(body.message),
        },
    )
    metrics.increment("contact_enterprise_submitted")

    notified = await _notify_sales_team(inquiry_id, body)
    if not notified:
        # Email is best-effort on top of the durable row; flag it for an
        # internal retry sweep rather than dropping or faking the inquiry.
        await _enterprise_inquiries.update(inquiry_id, {"status": "email_failed"})
        logger.warning(
            "enterprise_contact_email_failed",
            extra={"tenant_id": tenant.tenant_id, "inquiry_id": inquiry_id},
        )
    else:
        await _enterprise_inquiries.update(inquiry_id, {"status": "notified"})

    return APIResponse(data={
        "received": True,
        "inquiry_id": inquiry_id,
        "message": "Thank you — our team will respond within 2 business days.",
    }).to_dict()


async def _notify_sales_team(inquiry_id: str, body: EnterpriseContactRequest) -> bool:
    """Deliver an email to the sales team. Returns True on send success.

    Every user-controlled field is HTML-escaped before interpolation into the
    body — a tenant-supplied message/name/company must never carry raw markup
    into the sales team's mail client (email XSS via the HTML body). The
    subject is also newline-stripped so a crafted company name cannot inject
    SMTP headers (header-injection defense); email providers reject raw
    control characters in headers.
    """
    from config.settings import settings

    subject = (
        f"[Enterprise Inquiry] {body.company_name} ({body.company_type})"
    ).replace("\r", " ").replace("\n", " ")

    company_name = escape(body.company_name, quote=True)
    company_type = escape(body.company_type, quote=True)
    name = escape(body.name, quote=True)
    email = escape(body.email, quote=True)
    message = escape(body.message, quote=True)

    body_html = _base("Enterprise inquiry", f"""
<p><strong>Company:</strong> {company_name} ({company_type})</p>
<p><strong>Contact:</strong> {name} &lt;{email}&gt;</p>
<hr>
<p>{message}</p>
<p><em>Inquiry id: {inquiry_id}</em></p>
""")
    return await email_service.send_email(
        to=settings.email.enterprise_inquiry_email,
        subject=subject,
        body_html=body_html,
    )
