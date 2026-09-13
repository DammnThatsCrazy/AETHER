"""Deterministic deferred-attribution handoffs (iOS install attribution).

iOS has no Android-style install referrer. The ONLY honest deferred
attribution is deterministic: a controlled pre-install surface (landing page,
QR flow, partner placement) registers a handoff server-side, and the installed
app later presents the SAME explicit identifier. Matching is exact
(tenant-scoped SHA-256 of the identifier), resolve-once, and expiring.

Probabilistic fingerprint matching is intentionally NOT implemented and must
never be added here as "resolution" — unmatched installs stay Direct / Unknown.

Routes (registered in main.py like every other service router):
    POST /v1/attribution/deferred/handoffs   Register a pending handoff (RBAC)
    POST /v1/attribution/deferred/resolve    SDK resolve-once by identifier

Resolve responses are uniform for unmatched / expired / already-consumed
handoffs ({"resolved": false}) so callers never gain a handoff-state oracle.

Storage follows VerifiedReferralLinkRepository conventions: durable SQL rows
(``deferred_attribution_handoffs``, migration 20260803_deferred_attribution)
with an in-memory fallback when no pool is configured (local/test).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from shared.temporal import ensure_aware_utc

from repositories.repos import get_pool
from shared.auth.auth import Role, TenantContext
from shared.decorators import require_api_key

logger = logging.getLogger("aether.traffic.deferred_attribution")

router = APIRouter(prefix="/v1/attribution/deferred", tags=["deferred-attribution"])

# Evidence returned on resolution always carries these canonical markers:
# the match itself was observed server-side against a controlled handoff.
RESOLVED_ENTRY_METHOD = "verified_source_link"
RESOLVED_PROOF_LEVEL = "server_observed"

_MAX_IDENTIFIER_LENGTH = 512
_IDENTIFIER_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_DEFAULT_TTL = timedelta(days=30)
_MAX_TTL = timedelta(days=90)

# Evidence keys a handoff creator may declare. Everything else is dropped so
# the resolve payload can never smuggle arbitrary server-asserted fields.
_ALLOWED_EVIDENCE_KEYS = frozenset(
    {
        "source",
        "medium",
        "source_class",
        "placement",
        "campaign_id",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
    }
)

_LOCAL_DEFERRED_HANDOFFS: dict[str, dict[str, Any]] = {}


async def _pool() -> Any:
    return await get_pool()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        # Canonical persisted timestamps are UTC; interpret a naive value as UTC
        # via datetime.combine so no timezone-attaching mutation is needed.
        value = datetime.combine(value.date(), value.time(), tzinfo=timezone.utc)
    return ensure_aware_utc(value)


def _identifier_hash(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()


def _clean(value: Optional[str]) -> Optional[str]:
    cleaned = str(value).strip() if value is not None else ""
    return cleaned or None


def _sanitize_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in evidence.items():
        if key not in _ALLOWED_EVIDENCE_KEYS:
            continue
        cleaned = _clean(value if isinstance(value, str) else str(value))
        if cleaned is not None:
            sanitized[key] = cleaned[:255]
    return sanitized


def _evidence_dict(value: Any) -> dict[str, Any]:
    """Evidence column round-trip: asyncpg may hand JSON/JSONB back as text."""

    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def public_handoff(record: dict[str, Any]) -> dict[str, Any]:
    """API-safe handoff representation — never discloses identifier_hash."""

    fields = (
        "handoff_id",
        "tenant_id",
        "link_id",
        "evidence",
        "environment",
        "expires_at",
        "consumed_at",
        "created_at",
    )
    result = {field: record.get(field) for field in fields}
    result["evidence"] = _evidence_dict(record.get("evidence"))
    expires_at = _as_utc(record.get("expires_at"))
    if record.get("consumed_at") is not None:
        result["status"] = "consumed"
    elif expires_at is not None and expires_at <= _now():
        result["status"] = "expired"
    else:
        result["status"] = "pending"
    return result


class DeferredAttributionRepository:
    """Tenant-scoped pending-handoff registry with resolve-once semantics."""

    async def create(
        self,
        tenant_id: str,
        *,
        identifier: str,
        evidence: dict[str, Any],
        link_id: Optional[str] = None,
        environment: str = "production",
        expires_at: Optional[datetime] = None,
        created_by: Optional[str] = None,
    ) -> dict[str, Any]:
        tenant_id = str(tenant_id).strip()
        if not tenant_id:
            raise ValueError("tenant_id is required")
        identifier = str(identifier or "").strip()
        if not identifier or len(identifier) > _MAX_IDENTIFIER_LENGTH:
            raise ValueError("identifier must be 1-512 characters")
        if environment not in {"production", "sandbox"}:
            raise ValueError("environment must be production or sandbox")

        now = _now()
        expires_at = _as_utc(expires_at)
        if expires_at is None:
            expires_at = now + _DEFAULT_TTL
        if expires_at <= now:
            raise ValueError("expires_at must be in the future")
        if expires_at > now + _MAX_TTL:
            raise ValueError("expires_at must be within 90 days")

        sanitized = _sanitize_evidence(evidence)
        if not sanitized:
            raise ValueError(
                "evidence must declare at least one of: "
                + ", ".join(sorted(_ALLOWED_EVIDENCE_KEYS))
            )

        handoff_id = str(uuid4())
        digest = _identifier_hash(identifier)
        values: dict[str, Any] = {
            "handoff_id": handoff_id,
            "tenant_id": tenant_id,
            "identifier_hash": digest,
            "evidence": sanitized,
            "link_id": _clean(link_id),
            "environment": environment,
            "expires_at": expires_at,
            "consumed_at": None,
            "created_by": _clean(created_by),
            "created_at": now,
        }

        pool = await _pool()
        if pool is None:
            duplicate = any(
                record["tenant_id"] == tenant_id
                and secrets.compare_digest(record["identifier_hash"], digest)
                for record in _LOCAL_DEFERRED_HANDOFFS.values()
            )
            if duplicate:
                raise ValueError("a handoff already exists for this identifier")
            _LOCAL_DEFERRED_HANDOFFS[handoff_id] = values
            return public_handoff(values)

        try:
            row = await pool.fetchrow(
                """
                INSERT INTO deferred_attribution_handoffs (
                    handoff_id, tenant_id, identifier_hash, evidence, link_id,
                    environment, expires_at, created_by, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                RETURNING *
                """,
                handoff_id,
                tenant_id,
                digest,
                json.dumps(sanitized),
                values["link_id"],
                environment,
                expires_at,
                values["created_by"],
                now,
            )
        except Exception as exc:  # unique (tenant_id, identifier_hash)
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise ValueError("a handoff already exists for this identifier") from exc
            raise
        return public_handoff(dict(row))

    async def resolve_once(self, tenant_id: str, identifier: str) -> Optional[dict[str, Any]]:
        """Consume a matching pending, unexpired handoff exactly once.

        Unmatched, expired, cross-tenant, and already-consumed identifiers all
        return ``None`` — callers must translate that to the uniform
        ``{"resolved": false}`` response.
        """

        identifier = str(identifier or "").strip()
        if not identifier or len(identifier) > _MAX_IDENTIFIER_LENGTH:
            return None
        digest = _identifier_hash(identifier)
        if not _IDENTIFIER_HASH_RE.fullmatch(digest):  # defensive
            return None
        now = _now()

        pool = await _pool()
        if pool is None:
            record = next(
                (
                    candidate
                    for candidate in _LOCAL_DEFERRED_HANDOFFS.values()
                    if candidate["tenant_id"] == tenant_id
                    and secrets.compare_digest(candidate["identifier_hash"], digest)
                ),
                None,
            )
            if record is None or record.get("consumed_at") is not None:
                return None
            expires_at = _as_utc(record.get("expires_at"))
            if expires_at is not None and expires_at <= now:
                return None
            record["consumed_at"] = now
            return self._resolution(record)

        row = await pool.fetchrow(
            """
            UPDATE deferred_attribution_handoffs
            SET consumed_at = $3
            WHERE tenant_id = $1 AND identifier_hash = $2
              AND consumed_at IS NULL
              AND (expires_at IS NULL OR expires_at > $3)
            RETURNING *
            """,
            tenant_id,
            digest,
            now,
        )
        return self._resolution(dict(row)) if row else None

    def _resolution(self, record: dict[str, Any]) -> dict[str, Any]:
        evidence = _evidence_dict(record.get("evidence"))
        evidence["entry_method"] = RESOLVED_ENTRY_METHOD
        evidence["proof_level"] = RESOLVED_PROOF_LEVEL
        if record.get("link_id"):
            evidence["link_id"] = str(record["link_id"])
        return {
            "handoff_id": str(record["handoff_id"]),
            "evidence": evidence,
            "environment": record.get("environment") or "production",
        }


_repository = DeferredAttributionRepository()


def reset_deferred_handoffs_for_tests() -> None:
    """Clear only the local fallback; never mutates the database."""

    _LOCAL_DEFERRED_HANDOFFS.clear()


# =============================================================================
# RBAC — mirrors the _require_* pattern in services/traffic/routes.py:
# browser/viewer keys stay outside the deferred-attribution control plane.
# =============================================================================

def _deferred_attribution_access_allowed(tenant: TenantContext, permission: str) -> bool:
    if tenant.role in {Role.ADMIN, Role.EDITOR, Role.SERVICE}:
        return True
    return tenant.has_permission(permission)


async def _require_deferred_handoff_write(
    tenant: TenantContext = Depends(require_api_key),
) -> TenantContext:
    if not _deferred_attribution_access_allowed(tenant, "deferred_attribution:write"):
        raise HTTPException(
            status_code=403, detail="Deferred-attribution write access required"
        )
    return tenant


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================

class DeferredHandoffCreate(BaseModel):
    """Register a pending deterministic handoff before/at install time."""

    identifier: str = Field(min_length=1, max_length=_MAX_IDENTIFIER_LENGTH)
    evidence: dict[str, Any] = Field(default_factory=dict)
    link_id: Optional[str] = Field(default=None, max_length=255)
    environment: str = Field(default="production")
    expires_at: Optional[datetime] = None


class DeferredHandoffResolve(BaseModel):
    identifier: str = Field(min_length=1, max_length=_MAX_IDENTIFIER_LENGTH)


# =============================================================================
# ROUTES
# =============================================================================

@router.post("/handoffs", status_code=201)
async def create_deferred_handoff(
    body: DeferredHandoffCreate,
    tenant: TenantContext = Depends(_require_deferred_handoff_write),
) -> dict[str, Any]:
    """Register a pending handoff for later exact-identifier resolution.

    Only the SHA-256 of the identifier is persisted; the plaintext identifier
    lives solely in the controlled pre-install surface and the installed app.
    """

    try:
        handoff = await _repository.create(
            tenant.tenant_id,
            identifier=body.identifier,
            evidence=body.evidence,
            link_id=body.link_id,
            environment=body.environment,
            expires_at=body.expires_at,
            created_by=tenant.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"handoff": handoff}


@router.post("/resolve")
async def resolve_deferred_handoff(
    body: DeferredHandoffResolve,
    request: Request,
) -> dict[str, Any]:
    """SDK-facing resolve-once endpoint.

    A matching pending unexpired handoff for the tenant is consumed and its
    stored acquisition evidence returned with entry_method
    "verified_source_link" and proof_level "server_observed". Everything else
    is the uniform ``{"resolved": false}`` — the install stays Direct / Unknown.
    """

    tenant_id = _tenant_id_from_request(request)
    resolution = await _repository.resolve_once(tenant_id, body.identifier)
    if resolution is None:
        return {"resolved": False}

    logger.info(
        "Deferred handoff resolved tenant=%s handoff=%s",
        tenant_id,
        resolution["handoff_id"],
    )
    return {
        "resolved": True,
        "evidence": resolution["evidence"],
        "environment": resolution["environment"],
        "resolved_at": _now().isoformat(),
    }


def _tenant_id_from_request(request: Request) -> str:
    """Tenant from the auth middleware (Bearer SDK keys populate
    request.state.tenant, matching /v1/batch); local/test falls back to the
    default tenant like services/attribution/routes.py."""

    tenant = getattr(getattr(request, "state", None), "tenant", None)
    if tenant is not None and getattr(tenant, "tenant_id", None):
        return tenant.tenant_id

    import os

    env = os.getenv("AETHER_ENV", "local").lower()
    if env in ("local", "test"):
        return os.getenv("DEFAULT_TENANT_ID", "tenant_local_dev")
    raise HTTPException(status_code=401, detail="Authentication required")
