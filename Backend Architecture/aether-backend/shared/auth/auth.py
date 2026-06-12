"""
Aether Shared — @aether/auth
JWT verification, API key validation, permission checking, tenant context.
Used by ALL services via middleware.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import base64
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum

from shared.common.common import UnauthorizedError, ForbiddenError, utc_now
from shared.cache.cache import TTL  # noqa: E402 — used in _lookup_api_key_from_db
from config.settings import settings


# ═══════════════════════════════════════════════════════════════════════════
# TENANT / USER CONTEXT
# ═══════════════════════════════════════════════════════════════════════════

class Role(str, Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
    SERVICE = "service"


class APIKeyTier(str, Enum):
    """Legacy 3-tier model. Retained for backward-compatibility during migration.

    New code should use PlanTier (P1-P4). See shared/plans/catalog.py.
    """
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class PlanTier(str, Enum):
    """Self-serve plan tiers (P1-P4)."""
    P1_HOBBYIST = "P1"
    P2_PROFESSIONAL = "P2"
    P3_GROWTH_INTELLIGENCE = "P3"
    P4_PROTOCOL_MASTER = "P4"


# Mapping from legacy APIKeyTier -> PlanTier for backward compatibility.
# FREE -> P1, PRO -> P2, ENTERPRISE -> P4 (P3 is new).
_LEGACY_TIER_TO_PLAN = {
    APIKeyTier.FREE: PlanTier.P1_HOBBYIST,
    APIKeyTier.PRO: PlanTier.P2_PROFESSIONAL,
    APIKeyTier.ENTERPRISE: PlanTier.P4_PROTOCOL_MASTER,
}


def legacy_tier_to_plan(tier: APIKeyTier) -> PlanTier:
    """Map a legacy APIKeyTier to a PlanTier."""
    return _LEGACY_TIER_TO_PLAN.get(tier, PlanTier.P1_HOBBYIST)


@dataclass
class TenantContext:
    """Populated on every authenticated request — available to all handlers."""
    tenant_id: str
    user_id: Optional[str] = None
    role: Role = Role.VIEWER
    api_key_tier: APIKeyTier = APIKeyTier.FREE
    plan_tier: PlanTier = PlanTier.P1_HOBBYIST
    permissions: list[str] = field(default_factory=list)

    def has_permission(self, permission: str) -> bool:
        if self.role == Role.ADMIN:
            return True
        return permission in self.permissions

    def require_permission(self, permission: str) -> None:
        if not self.has_permission(permission):
            raise ForbiddenError(f"Missing permission: {permission}")

    def require_any_permission(self, *perms: str) -> None:
        if self.role == Role.ADMIN:
            return
        if not any(p in self.permissions for p in perms):
            raise ForbiddenError(
                f"Requires one of: {', '.join(perms)}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# JWT HANDLER (PyJWT when available, manual HS256 fallback)
# ═══════════════════════════════════════════════════════════════════════════

try:
    import jwt as pyjwt
    PYJWT_AVAILABLE = True
except ImportError:
    pyjwt = None  # type: ignore[assignment]
    PYJWT_AVAILABLE = False


class JWTHandler:
    """
    JWT encode/decode with algorithm selection.

    Supported algorithms:
      - HS256: Symmetric (shared secret). Default, used in local/dev.
      - RS256: Asymmetric (RSA private key signs, public key verifies). Production.

    Production: uses PyJWT library with full validation (exp, iat, iss, aud).
    Fallback: manual HS256 if PyJWT not installed (local dev only).

    RS256 configuration:
      - JWT_PRIVATE_KEY: PEM-encoded RSA private key (for signing)
      - JWT_PUBLIC_KEY: PEM-encoded RSA public key (for verification)
      - JWT_ALGORITHM: "RS256" (set in config or env)
      - JWT_ISSUER: Expected issuer claim (optional)
      - JWT_AUDIENCE: Expected audience claim (optional)

    Migration safety:
      When switching from HS256 to RS256, set JWT_ALGORITHM=RS256 and provide
      RSA keys. The handler will accept both HS256 and RS256 tokens during
      transition if PYJWT_AVAILABLE is True and JWT_ALLOW_HS256_FALLBACK=true.
    """

    def __init__(
        self,
        secret: str = "",
        algorithm: str = "",
        private_key: str = "",
        public_key: str = "",
        issuer: str = "",
        audience: str = "",
        allow_hs256_fallback: bool = False,
        secret_previous: str = "",
    ):
        self.secret = secret or settings.auth.jwt_secret
        self.secret_previous = secret_previous or settings.auth.jwt_secret_previous
        self.algorithm = algorithm or os.getenv("JWT_ALGORITHM", "HS256")
        self.private_key = private_key or os.getenv("JWT_PRIVATE_KEY", "")
        self.public_key = public_key or os.getenv("JWT_PUBLIC_KEY", "")
        self.issuer = issuer or os.getenv("JWT_ISSUER", "")
        self.audience = audience or os.getenv("JWT_AUDIENCE", "")
        self.allow_hs256_fallback = allow_hs256_fallback

    def _signing_key(self) -> str:
        """Get the appropriate signing key based on algorithm."""
        if self.algorithm == "RS256":
            if not self.private_key:
                raise UnauthorizedError("RS256 signing requires JWT_PRIVATE_KEY")
            return self.private_key
        return self.secret

    def _verification_key(self) -> str:
        """Get the appropriate verification key based on algorithm."""
        if self.algorithm == "RS256":
            if not self.public_key:
                raise UnauthorizedError("RS256 verification requires JWT_PUBLIC_KEY")
            return self.public_key
        return self.secret

    def _allowed_algorithms(self) -> list[str]:
        """Get algorithms accepted for verification (migration safety)."""
        if self.algorithm == "RS256" and self.allow_hs256_fallback:
            return ["RS256", "HS256"]
        return [self.algorithm]

    def encode(self, payload: dict) -> str:
        """Encode a payload into a JWT string.

        Uses RS256 with private key when configured, otherwise HS256.
        Automatically adds exp, iat, iss, and aud claims if configured.
        """
        if "exp" not in payload:
            payload["exp"] = int(time.time()) + settings.auth.jwt_expiry_minutes * 60
        if "iat" not in payload:
            payload["iat"] = int(time.time())
        if self.issuer and "iss" not in payload:
            payload["iss"] = self.issuer
        if self.audience and "aud" not in payload:
            payload["aud"] = self.audience

        if PYJWT_AVAILABLE:
            return pyjwt.encode(payload, self._signing_key(), algorithm=self.algorithm)

        # Manual HS256 fallback (local dev only — RS256 requires PyJWT)
        if self.algorithm == "RS256":
            raise UnauthorizedError("RS256 requires PyJWT library: pip install PyJWT[crypto]")

        header = base64.urlsafe_b64encode(
            json.dumps({"alg": self.algorithm, "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        payload_b64 = base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).rstrip(b"=").decode()
        signing_input = f"{header}.{payload_b64}".encode()
        signature = base64.urlsafe_b64encode(
            hmac.new(self.secret.encode(), signing_input, hashlib.sha256).digest()
        ).rstrip(b"=").decode()
        return f"{header}.{payload_b64}.{signature}"

    def decode(self, token: str) -> dict:
        """Decode and verify a JWT. Returns the payload dict.

        For RS256: verifies with public key.
        For HS256: verifies with shared secret.
        During migration: accepts both algorithms if allow_hs256_fallback is True.
        Validates exp, iat, and optionally iss/aud claims.
        """
        if PYJWT_AVAILABLE:
            # Determine verification key based on token's algorithm
            options = {"require": ["exp", "iat"]}
            kwargs: dict[str, Any] = {}
            if self.issuer:
                kwargs["issuer"] = self.issuer
            if self.audience:
                kwargs["audience"] = self.audience

            # For RS256 primary with HS256 fallback during migration
            algorithms = self._allowed_algorithms()
            key = self._verification_key()

            try:
                return pyjwt.decode(
                    token, key, algorithms=algorithms, options=options, **kwargs,
                )
            except pyjwt.InvalidAlgorithmError:
                # If RS256 verification failed, try HS256 fallback
                if self.allow_hs256_fallback and self.algorithm == "RS256":
                    try:
                        return pyjwt.decode(
                            token, self.secret, algorithms=["HS256"],
                            options=options, **kwargs,
                        )
                    except pyjwt.InvalidTokenError as e:
                        raise UnauthorizedError(f"Invalid token: {e}")
                raise UnauthorizedError("Invalid token algorithm")
            except pyjwt.ExpiredSignatureError:
                raise UnauthorizedError("Token expired")
            except pyjwt.InvalidSignatureError:
                # During JWT_SECRET rotation: accept tokens signed by the previous key.
                # Deploy with JWT_SECRET=<new> + JWT_SECRET_PREVIOUS=<old>, then wait
                # for all old tokens to expire before clearing JWT_SECRET_PREVIOUS.
                if self.secret_previous:
                    try:
                        return pyjwt.decode(
                            token, self.secret_previous,
                            algorithms=["HS256"], options=options, **kwargs,
                        )
                    except pyjwt.ExpiredSignatureError:
                        raise UnauthorizedError("Token expired")
                    except pyjwt.InvalidTokenError:
                        pass
                raise UnauthorizedError("Invalid token: Signature verification failed")
            except pyjwt.InvalidTokenError as e:
                raise UnauthorizedError(f"Invalid token: {e}")

        # Manual HS256 fallback (no PyJWT — local dev only)
        if self.algorithm == "RS256":
            raise UnauthorizedError("RS256 requires PyJWT library: pip install PyJWT[crypto]")

        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise UnauthorizedError("Malformed token")
            payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            if payload.get("exp", 0) < time.time():
                raise UnauthorizedError("Token expired")
            signing_input = f"{parts[0]}.{parts[1]}".encode()
            expected_sig = base64.urlsafe_b64encode(
                hmac.new(self.secret.encode(), signing_input, hashlib.sha256).digest()
            ).rstrip(b"=").decode()
            if not hmac.compare_digest(expected_sig, parts[2]):
                if self.secret_previous:
                    prev_sig = base64.urlsafe_b64encode(
                        hmac.new(self.secret_previous.encode(), signing_input, hashlib.sha256).digest()
                    ).rstrip(b"=").decode()
                    if hmac.compare_digest(prev_sig, parts[2]):
                        return payload
                raise UnauthorizedError("Invalid signature")
            return payload
        except UnauthorizedError:
            raise
        except Exception:
            raise UnauthorizedError("Invalid token")

    def extract_context(self, payload: dict) -> TenantContext:
        """Convert JWT payload to TenantContext."""
        return TenantContext(
            tenant_id=payload.get("tenant_id", ""),
            user_id=payload.get("sub"),
            role=Role(payload.get("role", "viewer")),
            permissions=payload.get("permissions", []),
        )


# ═══════════════════════════════════════════════════════════════════════════
# API KEY VALIDATOR
# ═══════════════════════════════════════════════════════════════════════════

# Stub keys for LOCAL development only
_LOCAL_STUB_KEYS: dict[str, dict] = {
    "ak_test_123": {
        "tenant_id": "tenant_001",
        "tier": "pro",
        "role": "editor",
        "permissions": [
            "read", "write", "analytics", "ml:inference",
            "agent:manage", "campaign:manage", "consent:manage",
            "admin", "billing", "x402:read", "x402:write",
        ],
    },
}


class APIKeyValidator:
    """
    Validates API keys and returns tenant context.

    Production: keys are SHA-256 hashed and stored in Redis (via CacheClient)
    with tenant metadata. Use `register_api_key()` to provision keys.

    Local: stub keys allowed for development without infrastructure.
    """

    def __init__(self, environment: Optional[str] = None, cache: Optional[Any] = None):
        self._environment = environment or settings.env
        self._cache = cache  # CacheClient instance, injected at startup

    @staticmethod
    def hash_key(api_key: str) -> str:
        """Hash an API key for storage/lookup. Never store raw keys."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    async def register_api_key(
        self,
        api_key: str,
        tenant_id: str,
        role: str = "viewer",
        tier: str = "free",
        permissions: Optional[list[str]] = None,
    ) -> str:
        """Register a new API key. Returns the key hash for reference."""
        key_hash = self.hash_key(api_key)
        key_data = {
            "tenant_id": tenant_id,
            "role": role,
            "tier": tier,
            "permissions": permissions or ["read"],
            "created_at": utc_now(),
        }
        if self._cache:
            from shared.cache.cache import CacheKey, TTL
            cache_key = CacheKey.api_key(key_hash)
            await self._cache.set_json(cache_key, key_data, ttl=TTL.DAY)
        return key_hash

    def validate(self, api_key: str) -> TenantContext:
        """Synchronous validation — checks stub keys in LOCAL mode."""
        from config.settings import Environment

        if self._environment == Environment.LOCAL:
            key_data = _LOCAL_STUB_KEYS.get(api_key)
            if key_data:
                return self._build_context(key_data)

        # Non-local: stub keys are forbidden
        if api_key in _LOCAL_STUB_KEYS:
            raise UnauthorizedError("Stub API keys are not allowed in non-local environments")

        # For sync validation without cache, reject
        # Use validate_async() for production key lookup
        raise UnauthorizedError("Invalid API key — use validate_async() for production")

    async def validate_async(self, api_key: str) -> TenantContext:
        """Async validation — looks up hashed key in Redis cache."""
        from config.settings import Environment

        # LOCAL mode: allow stub keys
        if self._environment == Environment.LOCAL:
            key_data = _LOCAL_STUB_KEYS.get(api_key)
            if key_data:
                ctx = self._build_context(key_data)
                ctx = await _maybe_apply_billing_plan_tier(ctx)
                return ctx

        # Reject stub keys outside LOCAL
        if api_key in _LOCAL_STUB_KEYS:
            raise UnauthorizedError("Stub API keys are not allowed in non-local environments")

        # Production: lookup hashed key in Redis
        if not self._cache:
            raise UnauthorizedError("API key validation unavailable — cache not configured")

        from shared.cache.cache import CacheKey
        key_hash = self.hash_key(api_key)
        cache_key = CacheKey.api_key(key_hash)
        key_data = await self._cache.get_json(cache_key)

        if not key_data:
            # Redis miss — fall back to durable Postgres lookup so API keys
            # survive cache restarts.  Repopulate cache on hit.
            key_data = await _lookup_api_key_from_db(key_hash)
            if key_data:
                try:
                    await self._cache.set_json(cache_key, key_data, ttl=TTL.DAY)
                except Exception:
                    pass  # Cache repopulation is best-effort
            else:
                raise UnauthorizedError("Invalid API key")

        ctx = self._build_context(key_data)
        ctx = await _maybe_apply_billing_plan_tier(ctx)

        # Fire-and-forget last_used_at update (does not block the request)
        import asyncio
        asyncio.ensure_future(_update_last_used_at(key_hash))

        return ctx

    @staticmethod
    def _build_context(key_data: dict) -> TenantContext:  # noqa: D401
        """See module-level helper below for billing-account override."""
        return _build_context_from_key_data(key_data)


async def _lookup_api_key_from_db(key_hash: str) -> Optional[dict]:
    """Durable Postgres fallback for API key lookup when Redis misses.

    Only called on cache miss.  Returns None if the key is not found or if
    the DB is unavailable (best-effort — missing key still means unauthorized).
    """
    try:
        from repositories.repos import APIKeyRepository
        repo = APIKeyRepository()
        key_id = key_hash[:12]
        record = await repo.find_by_id(key_id)
        if not record:
            return None
        # Validate full hash to prevent 48-bit prefix collisions
        if record.get("key_hash") != key_hash:
            return None
        # Normalize to the same shape that cache stores
        tier_raw = record.get("tier", "free")
        valid_tiers = {"free", "pro", "enterprise"}
        tier_safe = tier_raw if tier_raw in valid_tiers else "free"
        return {
            "tenant_id": record.get("tenant_id", ""),
            "role": record.get("role", "viewer"),
            "tier": tier_safe,
            "plan_tier": record.get("plan_tier"),
            "permissions": record.get("permissions", []),
        }
    except Exception:
        return None


async def _update_last_used_at(key_hash: str) -> None:
    """Background task: persist last_used_at on the api_keys record."""
    try:
        from repositories.repos import APIKeyRepository
        repo = APIKeyRepository()
        # The record's primary key is the first 12 chars of the hash
        key_id = key_hash[:12]
        record = await repo.find_by_id(key_id)
        if record:
            await repo.update(key_id, {"last_used_at": utc_now().isoformat()})
    except Exception:
        pass  # best-effort; never block auth path


def _build_context_from_key_data(key_data: dict) -> TenantContext:
    api_key_tier = APIKeyTier(key_data.get("tier", "free"))
    # plan_tier is preferred (P1-P4). Fall back to legacy tier mapping.
    plan_raw = key_data.get("plan_tier")
    if plan_raw:
        try:
            plan_tier = PlanTier(plan_raw)
        except ValueError:
            plan_tier = legacy_tier_to_plan(api_key_tier)
    else:
        plan_tier = legacy_tier_to_plan(api_key_tier)
    return TenantContext(
        tenant_id=key_data["tenant_id"],
        role=Role(key_data.get("role", "viewer")),
        api_key_tier=api_key_tier,
        plan_tier=plan_tier,
        permissions=key_data.get("permissions", []),
    )


async def _maybe_apply_billing_plan_tier(ctx: TenantContext) -> TenantContext:
    """If a tenant_billing_accounts row exists with a more recent plan_tier
    than the cached API-key data, apply it.

    This ensures Stripe subscription updates take effect even if a cached
    API key entry was created before the subscription change. Best-effort:
    any failure leaves the original context intact.
    """
    if not ctx.tenant_id:
        return ctx
    try:
        from shared.billing import stripe_repository
        account = await stripe_repository.get_billing_account(ctx.tenant_id)
        if not account:
            return ctx
        billing_plan = account.get("plan_tier")
        if not billing_plan:
            return ctx
        try:
            plan = PlanTier(billing_plan)
        except ValueError:
            return ctx
        if plan != ctx.plan_tier:
            ctx.plan_tier = plan
    except Exception:
        return ctx
    return ctx


# ═══════════════════════════════════════════════════════════════════════════
# PERMISSION CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

class Permissions:
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ANALYTICS = "analytics"
    ML_INFERENCE = "ml:inference"
    AGENT_MANAGE = "agent:manage"
    CAMPAIGN_MANAGE = "campaign:manage"
    CONSENT_MANAGE = "consent:manage"
    ADMIN = "admin"
    BILLING = "billing"
    X402_READ = "x402:read"
    X402_WRITE = "x402:write"
    # Agentic Commerce scopes
    COMMERCE_READ = "commerce:read"
    COMMERCE_CHALLENGE = "commerce:challenge"
    COMMERCE_VERIFY = "commerce:verify"
    COMMERCE_SETTLE = "commerce:settle"
    COMMERCE_APPROVE = "commerce:approve"
    COMMERCE_REVIEW = "commerce:review"
    COMMERCE_POLICY = "commerce:policy"
    COMMERCE_ADMIN = "commerce:admin"
    APPROVALS_READ = "approvals:read"
    APPROVALS_WRITE = "approvals:write"
    ENTITLEMENTS_READ = "entitlements:read"
    ENTITLEMENTS_WRITE = "entitlements:write"
    RESOURCES_ADMIN = "resources:admin"
    # Notification Intelligence scopes
    NOTIFICATIONS_APPROVE        = "notifications:approve"
    NOTIFICATIONS_MANAGE         = "notifications:manage"
    NOTIFICATIONS_CHANNELS_WRITE = "notifications:channels:write"


class KyberRole(str, Enum):
    """Kyber operator console roles for agentic commerce."""
    VIEWER   = "kyber:viewer"
    OPERATOR = "kyber:operator"
    APPROVER = "kyber:approver"
    ADMIN    = "kyber:admin"


# Permissions granted to each Kyber role (additive; higher roles include lower)
KYBER_ROLE_PERMISSIONS: dict[KyberRole, list[str]] = {
    KyberRole.VIEWER: [
        Permissions.COMMERCE_READ,
        Permissions.APPROVALS_READ,
        Permissions.ENTITLEMENTS_READ,
    ],
    KyberRole.OPERATOR: [
        Permissions.COMMERCE_READ,
        Permissions.COMMERCE_VERIFY,
        Permissions.COMMERCE_SETTLE,
        Permissions.COMMERCE_REVIEW,
        Permissions.APPROVALS_READ,
        Permissions.ENTITLEMENTS_READ,
    ],
    KyberRole.APPROVER: [
        Permissions.COMMERCE_READ,
        Permissions.COMMERCE_APPROVE,
        Permissions.COMMERCE_REVIEW,
        Permissions.COMMERCE_POLICY,
        Permissions.APPROVALS_READ,
        Permissions.APPROVALS_WRITE,
        Permissions.ENTITLEMENTS_READ,
    ],
    KyberRole.ADMIN: [
        Permissions.COMMERCE_READ,
        Permissions.COMMERCE_CHALLENGE,
        Permissions.COMMERCE_VERIFY,
        Permissions.COMMERCE_SETTLE,
        Permissions.COMMERCE_APPROVE,
        Permissions.COMMERCE_REVIEW,
        Permissions.COMMERCE_POLICY,
        Permissions.COMMERCE_ADMIN,
        Permissions.APPROVALS_READ,
        Permissions.APPROVALS_WRITE,
        Permissions.ENTITLEMENTS_READ,
        Permissions.ENTITLEMENTS_WRITE,
        Permissions.RESOURCES_ADMIN,
    ],
}
