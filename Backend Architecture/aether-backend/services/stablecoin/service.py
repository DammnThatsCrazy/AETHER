"""Stablecoin observation intake + normalization pipeline.

Deterministic identity, replay-safe idempotent persistence, exact
atomic→decimal scaling (Decimal only, never float transit), canonical
event emission (returned to the caller — the service never wires the bus).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from repositories.stablecoin_repos import StablecoinObservationRepo
from services.stablecoin.foundation import (
    deterministic_id,
    deterministic_idempotency_key,
    make_event,
    utc_now_iso,
)
from services.stablecoin.models import StablecoinObservation, StablecoinObservationIngest
from services.stablecoin.registry import StablecoinRegistry

# observation_type → canonical registry event name
_OBSERVATION_EVENT: dict[str, str] = {
    "transfer": "stablecoin_transfer_observed",
    "payment": "stablecoin_payment_observed",
    "mint": "stablecoin_mint_observed",
    "burn": "stablecoin_burn_observed",
    "bridge_outbound": "stablecoin_bridge_outbound_observed",
    "bridge_inbound": "stablecoin_bridge_inbound_observed",
    "swap": "stablecoin_swap_observed",
    "x402_settlement": "stablecoin_x402_settlement_observed",
    "treasury_movement": "stablecoin_treasury_movement_observed",
    "payout": "stablecoin_payout_observed",
    "venue_deposit": "stablecoin_venue_deposit_observed",
    "venue_withdrawal": "stablecoin_venue_withdrawal_observed",
}


class StablecoinObservationService:
    def __init__(
        self,
        registry: Optional[StablecoinRegistry] = None,
        observation_repo: Optional[StablecoinObservationRepo] = None,
    ) -> None:
        self.registry = registry or StablecoinRegistry()
        self.observations = observation_repo or StablecoinObservationRepo()

    async def ingest_observation(
        self, tenant_id: str, ingest: StablecoinObservationIngest,
    ) -> dict[str, Any]:
        """Normalize and persist one observation. Replay-safe: the same
        (chain, tx, log index, type) basis always produces the same identity,
        and a second ingest is a no-op with inserted=False."""
        basis = (
            f"{ingest.chain_id}|{ingest.transaction_hash}"
            f"|{ingest.log_or_instruction_index if ingest.log_or_instruction_index is not None else ''}"
            f"|{ingest.observation_type}"
        )
        observation_id = deterministic_id("scobs_", basis)
        idempotency_key = deterministic_idempotency_key(basis)

        deployment, resolution = await self._resolve(ingest)
        decimals = deployment["decimals"] if deployment else (ingest.decimals if ingest.decimals is not None else 6)

        amount_decimal = ingest.amount_decimal
        if amount_decimal is None:
            # Exact scaling: atomic / 10**decimals via Decimal scaleb.
            amount_decimal = (Decimal(ingest.amount_atomic)).scaleb(-decimals)

        observation = StablecoinObservation(
            tenant_id=tenant_id,
            observation_id=observation_id,
            idempotency_key=idempotency_key,
            evidence=ingest.evidence,
            observation_type=ingest.observation_type,
            deployment_id=deployment["deployment_id"] if deployment else f"unresolved:{ingest.contract_or_mint or 'unknown'}",
            canonical_asset_id=(
                deployment["canonical_asset_id"] if deployment
                else (ingest.canonical_asset_id or "unresolved")
            ),
            chain_id=ingest.chain_id,
            network=ingest.network or (deployment or {}).get("network"),
            block_number=ingest.block_number,
            block_hash=ingest.block_hash,
            transaction_hash=ingest.transaction_hash,
            log_or_instruction_index=ingest.log_or_instruction_index,
            amount_atomic=ingest.amount_atomic,
            amount_decimal=amount_decimal,
            from_address=ingest.from_address,
            to_address=ingest.to_address,
            from_wallet_id=ingest.from_wallet_id,
            to_wallet_id=ingest.to_wallet_id,
            from_entity_ref=ingest.from_entity_ref,
            to_entity_ref=ingest.to_entity_ref,
            counterparty_class=ingest.counterparty_class,
            protocol_id=ingest.protocol_id,
            merchant_id=ingest.merchant_id,
            facilitator_id=ingest.facilitator_id,
            agent_id=ingest.agent_id,
            campaign_id=ingest.campaign_id,
            journey_id=ingest.journey_id,
            session_id=ingest.session_id,
            finality_status=ingest.finality_status,
            classification_confidence=(
                ingest.classification_confidence
                if ingest.classification_confidence is not None
                else ("0.9" if deployment else "0")
            ),
            observed_at=ingest.observed_at,
            ingested_at=utc_now_iso(),
        )

        record = observation.model_dump()
        record["evidence"] = observation.evidence.model_dump() if observation.evidence else None
        record["from_entity_ref"] = (
            observation.from_entity_ref.model_dump() if observation.from_entity_ref else None
        )
        record["to_entity_ref"] = (
            observation.to_entity_ref.model_dump() if observation.to_entity_ref else None
        )
        inserted = await self.observations.insert(record)

        emitted: list[dict] = []
        if inserted:
            emitted.append(make_event(
                _OBSERVATION_EVENT[ingest.observation_type], tenant_id,
                {
                    "observation_id": observation_id,
                    "deployment_id": observation.deployment_id,
                    "canonical_asset_id": observation.canonical_asset_id,
                    "chain_id": observation.chain_id,
                    "transaction_hash": observation.transaction_hash,
                    "amount_decimal": str(amount_decimal),
                    "finality_status": observation.finality_status,
                },
            ))
        return {
            "inserted": inserted,
            "observation_id": observation_id,
            "deployment_resolution": resolution,
            "emitted_events": emitted,
        }

    async def _resolve(
        self, ingest: StablecoinObservationIngest,
    ) -> tuple[Optional[dict], str]:
        if ingest.deployment_id:
            deployment = await self.registry.get_deployment(ingest.deployment_id)
            if deployment:
                return deployment, "by_deployment_id"
        if ingest.contract_or_mint:
            deployment = await self.registry.resolve_deployment(
                ingest.chain_id, ingest.contract_or_mint,
            )
            if deployment:
                return deployment, "by_contract"
        return None, "unresolved"
