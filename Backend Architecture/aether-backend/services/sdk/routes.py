"""
Aether Service — SDK Utilities
Endpoints consumed directly by the Aether SDK clients (Web, iOS, Android).
Not exposed publicly — requires a valid SDK API key.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, utc_now
from shared.cache.cache import CacheClient, TTL
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger
from dependencies.providers import get_cache, get_producer
from repositories.repos import IdentityClusterRepository

logger = get_logger("aether.service.sdk")
router = APIRouter(prefix="/sdk", tags=["SDK"])


# ── Models ────────────────────────────────────────────────────────────

class WalletRef(BaseModel):
    address: str = Field(..., description="Wallet address (any VM)")
    vm: str = Field(default="evm", description="VM type: evm, svm, btc, move, near, tron, cosmos")


class IdentityResolveRequest(BaseModel):
    wallets: list[WalletRef] = Field(..., min_length=1, max_length=20)
    anonymous_id: str = Field(..., description="The calling device's current anonymousId")
    device_fingerprint: Optional[str] = Field(None, description="Device fingerprint hash (optional)")


class ResolvedIdentity(BaseModel):
    anonymous_id: str
    user_id: Optional[str] = None
    wallet_addresses: list[str] = Field(default_factory=list)
    resolved_at: str


class IdentityResolveResponse(BaseModel):
    resolved: bool
    identity: Optional[ResolvedIdentity] = None


# ── Dependency ────────────────────────────────────────────────────────

_cluster_repo: Optional[IdentityClusterRepository] = None


def _get_cluster_repo() -> IdentityClusterRepository:
    global _cluster_repo
    if _cluster_repo is None:
        _cluster_repo = IdentityClusterRepository()
    return _cluster_repo


# ── Cache helpers ─────────────────────────────────────────────────────

def _wallet_cache_key(tenant_id: str, normalized_address: str) -> str:
    return f"aether:sdk:wallet_resolve:{tenant_id}:{normalized_address}"


# ── Routes ────────────────────────────────────────────────────────────

@router.post("/identity/resolve", response_model=IdentityResolveResponse)
async def resolve_identity(
    body: IdentityResolveRequest,
    request: Request,
    cache: CacheClient = Depends(get_cache),
    producer: EventProducer = Depends(get_producer),
    cluster_repo: IdentityClusterRepository = Depends(_get_cluster_repo),
):
    """
    Cross-device identity resolution via wallet address.

    Called by SDK clients on init (if wallets are already linked) and on every
    wallet connect event. The backend looks up whether any of the provided wallet
    addresses have been seen before on a different device/anonymousId.

    Flow:
      resolved=false → wallet is new; backend links it to the calling anonymousId
                       for future cross-device lookups.
      resolved=true  → wallet was seen on a prior device; the response carries
                       the original anonymousId (and userId if known) so the SDK
                       can merge the sessions via hydrateIdentity().

    Idempotent: calling with the same (anonymousId, wallet) pair multiple times
    is safe and returns resolved=false after the first call.
    """
    tenant = request.state.tenant
    tenant_id: str = tenant.tenant_id
    caller_anon_id: str = body.anonymous_id.strip()

    if not caller_anon_id:
        raise BadRequestError("anonymous_id is required")

    for wallet_ref in body.wallets:
        normalized = _normalize_address(wallet_ref.address, wallet_ref.vm)
        if not normalized:
            continue

        cache_key = _wallet_cache_key(tenant_id, normalized)

        # ── 1. Cache hit ──────────────────────────────────────────────
        cached = await cache.get_json(cache_key)
        if cached and cached.get("entity_id") and cached["entity_id"] != caller_anon_id:
            prior_anon_id = cached["entity_id"]
            all_wallets = await _get_all_wallets_for_entity(cluster_repo, prior_anon_id)
            await _link_alias(cluster_repo, tenant_id, caller_anon_id, normalized, wallet_ref.vm)
            await _emit_resolved(producer, tenant_id, caller_anon_id, prior_anon_id, normalized)
            logger.info(
                f"[sdk/resolve] wallet={normalized[:10]}… matched prior anon={prior_anon_id[:8]}… "
                f"caller={caller_anon_id[:8]}… (cache hit)"
            )
            return IdentityResolveResponse(
                resolved=True,
                identity=ResolvedIdentity(
                    anonymous_id=prior_anon_id,
                    user_id=cached.get("user_id"),
                    wallet_addresses=all_wallets,
                    resolved_at=utc_now().isoformat(),
                ),
            )

        # ── 2. DB lookup ──────────────────────────────────────────────
        existing = await cluster_repo.find_many(
            filters={
                "tenant_id": tenant_id,
                "identifier_type": "wallet",
                "identifier_value": normalized,
            },
            limit=1,
        )
        # Filter to active (non-unlinked) records
        existing = [r for r in existing if not r.get("unlinked_at")]

        if existing and existing[0]["entity_id"] != caller_anon_id:
            prior_record = existing[0]
            prior_anon_id = prior_record["entity_id"]
            user_id: Optional[str] = prior_record.get("user_id")

            # Warm cache with this wallet → entity mapping
            await cache.set_json(
                cache_key,
                {"entity_id": prior_anon_id, "user_id": user_id},
                TTL.DAY,
            )

            all_wallets = await _get_all_wallets_for_entity(cluster_repo, prior_anon_id)

            # Link the calling anonymousId as an alias so Device B's session
            # is connected to this wallet in the graph.
            await _link_alias(cluster_repo, tenant_id, caller_anon_id, normalized, wallet_ref.vm)
            await _emit_resolved(producer, tenant_id, caller_anon_id, prior_anon_id, normalized)

            logger.info(
                f"[sdk/resolve] wallet={normalized[:10]}… matched prior anon={prior_anon_id[:8]}… "
                f"caller={caller_anon_id[:8]}… (db hit)"
            )
            return IdentityResolveResponse(
                resolved=True,
                identity=ResolvedIdentity(
                    anonymous_id=prior_anon_id,
                    user_id=user_id,
                    wallet_addresses=all_wallets,
                    resolved_at=utc_now().isoformat(),
                ),
            )

        # ── 3. First time seeing this wallet — link it ─────────────────
        if not existing:
            cluster_id = str(uuid.uuid4())
            await cluster_repo.link(
                cluster_id=cluster_id,
                entity_id=caller_anon_id,
                tenant_id=tenant_id,
                identifier_type="wallet",
                identifier_value=normalized,
                confidence=1.0,
                provenance={"vm": wallet_ref.vm, "raw_address": wallet_ref.address},
            )
            await cache.set_json(
                cache_key,
                {"entity_id": caller_anon_id, "user_id": None},
                TTL.DAY,
            )
            logger.info(
                f"[sdk/resolve] wallet={normalized[:10]}… linked to anon={caller_anon_id[:8]}… (new)"
            )

    # No wallet matched a prior identity
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
) -> list[str]:
    """Return all active wallet addresses linked to an entity."""
    records = await repo.list_for_entity(entity_id)
    return [
        r["identifier_value"]
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
    # Check if this exact (caller_anon_id, wallet) pair is already recorded
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
            confidence=0.9,  # secondary linkage — slightly lower confidence
            provenance={"vm": vm, "role": "alias"},
        )


async def _emit_resolved(
    producer: EventProducer,
    tenant_id: str,
    caller_anon_id: str,
    prior_anon_id: str,
    wallet_address: str,
) -> None:
    """Emit IDENTITY_RESOLVED so downstream services can stitch sessions."""
    await producer.publish(Event(
        topic=Topic.IDENTITY_RESOLVED,
        tenant_id=tenant_id,
        source_service="sdk",
        payload={
            "resolution_type": "wallet",
            "wallet_address": wallet_address,
            "prior_anonymous_id": prior_anon_id,
            "current_anonymous_id": caller_anon_id,
            "resolved_at": utc_now().isoformat(),
        },
    ))
