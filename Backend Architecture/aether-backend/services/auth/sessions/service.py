"""Session, service-credential, and public-ingest-identifier services.

Design notes
------------
* Sessions and credentials are opaque bearer tokens. The raw token is returned
  to the caller exactly once; only its sha256 is persisted (``token_hash`` /
  ``credential_hash``). Lookups run against the JSONB ``data`` field via
  BaseRepository (``data->>'token_hash'``), backed by the expression indexes in
  the 20260722_trust_plane migration.
* A human session is NOT a reusable API key: it is revocable, has idle +
  absolute expiry, and is tracked server-side.
* A public ingest identifier is non-secret and ingest-only — it carries the
  ``ingest`` permission ONLY, never ``analytics`` or admin.

Pure stdlib + BaseRepository; no FastAPI / cryptography imports so this module
is unit-testable in isolation.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from repositories.repos import BaseRepository


# ── Credential classes ──────────────────────────────────────────────────────

class CredentialClass:
    HUMAN_SESSION = "human_session"
    SERVICE_CREDENTIAL = "service_credential"
    PUBLIC_INGEST_IDENTIFIER = "public_ingest_identifier"


# Human sessions carry the same working permissions as the legacy key, but are
# revocable/expiring and never handed out as a reusable API key.
_HUMAN_SESSION_PERMISSIONS = ["read", "write", "ingest", "analytics"]
# Public ingest identifiers are ingest-only. They can never read analytics or
# call admin routes.
_PUBLIC_INGEST_PERMISSIONS = ["ingest"]

# Cookie name for the HttpOnly human-session cookie.
SESSION_COOKIE_NAME = "aether_session"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class SessionValidationError(Exception):
    """Raised when a session token is missing, expired, or revoked."""


@dataclass
class SessionIssue:
    """The result of creating a session — returned to the caller once."""

    session_id: str
    token: str  # opaque session token (NOT a reusable API key)
    tenant_id: str
    principal_id: Optional[str]
    credential_class: str
    idle_expires_at: str
    absolute_expires_at: str
    cookie_name: str
    cookie_max_age: int

    def public_dict(self) -> dict:
        """Body-safe representation (no hashes)."""
        return {
            "session_id": self.session_id,
            "token": self.token,
            "credential_class": self.credential_class,
            "idle_expires_at": self.idle_expires_at,
            "absolute_expires_at": self.absolute_expires_at,
        }


# ── Repositories (BaseRepository JSONB stores) ──────────────────────────────

class _SessionRepo(BaseRepository):
    def __init__(self) -> None:
        super().__init__("auth_sessions")


class _ServiceAccountRepo(BaseRepository):
    def __init__(self) -> None:
        super().__init__("service_accounts")


class _ServiceCredentialRepo(BaseRepository):
    def __init__(self) -> None:
        super().__init__("service_credentials")


class _PublicIngestRepo(BaseRepository):
    def __init__(self) -> None:
        super().__init__("public_ingest_identifiers")


# ── Session service ─────────────────────────────────────────────────────────

class SessionService:
    """Durable, revocable human sessions with idle + absolute expiry."""

    def __init__(self) -> None:
        self._repo = _SessionRepo()

    async def create_session(
        self,
        tenant_id: str,
        principal_id: Optional[str] = None,
        *,
        idle_minutes: int = 60,
        absolute_minutes: int = 12 * 60,
        credential_class: str = CredentialClass.HUMAN_SESSION,
        device_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        permissions: Optional[list[str]] = None,
    ) -> SessionIssue:
        now = _now()
        session_id = str(uuid.uuid4())
        raw_token = f"sess_{secrets.token_hex(24)}"
        token_hash = _hash(raw_token)
        idle_expires = now + timedelta(minutes=idle_minutes)
        absolute_expires = now + timedelta(minutes=absolute_minutes)

        record = {
            "tenant_id": tenant_id,
            "principal_id": principal_id,
            "token_hash": token_hash,
            "status": "active",
            "credential_class": credential_class,
            "permissions": list(
                permissions if permissions is not None else _HUMAN_SESSION_PERMISSIONS
            ),
            "idle_expires_at": idle_expires.isoformat(),
            "absolute_expires_at": absolute_expires.isoformat(),
            "device_id": device_id,
            "risk_state": "normal",
            "last_seen_at": now.isoformat(),
            "revoked_at": None,
            "metadata": metadata or {},
        }
        await self._repo.insert(session_id, record)

        return SessionIssue(
            session_id=session_id,
            token=raw_token,
            tenant_id=tenant_id,
            principal_id=principal_id,
            credential_class=credential_class,
            idle_expires_at=record["idle_expires_at"],
            absolute_expires_at=record["absolute_expires_at"],
            cookie_name=SESSION_COOKIE_NAME,
            cookie_max_age=absolute_minutes * 60,
        )

    async def validate_session(self, raw_token: str) -> dict:
        """Return the active session record or raise SessionValidationError."""
        if not raw_token or not raw_token.startswith("sess_"):
            raise SessionValidationError("missing or malformed session token")

        token_hash = _hash(raw_token)
        matches = await self._repo.find_many(filters={"token_hash": token_hash}, limit=1)
        if not matches:
            raise SessionValidationError("session not found")
        record = matches[0]

        if record.get("status") != "active" or record.get("revoked_at"):
            raise SessionValidationError("session revoked")

        now = _now()
        if _expired(record.get("absolute_expires_at"), now):
            await self._mark_expired(record.get("id"))
            raise SessionValidationError("session absolute expiry reached")
        if _expired(record.get("idle_expires_at"), now):
            await self._mark_expired(record.get("id"))
            raise SessionValidationError("session idle expiry reached")

        # Activity is durable operational evidence.  Do not extend the absolute
        # or idle deadlines here: expiry policy remains fixed and predictable.
        # Failure to record activity must not turn a valid session into an
        # authentication outage.
        try:
            last_seen_at = now.isoformat()
            await self._repo.update(record["id"], {"last_seen_at": last_seen_at})
            record["last_seen_at"] = last_seen_at
        except Exception:
            pass
        return record

    async def list_for_tenant(
        self, tenant_id: str, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[dict], int]:
        """List a tenant's sessions without ever exposing token hashes."""
        sessions = await self._repo.find_many(
            filters={"tenant_id": tenant_id}, limit=limit, offset=offset
        )
        total = await self._repo.count(filters={"tenant_id": tenant_id})
        safe = [
            {key: value for key, value in session.items() if key != "token_hash"}
            for session in sessions
        ]
        return safe, total

    async def revoke_for_tenant(self, tenant_id: str, session_id: str) -> bool:
        """Revoke a session only when it belongs to the authenticated tenant."""
        record = await self._repo.find_by_id(session_id)
        if not record or record.get("tenant_id") != tenant_id:
            return False
        return await self.revoke_session(session_id)

    async def revoke_other_sessions(self, tenant_id: str, current_session_id: str) -> int:
        """Revoke all active tenant sessions except the caller's session."""
        revoked = 0
        sessions = await self._repo.find_many(filters={"tenant_id": tenant_id}, limit=1000)
        for record in sessions:
            session_id = record.get("id")
            if (
                session_id
                and session_id != current_session_id
                and record.get("status") == "active"
                and await self.revoke_session(session_id)
            ):
                revoked += 1
        return revoked

    async def revoke_session(self, session_id: str) -> bool:
        try:
            await self._repo.update(
                session_id, {"status": "revoked", "revoked_at": _now().isoformat()}
            )
            return True
        except Exception:
            return False

    async def revoke_all_for_tenant(self, tenant_id: str) -> int:
        revoked = 0
        sessions = await self._repo.find_many(filters={"tenant_id": tenant_id}, limit=1000)
        for rec in sessions:
            sid = rec.get("id")
            if sid and rec.get("status") == "active":
                if await self.revoke_session(sid):
                    revoked += 1
        return revoked

    async def _mark_expired(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        try:
            await self._repo.update(session_id, {"status": "expired"})
        except Exception:
            pass


def _expired(iso: Optional[str], now: datetime) -> bool:
    if not iso:
        return False
    try:
        exp = datetime.fromisoformat(iso)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return now >= exp
    except ValueError:
        return False


# ── Service credentials ─────────────────────────────────────────────────────

class ServiceCredentialService:
    """Scoped, purpose-bound, rotatable, revocable machine credentials."""

    def __init__(self) -> None:
        self._accounts = _ServiceAccountRepo()
        self._creds = _ServiceCredentialRepo()

    async def create_service_account(
        self, tenant_id: str, name: str, *,
        environment: str = "production",
        created_by_principal_id: Optional[str] = None,
    ) -> dict:
        account_id = str(uuid.uuid4())
        record = {
            "tenant_id": tenant_id,
            "name": name,
            "environment": environment,
            "status": "active",
            "created_by_principal_id": created_by_principal_id,
        }
        return await self._accounts.insert(account_id, record)

    async def issue_credential(
        self, tenant_id: str, service_account_id: str, *,
        purpose: str,
        permissions: list[str],
        environment: str = "production",
        expires_at: Optional[str] = None,
        created_by_principal_id: Optional[str] = None,
    ) -> tuple[str, dict]:
        cred_id = str(uuid.uuid4())
        raw = f"svc_{secrets.token_hex(24)}"
        record = {
            "tenant_id": tenant_id,
            "service_account_id": service_account_id,
            "credential_hash": _hash(raw),
            "purpose": purpose,
            # Scoped permissions — never silently analytics/admin unless granted.
            "permissions": list(permissions),
            "environment": environment,
            "status": "active",
            "expires_at": expires_at,
            "last_used_at": None,
            "revoked_at": None,
            "created_by_principal_id": created_by_principal_id,
            "credential_class": CredentialClass.SERVICE_CREDENTIAL,
        }
        await self._creds.insert(cred_id, record)
        return raw, {**record, "id": cred_id}

    async def validate_credential(self, raw: str) -> dict:
        if not raw or not raw.startswith("svc_"):
            raise SessionValidationError("missing or malformed service credential")
        matches = await self._creds.find_many(
            filters={"credential_hash": _hash(raw)}, limit=1
        )
        if not matches:
            raise SessionValidationError("service credential not found")
        rec = matches[0]
        if rec.get("status") != "active" or rec.get("revoked_at"):
            raise SessionValidationError("service credential revoked")
        if _expired(rec.get("expires_at"), _now()):
            raise SessionValidationError("service credential expired")
        account_id = rec.get("service_account_id")
        account = await self._accounts.find_by_id(account_id) if account_id else None
        if not account or account.get("status") != "active":
            raise SessionValidationError("service account inactive")
        if account.get("tenant_id") != rec.get("tenant_id"):
            raise SessionValidationError("service account tenant mismatch")
        return rec

    async def rotate_credential(self, credential_id: str) -> None:
        try:
            await self._creds.update(credential_id, {"status": "rotating"})
        except Exception:
            pass

    async def revoke_credential(self, credential_id: str) -> bool:
        try:
            await self._creds.update(
                credential_id, {"status": "revoked", "revoked_at": _now().isoformat()}
            )
            return True
        except Exception:
            return False

    async def revoke_all_for_tenant(self, tenant_id: str) -> int:
        """Revoke every service credential and account owned by a tenant."""
        revoked = 0
        credentials = await self._creds.find_many(
            filters={"tenant_id": tenant_id}, limit=1000
        )
        for record in credentials:
            credential_id = record.get("id")
            if credential_id and record.get("status") == "active":
                if await self.revoke_credential(credential_id):
                    revoked += 1
        accounts = await self._accounts.find_many(
            filters={"tenant_id": tenant_id}, limit=1000
        )
        for account in accounts:
            account_id = account.get("id")
            if account_id and account.get("status") == "active":
                try:
                    await self._accounts.update(account_id, {"status": "suspended"})
                except Exception:
                    pass
        return revoked


# ── Public ingest identifiers ───────────────────────────────────────────────

class PublicIngestService:
    """Non-secret, ingest-only, tenant/environment-scoped identifiers."""

    def __init__(self) -> None:
        self._repo = _PublicIngestRepo()

    async def issue_identifier(
        self, tenant_id: str, *, environment: str = "production",
        label: str = "public ingest",
    ) -> dict:
        ident_id = str(uuid.uuid4())
        # Non-secret: the identifier value itself is stored and returned; it is
        # not a bearer secret and carries only the `ingest` permission.
        identifier = f"pik_{secrets.token_hex(12)}"
        record = {
            "tenant_id": tenant_id,
            "identifier": identifier,
            "environment": environment,
            "label": label,
            "status": "active",
            "permissions": list(_PUBLIC_INGEST_PERMISSIONS),
            "credential_class": CredentialClass.PUBLIC_INGEST_IDENTIFIER,
            "revoked_at": None,
        }
        await self._repo.insert(ident_id, record)
        return {**record, "id": ident_id}

    async def validate_identifier(self, identifier: str) -> dict:
        if not identifier or not identifier.startswith("pik_"):
            raise SessionValidationError("missing or malformed ingest identifier")
        matches = await self._repo.find_many(
            filters={"identifier": identifier}, limit=1
        )
        if not matches:
            raise SessionValidationError("ingest identifier not found")
        rec = matches[0]
        if rec.get("status") != "active" or rec.get("revoked_at"):
            raise SessionValidationError("ingest identifier revoked")
        return rec

    async def revoke_identifier(self, ident_id: str) -> bool:
        try:
            await self._repo.update(
                ident_id, {"status": "revoked", "revoked_at": _now().isoformat()}
            )
            return True
        except Exception:
            return False

    async def revoke_all_for_tenant(self, tenant_id: str) -> int:
        """Revoke every public ingest identifier owned by a tenant."""
        revoked = 0
        identifiers = await self._repo.find_many(
            filters={"tenant_id": tenant_id}, limit=1000
        )
        for record in identifiers:
            identifier_id = record.get("id")
            if identifier_id and record.get("status") == "active":
                if await self.revoke_identifier(identifier_id):
                    revoked += 1
        return revoked


# Module-level singletons (mirrors the repo's singleton pattern).
session_service = SessionService()
service_credential_service = ServiceCredentialService()
public_ingest_service = PublicIngestService()
