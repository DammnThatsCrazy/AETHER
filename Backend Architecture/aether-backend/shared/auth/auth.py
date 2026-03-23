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
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from shared.common.common import ForbiddenError, UnauthorizedError
from config.settings import Environment, settings


def _state_dir(app_name: str) -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".local" / "state"
    path = root / "aether" / app_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _auth_db_path(environment: Environment | str) -> Path:
    explicit = os.environ.get("AETHER_AUTH_DB_PATH")
    if explicit:
        path = Path(explicit)
    else:
        env_name = environment.value if isinstance(environment, Environment) else str(environment)
        if env_name != Environment.LOCAL.value:
            raise RuntimeError(
                "AETHER_AUTH_DB_PATH must be set in non-local environments to enable durable API-key validation."
            )
        path = _state_dir("auth") / "api_keys.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


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
            raise ForbiddenError(f"Requires one of: {', '.join(perms)}")


class JWTHandler:
    """Minimal JWT encode/decode for HS256."""

    def __init__(self, secret: str = "", algorithm: str = "HS256"):
        self.secret = secret or settings.auth.jwt_secret
        self.algorithm = algorithm

    def encode(self, payload: dict) -> str:
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": self.algorithm, "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        if "exp" not in payload:
            payload["exp"] = int(time.time()) + settings.auth.jwt_expiry_minutes * 60
        if "iat" not in payload:
            payload["iat"] = int(time.time())
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        signing_input = f"{header}.{payload_b64}".encode()
        signature = base64.urlsafe_b64encode(
            hmac.new(self.secret.encode(), signing_input, hashlib.sha256).digest()
        ).rstrip(b"=").decode()
        return f"{header}.{payload_b64}.{signature}"

    def decode(self, token: str) -> dict:
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
        except Exception as exc:
            raise UnauthorizedError("Invalid token") from exc

    def extract_context(self, payload: dict) -> TenantContext:
        return TenantContext(
            tenant_id=payload.get("tenant_id", ""),
            user_id=payload.get("sub"),
            role=Role(payload.get("role", "viewer")),
            permissions=payload.get("permissions", []),
        )


class APIKeyRecordStore:
    """Durable SQLite-backed API-key registry."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_hash TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    permissions TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    expires_at INTEGER,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )

    @staticmethod
    def hash_key(api_key: str) -> str:
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    def upsert_key(
        self,
        api_key: str,
        *,
        tenant_id: str,
        role: str = Role.VIEWER.value,
        tier: str = APIKeyTier.FREE.value,
        permissions: list[str] | None = None,
        revoked: bool = False,
        expires_at: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO api_keys (
                    key_hash, tenant_id, role, tier, permissions, revoked,
                    expires_at, metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key_hash) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    role=excluded.role,
                    tier=excluded.tier,
                    permissions=excluded.permissions,
                    revoked=excluded.revoked,
                    expires_at=excluded.expires_at,
                    metadata=excluded.metadata,
                    updated_at=excluded.updated_at
                """,
                (
                    self.hash_key(api_key), tenant_id, role, tier,
                    json.dumps(permissions or []), int(revoked), expires_at,
                    json.dumps(metadata or {}), now, now,
                ),
            )

    def get_key(self, api_key: str) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM api_keys WHERE key_hash = ?",
                (self.hash_key(api_key),),
            ).fetchone()


class APIKeyValidator:
    """Validates API keys against a durable store and returns tenant context."""

    def __init__(self, environment: Optional[str] = None, db_path: Optional[str] = None):
        self._environment = Environment(environment) if environment else settings.env
        self._store = APIKeyRecordStore(Path(db_path) if db_path else _auth_db_path(self._environment))
        self._seed_from_env_if_requested()

    def _seed_from_env_if_requested(self) -> None:
        seed = os.environ.get("AETHER_BOOTSTRAP_API_KEYS_JSON", "").strip()
        if not seed:
            return
        for item in json.loads(seed):
            self._store.upsert_key(
                item["api_key"],
                tenant_id=item["tenant_id"],
                role=item.get("role", Role.VIEWER.value),
                tier=item.get("tier", APIKeyTier.FREE.value),
                permissions=item.get("permissions", []),
                revoked=bool(item.get("revoked", False)),
                expires_at=item.get("expires_at"),
                metadata=item.get("metadata", {}),
            )

    def provision_key(self, *, tenant_id: str, role: str = Role.VIEWER.value, tier: str = APIKeyTier.FREE.value,
                      permissions: Optional[list[str]] = None, expires_at: Optional[int] = None,
                      revoked: bool = False, metadata: Optional[dict[str, Any]] = None) -> str:
        api_key = f"ak_{secrets.token_urlsafe(24)}"
        self._store.upsert_key(
            api_key,
            tenant_id=tenant_id,
            role=role,
            tier=tier,
            permissions=permissions or [],
            expires_at=expires_at,
            revoked=revoked,
            metadata=metadata,
        )
        return api_key

    def validate(self, api_key: str) -> TenantContext:
        record = self._store.get_key(api_key)
        if record is None:
            raise UnauthorizedError("Invalid API key")
        if bool(record["revoked"]):
            raise UnauthorizedError("API key revoked")
        expires_at = record["expires_at"]
        if expires_at is not None and expires_at < int(time.time()):
            raise UnauthorizedError("API key expired")
        permissions = json.loads(record["permissions"])
        return TenantContext(
            tenant_id=record["tenant_id"],
            role=Role(record["role"]),
            api_key_tier=APIKeyTier(record["tier"]),
            permissions=permissions,
        )


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
