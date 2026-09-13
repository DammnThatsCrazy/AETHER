"""
Aether Shared — @aether/auth
JWT verification, API key validation, permission checking, tenant context.
Used by ALL services via middleware.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from config.settings import settings
from shared.common.common import (
    ForbiddenError,
    UnauthorizedError,
)

# ═══════════════════════════════════════════════════════════════════════════
# TENANT / USER CONTEXT
# ═══════════════════════════════════════════════════════════════════════════

class Role(str, Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
    SERVICE = "service"  # service-to-service


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

    def require_permission(self, permission: str):
        if not self.has_permission(permission):
            raise ForbiddenError(f"Missing permission: {permission}")


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

    def decode(self, token: str) -> dict:
        """Decode and verify a JWT. Returns the payload dict."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise UnauthorizedError("Malformed token")

            # Decode payload (middle segment)
            payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))

            # Check expiry
            if payload.get("exp", 0) < time.time():
                raise UnauthorizedError("Token expired")

            # Verify signature (simplified — use a real library in prod)
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

    # Stub store — replace with DynamoDB lookup
    _STUB_KEYS: dict[str, dict] = {
        "ak_test_123": {
            "tenant_id": "tenant_001",
            "tier": "pro",
            "role": "editor",
            "permissions": ["read", "write", "analytics", "ml:inference", "agent:manage", "campaign:manage", "consent:manage", "admin", "billing"],
        },
    }

    def validate(self, api_key: str) -> TenantContext:
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
