"""Multi-venue derivatives normalization capability scaffolds.

Adapters here prove structurally different venues normalize into the same
canonical Bronze/Silver concepts without provider-specific API leakage. They
normalize caller-supplied provider observations only; this module contains no
runtime sample records and performs no provider I/O.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from shared.logger.logger import get_logger, metrics

from services.derivatives.models import (
    BronzeObservation,
    LiquidityRole,
    NormalizedFillFact,
    OrderSide,
    SourceRef,
    decimal_from_provider,
)

logger = get_logger("aether.derivatives.multi_venue")

NORMALIZATION_VERSION = "derivatives-multivenue-normalization-v1"
SUPPORTED_VENUES = ("hyperliquid", "dydx", "gmx", "drift", "centralized_futures")
CANONICAL_CONCEPTS = ("markets", "orders", "fills", "positions", "funding", "fees", "margin", "liquidations", "account_state")


@dataclass(frozen=True)
class VenueCapabilityProfile:
    venue_id: str
    venue_type: str
    supported_concepts: tuple[str, ...]
    missing_concepts: tuple[str, ...]
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue_id": self.venue_id,
            "venue_type": self.venue_type,
            "supported_concepts": list(self.supported_concepts),
            "missing_concepts": list(self.missing_concepts),
            "limitations": list(self.limitations),
            "normalization_version": NORMALIZATION_VERSION,
        }


class VenueNormalizationAdapter:
    """Normalization scaffold for a structurally distinct derivatives source."""

    def __init__(self, venue_id: str, venue_type: str, field_map: Mapping[str, str], capabilities: VenueCapabilityProfile) -> None:
        self.venue_id = venue_id
        self.venue_type = venue_type
        self.field_map = dict(field_map)
        self.capabilities = capabilities

    def bronze(self, tenant_id: str, deployment: str, source_record_id: str, payload: Mapping[str, Any]) -> BronzeObservation:
        observed_at_field = self.field_map["executed_at"]
        if observed_at_field not in payload:
            raise ValueError(f"Provider observation is missing required field '{observed_at_field}'")
        return BronzeObservation(
            tenant_id=tenant_id,
            provider=self.venue_id,
            deployment=deployment,
            record_type="raw_fill",
            source_record_id=source_record_id,
            raw_payload=dict(payload),
            observed_at=str(payload[observed_at_field]),
            idempotency_key=":".join([tenant_id, self.venue_id, deployment, source_record_id]),
        )

    def normalize_fill(self, observation: BronzeObservation) -> NormalizedFillFact:
        payload = observation.raw_payload
        side_value = str(payload[self.field_map["side"]]).lower()
        side = OrderSide.BUY if side_value in {"buy", "b", "long"} else OrderSide.SELL
        role_value = str(payload.get(self.field_map.get("liquidity", "liquidity"), "unknown")).lower()
        role = LiquidityRole.MAKER if role_value == "maker" else LiquidityRole.TAKER if role_value == "taker" else LiquidityRole.UNKNOWN
        account = str(payload[self.field_map["account"]])
        market = str(payload[self.field_map["market"]])
        fill_id = str(payload[self.field_map["fill_id"]])
        return NormalizedFillFact(
            tenant_id=observation.tenant_id,
            provider=self.venue_id,
            deployment=observation.deployment,
            trading_account_id=f"acct_{self.venue_id}_{account}",
            canonical_market_id=f"{self.venue_id}:{observation.deployment}:{market}",
            fill_id=fill_id,
            side=side,
            price=decimal_from_provider(payload[self.field_map["price"]], "price"),
            quantity=decimal_from_provider(payload[self.field_map["quantity"]], "quantity"),
            executed_at=str(payload[self.field_map["executed_at"]]),
            liquidity_role=role,
            fee_amount=decimal_from_provider(payload.get(self.field_map.get("fee", "fee"), "0"), "fee"),
            fee_asset_id=str(payload.get(self.field_map.get("fee_asset", "fee_asset"), "USDC")),
            source_ref=SourceRef(provider=self.venue_id, source_record_id=observation.source_record_id, observed_at=observation.observed_at),
        )


def build_scaffolded_adapters() -> dict[str, VenueNormalizationAdapter]:
    full = tuple(CANONICAL_CONCEPTS)
    return {
        "dydx": VenueNormalizationAdapter(
            "dydx",
            "decentralized_perpetual_exchange",
            {"fill_id": "id", "account": "subaccount", "market": "ticker", "side": "side", "price": "price", "quantity": "size", "fee": "fee", "fee_asset": "feeAsset", "executed_at": "createdAt", "liquidity": "liquidity"},
            VenueCapabilityProfile("dydx", "decentralized_perpetual_exchange", full, ()),
        ),
        "gmx": VenueNormalizationAdapter(
            "gmx",
            "onchain_derivatives_protocol",
            {"fill_id": "eventId", "account": "account", "market": "market", "side": "direction", "price": "executionPrice", "quantity": "sizeUsd", "fee": "feeUsd", "fee_asset": "feeAsset", "executed_at": "blockTime"},
            VenueCapabilityProfile("gmx", "onchain_derivatives_protocol", tuple(c for c in CANONICAL_CONCEPTS if c != "orders"), ("orders",), ("Onchain execution events may not expose centralized order lifecycle states.",)),
        ),
        "drift": VenueNormalizationAdapter(
            "drift",
            "decentralized_perpetual_exchange",
            {"fill_id": "fillId", "account": "authority", "market": "marketName", "side": "direction", "price": "oraclePrice", "quantity": "baseAssetAmount", "fee": "fee", "fee_asset": "feeAsset", "executed_at": "slotTime", "liquidity": "liquidity"},
            VenueCapabilityProfile("drift", "decentralized_perpetual_exchange", full, ()),
        ),
        "centralized_futures": VenueNormalizationAdapter(
            "centralized_futures",
            "centralized_futures_exchange",
            {"fill_id": "tradeId", "account": "accountId", "market": "symbol", "side": "side", "price": "avgPrice", "quantity": "contracts", "fee": "commission", "fee_asset": "commissionAsset", "executed_at": "time", "liquidity": "makerTaker"},
            VenueCapabilityProfile("centralized_futures", "centralized_futures_exchange", full, ()),
        ),
    }


def cross_venue_parity_report(adapters: Mapping[str, VenueNormalizationAdapter]) -> dict[str, Any]:
    venue_reports = {venue_id: adapter.capabilities.to_dict() for venue_id, adapter in adapters.items()}
    missing_by_concept = {
        concept: sorted(venue_id for venue_id, adapter in adapters.items() if concept in adapter.capabilities.missing_concepts)
        for concept in CANONICAL_CONCEPTS
    }
    return {
        "normalization_version": NORMALIZATION_VERSION,
        "canonical_concepts": list(CANONICAL_CONCEPTS),
        "venues": venue_reports,
        "missing_by_concept": missing_by_concept,
        "provider_specific_api_leakage": False,
        "availability": "scaffolded",
        "operational_observations": None,
    }


# ── Supervised venue reconciliation sweep loop ───────────────────────────────
#
# Drives :class:`SupervisedStreamWorker` (services/derivatives/sequence.py) per
# registered venue on an interval for the runtime WorkerSpec: heartbeat,
# per-pass exception isolation, graceful shutdown. Each venue cycle restores the
# durable cursor -> streams -> persists the advanced cursor (at-least-once).

DEFAULT_SWEEP_TENANT = "tenant_local_dev"
DEFAULT_SWEEP_INTERVAL_SECONDS = 300.0


def _supported_venue_ids() -> tuple[str, ...]:
    """Venues currently registered in the derivatives adapters registry."""
    try:
        from services.derivatives.adapters import ADAPTER_REGISTRY

        return tuple(sorted(ADAPTER_REGISTRY))
    except Exception:  # noqa: BLE001 - registry absence must not crash the sweep
        return SUPPORTED_VENUES


async def run_venue_sweep_iteration(
    *,
    tenant_id: str = DEFAULT_SWEEP_TENANT,
    venue_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """One supervised venue sweep pass: restore cursor -> stream -> persist.

    Returns a deterministic summary dict — counters only, never fabricated
    success. Each venue is swept through :class:`SupervisedStreamWorker`, which
    restarts from the last persisted cursor (at-least-once) and persists the
    advanced cursor before returning. A venue whose adapter is unavailable, or
    whose cycle raises, is counted and logged — never allowed to abort the pass.
    """
    from services.derivatives.sequence import SupervisedStreamWorker

    targets = venue_ids if venue_ids is not None else _supported_venue_ids()
    summary: dict[str, Any] = {
        "tenant_id": tenant_id,
        "venues_targeted": len(targets),
        "venues_scanned": 0,
        "completed": 0,
        "skipped": 0,
        "errors": [],
    }

    for venue_id in targets:
        try:
            from services.derivatives.adapters import get_adapter

            adapter = get_adapter(venue_id)
            if adapter is None:
                summary["skipped"] += 1
                continue
            worker = SupervisedStreamWorker(
                adapter, tenant_id=tenant_id, connector_id=venue_id
            )
            result = await worker.run_once()
            summary["venues_scanned"] += 1
            if bool(getattr(result, "completed", False)):
                summary["completed"] += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — one venue must not abort the sweep
            summary["errors"].append(f"{venue_id}:{exc}")

    return summary


async def venue_sweep_loop(
    interval_s: float = DEFAULT_SWEEP_INTERVAL_SECONDS,
) -> None:
    """Supervised derivatives venue reconciliation sweep (heartbeat, isolated)."""
    logger.info("derivatives_venue_sweep_loop started interval=%ss", interval_s)
    while True:
        try:
            summary = await run_venue_sweep_iteration()
            metrics.gauge("derivatives_venue_sweep_heartbeat", 1.0)
            if summary["errors"]:
                logger.warning(
                    "venue sweep pass errors=%d scanned=%d skipped=%d",
                    len(summary["errors"]), summary["venues_scanned"], summary["skipped"],
                )
            elif summary["venues_scanned"]:
                logger.debug(
                    "venue sweep pass scanned=%d completed=%d",
                    summary["venues_scanned"], summary["completed"],
                )
        except asyncio.CancelledError:
            logger.info("derivatives_venue_sweep_loop stopped")
            raise
        except Exception as exc:  # noqa: BLE001 — loop survives a bad pass
            metrics.increment("derivatives_venue_sweep_error_total")
            logger.error("venue sweep iteration failed: %s", exc)
        await asyncio.sleep(interval_s)


def build_venue_sweep_coro() -> Any:
    """Zero-arg coroutine factory for the runtime WorkerSpec (INT-C wires it)."""
    return venue_sweep_loop()
