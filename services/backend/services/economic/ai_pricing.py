"""Effective-dated AI price card registry.

Cards live in the durable ``ai_price_cards`` store. Platform default cards are
stored under ``tenant_id=""``; tenants may add their own cards which take
precedence over platform cards at equal specificity. Card selection is
effective-dated (``effective_from <= at < effective_to``, open-ended when
``effective_to`` is null) and most-specific-match-wins:

    provider+model+region+service_tier
  > provider+model+region
  > provider+model
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger
from shared.store import get_store

from services.economic.ai_models import AIPriceCard

logger = get_logger("aether.economic.ai_pricing")

PRICE_CARD_STORE = "ai_price_cards"
PLATFORM_TENANT_ID = ""

SEED_PRICING_VERSION = "seed-2026-07"
SEED_EFFECTIVE_FROM = "2026-07-01T00:00:00+00:00"

# Platform default seed cards (USD, per-1k token rates).
SEED_CARDS: tuple[dict[str, Any], ...] = (
    {
        "id": "seed-anthropic-claude-haiku-4-5",
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "currency": "USD",
        "pricing_version": SEED_PRICING_VERSION,
        "rates": {
            "input_tokens_per_1k": 0.001,
            "output_tokens_per_1k": 0.005,
            "cached_input_tokens_per_1k": 0.0001,
        },
        "effective_from": SEED_EFFECTIVE_FROM,
        "source": "seed",
        "created_at": SEED_EFFECTIVE_FROM,
    },
    {
        "id": "seed-openai-gpt-4o-mini",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "currency": "USD",
        "pricing_version": SEED_PRICING_VERSION,
        "rates": {
            "input_tokens_per_1k": 0.00015,
            "output_tokens_per_1k": 0.0006,
            "cached_input_tokens_per_1k": 0.000075,
        },
        "effective_from": SEED_EFFECTIVE_FROM,
        "source": "seed",
        "created_at": SEED_EFFECTIVE_FROM,
    },
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp; naive values are treated as UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _card_key(tenant_id: str, card_id: str) -> str:
    return f"{tenant_id}:{card_id}"


class AIPriceCardRegistry:
    """Durable, effective-dated price card registry."""

    def __init__(self) -> None:
        self._store = get_store(PRICE_CARD_STORE)

    async def add_card(
        self, card: AIPriceCard | dict[str, Any], tenant_id: str = PLATFORM_TENANT_ID
    ) -> AIPriceCard:
        """Validate and persist a price card (platform when tenant_id == "")."""
        if isinstance(card, dict):
            payload = dict(card)
            payload.setdefault("id", f"pc-{uuid.uuid4().hex[:12]}")
            payload.setdefault("created_at", utc_now_iso())
            validated = AIPriceCard.model_validate(payload)
        else:
            validated = card
        record = validated.model_dump(mode="json")
        record["tenant_id"] = tenant_id
        await self._store.set(_card_key(tenant_id, validated.id), record)
        return validated

    async def get_card(
        self, card_id: str, tenant_id: str = PLATFORM_TENANT_ID
    ) -> Optional[AIPriceCard]:
        record = await self._store.get(_card_key(tenant_id, card_id))
        if record is None:
            return None
        return AIPriceCard.model_validate({k: v for k, v in record.items() if k != "tenant_id"})

    async def list_cards(
        self,
        tenant_id: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        include_platform: bool = True,
    ) -> list[dict[str, Any]]:
        """List card records (dicts including ``tenant_id``) with optional filters."""
        records = await self._store.find()
        out: list[dict[str, Any]] = []
        for record in records:
            record_tenant = record.get("tenant_id", PLATFORM_TENANT_ID)
            if tenant_id is not None:
                if record_tenant != tenant_id and not (
                    include_platform and record_tenant == PLATFORM_TENANT_ID
                ):
                    continue
            if provider is not None and record.get("provider") != provider:
                continue
            if model is not None and record.get("model") != model:
                continue
            out.append(record)
        out.sort(key=lambda r: (r.get("provider", ""), r.get("model", ""), r.get("effective_from", "")))
        return out

    async def get_active_card(
        self,
        provider: str,
        model: str,
        region: Optional[str] = None,
        service_tier: Optional[str] = None,
        at: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Optional[AIPriceCard]:
        """Select the effective card for provider/model at ``at`` (default: now).

        Cards whose region/service_tier are set but do not match the request are
        excluded. Among matches, the most specific card wins (region+tier >
        region > base); tenant cards beat platform cards at equal specificity;
        remaining ties resolve to the latest ``effective_from``.
        """
        at_ts = _parse_ts(at) if at else datetime.now(timezone.utc)
        # No tenant context → platform default cards only (never another tenant's).
        scope = tenant_id if tenant_id is not None else PLATFORM_TENANT_ID
        candidates = await self.list_cards(tenant_id=scope, provider=provider, model=model)

        best: tuple[int, int, datetime] | None = None
        best_card: Optional[AIPriceCard] = None
        for record in candidates:
            card_region = record.get("region")
            card_tier = record.get("service_tier")
            if card_region is not None and card_region != region:
                continue
            if card_tier is not None and card_tier != service_tier:
                continue
            try:
                effective_from = _parse_ts(record["effective_from"])
            except (KeyError, ValueError):
                continue
            if effective_from > at_ts:
                continue
            effective_to = record.get("effective_to")
            if effective_to is not None and _parse_ts(effective_to) <= at_ts:
                continue

            specificity = (2 if card_region is not None else 0) + (1 if card_tier is not None else 0)
            tenant_rank = 1 if record.get("tenant_id", PLATFORM_TENANT_ID) != PLATFORM_TENANT_ID else 0
            rank = (specificity, tenant_rank, effective_from)
            if best is None or rank > best:
                try:
                    best_card = AIPriceCard.model_validate(
                        {k: v for k, v in record.items() if k != "tenant_id"}
                    )
                except ValueError:
                    continue
                best = rank
        return best_card

    async def ensure_seed_cards(self) -> int:
        """Idempotently install the platform default price cards.

        Returns the number of cards written on this call (0 when already seeded).
        """
        written = 0
        for seed in SEED_CARDS:
            key = _card_key(PLATFORM_TENANT_ID, seed["id"])
            if await self._store.get(key) is not None:
                continue
            await self.add_card(dict(seed), tenant_id=PLATFORM_TENANT_ID)
            written += 1
        if written:
            logger.info("ai_pricing seeded %d platform default price cards", written)
        return written


_registry: AIPriceCardRegistry | None = None


def get_price_card_registry() -> AIPriceCardRegistry:
    global _registry
    if _registry is None:
        _registry = AIPriceCardRegistry()
    return _registry
