"""
Aether Service — Public Tenant Registration

No-auth endpoint for new customer sign-up. Creates:
  1. Tenant record (tenants table)
  2. Stripe billing account (tenant_billing_accounts) + Stripe Customer
  3. First API key (api_keys table + Redis auth cache)
  4. Welcome email with the first key

This is intentionally the only unauthenticated write endpoint in AETHER.
Rate-limiting is applied by the burst middleware on the IP level.

Endpoint:
    POST /v1/tenants
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field

from config.settings import settings
from shared.auth.auth import PlanTier
from shared.billing import stripe_client, stripe_repository
from shared.common.common import APIResponse, BadRequestError, ConflictError
from shared.logger.logger import get_logger, metrics
from repositories.repos import AdminRepository, APIKeyRepository

logger = get_logger("aether.service.registration")
router = APIRouter(prefix="/v1/tenants", tags=["Registration"])

_repo = AdminRepository()
_key_repo = APIKeyRepository()


class TenantRegistration(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    contact_email: str = Field(..., min_length=5, max_length=254)
    plan_tier: str = Field(default="P1", pattern="^(P1|P2|P3|P4)$")
    settings: dict = Field(default_factory=dict)


@router.post("")
async def register_tenant(body: TenantRegistration, request: Request):
    """Public endpoint: sign up for AETHER.

    Creates tenant + billing account + first API key, then sends a welcome email.
    Rate-limited by IP via burst middleware.
    """
    if not body.contact_email or "@" not in body.contact_email:
        raise BadRequestError("contact_email must be a valid email address")

    try:
        plan_tier = PlanTier(body.plan_tier)
    except ValueError:
        raise BadRequestError(f"Invalid plan_tier: {body.plan_tier!r}")

    tenant_id = str(uuid.uuid4())

    # 1. Create tenant record
    tenant = await _repo.insert(tenant_id, {
        "name": body.name,
        "contact_email": body.contact_email,
        "plan": plan_tier.value,
        "plan_tier": plan_tier.value,
        "status": "active",
        "settings": body.settings,
    })

    # 2. Upsert billing account (creates row, no Stripe call yet)
    await stripe_repository.upsert_billing_account(
        tenant_id=tenant_id,
        contact_email=body.contact_email,
        plan_tier=plan_tier.value,
    )

    # 3. Create Stripe customer (best-effort — does not block registration)
    customer_id: Optional[str] = None
    try:
        customer_id = await stripe_client.create_or_get_customer(
            tenant_id=tenant_id,
            contact_email=body.contact_email,
        )
        if customer_id:
            await stripe_repository.update_customer_mapping(
                tenant_id=tenant_id,
                stripe_customer_id=customer_id,
                contact_email=body.contact_email,
            )
    except Exception as e:
        logger.warning(f"Stripe customer create skipped: tenant={tenant_id} error={e}")

    # 4. Create first API key
    raw_key = f"ak_{uuid.uuid4().hex[:24]}"
    hashed = hashlib.sha256(raw_key.encode()).hexdigest()
    await _key_repo.insert(hashed[:12], {
        "tenant_id": tenant_id,
        "name": "Default key",
        "tier": plan_tier.value,
        "permissions": ["read", "write", "ingest", "analytics"],
        "key_hash": hashed,
        "last_used_at": None,
    })

    # Register in auth cache for immediate use
    try:
        from dependencies.providers import get_registry
        registry = get_registry()
        await registry.api_key_validator.register_api_key(
            api_key=raw_key,
            tenant_id=tenant_id,
            role="editor",
            tier=plan_tier.value,
            permissions=["read", "write", "ingest", "analytics"],
        )
    except Exception as e:
        logger.warning(f"Auth cache registration failed: tenant={tenant_id} error={e}")

    # 5. Send welcome email (best-effort)
    try:
        from shared.email import email_service, templates
        subject, body_html = templates.welcome(tenant_name=body.name, api_key=raw_key)
        await email_service.send_email(
            to=body.contact_email,
            subject=subject,
            body_html=body_html,
        )
    except Exception as e:
        logger.debug(f"Welcome email skipped: tenant={tenant_id} error={e}")

    metrics.increment("tenant_registrations", labels={"plan_tier": plan_tier.value})
    logger.info(f"Tenant registered: id={tenant_id} name={body.name!r} plan={plan_tier.value}")

    return APIResponse(data={
        "tenant_id": tenant_id,
        "name": body.name,
        "plan_tier": plan_tier.value,
        "api_key": raw_key,
        "message": "Welcome to AETHER! Store your API key securely — it will not be shown again.",
    }).to_dict()
