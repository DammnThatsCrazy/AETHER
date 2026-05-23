"""
Aether Service — Public Tenant Registration + Key Recovery

Unauthenticated endpoints for new customer sign-up and API key recovery.

Endpoints:
    POST /v1/tenants          Sign up: creates tenant + API key, sends welcome email
    POST /v1/auth/recover     Recover access: emails a new key to a registered address
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from config.settings import settings
from shared.auth.auth import PlanTier
from shared.billing import stripe_client, stripe_repository
from shared.common.common import APIResponse, BadRequestError, RateLimitedError
from shared.logger.logger import get_logger, metrics
from repositories.repos import AdminRepository, APIKeyRepository

logger = get_logger("aether.service.registration")
router = APIRouter(tags=["Registration"])

# In-memory fallback for IP rate limiting (used when Redis is unavailable)
_ip_buckets: dict[str, dict] = {}
_IP_REGISTER_LIMIT = 10   # max registrations per IP per minute
_IP_RECOVER_LIMIT  = 5    # max recovery requests per IP per minute


async def _check_ip_limit(ip: str, key_prefix: str, limit: int) -> None:
    """Enforce a per-IP per-minute cap using Redis or in-memory bucket.

    Raises RateLimitedError if the IP has exceeded the limit.
    """
    now = time.time()
    window = 60
    redis_key = f"reg:{key_prefix}:{ip}:{int(now // window)}"

    try:
        from dependencies.providers import get_registry
        registry = get_registry()
        redis = getattr(getattr(registry, "cache", None), "_redis", None)
        if redis is not None:
            count = await redis.incr(redis_key)
            if count == 1:
                await redis.expire(redis_key, window)
            if count > limit:
                raise RateLimitedError(retry_after=window)
            return
    except RateLimitedError:
        raise
    except Exception:
        pass

    # In-memory fallback
    bucket = _ip_buckets.get(redis_key)
    if bucket is None or bucket["reset"] <= now:
        _ip_buckets[redis_key] = {"count": 1, "reset": now + window}
    else:
        _ip_buckets[redis_key]["count"] += 1
        if _ip_buckets[redis_key]["count"] > limit:
            raise RateLimitedError(retry_after=int(_ip_buckets[redis_key]["reset"] - now))

_repo = AdminRepository()
_key_repo = APIKeyRepository()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or request.client.host if request.client else "unknown"


class TenantRegistration(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    contact_email: str = Field(..., min_length=5, max_length=254)
    plan_tier: str = Field(default="P1", pattern="^(P1|P2|P3|P4)$")
    settings: dict = Field(default_factory=dict)


class RecoverRequest(BaseModel):
    contact_email: str = Field(..., min_length=5, max_length=254)


@router.post("/v1/tenants")
async def register_tenant(body: TenantRegistration, request: Request):
    """Public endpoint: sign up for AETHER.

    Creates tenant + billing account + first API key, then sends a welcome email.
    Rate-limited: max 10 registrations per IP per minute.
    """
    await _check_ip_limit(_client_ip(request), "register", _IP_REGISTER_LIMIT)

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


@router.post("/v1/auth/recover")
async def recover_api_key(body: RecoverRequest, request: Request):
    """Public endpoint: recover access by emailing a new API key.

    Rate-limited: max 5 requests per IP per minute.
    Always returns the same response to prevent email enumeration.
    """
    await _check_ip_limit(_client_ip(request), "recover", _IP_RECOVER_LIMIT)

    _SAFE_RESPONSE = APIResponse(data={
        "message": "If an account exists with that email address, a new API key has been sent."
    }).to_dict()

    if not body.contact_email or "@" not in body.contact_email:
        return _SAFE_RESPONSE

    # Find tenant by contact_email in billing accounts (most reliable source)
    tenant_id: Optional[str] = None
    tenant_name: str = ""
    plan_tier_value: str = "P1"
    try:
        from repositories.repos import get_pool
        pool = await get_pool()
        if pool is not None:
            row = await pool.fetchrow(
                "SELECT tenant_id, plan_tier FROM tenant_billing_accounts WHERE contact_email=$1 LIMIT 1",
                body.contact_email,
            )
            if row:
                tenant_id = row["tenant_id"]
                plan_tier_value = row.get("plan_tier", "P1") or "P1"
        else:
            # In-memory fallback
            from shared.billing.stripe_repository import _mem_accounts
            for tid, acct in _mem_accounts.items():
                if acct.get("contact_email") == body.contact_email:
                    tenant_id = tid
                    plan_tier_value = acct.get("plan_tier", "P1") or "P1"
                    break
    except Exception as e:
        logger.debug(f"Recovery tenant lookup failed: {e}")

    if not tenant_id:
        # No account — return safe response (no enumeration)
        metrics.increment("recovery_attempts_not_found")
        return _SAFE_RESPONSE

    # Look up tenant name
    try:
        record = await _repo.find_by_id(tenant_id) or {}
        tenant_name = record.get("name", "")
    except Exception:
        pass

    # Create a new recovery API key
    raw_key = f"ak_{uuid.uuid4().hex[:24]}"
    hashed = hashlib.sha256(raw_key.encode()).hexdigest()
    try:
        await _key_repo.insert(hashed[:12], {
            "tenant_id": tenant_id,
            "name": "Recovery key",
            "tier": plan_tier_value,
            "permissions": ["read", "write", "ingest", "analytics"],
            "key_hash": hashed,
            "last_used_at": None,
        })
        from dependencies.providers import get_registry
        registry = get_registry()
        await registry.api_key_validator.register_api_key(
            api_key=raw_key,
            tenant_id=tenant_id,
            role="editor",
            tier=plan_tier_value,
            permissions=["read", "write", "ingest", "analytics"],
        )
    except Exception as e:
        logger.warning(f"Recovery key creation failed: tenant={tenant_id} error={e}")
        return _SAFE_RESPONSE

    # Email the recovery key (best-effort)
    try:
        from shared.email import email_service
        from shared.email.templates import _base
        subject = "AETHER — your recovery API key"
        body_html = _base("Account recovery", f"""
<p>Hi{f' <strong>{tenant_name}</strong>' if tenant_name else ''},</p>
<p>Here is a new API key for your AETHER account:</p>
<pre style="background:#f4f4f4;padding:12px;border-radius:4px;font-size:14px">{raw_key}</pre>
<p><strong>Store this securely — it will not be shown again.</strong></p>
<p>If you did not request this, contact support immediately.</p>
""")
        await email_service.send_email(to=body.contact_email, subject=subject, body_html=body_html)
    except Exception as e:
        logger.debug(f"Recovery email skipped: {e}")

    metrics.increment("recovery_attempts_succeeded")
    logger.info(f"Recovery key issued: tenant={tenant_id}")
    return _SAFE_RESPONSE
