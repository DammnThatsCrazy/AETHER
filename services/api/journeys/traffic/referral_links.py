"""Durable verified referral-link repository.

Verified links are an evidence source for the existing canonical touchpoint
pipeline.  They are not a second referral or attribution system.  The public
token is returned once at creation time; only its SHA-256 digest is persisted.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from repositories.repos import get_pool

from .generated_registry import (
    CHANNEL_FAMILIES,
    ECONOMIC_CLASSES,
    SOURCE_CLASSES,
    SOURCE_CLASS_DEFAULTS,
    canonical_source_class,
)


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
_HANDOFF_TTL = timedelta(minutes=15)
_MAX_DESTINATION_URL_LENGTH = 2048
# Placement metadata is an allowlist: arbitrary client-supplied keys never
# reach persistence, so the link record cannot become a free-form side channel.
_METADATA_ALLOWED_KEYS = frozenset({"label", "owner", "surface", "notes"})
_METADATA_VALUE_MAX_LENGTH = 500
_LOCAL_VERIFIED_REFERRAL_LINKS: dict[str, dict[str, Any]] = {}
_LOCAL_VERIFIED_REFERRAL_LINK_USES: set[tuple[str, str, str]] = set()
# use_id -> immutable link-use record (local in-memory fallback).
_LOCAL_LINK_USE_RECORDS: dict[str, dict[str, Any]] = {}
# handoff_hash -> handoff record (local in-memory fallback).
_LOCAL_SOURCE_LINK_HANDOFFS: dict[str, dict[str, Any]] = {}


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


def _clean_destination_url(value: Optional[str]) -> Optional[str]:
    """Validate a link-owned destination URL.

    The redirect endpoint only ever sends visitors here — never to a
    request-supplied URL — so this is the single open-redirect control point.
    """

    cleaned = _clean(value)
    if cleaned is None:
        return None
    if len(cleaned) > _MAX_DESTINATION_URL_LENGTH:
        raise ValueError("destination_url is too long")
    try:
        parsed = urlsplit(cleaned)
    except ValueError as exc:
        raise ValueError("destination_url must be a valid absolute URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("destination_url must be an absolute http(s) URL")
    return cleaned


def _clean_metadata(value: Optional[dict[str, Any]]) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key in sorted(value):
        if key not in _METADATA_ALLOWED_KEYS:
            continue
        item = _clean(value.get(key))
        if item is not None:
            cleaned[key] = item[:_METADATA_VALUE_MAX_LENGTH]
    return cleaned


def _validate_vocabulary(
    *,
    source_class: Optional[str],
    channel_family: Optional[str],
    economic_class: Optional[str],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Validate placement enums against the generated canonical registry."""

    if source_class is not None:
        source_class = canonical_source_class(source_class)
        if source_class not in SOURCE_CLASSES:
            raise ValueError(f"unsupported source_class: {source_class}")
        defaults = SOURCE_CLASS_DEFAULTS.get(source_class, {})
        channel_family = channel_family or defaults.get("channelFamily")
        economic_class = economic_class or defaults.get("economicClass")
    if channel_family is not None and channel_family not in CHANNEL_FAMILIES:
        raise ValueError(f"unsupported channel_family: {channel_family}")
    if economic_class is not None and economic_class not in ECONOMIC_CLASSES:
        raise ValueError(f"unsupported economic_class: {economic_class}")
    return source_class, channel_family, economic_class


def _classify_redirect_user_agent(user_agent: str) -> tuple[str, bool]:
    """Return (ua_class, is_machine) using the shared machine-UA table."""

    ua = (user_agent or "").lower()
    if not ua:
        return "unknown", False
    from .classifier import SourceClassifier

    for signature, mediation, _provider, _product in SourceClassifier.MACHINE_USER_AGENTS:
        if signature in ua:
            return mediation, True
    return "browser", False


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
        "source",
        "medium",
        "channel_family",
        "economic_class",
        "source_class",
        "destination_url",
        "valid_from",
        "environment",
        "max_uses",
        "metadata",
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


def verified_referral_claim(
    record: dict[str, Any],
    *,
    entry_method: str = "verified_source_link",
    proof_level: str = "cryptographic",
) -> dict[str, Any]:
    """Build the strict server-side claim consumed by SourceClassifier.

    The shape is ADDITIVE over the Phase-1 claim: every historical key keeps
    its meaning, and canonical placement vocabulary (source_class /
    channel_family / economic_class / medium / entry_method / proof_level) is
    layered on top for links that declare it.
    """

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
    claim = {
        "verified_referral_link_id": str(record["verified_referral_link_id"]),
        "placement_id": record.get("placement_id"),
        "agent_id": record.get("agent_id"),
        "campaign_id": record.get("campaign_id"),
        "ai_provider": provider,
        "ai_product": product,
        "referral_mediation_type": mediation,
        "actor_type": actor_type,
        "journey_role": journey_role,
        "source": record.get("source") or provider or product or "verified_referral",
        "entry_method": entry_method,
        "proof_level": proof_level,
    }
    for field in ("medium", "channel_family", "economic_class", "source_class"):
        if record.get(field):
            claim[field] = record[field]
    return claim


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
        source: Optional[str] = None,
        medium: Optional[str] = None,
        channel_family: Optional[str] = None,
        economic_class: Optional[str] = None,
        source_class: Optional[str] = None,
        destination_url: Optional[str] = None,
        valid_from: Optional[datetime] = None,
        environment: Optional[str] = None,
        max_uses: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> tuple[dict[str, Any], str]:
        tenant_id = str(tenant_id).strip()
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if referral_mediation_type not in ALLOWED_REFERRAL_MEDIATION_TYPES:
            raise ValueError(
                f"unsupported referral_mediation_type: {referral_mediation_type}"
            )

        expires_at = _as_utc(expires_at)
        valid_from = _as_utc(valid_from)
        now = _now()
        if expires_at is not None and expires_at <= now:
            raise ValueError("expires_at must be in the future")
        if (
            valid_from is not None
            and expires_at is not None
            and valid_from >= expires_at
        ):
            raise ValueError("valid_from must precede expires_at")
        if max_uses is not None:
            max_uses = int(max_uses)
            if max_uses < 1:
                raise ValueError("max_uses must be a positive integer")

        source_class, channel_family, economic_class = _validate_vocabulary(
            source_class=_clean_ai_dimension(source_class),
            channel_family=_clean_ai_dimension(channel_family),
            economic_class=_clean_ai_dimension(economic_class),
        )
        destination_url = _clean_destination_url(destination_url)

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
            "source": _clean_ai_dimension(source),
            "medium": _clean_ai_dimension(medium),
            "channel_family": channel_family,
            "economic_class": economic_class,
            "source_class": source_class,
            "destination_url": destination_url,
            "valid_from": valid_from,
            "environment": _clean_ai_dimension(environment),
            "max_uses": max_uses,
            "metadata": _clean_metadata(metadata),
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
                referral_mediation_type, source, medium, channel_family,
                economic_class, source_class, destination_url, valid_from,
                environment, max_uses, metadata,
                status, expires_at, created_by, created_at, updated_at
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,
                'active',$20,$21,$22,$22
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
            values["source"],
            values["medium"],
            values["channel_family"],
            values["economic_class"],
            values["source_class"],
            values["destination_url"],
            values["valid_from"],
            values["environment"],
            values["max_uses"],
            values["metadata"],
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
                        ) WHERE source_event_id IS NOT NULL DO NOTHING
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

    # ------------------------------------------------------------------
    # Verified source-link redirect + one-time handoff proof flow
    # ------------------------------------------------------------------

    async def resolve_redirect(
        self,
        token: str,
        *,
        environment: Optional[str] = None,
        user_agent: str = "",
    ) -> Optional[dict[str, Any]]:
        """Resolve a public redirect token and record an immutable link use.

        Every invalid condition (unknown token, wrong environment, revoked,
        expired, not-yet-valid, exhausted, missing destination) returns
        ``None`` so the public endpoint stays a uniform 404 with no token
        oracle.  Machine/scanner/link-preview requests are recorded flagged
        ``is_machine`` and never mint a human handoff token.
        """

        if not token or len(token) > _MAX_TOKEN_LENGTH:
            return None
        digest = _token_hash(token)
        now = _now()
        environment = _clean_ai_dimension(environment)
        ua_class, is_machine = _classify_redirect_user_agent(user_agent)

        pool = await _pool()
        if pool is None:
            record = next(
                (
                    candidate
                    for candidate in _LOCAL_VERIFIED_REFERRAL_LINKS.values()
                    if secrets.compare_digest(candidate.get("token_hash", ""), digest)
                ),
                None,
            )
            if record is None or not self._redirect_eligible(record, now, environment):
                return None
            return self._record_redirect_use_local(
                record, now, ua_class=ua_class, is_machine=is_machine,
                environment=environment,
            )

        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT * FROM verified_referral_links
                    WHERE token_hash = $1
                      AND status = 'active' AND revoked_at IS NULL
                      AND destination_url IS NOT NULL
                      AND (expires_at IS NULL OR expires_at > $2)
                      AND (valid_from IS NULL OR valid_from <= $2)
                    FOR UPDATE
                    """,
                    digest,
                    now,
                )
                if row is None:
                    return None
                record = _row_to_dict(row)
                if not self._redirect_eligible(record, now, environment):
                    return None
                use_id = uuid4()
                await conn.execute(
                    """
                    INSERT INTO verified_referral_link_uses (
                        use_id, tenant_id, verified_referral_link_id,
                        source_event_id, first_used_at, placement_id, ua_class,
                        is_machine, verification_result, environment,
                        handoff_minted
                    ) VALUES ($1,$2,$3,NULL,$4,$5,$6,$7,'verified',$8,$9)
                    """,
                    use_id,
                    record["tenant_id"],
                    record["verified_referral_link_id"],
                    now,
                    record.get("placement_id"),
                    ua_class,
                    is_machine,
                    environment,
                    not is_machine,
                )
                handoff_token: Optional[str] = None
                if not is_machine:
                    await conn.execute(
                        """
                        UPDATE verified_referral_links
                        SET use_count = use_count + 1,
                            first_used_at = COALESCE(first_used_at, $2),
                            last_used_at = $2, updated_at = $2
                        WHERE verified_referral_link_id = $1
                        """,
                        record["verified_referral_link_id"],
                        now,
                    )
                    handoff_token = secrets.token_urlsafe(_TOKEN_BYTES)
                    await conn.execute(
                        """
                        INSERT INTO source_link_handoffs (
                            handoff_id, tenant_id, handoff_hash, link_id,
                            link_use_id, expires_at, replay_count, created_at,
                            environment
                        ) VALUES ($1,$2,$3,$4,$5,$6,0,$7,$8)
                        """,
                        uuid4(),
                        record["tenant_id"],
                        _token_hash(handoff_token),
                        record["verified_referral_link_id"],
                        use_id,
                        now + _HANDOFF_TTL,
                        now,
                        environment,
                    )
        return {
            "tenant_id": record["tenant_id"],
            "link": public_referral_link(record),
            "use_id": str(use_id),
            "destination_url": record["destination_url"],
            "handoff_token": handoff_token,
            "is_machine": is_machine,
            "ua_class": ua_class,
        }

    @staticmethod
    def _redirect_eligible(
        record: dict[str, Any], now: datetime, environment: Optional[str]
    ) -> bool:
        expires_at = _as_utc(record.get("expires_at"))
        valid_from = _as_utc(record.get("valid_from"))
        link_environment = record.get("environment")
        if record.get("status") != "active" or record.get("revoked_at") is not None:
            return False
        if not record.get("destination_url"):
            return False
        if expires_at is not None and expires_at <= now:
            return False
        if valid_from is not None and valid_from > now:
            return False
        if link_environment and environment and link_environment != environment:
            return False
        max_uses = record.get("max_uses")
        if max_uses is not None and int(record.get("use_count") or 0) >= int(max_uses):
            return False
        return True

    def _record_redirect_use_local(
        self,
        record: dict[str, Any],
        now: datetime,
        *,
        ua_class: str,
        is_machine: bool,
        environment: Optional[str],
    ) -> dict[str, Any]:
        use_id = str(uuid4())
        _LOCAL_LINK_USE_RECORDS[use_id] = {
            "use_id": use_id,
            "tenant_id": record["tenant_id"],
            "verified_referral_link_id": str(record["verified_referral_link_id"]),
            "source_event_id": None,
            "first_used_at": now,
            "placement_id": record.get("placement_id"),
            "ua_class": ua_class,
            "is_machine": is_machine,
            "verification_result": "verified",
            "environment": environment,
            "handoff_minted": not is_machine,
            "correlated_at": None,
        }
        handoff_token: Optional[str] = None
        if not is_machine:
            record["use_count"] = int(record.get("use_count") or 0) + 1
            record["first_used_at"] = record.get("first_used_at") or now
            record["last_used_at"] = now
            record["updated_at"] = now
            handoff_token = secrets.token_urlsafe(_TOKEN_BYTES)
            _LOCAL_SOURCE_LINK_HANDOFFS[_token_hash(handoff_token)] = {
                "handoff_id": str(uuid4()),
                "tenant_id": record["tenant_id"],
                "handoff_hash": _token_hash(handoff_token),
                "link_id": str(record["verified_referral_link_id"]),
                "link_use_id": use_id,
                "expires_at": now + _HANDOFF_TTL,
                "consumed_at": None,
                "consumed_source_event_id": None,
                "replay_count": 0,
                "created_at": now,
                "environment": environment,
            }
        return {
            "tenant_id": record["tenant_id"],
            "link": public_referral_link(record),
            "use_id": use_id,
            "destination_url": record["destination_url"],
            "handoff_token": handoff_token,
            "is_machine": is_machine,
            "ua_class": ua_class,
        }

    async def consume_handoff(
        self,
        tenant_id: str,
        token: str,
        *,
        source_event_id: Optional[str] = None,
    ) -> tuple[Optional[dict[str, Any]], str]:
        """Consume a one-time handoff token minted by the redirect endpoint.

        Returns ``(claim, status)`` where status is one of ``consumed``,
        ``replayed``, ``expired``, ``link_inactive``, or ``not_found``.  A
        replay of the SAME source event (durable pipeline replay) is
        idempotent and returns the claim again; a different consumer replaying
        the token is rejected and recorded via ``replay_count``.
        """

        if not token or len(token) > _MAX_TOKEN_LENGTH:
            return None, "not_found"
        return await self.consume_handoff_hash(
            tenant_id, _token_hash(token), source_event_id=source_event_id
        )

    async def consume_handoff_hash(
        self,
        tenant_id: str,
        digest: str,
        *,
        source_event_id: Optional[str] = None,
    ) -> tuple[Optional[dict[str, Any]], str]:
        digest = str(digest or "").lower()
        if not _TOKEN_HASH_RE.fullmatch(digest):
            return None, "not_found"
        now = _now()
        source_event_id = _clean(source_event_id)

        pool = await _pool()
        if pool is None:
            handoff = next(
                (
                    candidate
                    for candidate in _LOCAL_SOURCE_LINK_HANDOFFS.values()
                    if secrets.compare_digest(candidate["handoff_hash"], digest)
                    and candidate.get("tenant_id") == tenant_id
                ),
                None,
            )
            if handoff is None:
                return None, "not_found"
            link = _LOCAL_VERIFIED_REFERRAL_LINKS.get(str(handoff["link_id"]))
            if handoff.get("consumed_at") is not None:
                if (
                    source_event_id
                    and handoff.get("consumed_source_event_id") == source_event_id
                    and link is not None
                ):
                    return self._handoff_claim(link), "consumed"
                handoff["replay_count"] = int(handoff.get("replay_count") or 0) + 1
                return None, "replayed"
            if _as_utc(handoff["expires_at"]) <= now:
                return None, "expired"
            if (
                link is None
                or link.get("status") != "active"
                or link.get("revoked_at") is not None
            ):
                return None, "link_inactive"
            handoff["consumed_at"] = now
            handoff["consumed_source_event_id"] = source_event_id
            use = _LOCAL_LINK_USE_RECORDS.get(str(handoff["link_use_id"]))
            if use is not None:
                use["correlated_at"] = now
            return self._handoff_claim(link), "consumed"

        async with pool.acquire() as conn:
            async with conn.transaction():
                handoff = await conn.fetchrow(
                    """
                    SELECT * FROM source_link_handoffs
                    WHERE tenant_id = $1 AND handoff_hash = $2
                    FOR UPDATE
                    """,
                    tenant_id,
                    digest,
                )
                if handoff is None:
                    return None, "not_found"
                handoff = _row_to_dict(handoff)
                link_row = await conn.fetchrow(
                    """
                    SELECT * FROM verified_referral_links
                    WHERE tenant_id = $1 AND verified_referral_link_id = $2
                      AND status = 'active' AND revoked_at IS NULL
                    """,
                    tenant_id,
                    handoff["link_id"],
                )
                if handoff.get("consumed_at") is not None:
                    if (
                        source_event_id
                        and handoff.get("consumed_source_event_id") == source_event_id
                        and link_row is not None
                    ):
                        return self._handoff_claim(_row_to_dict(link_row)), "consumed"
                    await conn.execute(
                        """
                        UPDATE source_link_handoffs
                        SET replay_count = replay_count + 1
                        WHERE tenant_id = $1 AND handoff_hash = $2
                        """,
                        tenant_id,
                        digest,
                    )
                    return None, "replayed"
                if _as_utc(handoff["expires_at"]) <= now:
                    return None, "expired"
                if link_row is None:
                    return None, "link_inactive"
                await conn.execute(
                    """
                    UPDATE source_link_handoffs
                    SET consumed_at = $3, consumed_source_event_id = $4
                    WHERE tenant_id = $1 AND handoff_hash = $2
                    """,
                    tenant_id,
                    digest,
                    now,
                    source_event_id,
                )
                await conn.execute(
                    """
                    UPDATE verified_referral_link_uses
                    SET correlated_at = $2
                    WHERE use_id = $1 AND correlated_at IS NULL
                    """,
                    handoff["link_use_id"],
                    now,
                )
                return self._handoff_claim(_row_to_dict(link_row)), "consumed"

    @staticmethod
    def _handoff_claim(link: dict[str, Any]) -> dict[str, Any]:
        # The handoff proves the server itself observed the redirect hop; the
        # direct-token path stays "cryptographic" (possession of the signed
        # link secret), the handoff path is "server_observed".
        return verified_referral_claim(
            link, entry_method="verified_source_link", proof_level="server_observed"
        )


def reset_verified_referral_links_for_tests() -> None:
    """Clear only the local fallback; never mutates the database."""

    _LOCAL_VERIFIED_REFERRAL_LINKS.clear()
    _LOCAL_VERIFIED_REFERRAL_LINK_USES.clear()
    _LOCAL_LINK_USE_RECORDS.clear()
    _LOCAL_SOURCE_LINK_HANDOFFS.clear()
