"""Stablecoin wallet identity resolution primitives.

Wallet identity links are tenant-scoped, evidence-backed, and reversible. A wallet
address is never treated as legal identity; unresolved wallets remain visible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping

from repositories.stablecoin_repos import StablecoinIdentityLinkRepository
from shared.common.common import utc_now


@dataclass(frozen=True)
class StablecoinWalletIdentityLink:
    tenant_id: str
    wallet_address: str
    chain_id: str
    entity_id: str
    entity_type: str
    resolution_method: str
    deterministic: bool
    confidence: Decimal
    evidence_id: str
    consent_context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id is required for wallet identity links")
        if not self.wallet_address:
            raise ValueError("wallet_address is required for wallet identity links")
        if not self.chain_id:
            raise ValueError("chain_id is required for wallet identity links")
        if not self.entity_id:
            raise ValueError("entity_id is required for wallet identity links")
        if self.confidence < 0 or self.confidence > 1:
            raise ValueError("identity confidence must be between 0 and 1")
        if not self.evidence_id:
            raise ValueError("evidence_id is required for wallet identity links")


class StablecoinIdentityResolver:
    def __init__(self, repo: StablecoinIdentityLinkRepository | None = None) -> None:
        self.repo = repo or StablecoinIdentityLinkRepository()

    @staticmethod
    def normalize_wallet(wallet_address: str) -> str:
        return wallet_address.lower().strip()

    async def link_wallet(self, link: StablecoinWalletIdentityLink) -> dict[str, Any]:
        wallet = self.normalize_wallet(link.wallet_address)
        link_id = f"stablecoin_identity:{link.tenant_id}:{link.chain_id}:{wallet}:{link.entity_id}"
        now = utc_now().isoformat()
        existing = await self.repo.find_by_id(link_id)
        history = list(existing.get("history", [])) if existing else []
        history.append({"at": now, "resolution_method": link.resolution_method, "evidence_id": link.evidence_id})
        record = {
            "link_id": link_id,
            "tenant_id": link.tenant_id,
            "wallet_address": wallet,
            "chain_id": link.chain_id,
            "entity_id": link.entity_id,
            "entity_type": link.entity_type,
            "resolution_method": link.resolution_method,
            "deterministic": link.deterministic,
            "confidence": str(link.confidence),
            "evidence_id": link.evidence_id,
            "consent_context": dict(link.consent_context),
            "history": history,
            "last_seen_at": now,
        }
        return await self.repo.update(link_id, record) if existing else await self.repo.insert(link_id, {**record, "first_seen_at": now})

    async def resolve_wallet(self, *, tenant_id: str, chain_id: str, wallet_address: str) -> dict[str, Any]:
        if not tenant_id:
            raise ValueError("tenant_id is required for wallet resolution")
        wallet = self.normalize_wallet(wallet_address)
        rows = await self.repo.find_many(filters={"tenant_id": tenant_id, "chain_id": chain_id, "wallet_address": wallet}, limit=10)
        if not rows:
            return {
                "tenant_id": tenant_id,
                "wallet_address": wallet,
                "chain_id": chain_id,
                "entity_id": "unknown",
                "entity_type": "unknown",
                "confidence": "0",
                "resolution_state": "unresolved",
            }
        rows.sort(key=lambda r: Decimal(str(r.get("confidence", "0"))), reverse=True)
        return {**rows[0], "resolution_state": "resolved"}
