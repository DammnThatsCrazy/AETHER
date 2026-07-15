"""Durable verified referral-link repository.

Verified links are an evidence source for the existing canonical touchpoint
pipeline.  They are not a second referral or attribution system.  The public
token is returned once at creation time; only its SHA-256 digest is persisted.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from repositories.repos import get_pool


ALLOWED_REFERRAL_MEDIATION_TYPES = frozenset(
    {
        "ordinary_referral",
        "ai_mediated_human_referral",
        "agent_mediated_referral",
        "owned_agent_referral",
        "partner_referral",
        "affiliate_referral",
    }
)

_TOKEN_BYTES = 32
_MAX_TOKEN_LENGTH = 512
_TOKEN_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCAL_VERIFIED_REFERRAL_LINKS: dict[str, dict[str, Any]] = {}
_LOCAL_VERIFIED_REFERRAL_LINK_USES: set[tuple[str, str, str]] = set()


async def _pool() -> Any:
    return await get_pool()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clean(value: Optional[str]) -> Optional[str]:
    cleaned = str(value).strip() if value is not None else ""
    return cleaned or None


def _clean_ai_dimension(value: Optional[str]) -> Optional[str]:
    cleaned = _clean(value)
    return cleaned.lower().replace(" ", "_")[:120] if cleaned else None


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row)


def public_referral_link(record: dict[str, Any]) -> dict[str, Any]:
    """Return the API-safe representation of a stored link.

    This allowlist intentionally excludes ``token_hash``.  Keeping the
    serializer next to the repository makes it difficult for future routes to
    accidentally expose the credential-equivalent digest.
    """

    fields = (
        "verified_referral_link_id",
        "tenant_id",
        "placement_id",
        "agent_id",
        "campaign_id",
        "ai_provider",
        "ai_product",
        "referral_mediation_type",
        "status",
        "expires_at",
        "use_count",
        "first_used_at",
        "last_used_at",
        "created_by",
        "revoked_by",
        "revocation_reason",
        "revoked_at",
        "created_at",
        "updated_at",
    )
    result = {field: record.get(field) for field in fields}
    expires_at = _as_utc(record.get("expires_at"))
    if (
        result.get("status") == "active"
        and expires_at is not None
        and expires_at <= _now()
    ):
        result["effective_status"] = "expired"
    else:
        result["effective_status"] = result.get("status")
    return result


def verified_referral_claim(record: dict[str, Any]) -> dict[str, Any]:
    """Build the strict server-side claim consumed by SourceClassifier."""

    mediation = record.get("referral_mediation_type") or "agent_mediated_referral"
    actor_type = (
        "agent"
        if mediation in {"agent_mediated_referral", "owned_agent_referral"}
        else "human"
    )
    if actor_type == "agent":
        journey_role = "handoff"
    elif mediation in {"partner_referral", "affiliate_referral"}:
        journey_role = "campaign"
    else:
        journey_role = "discovery"
    provider = record.get("ai_provider")
    product = record.get("ai_product")
    return {
        "verified_referral_link_id": str(record["verified_referral_link_id"]),
        "placement_id": record.get("placement_id"),
        "agent_id": record.get("agent_id"),
        "campaign_id": record.get("campaign_id"),
        "ai_provider": provider,
        "ai_product": product,
        "referral_mediation_type": mediation,
        "actor_type": actor_type,
        "journey_role": journey_role,
        "source": provider or product or "verified_referral",
    }


class VerifiedReferralLinkRepository:
    """Tenant-scoped CRUD and token resolution for verified referral links."""

    async def create(
        self,
        tenant_id: str,
        *,
        placement_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        ai_provider: Optional[str] = None,
        ai_product: Optional[str] = None,
        referral_mediation_type: str = "agent_mediated_referral",
        expires_at: Optional[datetime] = None,
        created_by: Optional[str] = None,
    ) -> tuple[dict[str, Any], str]:
        tenant_id = str(tenant_id).strip()
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if referral_mediation_type not in ALLOWED_REFERRAL_MEDIATION_TYPES:
            raise ValueError(
                f"unsupported referral_mediation_type: {referral_mediation_type}"
            )

        expires_at = _as_utc(expires_at)
        now = _now()
        if expires_at is not None and expires_at <= now:
            raise ValueError("expires_at must be in the future")

        canonical_campaign_id = _clean(campaign_id)
        if canonical_campaign_id is not None:
            try:
                UUID(canonical_campaign_id)
            except ValueError as exc:
                raise ValueError("campaign_id must be a canonical campaign UUID") from exc

        link_id = uuid4()
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        digest = _token_hash(token)
        values = {
            "verified_referral_link_id": link_id,
            "tenant_id": tenant_id,
            "token_hash": digest,
            "placement_id": _clean(placement_id),
            "agent_id": _clean(agent_id),
            "campaign_id": canonical_campaign_id,
            "ai_provider": _clean_ai_dimension(ai_provider),
            "ai_product": _clean_ai_dimension(ai_product),
            "referral_mediation_type": referral_mediation_type,
            "status": "active",
            "expires_at": expires_at,
            "use_count": 0,
            "first_used_at": None,
            "last_used_at": None,
            "created_by": _clean(created_by),
            "revoked_by": None,
            "revocation_reason": None,
            "revoked_at": None,
            "created_at": now,
            "updated_at": now,
        }

        pool = await _pool()
        if pool is None:
            _LOCAL_VERIFIED_REFERRAL_LINKS[str(link_id)] = values
            return public_referral_link(values), token

        row = await pool.fetchrow(
            """
            INSERT INTO verified_referral_links (
                verified_referral_link_id, tenant_id, token_hash,
                placement_id, agent_id, campaign_id, ai_provider, ai_product,
                referral_mediation_type, status, expires_at, created_by,
                created_at, updated_at
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,'active',$10,$11,$12,$12
            )
            RETURNING *
            """,
            link_id,
            tenant_id,
            digest,
            values["placement_id"],
            values["agent_id"],
            values["campaign_id"],
            values["ai_provider"],
            values["ai_product"],
            referral_mediation_type,
            expires_at,
            values["created_by"],
            now,
        )
        return public_referral_link(_row_to_dict(row)), token

    async def get(
        self, tenant_id: str, verified_referral_link_id: UUID | str
    ) -> Optional[dict[str, Any]]:
        try:
            link_id = UUID(str(verified_referral_link_id))
        except (TypeError, ValueError):
            return None

        pool = await _pool()
        if pool is None:
            record = _LOCAL_VERIFIED_REFERRAL_LINKS.get(str(link_id))
            if not record or record.get("tenant_id") != tenant_id:
                return None
            return public_referral_link(record)

        row = await pool.fetchrow(
            """
            SELECT * FROM verified_referral_links
            WHERE tenant_id = $1 AND verified_referral_link_id = $2
            """,
            tenant_id,
            link_id,
        )
        return public_referral_link(_row_to_dict(row)) if row else None

    async def list(
        self,
        tenant_id: str,
        *,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        if status is not None and status not in {"active", "revoked"}:
            raise ValueError("status must be active or revoked")

        pool = await _pool()
        if pool is None:
            rows = [
                record
                for record in _LOCAL_VERIFIED_REFERRAL_LINKS.values()
                if record.get("tenant_id") == tenant_id
                and (status is None or record.get("status") == status)
            ]
            rows.sort(key=lambda record: record["created_at"], reverse=True)
            return [public_referral_link(record) for record in rows[offset : offset + limit]]

        params: list[Any] = [tenant_id]
        where = ["tenant_id = $1"]
        if status is not None:
            params.append(status)
            where.append("status = $2")
        params.extend([limit, offset])
        limit_idx = len(params) - 1
        offset_idx = len(params)
        rows = await pool.fetch(
            f"""
            SELECT * FROM verified_referral_links
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT ${limit_idx} OFFSET ${offset_idx}
            """,
            *params,
        )
        return [public_referral_link(_row_to_dict(row)) for row in rows]

    async def revoke(
        self,
        tenant_id: str,
        verified_referral_link_id: UUID | str,
        *,
        revoked_by: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        try:
            link_id = UUID(str(verified_referral_link_id))
        except (TypeError, ValueError):
            return None
        now = _now()

        pool = await _pool()
        if pool is None:
            record = _LOCAL_VERIFIED_REFERRAL_LINKS.get(str(link_id))
            if not record or record.get("tenant_id") != tenant_id:
                return None
            if record.get("status") == "active":
                record.update(
                    {
                        "status": "revoked",
                        "revoked_by": _clean(revoked_by),
                        "revocation_reason": _clean(reason),
                        "revoked_at": now,
                        "updated_at": now,
                    }
                )
            return public_referral_link(record)

        row = await pool.fetchrow(
            """
            UPDATE verified_referral_links
            SET status = 'revoked', revoked_by = $3, revocation_reason = $4,
                revoked_at = $5, updated_at = $5
            WHERE tenant_id = $1 AND verified_referral_link_id = $2
              AND status = 'active'
            RETURNING *
            """,
            tenant_id,
            link_id,
            _clean(revoked_by),
            _clean(reason),
            now,
        )
        if row:
            return public_referral_link(_row_to_dict(row))
        return await self.get(tenant_id, link_id)

    async def resolve_token(
        self,
        tenant_id: str,
        token: str,
        *,
        source_event_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Resolve and consume an active tenant-scoped token.

        Invalid, cross-tenant, expired, and revoked tokens intentionally all
        return ``None`` so callers do not gain a token-state oracle.
        """

        if not token or len(token) > _MAX_TOKEN_LENGTH:
            return None
        return await self.resolve_token_hash(
            tenant_id,
            _token_hash(token),
            source_event_id=source_event_id,
        )

    async def resolve_token_hash(
        self,
        tenant_id: str,
        digest: str,
        *,
        source_event_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Resolve an ingestion-produced token digest for durable replay.

        The digest is still credential-equivalent; callers must not expose or
        copy it into analytical facts. It exists solely so Bronze/outbox replay
        can verify a link without persisting its plaintext token.
        """

        digest = str(digest or "").lower()
        if not _TOKEN_HASH_RE.fullmatch(digest):
            return None
        now = _now()

        pool = await _pool()
        if pool is None:
            record = next(
                (
                    candidate
                    for candidate in _LOCAL_VERIFIED_REFERRAL_LINKS.values()
                    if candidate.get("tenant_id") == tenant_id
                    and secrets.compare_digest(candidate.get("token_hash", ""), digest)
                ),
                None,
            )
            if record is None:
                return None
            expires_at = _as_utc(record.get("expires_at"))
            if (
                record.get("status") != "active"
                or record.get("revoked_at") is not None
                or (expires_at is not None and expires_at <= now)
            ):
                return None
            should_increment = True
            if source_event_id:
                use_key = (
                    tenant_id,
                    str(record["verified_referral_link_id"]),
                    str(source_event_id),
                )
                should_increment = use_key not in _LOCAL_VERIFIED_REFERRAL_LINK_USES
                _LOCAL_VERIFIED_REFERRAL_LINK_USES.add(use_key)
            if should_increment:
                record["use_count"] = int(record.get("use_count") or 0) + 1
                record["first_used_at"] = record.get("first_used_at") or now
                record["last_used_at"] = now
                record["updated_at"] = now
            return verified_referral_claim(record)

        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT * FROM verified_referral_links
                    WHERE tenant_id = $1 AND token_hash = $2
                      AND status = 'active' AND revoked_at IS NULL
                      AND (expires_at IS NULL OR expires_at > $3)
                    FOR UPDATE
                    """,
                    tenant_id,
                    digest,
                    now,
                )
                if row is None:
                    return None
                should_increment = True
                if source_event_id:
                    inserted = await conn.fetchval(
                        """
                        INSERT INTO verified_referral_link_uses (
                            tenant_id, verified_referral_link_id,
                            source_event_id, first_used_at
                        ) VALUES ($1,$2,$3,$4)
                        ON CONFLICT (
                            tenant_id, verified_referral_link_id, source_event_id
                        ) DO NOTHING
                        RETURNING 1
                        """,
                        tenant_id,
                        row["verified_referral_link_id"],
                        str(source_event_id),
                        now,
                    )
                    should_increment = bool(inserted)
                if should_increment:
                    row = await conn.fetchrow(
                        """
                        UPDATE verified_referral_links
                        SET use_count = use_count + 1,
                            first_used_at = COALESCE(first_used_at, $3),
                            last_used_at = $3,
                            updated_at = $3
                        WHERE tenant_id = $1 AND token_hash = $2
                        RETURNING *
                        """,
                        tenant_id,
                        digest,
                        now,
                    )
        return verified_referral_claim(_row_to_dict(row)) if row else None


def reset_verified_referral_links_for_tests() -> None:
    """Clear only the local fallback; never mutates the database."""

    _LOCAL_VERIFIED_REFERRAL_LINKS.clear()
    _LOCAL_VERIFIED_REFERRAL_LINK_USES.clear()
