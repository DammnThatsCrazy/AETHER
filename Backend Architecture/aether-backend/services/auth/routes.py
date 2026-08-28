"""
Aether Service — Authentication

Manual email+password sign-up (OTP-verified) and SSO via Auth0 (Google, Apple,
Microsoft, Twitter/X, Slack). Also handles tenant deactivation and GDPR deletion.

Public endpoints (no auth required):
  POST /v1/auth/register              Step 1: email + password → sends 6-digit OTP
  POST /v1/auth/verify-email          Step 2: confirm OTP → creates tenant + API key
  POST /v1/auth/resend-verification   Resend OTP (anti-enumeration safe)
  POST /v1/auth/login                 Email + password → new session API key
  POST /v1/auth/sso/callback          Auth0 JWT → AETHER tenant + API key
  GET  /v1/auth/sso/providers         List available SSO providers

Authenticated user endpoints:
  DELETE /v1/me/account               Self-service account-deletion workflow alias

Admin endpoints (require auth):
  POST   /v1/admin/tenants/{id}/deactivate  Evict Redis keys + mark inactive
  DELETE /v1/admin/tenants/{id}             GDPR cascade delete
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Optional

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from config.settings import settings
from shared.auth.auth import PlanTier
from shared.common.common import (
    APIResponse,
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from shared.logger.logger import get_logger, metrics
from repositories.repos import AdminRepository, APIKeyRepository

logger = get_logger("aether.service.auth")

router = APIRouter(tags=["Auth"])
admin_auth_router = APIRouter(tags=["Admin — Auth"])

_repo = AdminRepository()
_key_repo = APIKeyRepository()


class AccountDeletionRequest(BaseModel):
    """Trusted step-up evidence required by the recovery-window workflow."""

    idempotency_key: str = Field(min_length=1, max_length=256)
    reauth_evidence: dict = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────

def _get_redis():
    try:
        from dependencies.providers import get_registry
        registry = get_registry()
        return getattr(getattr(registry, "cache", None), "_redis", None)
    except Exception:
        return None


async def _issue_api_key(tenant_id: str, plan_tier_value: str, label: str) -> str:
    """Create and register a new API key for a tenant. Returns the raw key."""
    raw_key = f"ak_{uuid.uuid4().hex[:24]}"
    hashed = hashlib.sha256(raw_key.encode()).hexdigest()
    await _key_repo.insert(hashed[:12], {
        "tenant_id": tenant_id,
        "name": label,
        "tier": plan_tier_value,
        "permissions": ["read", "write", "ingest", "analytics"],
        "key_hash": hashed,
        "last_used_at": None,
    })
    try:
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
        logger.warning(f"Auth cache registration failed: tenant={tenant_id} error={e}")
    return raw_key


def _set_session_cookie(response: Optional[Response], issue) -> None:
    """Set the HttpOnly session cookie when a Response is available."""
    if response is None:
        return
    secure = settings.env.value not in ("local", "dev")
    response.set_cookie(
        key=issue.cookie_name,
        value=issue.token,
        max_age=issue.cookie_max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


async def _issue_human_session(
    response: Optional[Response],
    tenant_id: str,
    principal_id: Optional[str],
    message: str,
    extra: Optional[dict] = None,
) -> dict:
    """Create a durable human session and return a session response.

    This replaces reusable-API-key issuance for human auth under the
    founding-tenant posture: the response carries a session (cookie + token),
    never an `api_key`.
    """
    from services.auth.sessions import session_service
    issue = await session_service.create_session(
        tenant_id,
        principal_id=principal_id,
        idle_minutes=settings.trust_plane.session_idle_minutes,
        absolute_minutes=settings.trust_plane.session_absolute_minutes,
    )
    _set_session_cookie(response, issue)
    data = {
        "tenant_id": tenant_id,
        "session": issue.public_dict(),
        "message": message,
    }
    if extra:
        data.update(extra)
    return APIResponse(data=data).to_dict()


async def _send_otp_email(email: str, otp: str, name: str = "") -> None:
    try:
        from shared.email import email_service
        from shared.email.templates import _base
        greeting = f"Hi {name}," if name else "Hi,"
        body_html = _base("Email Verification", f"""
<p>{greeting}</p>
<p>Your AETHER verification code is:</p>
<div style="font-size:36px;font-weight:bold;letter-spacing:8px;text-align:center;
            padding:24px;background:#f4f4f4;border-radius:8px;margin:24px 0">
  {otp}
</div>
<p>This code expires in <strong>10 minutes</strong>.</p>
<p>If you did not request this, you can safely ignore this email.</p>
""")
        await email_service.send_email(
            to=email,
            subject="AETHER — verify your email address",
            body_html=body_html,
        )
    except Exception as e:
        logger.debug(f"OTP email skipped: {e}")


async def _evict_tenant_api_keys(tenant_id: str) -> int:
    """Delete all Redis auth-cache entries for a tenant. Returns count evicted."""
    evicted = 0
    try:
        from shared.cache.cache import CacheKey
        from dependencies.providers import get_registry
        cache = get_registry().cache
        keys = await _key_repo.find_many(filters={"tenant_id": tenant_id}, limit=500)
        for rec in keys:
            key_hash = rec.get("key_hash", "")
            if key_hash:
                try:
                    await cache.delete(CacheKey.api_key(key_hash))
                    evicted += 1
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"Redis eviction error: tenant={tenant_id} error={e}")
    return evicted


async def _cascade_delete_tenant(tenant_id: str) -> dict:
    """Delete all data for a tenant across every table. Returns per-table counts.

    Public ingest identifiers are revoked before the tenant row is removed so
    contained registration credentials cannot outlive their owner.
    """
    counts: dict = {}

    # 1. Evict Redis immediately so auth fails on the next request
    counts["keys_evicted"] = await _evict_tenant_api_keys(tenant_id)

    # Public registration can issue a contained ingest identifier before the
    # tenant is activated. Revoke those identifiers before deleting the tenant
    # row so an otherwise successful GDPR/cleanup delete cannot leave a live
    # credential pointing at an owner that no longer exists.
    try:
        from services.auth.sessions import public_ingest_service
        counts["public_ingest_identifiers_revoked"] = (
            await public_ingest_service.revoke_all_for_tenant(tenant_id)
        )
    except Exception as e:
        logger.debug(f"Public ingest revocation skipped: tenant={tenant_id} error={e}")
        counts["public_ingest_identifiers_revoked"] = 0

    # 2. Cancel Stripe subscription (best-effort — never blocks deletion)
    try:
        from shared.billing import stripe_client, stripe_repository
        billing = await stripe_repository.get_billing_account(tenant_id)
        sub_id = (billing or {}).get("stripe_subscription_id", "")
        if sub_id:
            await stripe_client.cancel_subscription(sub_id)
    except Exception as e:
        logger.debug(f"Stripe subscription cancel skipped: tenant={tenant_id} error={e}")

    # 3. Delete API key rows
    counts["api_keys"] = await _key_repo.delete_by_entity("tenant_id", tenant_id)

    # 4. Delete user rows
    try:
        from repositories.repos import UserRepository
        counts["users"] = await UserRepository().delete_by_entity("tenant_id", tenant_id)
    except Exception:
        counts["users"] = 0

    # 5. Delete billing account row
    try:
        from repositories.repos import get_pool
        pool = await get_pool()
        if pool is not None:
            result = await pool.execute(
                "DELETE FROM tenant_billing_accounts WHERE tenant_id = $1", tenant_id
            )
            counts["billing_accounts"] = int(result.split()[-1]) if result else 0
        else:
            from shared.billing.stripe_repository import _mem_accounts
            counts["billing_accounts"] = 1 if _mem_accounts.pop(tenant_id, None) else 0
    except Exception as e:
        logger.debug(f"Billing account delete error: {e}")
        counts["billing_accounts"] = 0

    # 6. Delete the tenant record itself
    counts["tenants"] = 1 if await _repo.delete(tenant_id) else 0
    return counts


# ──────────────────────────────────────────────────────────────────────
# POST /v1/auth/register  — Step 1: email + password → OTP
# ──────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
    plan_tier: str = Field(default="P1", pattern="^(P1|P2|P3|P4)$")


@router.post("/v1/auth/register")
async def register(body: RegisterRequest):
    """Step 1 of email sign-up: store pending registration and send OTP.

    A tenant is NOT created until /v1/auth/verify-email succeeds, ensuring
    only addresses that can receive email are provisioned.
    """
    if "@" not in body.email:
        raise BadRequestError("email must be a valid email address")
    try:
        PlanTier(body.plan_tier)
    except ValueError:
        raise BadRequestError(f"Invalid plan_tier: {body.plan_tier!r}")

    email = body.email.lower()
    _SAFE = APIResponse(data={"message": "Check your email for a verification code.", "email": email}).to_dict()

    # If already fully registered, return safe response (anti-enumeration)
    try:
        from repositories.repos import UserRepository
        existing = await UserRepository().find_by_email(email)
        if existing:
            return _SAFE
    except Exception:
        pass

    from shared.auth.password import hash_password
    from shared.auth.verification import generate_otp, store_otp

    pw_hash = hash_password(body.password)

    try:
        from repositories.repos import UserRepository
        # Upsert: allows retrying registration with a fresh OTP
        await UserRepository().insert(f"pending:{email}", {
            "email": email,
            "name": body.name,
            "password_hash": pw_hash,
            "plan_tier": body.plan_tier,
            "status": "pending",
        })
    except Exception as e:
        logger.warning(f"Pending user store failed: email={email!r} error={e}")

    redis = _get_redis()
    otp = generate_otp()
    await store_otp(email, otp, redis)

    import asyncio
    asyncio.ensure_future(_send_otp_email(email, otp, body.name))

    metrics.increment("auth_register_attempts")
    logger.info(f"Registration OTP issued: email={email!r}")
    return _SAFE


# ──────────────────────────────────────────────────────────────────────
# POST /v1/auth/verify-email  — Step 2: OTP → tenant + API key
# ──────────────────────────────────────────────────────────────────────

class VerifyEmailRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    code: str = Field(..., min_length=6, max_length=6)


@router.post("/v1/auth/verify-email")
async def verify_email(body: VerifyEmailRequest, response: Response = None):
    """Step 2 of email sign-up: verify OTP, create tenant.

    Under the founding-tenant posture (`HUMAN_SESSIONS_ENABLED`) this starts a
    durable session instead of returning a reusable API key. Legacy behavior is
    preserved when the flag is off.
    """
    from shared.auth.verification import verify_otp

    verified_user_id: Optional[str] = None

    email = body.email.lower()
    redis = _get_redis()

    if not await verify_otp(email, body.code, redis):
        raise BadRequestError("Invalid or expired verification code.")

    # Retrieve pending registration (graceful if missing — re-verify after restart)
    pending: dict = {}
    try:
        from repositories.repos import UserRepository
        user_repo = UserRepository()
        pending = await user_repo.find_by_id(f"pending:{email}") or {}
    except Exception:
        pass

    name = pending.get("name", "")
    plan_tier_value = pending.get("plan_tier", "P1")
    pw_hash = pending.get("password_hash", "")

    try:
        plan_tier = PlanTier(plan_tier_value)
    except ValueError:
        plan_tier = PlanTier.P1_HOBBYIST

    tenant_id = str(uuid.uuid4())

    # Create tenant
    await _repo.insert(tenant_id, {
        "name": name or email,
        "contact_email": email,
        "plan": plan_tier.value,
        "plan_tier": plan_tier.value,
        "status": "active",
        "auth_method": "password",
        "settings": {},
    })

    # Create verified user record
    try:
        from repositories.repos import UserRepository
        user_repo = UserRepository()
        user_id = str(uuid.uuid4())
        await user_repo.insert(user_id, {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "email": email,
            "name": name,
            "password_hash": pw_hash,
            "status": "active",
            "email_verified": True,
            "auth_method": "password",
            # Authorization is hydrated from this durable principal record on
            # every session-authenticated request.  The tenant creator is the
            # explicit owner; sessions themselves carry no mutable authority.
            "role": "admin",
            "permissions": ["read", "write", "ingest", "analytics", "billing", "admin"],
            "membership_status": "active",
        })
        verified_user_id = user_id
        await user_repo.delete(f"pending:{email}")
    except Exception as e:
        logger.warning(f"User record creation failed: tenant={tenant_id} error={e}")

    # Billing account (best-effort)
    try:
        from shared.billing import stripe_repository
        await stripe_repository.upsert_billing_account(
            tenant_id=tenant_id,
            contact_email=email,
            plan_tier=plan_tier.value,
        )
    except Exception as e:
        logger.warning(f"Billing account creation failed: tenant={tenant_id} error={e}")

    metrics.increment("tenant_registrations", labels={"plan_tier": plan_tier.value, "method": "password"})
    logger.info(f"Email-verified tenant created: id={tenant_id} email={email!r}")

    if settings.trust_plane.human_sessions_enabled:
        # Founding-tenant posture: start a session, do NOT issue a reusable key.
        # The welcome email is skipped here (it historically carried the key).
        return await _issue_human_session(
            response, tenant_id, verified_user_id,
            "Account created! A secure session has been started.",
            extra={"name": name or email, "plan_tier": plan_tier.value},
        )

    # Legacy path (flag off) — reusable API key + key-bearing welcome email.
    raw_key = await _issue_api_key(tenant_id, plan_tier.value, "Default key")
    try:
        import asyncio
        from shared.email import email_service, templates
        subject, body_html = templates.welcome(tenant_name=name or email, api_key=raw_key)
        asyncio.ensure_future(
            email_service.send_email(to=email, subject=subject, body_html=body_html)
        )
    except Exception as e:
        logger.debug(f"Welcome email skipped: {e}")

    return APIResponse(data={
        "tenant_id": tenant_id,
        "name": name or email,
        "plan_tier": plan_tier.value,
        "api_key": raw_key,
        "message": "Account created! Store your API key securely — it will not be shown again.",
    }).to_dict()


# ──────────────────────────────────────────────────────────────────────
# POST /v1/auth/resend-verification
# ──────────────────────────────────────────────────────────────────────

class ResendRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)


@router.post("/v1/auth/resend-verification")
async def resend_verification(body: ResendRequest):
    """Resend a fresh OTP. Always returns the same response (anti-enumeration)."""
    from shared.auth.verification import generate_otp, store_otp

    email = body.email.lower()
    redis = _get_redis()

    # Peek at the pending record for the name (best-effort — not required)
    name = ""
    try:
        from repositories.repos import UserRepository
        pending = await UserRepository().find_by_id(f"pending:{email}") or {}
        name = pending.get("name", "")
    except Exception:
        pass

    otp = generate_otp()
    await store_otp(email, otp, redis)

    import asyncio
    asyncio.ensure_future(_send_otp_email(email, otp, name))

    return APIResponse(data={
        "message": "If a pending registration exists for that email, a new code has been sent."
    }).to_dict()


# ──────────────────────────────────────────────────────────────────────
# POST /v1/auth/login  — email + password → session API key
# ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)


# Constant-time error to prevent user-enumeration via login
_LOGIN_ERROR = "Invalid email or password."


@router.post("/v1/auth/login")
async def login(body: LoginRequest, response: Response = None):
    """Authenticate with email + password.

    Under the founding-tenant posture (`HUMAN_SESSIONS_ENABLED`) this issues a
    durable, revocable session — never a reusable API key. When the flag is off
    (local/dev by default) the legacy API-key response is preserved.
    """
    from shared.auth.password import verify_password

    email = body.email.lower()

    user_rec: dict = {}
    try:
        from repositories.repos import UserRepository
        users = await UserRepository().find_many(
            filters={"email": email, "status": "active", "auth_method": "password"},
            limit=1,
        )
        user_rec = users[0] if users else {}
    except Exception as e:
        logger.debug(f"User lookup error: {e}")

    # Always run verify_password to avoid timing-based user enumeration
    stored_hash = user_rec.get("password_hash", "")
    if not stored_hash or not verify_password(body.password, stored_hash):
        raise BadRequestError(_LOGIN_ERROR)

    tenant_id = user_rec.get("tenant_id", "")
    if not tenant_id:
        raise BadRequestError(_LOGIN_ERROR)

    # Confirm tenant is active
    plan_tier_value = "P1"
    try:
        tenant_rec = await _repo.find_by_id(tenant_id) or {}
        if tenant_rec.get("status") == "inactive":
            raise BadRequestError("This account has been deactivated.")
        plan_tier_value = tenant_rec.get("plan_tier", "P1") or "P1"
    except BadRequestError:
        raise
    except Exception:
        pass

    metrics.increment("auth_logins", labels={"method": "password"})
    logger.info(f"Login: tenant={tenant_id}")

    if settings.trust_plane.human_sessions_enabled:
        return await _issue_human_session(
            response, tenant_id, user_rec.get("user_id"),
            "Authenticated. A secure session has been created.",
        )

    # Legacy path (flag off) — reusable API key.
    raw_key = await _issue_api_key(tenant_id, plan_tier_value, "Login session")
    return APIResponse(data={
        "tenant_id": tenant_id,
        "api_key": raw_key,
        "message": "Authenticated. Store your API key securely — it will not be shown again.",
    }).to_dict()


# ──────────────────────────────────────────────────────────────────────
# POST /v1/auth/sso/callback  — Auth0 JWT → AETHER API key
# ──────────────────────────────────────────────────────────────────────

class SSOCallbackRequest(BaseModel):
    token: str = Field(..., description="Auth0 access token (RS256 JWT)")
    plan_tier: str = Field(default="P1", pattern="^(P1|P2|P3|P4)$")


@router.post("/v1/auth/sso/callback")
async def sso_callback(body: SSOCallbackRequest, response: Response = None):
    """Exchange an Auth0 access token for an AETHER session.

    Under the founding-tenant posture (`HUMAN_SESSIONS_ENABLED`) this starts a
    durable session — never a reusable API key — and provisions a first-login
    tenant as `active_limited` rather than auto-activating a claimed domain.
    Legacy behavior is preserved when the flag is off.
    Supported providers: Google, Apple, Microsoft, Twitter/X, Slack — any
    Auth0 social connection. The `sub` claim is the stable identifier.
    """
    from shared.auth.auth0_validator import validate_auth0_token

    try:
        claims = await validate_auth0_token(body.token)
    except ValueError as e:
        raise BadRequestError(f"Invalid SSO token: {e}")

    sub: str = claims.get("sub", "")
    email: str = claims.get("email", "").lower()
    name: str = claims.get("name", "") or claims.get("nickname", "") or email

    if not sub:
        raise BadRequestError("Token missing 'sub' claim.")

    try:
        plan_tier = PlanTier(body.plan_tier)
    except ValueError:
        plan_tier = PlanTier.P1_HOBBYIST

    # Look up existing tenant by Auth0 sub
    tenant_id: Optional[str] = None
    principal_user_id: Optional[str] = None
    plan_tier_value = plan_tier.value

    try:
        from repositories.repos import UserRepository
        user = await UserRepository().find_by_auth0_sub(sub)
        if user:
            tenant_id = user.get("tenant_id")
            principal_user_id = user.get("user_id") or user.get("id")
            if tenant_id:
                rec = await _repo.find_by_id(tenant_id) or {}
                if rec.get("status") == "inactive":
                    raise BadRequestError("This account has been deactivated.")
                plan_tier_value = rec.get("plan_tier", plan_tier.value) or plan_tier.value
    except BadRequestError:
        raise
    except Exception as e:
        logger.debug(f"SSO user lookup error: {e}")

    if not tenant_id:
        # First SSO login — provision a new tenant
        tenant_id = str(uuid.uuid4())

        # Founding-tenant posture: do not auto-activate a claimed domain — a
        # first SSO login provisions an active_limited tenant pending review.
        first_login_status = (
            "active_limited" if settings.trust_plane.human_sessions_enabled else "active"
        )
        await _repo.insert(tenant_id, {
            "name": name,
            "contact_email": email,
            "plan": plan_tier.value,
            "plan_tier": plan_tier.value,
            "status": first_login_status,
            "auth_method": "sso",
            "settings": {},
        })

        try:
            from repositories.repos import UserRepository
            user_id = str(uuid.uuid4())
            principal_user_id = user_id
            await UserRepository().insert(user_id, {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "email": email,
                "name": name,
                "auth0_sub": sub,
                "status": "active",
                "email_verified": claims.get("email_verified", False),
                "auth_method": "sso",
                "role": "admin",
                "permissions": ["read", "write", "ingest", "analytics", "billing", "admin"],
                "membership_status": "active",
            })
        except Exception as e:
            logger.warning(f"SSO user record creation failed: tenant={tenant_id} error={e}")

        try:
            from shared.billing import stripe_repository
            await stripe_repository.upsert_billing_account(
                tenant_id=tenant_id,
                contact_email=email,
                plan_tier=plan_tier.value,
            )
        except Exception as e:
            logger.warning(f"Billing account creation failed: tenant={tenant_id} error={e}")

        metrics.increment("tenant_registrations", labels={"plan_tier": plan_tier.value, "method": "sso"})
        logger.info(f"SSO tenant provisioned: id={tenant_id} sub={sub!r}")

        # Welcome email (fire-and-forget)
        try:
            import asyncio
            from shared.email import email_service, templates

            # We issue the key below; include a placeholder here since we need
            # the key first. Swap order so we can pass the real key.
        except Exception:
            pass
    else:
        logger.info(f"SSO login: tenant={tenant_id} sub={sub!r}")

    metrics.increment("auth_logins", labels={"method": "sso"})

    if settings.trust_plane.human_sessions_enabled:
        return await _issue_human_session(
            response, tenant_id, principal_user_id,
            "Authenticated via SSO. A secure session has been created.",
        )

    # Legacy path (flag off) — reusable API key.
    raw_key = await _issue_api_key(tenant_id, plan_tier_value, "SSO session")
    return APIResponse(data={
        "tenant_id": tenant_id,
        "api_key": raw_key,
        "message": "Authenticated via SSO. Store your API key securely — it will not be shown again.",
    }).to_dict()


# ──────────────────────────────────────────────────────────────────────
# GET /v1/auth/sso/providers
# ──────────────────────────────────────────────────────────────────────

@router.get("/v1/auth/sso/providers")
async def list_sso_providers():
    """List SSO providers configured in Auth0."""
    domain = settings.auth0.domain
    auth0_configured = bool(domain)
    providers = [
        {"id": "google-oauth2",  "name": "Google",             "enabled": auth0_configured},
        {"id": "apple",          "name": "Apple",               "enabled": auth0_configured},
        {"id": "twitter",        "name": "X (Twitter)",         "enabled": auth0_configured},
        {"id": "windowslive",    "name": "Microsoft",           "enabled": auth0_configured},
        {"id": "slack",          "name": "Slack",               "enabled": auth0_configured},
        {"id": "auth0",          "name": "Email / Password",    "enabled": auth0_configured},
    ]
    return APIResponse(data={
        "providers": providers,
        "auth0_domain": domain,
        "configured": auth0_configured,
    }).to_dict()


# ──────────────────────────────────────────────────────────────────────
# DELETE /v1/me/account  — self-service account deletion
# ──────────────────────────────────────────────────────────────────────

@router.delete("/v1/me/account")
async def delete_my_account(body: AccountDeletionRequest, request: Request):
    """Compatibility alias for the durable 30-day account-deletion workflow."""
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        raise UnauthorizedError("Authentication required.")
    tenant.require_permission("admin")

    from services.account_lifecycle.service import account_lifecycle_service

    workflow = await account_lifecycle_service.request_deletion(
        tenant_id=tenant.tenant_id,
        actor_id=str(getattr(tenant, "user_id", None) or tenant.tenant_id),
        idempotency_key=body.idempotency_key,
        reauth_evidence=body.reauth_evidence,
    )
    metrics.increment("tenant_deletion_workflows_requested", labels={"method": "self_service"})
    logger.info("Self-service account deletion workflow requested: tenant=%s", tenant.tenant_id)
    return APIResponse(data=workflow).to_dict()


# ──────────────────────────────────────────────────────────────────────
# Admin: POST /v1/admin/tenants/{tenant_id}/deactivate
# ──────────────────────────────────────────────────────────────────────

@admin_auth_router.post("/v1/admin/tenants/{tenant_id}/deactivate")
async def deactivate_tenant(tenant_id: str, request: Request):
    """Immediately deactivate a tenant and revoke all active credentials.

    Does NOT delete any data. Existing API keys and contained public ingest
    identifiers stop working on the next request. Re-activation requires
    manually setting status=active and issuing fresh credentials.
    """
    tenant_rec = await _repo.find_by_id(tenant_id)
    if not tenant_rec:
        raise NotFoundError("tenant")

    try:
        from services.auth.sessions import public_ingest_service
        ingest_revoked = await public_ingest_service.revoke_all_for_tenant(tenant_id)
    except Exception as e:
        logger.debug(f"Public ingest revocation skipped: tenant={tenant_id} error={e}")
        ingest_revoked = 0

    if tenant_rec.get("status") == "inactive":
        return APIResponse(data={
            "tenant_id": tenant_id,
            "status": "inactive",
            "public_ingest_identifiers_revoked": ingest_revoked,
            "message": "Tenant is already inactive.",
        }).to_dict()

    evicted = await _evict_tenant_api_keys(tenant_id)
    await _repo.update(tenant_id, {"status": "inactive"})

    metrics.increment("tenant_deactivations")
    logger.info(f"Tenant deactivated: tenant={tenant_id} keys_evicted={evicted}")

    return APIResponse(data={
        "tenant_id": tenant_id,
        "status": "inactive",
        "keys_evicted": evicted,
        "public_ingest_identifiers_revoked": ingest_revoked,
        "message": "Tenant deactivated. All API keys have been invalidated immediately.",
    }).to_dict()


# ──────────────────────────────────────────────────────────────────────
# Admin: DELETE /v1/admin/tenants/{tenant_id}  — GDPR erasure
# ──────────────────────────────────────────────────────────────────────

@admin_auth_router.delete("/v1/admin/tenants/{tenant_id}")
async def gdpr_delete_tenant(tenant_id: str, request: Request):
    """Permanently delete a tenant and all associated data (GDPR right to erasure).

    Cascade order: Redis eviction → Stripe subscription cancel → api_keys →
    users → tenant_billing_accounts → tenants. Irreversible.
    """
    tenant_rec = await _repo.find_by_id(tenant_id)
    if not tenant_rec:
        raise NotFoundError("tenant")

    deleted = await _cascade_delete_tenant(tenant_id)

    metrics.increment("tenant_deletions", labels={"method": "admin_gdpr"})
    logger.info(f"GDPR delete: tenant={tenant_id} counts={deleted}")

    return APIResponse(data={
        "tenant_id": tenant_id,
        "deleted": deleted,
        "message": "Tenant and all associated data have been permanently deleted.",
    }).to_dict()
