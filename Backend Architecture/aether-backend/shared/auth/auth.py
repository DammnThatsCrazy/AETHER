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
# JWT HANDLER (simplified — swap with PyJWT in production)
# ═══════════════════════════════════════════════════════════════════════════

class JWTHandler:
    """
    Minimal JWT encode/decode for HS256.
    In production, use python-jose or PyJWT with RS256 + key rotation.
    """

    def __init__(self, secret: str = "", algorithm: str = "HS256"):
        self.secret = secret or settings.auth.jwt_secret
        self.algorithm = algorithm

    def encode(self, payload: dict) -> str:
        """Encode a payload into a JWT string."""
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": self.algorithm, "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()

        # Ensure expiry
        if "exp" not in payload:
            payload["exp"] = int(time.time()) + settings.auth.jwt_expiry_minutes * 60
        if "iat" not in payload:
            payload["iat"] = int(time.time())

        payload_b64 = base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).rstrip(b"=").decode()

        signing_input = f"{header}.{payload_b64}".encode()
        signature = base64.urlsafe_b64encode(
            hmac.new(self.secret.encode(), signing_input, hashlib.sha256).digest()
        ).rstrip(b"=").decode()

        return f"{header}.{payload_b64}.{signature}"

    def decode(self, token: str) -> dict:
        """Decode and verify a JWT. Returns the payload dict."""
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
# API KEY VALIDATOR (stub — look up keys in DynamoDB / Redis)
# ═══════════════════════════════════════════════════════════════════════════

class APIKeyValidator:
    """
    Validates API keys and returns tenant context.
    In production, keys are hashed and stored in DynamoDB with metadata.
    """

    _STUB_KEYS: dict[str, dict] = {
        "ak_test_123": {
            "tenant_id": "tenant_001",
            "tier": "pro",
            "role": "editor",
            "permissions": [
                "read", "write", "analytics", "ml:inference",
                "agent:manage", "campaign:manage", "consent:manage",
                "admin", "billing",
            ],
        },
    }

    def __init__(self, environment: Optional[str] = None):
        from config.settings import Environment
        self._environment = environment or settings.env

    def validate(self, api_key: str) -> TenantContext:
        from config.settings import Environment

        # Only allow stub keys in LOCAL environment
        if self._environment != Environment.LOCAL:
            # In non-local environments, stub keys must not be used
            if api_key in self._STUB_KEYS:
                raise UnauthorizedError("Stub API keys are not allowed in non-local environments")
            # In production, look up keys from DynamoDB/Redis (stub: reject all)
            raise UnauthorizedError("Invalid API key")

        key_data = self._STUB_KEYS.get(api_key)
        if not key_data:
            raise UnauthorizedError("Invalid API key")

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
