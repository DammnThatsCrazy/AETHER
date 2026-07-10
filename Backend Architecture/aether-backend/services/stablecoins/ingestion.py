"""Stablecoin Bronze ingestion and Silver normalization pipeline.

Keeps Aether observation-first: provider payloads become governed Bronze records
first, then eligible records are normalized into tenant-scoped Silver stablecoin
observations. Does not mutate the graph and does not execute payments.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping

from repositories.lake import BronzeRepository, ProvenanceStatus, SilverRepository
from repositories.stablecoin_repos import StablecoinObservationRepository
from shared.common.common import utc_now

from .models import FinalityState, StablecoinEventType, StablecoinMoney, StablecoinObservation
from .registry import PLATFORM_STABLECOIN_REGISTRY, StablecoinDeploymentRegistry


@dataclass(frozen=True)
class StablecoinProviderStatus:
    provider: str
    configured_state: str
    last_success_at: str = ""
    last_failure_at: str = ""
    freshness: str = "unknown"
    rate_limit_state: str = "unknown"
    credential_reference: str = ""
    data_rights_state: str = "unknown"
    rows_observed: int = 0
    rows_accepted: int = 0
    rows_rejected: int = 0
    tenant_impact: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderObservation:
    tenant_id: str
    provider: str
    source_record_id: str
    source_execution_id: str
    source_manifest_id: str
    observed_at: str
    chain_id: str
    network: str
    contract_or_mint: str
    transaction_hash: str
    amount_atomic: int
    from_address: str = ""
    to_address: str = ""
    log_or_instruction_index: int | None = None
    event_type: StablecoinEventType = StablecoinEventType.UNKNOWN_STABLECOIN_MOVEMENT
    finality_status: FinalityState = FinalityState.OBSERVED
    raw_payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id is required for stablecoin ingestion")
        if not self.source_execution_id:
            raise ValueError("source_execution_id is required for repeated provider executions")
        if not isinstance(self.amount_atomic, int):
            raise TypeError("amount_atomic must be an integer")


@dataclass(frozen=True)
class NormalizedStablecoinFact:
    observation: StablecoinObservation
    money: StablecoinMoney
    bronze_id: str
    idempotency_key: str
    data_quality_status: str
    classification_method: str
    evidence: Mapping[str, Any]


class StablecoinIngestionPipeline:
    def __init__(
        self,
        *,
        bronze: BronzeRepository | None = None,
        silver: SilverRepository | None = None,
        observations: StablecoinObservationRepository | None = None,
        registry: StablecoinDeploymentRegistry | None = None,
    ) -> None:
        self.bronze = bronze or BronzeRepository("stablecoin")
        self.silver = silver or SilverRepository("stablecoin")
        self.observations = observations or StablecoinObservationRepository()
        self.registry = registry or PLATFORM_STABLECOIN_REGISTRY

    async def ingest_provider_observation(self, obs: ProviderObservation) -> NormalizedStablecoinFact:
        deployment = self.registry.resolve(
            chain_id=obs.chain_id,
            network=obs.network,
            contract_or_mint=obs.contract_or_mint,
        )
        if deployment is None:
            raise ValueError("unknown stablecoin deployment; quarantine or operator registration required")

        payload = {
            **dict(obs.raw_payload),
            "tenant_id": obs.tenant_id,
            "source_execution_id": obs.source_execution_id,
            "source_manifest_id": obs.source_manifest_id,
            "chain_id": obs.chain_id,
            "network": obs.network,
            "contract_or_mint": obs.contract_or_mint,
            "transaction_hash": obs.transaction_hash,
            "log_or_instruction_index": obs.log_or_instruction_index,
            "amount_atomic": str(obs.amount_atomic),
        }
        bronze_record, _ = await self.bronze.ingest(
            source=obs.provider,
            source_tag=f"tenant:{obs.tenant_id}:stablecoin:{obs.provider}",
            provider_record_id=f"{obs.source_execution_id}:{obs.source_record_id}",
            payload=payload,
            schema_version="stablecoin.observation.v1",
            tenant_id=obs.tenant_id,
            provenance_status=ProvenanceStatus.VALID.value,
            license_status="enterprise_contract",
            terms_status="approved",
            commercial_use_status="approved",
            source_manifest_id=obs.source_manifest_id,
            sensitivity_classification="financial_observation",
        )
        fact = self._normalize(obs, deployment.deployment_id, deployment.canonical_asset_id, deployment.decimals, bronze_record)
        await self.silver.upsert_record(
            entity_id=fact.observation.transaction_hash,
            entity_type="stablecoin_observation",
            source=obs.provider,
            source_tag=f"tenant:{obs.tenant_id}:stablecoin:{obs.provider}",
            normalized={
                "observation_id": fact.observation.observation_id,
                "deployment_id": fact.observation.deployment_id,
                "canonical_asset_id": fact.observation.canonical_asset_id,
                "finality_status": fact.observation.finality_status.value,
                "event_type": fact.observation.event_type.value,
                "source_execution_id": fact.observation.source_execution_id,
                "source_record_id": fact.observation.source_record_id,
                "data_quality_status": fact.data_quality_status,
                "evidence": dict(fact.evidence),
            },
            bronze_id=bronze_record["id"],
            tenant_id=obs.tenant_id,
            bronze_record=bronze_record,
        )
        await self.observations.upsert_observation(self._observation_to_record(fact.observation))
        return fact

    def _normalize(
        self,
        obs: ProviderObservation,
        deployment_id: str,
        canonical_asset_id: str,
        decimals: int,
        bronze_record: dict[str, Any],
    ) -> NormalizedStablecoinFact:
        observation_id = hashlib.sha256(
            f"{obs.tenant_id}:{obs.chain_id}:{obs.network}:{deployment_id}:{obs.transaction_hash}:{obs.log_or_instruction_index}".encode()
        ).hexdigest()[:32]
        observation = StablecoinObservation(
            observation_id=observation_id,
            tenant_id=obs.tenant_id,
            source=obs.provider,
            source_record_id=obs.source_record_id,
            source_execution_id=obs.source_execution_id,
            source_manifest_id=obs.source_manifest_id,
            evidence_id=bronze_record["id"],
            observed_at=obs.observed_at,
            chain_id=obs.chain_id,
            network=obs.network,
            transaction_hash=obs.transaction_hash,
            log_or_instruction_index=obs.log_or_instruction_index,
            finality_status=obs.finality_status,
            event_type=obs.event_type,
            deployment_id=deployment_id,
            canonical_asset_id=canonical_asset_id,
            amount_atomic=obs.amount_atomic,
            from_address=obs.from_address,
            to_address=obs.to_address,
            classification_confidence=(
                Decimal("0.95")
                if obs.event_type != StablecoinEventType.UNKNOWN_STABLECOIN_MOVEMENT
                else Decimal("0.25")
            ),
        )
        money = StablecoinMoney(obs.amount_atomic, decimals, canonical_asset_id, deployment_id, obs.chain_id, obs.network)
        return NormalizedStablecoinFact(
            observation=observation,
            money=money,
            bronze_id=bronze_record["id"],
            idempotency_key=bronze_record["idempotency_key"],
            data_quality_status="accepted",
            classification_method="deterministic_registry_v1",
            evidence={"bronze_id": bronze_record["id"], "source_manifest_id": obs.source_manifest_id},
        )

    @staticmethod
    def _observation_to_record(observation: StablecoinObservation) -> dict[str, Any]:
        return {
            "observation_id": observation.observation_id,
            "tenant_id": observation.tenant_id,
            "schema_version": observation.schema_version,
            "source": observation.source,
            "source_record_id": observation.source_record_id,
            "source_execution_id": observation.source_execution_id,
            "source_manifest_id": observation.source_manifest_id,
            "evidence_id": observation.evidence_id,
            "observed_at": observation.observed_at,
            "ingested_at": utc_now().isoformat(),
            "chain_id": observation.chain_id,
            "network": observation.network,
            "transaction_hash": observation.transaction_hash,
            "log_or_instruction_index": observation.log_or_instruction_index,
            "finality_status": observation.finality_status.value,
            "event_type": observation.event_type.value,
            "deployment_id": observation.deployment_id,
            "canonical_asset_id": observation.canonical_asset_id,
            "amount_atomic": observation.amount_atomic,
            "from_address": observation.from_address,
            "to_address": observation.to_address,
        }
