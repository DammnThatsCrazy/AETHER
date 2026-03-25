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
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass
class TenantContext:
    """Populated on every authenticated request — available to all handlers."""
    tenant_id: str
    user_id: Optional[str] = None
    role: Role = Role.VIEWER
    api_key_tier: APIKeyTier = APIKeyTier.FREE
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
        allow_hs256_fallback: bool = True,
    ):
        self.secret = secret or settings.auth.jwt_secret
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
        from config.settings import Environment
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
                return self._build_context(key_data)

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
            raise UnauthorizedError("Invalid API key")

        return self._build_context(key_data)

    @staticmethod
    def _build_context(key_data: dict) -> TenantContext:
        return TenantContext(
            tenant_id=key_data["tenant_id"],
            role=Role(key_data.get("role", "viewer")),
            api_key_tier=APIKeyTier(key_data.get("tier", "free")),
            permissions=key_data.get("permissions", []),
        )


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
