"""
Aether Service — SDK Utilities
Endpoints consumed directly by the Aether SDK clients (Web, iOS, Android).
Not exposed publicly — requires a valid SDK API key.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, utc_now
from shared.cache.cache import CacheClient, TTL
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger
from dependencies.providers import get_cache, get_producer
from repositories.repos import IdentityClusterRepository, BaseRepository

logger = get_logger("aether.service.sdk")
router = APIRouter(prefix="/sdk", tags=["SDK"])


# ── Models ────────────────────────────────────────────────────────────

class WalletRef(BaseModel):
    address: str = Field(..., description="Wallet address (any VM)")
    vm: str = Field(default="evm", description="VM type: evm, svm, btc, move, near, tron, cosmos")


class FingerprintSignals(BaseModel):
    canvas_hash: Optional[str] = None
    webgl_renderer: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None


class IdentityResolveRequest(BaseModel):
    wallets: list[WalletRef] = Field(default_factory=list, max_length=20)
    anonymous_id: str = Field(..., description="The calling device's current anonymousId")
    device_fingerprint: Optional[str] = Field(None, description="Device fingerprint hash")
    fingerprint_signals: Optional[FingerprintSignals] = None
    user_id: Optional[str] = None
    email_hash: Optional[str] = None
    platform: Optional[str] = None


class ResolvedIdentity(BaseModel):
    anonymous_id: str
    user_id: Optional[str] = None
    wallet_addresses: list[str] = Field(default_factory=list)
    wallet_refs: list[dict] = Field(default_factory=list)
    resolved_at: str


class IdentityResolveResponse(BaseModel):
    resolved: bool
    identity: Optional[ResolvedIdentity] = None


# ── Dependencies ──────────────────────────────────────────────────────

_cluster_repo: Optional[IdentityClusterRepository] = None
_session_repo: Optional[BaseRepository] = None


def _get_cluster_repo() -> IdentityClusterRepository:
    global _cluster_repo
    if _cluster_repo is None:
        _cluster_repo = IdentityClusterRepository()
    return _cluster_repo


def _get_session_repo() -> BaseRepository:
    global _session_repo
    if _session_repo is None:
        _session_repo = BaseRepository("device_sessions")
    return _session_repo


# ── Cache helpers ─────────────────────────────────────────────────────

def _wallet_cache_key(tenant_id: str, normalized_address: str) -> str:
    return f"aether:sdk:wallet_resolve:{tenant_id}:{normalized_address}"


# ── Fingerprint helpers ───────────────────────────────────────────────

def _hash_ip_subnet(ip: str) -> str:
    parts = ip.split(".")
    subnet = ".".join(parts[:3]) + ".0/24" if len(parts) == 4 else ip
    return hashlib.sha256(subnet.encode()).hexdigest()[:16]


def _cutoff_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ── Routes ────────────────────────────────────────────────────────────

@router.post("/identity/resolve", response_model=IdentityResolveResponse)
async def resolve_identity(
    body: IdentityResolveRequest,
    request: Request,
    cache: CacheClient = Depends(get_cache),
    producer: EventProducer = Depends(get_producer),
    cluster_repo: IdentityClusterRepository = Depends(_get_cluster_repo),
    session_repo: BaseRepository = Depends(_get_session_repo),
):
    """
    Cross-device identity resolution.

    Tries four anchors in priority order:
      1. userId       — authenticated Web2 + Web3 users
      2. wallet       — Web3 users (existing behaviour, unchanged)
      3. email hash   — pre-auth Web2 users (SHA-256 of email, never raw)
      4. fingerprint  — all anonymous users; deterministic on mobile,
                        high-confidence rule-scored on web

    On a match the response carries the prior anonymousId so the SDK fires
    onJourneyResumed. All paths emit IDENTITY_RESOLVED.
    """
    tenant = request.state.tenant
    tenant_id: str = tenant.tenant_id
    caller_anon_id: str = body.anonymous_id.strip()

    if not caller_anon_id:
        raise BadRequestError("anonymous_id is required")

    # ── Priority 1: userId ─────────────────────────────────────────────
    if body.user_id:
        uid = body.user_id.strip()
        if uid:
            prior = [
                r for r in await cluster_repo.find_many(
                    filters={"tenant_id": tenant_id, "identifier_type": "user_id", "identifier_value": uid},
                    limit=1,
                )
                if not r.get("unlinked_at")
            ]
            # Store this userId→anonymousId mapping idempotently
            existing_uid = [
                r for r in await cluster_repo.find_many(
                    filters={"tenant_id": tenant_id, "identifier_type": "user_id",
                              "identifier_value": uid, "entity_id": caller_anon_id},
                    limit=1,
                )
                if not r.get("unlinked_at")
            ]
            if not existing_uid:
                await cluster_repo.link(
                    cluster_id=str(uuid.uuid4()),
                    entity_id=caller_anon_id,
                    tenant_id=tenant_id,
                    identifier_type="user_id",
                    identifier_value=uid,
                    confidence=1.0,
                    provenance={"platform": body.platform or "unknown"},
                )
            if prior and prior[0]["entity_id"] != caller_anon_id:
                prior_anon_id = prior[0]["entity_id"]
                wallets = await _get_all_wallets_for_entity(cluster_repo, prior_anon_id)
                await _emit_resolved(producer, tenant_id, caller_anon_id, prior_anon_id, "user_id")
                logger.info(
                    f"[sdk/resolve] user_id={uid[:8]}… matched prior anon={prior_anon_id[:8]}… "
                    f"caller={caller_anon_id[:8]}…"
                )
                return IdentityResolveResponse(
                    resolved=True,
                    identity=ResolvedIdentity(
                        anonymous_id=prior_anon_id,
                        user_id=uid,
                        wallet_addresses=[w["address"] for w in wallets],
                        wallet_refs=wallets,
                        resolved_at=utc_now().isoformat(),
                    ),
                )

    # ── Priority 2: wallet ─────────────────────────────────────────────
    for wallet_ref in body.wallets:
        normalized = _normalize_address(wallet_ref.address, wallet_ref.vm)
        if not normalized:
            continue

        cache_key = _wallet_cache_key(tenant_id, normalized)

        # Cache hit
        cached = await cache.get_json(cache_key)
        if cached and cached.get("entity_id") and cached["entity_id"] != caller_anon_id:
            prior_anon_id = cached["entity_id"]
            all_wallets = await _get_all_wallets_for_entity(cluster_repo, prior_anon_id)
            await _link_alias(cluster_repo, tenant_id, caller_anon_id, normalized, wallet_ref.vm)
            await _emit_resolved(producer, tenant_id, caller_anon_id, prior_anon_id, "wallet", normalized)
            logger.info(
                f"[sdk/resolve] wallet={normalized[:10]}… matched prior anon={prior_anon_id[:8]}… "
                f"caller={caller_anon_id[:8]}… (cache hit)"
            )
            return IdentityResolveResponse(
                resolved=True,
                identity=ResolvedIdentity(
                    anonymous_id=prior_anon_id,
                    user_id=cached.get("user_id"),
                    wallet_addresses=[w["address"] for w in all_wallets],
                    wallet_refs=all_wallets,
                    resolved_at=utc_now().isoformat(),
                ),
            )

        # DB lookup
        existing = [
            r for r in await cluster_repo.find_many(
                filters={"tenant_id": tenant_id, "identifier_type": "wallet", "identifier_value": normalized},
                limit=1,
            )
            if not r.get("unlinked_at")
        ]

        if existing and existing[0]["entity_id"] != caller_anon_id:
            prior_record = existing[0]
            prior_anon_id = prior_record["entity_id"]
            user_id = prior_record.get("user_id")
            await cache.set_json(cache_key, {"entity_id": prior_anon_id, "user_id": user_id}, TTL.DAY)
            all_wallets = await _get_all_wallets_for_entity(cluster_repo, prior_anon_id)
            await _link_alias(cluster_repo, tenant_id, caller_anon_id, normalized, wallet_ref.vm)
            await _emit_resolved(producer, tenant_id, caller_anon_id, prior_anon_id, "wallet", normalized)
            logger.info(
                f"[sdk/resolve] wallet={normalized[:10]}… matched prior anon={prior_anon_id[:8]}… "
                f"caller={caller_anon_id[:8]}… (db hit)"
            )
            return IdentityResolveResponse(
                resolved=True,
                identity=ResolvedIdentity(
                    anonymous_id=prior_anon_id,
                    user_id=user_id,
                    wallet_addresses=[w["address"] for w in all_wallets],
                    wallet_refs=all_wallets,
                    resolved_at=utc_now().isoformat(),
                ),
            )

        # First time seeing this wallet — link it
        if not existing:
            await cluster_repo.link(
                cluster_id=str(uuid.uuid4()),
                entity_id=caller_anon_id,
                tenant_id=tenant_id,
                identifier_type="wallet",
                identifier_value=normalized,
                confidence=1.0,
                provenance={"vm": wallet_ref.vm, "raw_address": wallet_ref.address},
            )
            await cache.set_json(cache_key, {"entity_id": caller_anon_id, "user_id": None}, TTL.DAY)
            logger.info(f"[sdk/resolve] wallet={normalized[:10]}… linked to anon={caller_anon_id[:8]}… (new)")

    # ── Priority 3: email hash ─────────────────────────────────────────
    if body.email_hash:
        eh = body.email_hash.strip().lower()
        if eh and re.fullmatch(r'[0-9a-f]{64}', eh):
            prior = [
                r for r in await cluster_repo.find_many(
                    filters={"tenant_id": tenant_id, "identifier_type": "email", "identifier_value": eh},
                    limit=1,
                )
                if not r.get("unlinked_at")
            ]
            # Store this email→anonymousId mapping idempotently
            existing_em = [
                r for r in await cluster_repo.find_many(
                    filters={"tenant_id": tenant_id, "identifier_type": "email",
                              "identifier_value": eh, "entity_id": caller_anon_id},
                    limit=1,
                )
                if not r.get("unlinked_at")
            ]
            if not existing_em:
                await cluster_repo.link(
                    cluster_id=str(uuid.uuid4()),
                    entity_id=caller_anon_id,
                    tenant_id=tenant_id,
                    identifier_type="email",
                    identifier_value=eh,
                    confidence=0.98,
                    provenance={"platform": body.platform or "unknown"},
                )
            if prior and prior[0]["entity_id"] != caller_anon_id:
                prior_anon_id = prior[0]["entity_id"]
                wallets = await _get_all_wallets_for_entity(cluster_repo, prior_anon_id)
                await _emit_resolved(producer, tenant_id, caller_anon_id, prior_anon_id, "email")
                logger.info(
                    f"[sdk/resolve] email_hash matched prior anon={prior_anon_id[:8]}… "
                    f"caller={caller_anon_id[:8]}…"
                )
                return IdentityResolveResponse(
                    resolved=True,
                    identity=ResolvedIdentity(
                        anonymous_id=prior_anon_id,
                        wallet_addresses=[w["address"] for w in wallets],
                        wallet_refs=wallets,
                        resolved_at=utc_now().isoformat(),
                    ),
                )

    # ── Priority 4: device fingerprint ────────────────────────────────
    if body.device_fingerprint:
        fp_hash = body.device_fingerprint.strip()
        if fp_hash:
            ip_subnet = _hash_ip_subnet((request.client.host if request.client else "") or "")
            await session_repo.insert(f"ds:{tenant_id}:{caller_anon_id}", {
                "anonymous_id": caller_anon_id,
                "tenant_id": tenant_id,
                "fingerprint_hash": fp_hash,
                "canvas_hash": body.fingerprint_signals.canvas_hash if body.fingerprint_signals else None,
                "webgl_renderer": body.fingerprint_signals.webgl_renderer if body.fingerprint_signals else None,
                "timezone": body.fingerprint_signals.timezone if body.fingerprint_signals else None,
                "language": body.fingerprint_signals.language if body.fingerprint_signals else None,
                "ip_subnet": ip_subnet,
                "platform": body.platform,
                "last_seen": utc_now().isoformat(),
            })

            cutoff = _cutoff_iso(days=90)
            candidates = [
                c for c in await session_repo.find_many(
                    filters={"fingerprint_hash": fp_hash, "tenant_id": tenant_id},
                    limit=10,
                )
                if c["anonymous_id"] != caller_anon_id and c.get("last_seen", "") >= cutoff
            ]

            sigs = body.fingerprint_signals

            if candidates:
                best = max(candidates, key=lambda r: r.get("last_seen", ""))
                confidence = 0.90

                if sigs and sigs.timezone and best.get("timezone") and sigs.timezone != best["timezone"]:
                    confidence = 0.0  # cross-timezone → reject
                elif sigs and sigs.canvas_hash and best.get("canvas_hash") and sigs.canvas_hash == best["canvas_hash"]:
                    confidence += 0.05

                if ip_subnet and ip_subnet == best.get("ip_subnet"):
                    confidence += 0.03

                if confidence >= 0.85:
                    prior_anon_id = best["anonymous_id"]
                    wallets = await _get_all_wallets_for_entity(cluster_repo, prior_anon_id)
                    await _emit_resolved(producer, tenant_id, caller_anon_id, prior_anon_id, "fingerprint")
                    logger.info(
                        f"[sdk/resolve] fingerprint matched prior anon={prior_anon_id[:8]}… "
                        f"caller={caller_anon_id[:8]}… confidence={confidence:.2f}"
                    )
                    return IdentityResolveResponse(
                        resolved=True,
                        identity=ResolvedIdentity(
                            anonymous_id=prior_anon_id,
                            wallet_addresses=[w["address"] for w in wallets],
                            wallet_refs=wallets,
                            resolved_at=utc_now().isoformat(),
                        ),
                    )

            # Partial match: hash changed (e.g. browser update) but canvas hash still matches.
            # Lower base confidence because we can't verify the full fingerprint hasn't drifted.
            if not candidates and sigs and sigs.canvas_hash:
                partial = [
                    c for c in await session_repo.find_many(
                        filters={"canvas_hash": sigs.canvas_hash, "tenant_id": tenant_id},
                        limit=10,
                    )
                    if c["anonymous_id"] != caller_anon_id
                    and c.get("fingerprint_hash") != fp_hash  # skip exact-hash records
                    and c.get("last_seen", "") >= cutoff
                ]
                if partial:
                    best = max(partial, key=lambda r: r.get("last_seen", ""))
                    confidence = 0.75  # canvas matches but combined hash changed

                    if sigs.timezone and best.get("timezone") and sigs.timezone != best["timezone"]:
                        confidence = 0.0  # cross-timezone → reject
                    else:
                        if sigs.webgl_renderer and sigs.webgl_renderer == best.get("webgl_renderer"):
                            confidence += 0.08  # same GPU: strong signal
                        if sigs.language and sigs.language == best.get("language"):
                            confidence += 0.05
                        if ip_subnet and ip_subnet == best.get("ip_subnet"):
                            confidence += 0.03

                    if confidence >= 0.85:
                        prior_anon_id = best["anonymous_id"]
                        wallets = await _get_all_wallets_for_entity(cluster_repo, prior_anon_id)
                        await _emit_resolved(producer, tenant_id, caller_anon_id, prior_anon_id, "fingerprint")
                        logger.info(
                            f"[sdk/resolve] fingerprint (partial/browser-update) matched "
                            f"prior anon={prior_anon_id[:8]}… caller={caller_anon_id[:8]}… "
                            f"confidence={confidence:.2f}"
                        )
                        return IdentityResolveResponse(
                            resolved=True,
                            identity=ResolvedIdentity(
                                anonymous_id=prior_anon_id,
                                wallet_addresses=[w["address"] for w in wallets],
                                wallet_refs=wallets,
                                resolved_at=utc_now().isoformat(),
                            ),
                        )

    return IdentityResolveResponse(resolved=False)


# ── Helpers ───────────────────────────────────────────────────────────

def _normalize_address(address: str, vm: str) -> Optional[str]:
    """Normalize a wallet address for consistent storage and lookup."""
    address = address.strip()
    if not address:
        return None
    # EVM: lowercase hex
    if vm in ("evm",):
        return address.lower()
    # SVM (Solana), NEAR, Cosmos, Tron: case-sensitive base58/bech32, preserve as-is
    # BTC: preserve (P2PKH, P2SH, bech32 are case-sensitive)
    return address


async def _get_all_wallets_for_entity(
    repo: IdentityClusterRepository, entity_id: str
) -> list[dict]:
    """Return all active wallets linked to an entity as {address, vm} dicts."""
    records = await repo.list_for_entity(entity_id)
    return [
        {
            "address": r["identifier_value"],
            "vm": (r.get("provenance") or {}).get("vm", "evm"),
        }
        for r in records
        if r.get("identifier_type") == "wallet"
    ]


async def _link_alias(
    repo: IdentityClusterRepository,
    tenant_id: str,
    caller_anon_id: str,
    normalized_address: str,
    vm: str,
) -> None:
    """Link the calling anonymousId to this wallet (as an alias / secondary entry)."""
    existing = await repo.find_many(
        filters={
            "tenant_id": tenant_id,
            "identifier_type": "wallet",
            "identifier_value": normalized_address,
            "entity_id": caller_anon_id,
        },
        limit=1,
    )
    if not existing:
        await repo.link(
            cluster_id=str(uuid.uuid4()),
            entity_id=caller_anon_id,
            tenant_id=tenant_id,
            identifier_type="wallet",
            identifier_value=normalized_address,
            confidence=0.9,
            provenance={"vm": vm, "role": "alias"},
        )


async def _emit_resolved(
    producer: EventProducer,
    tenant_id: str,
    caller_anon_id: str,
    prior_anon_id: str,
    resolution_type: str,
    wallet_address: Optional[str] = None,
) -> None:
    """Emit IDENTITY_RESOLVED so downstream services can stitch sessions."""
    payload: dict = {
        "resolution_type": resolution_type,
        "prior_anonymous_id": prior_anon_id,
        "current_anonymous_id": caller_anon_id,
        "resolved_at": utc_now().isoformat(),
    }
    if wallet_address:
        payload["wallet_address"] = wallet_address
    await producer.publish(Event(
        topic=Topic.IDENTITY_RESOLVED,
        tenant_id=tenant_id,
        source_service="sdk",
        payload=payload,
    ))
