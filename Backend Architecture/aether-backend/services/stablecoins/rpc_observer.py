"""Read-only RPC verification for Stablecoin Intelligence observations.

A transaction hash alone is not proof of payment.  This module compares an
already-ingested tenant-scoped observation against an EVM transaction receipt,
registered deployment identity, receipt status, and chain-tip confirmations
before changing finality.  It never signs transactions, routes funds, or treats
Aether as the executor of an external stablecoin movement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from repositories.stablecoin_repos import StablecoinObservationRepository
from services.onchain.rpc_gateway import RPCGateway

from .finality import FinalityTransition, StablecoinFinalityService
from .models import FinalityState
from .registry import PLATFORM_STABLECOIN_REGISTRY, StablecoinDeploymentRegistry


@dataclass(frozen=True)
class StablecoinRPCVerificationResult:
    """Evidence emitted by the RPC verification layer."""

    observation_id: str
    tenant_id: str
    transaction_hash: str
    finality_status: FinalityState
    confirmations: int
    receipt_status: str | None
    matched_deployment: bool
    provider: str = "evm_rpc"
    warnings: tuple[str, ...] = field(default_factory=tuple)
    finality_transitions: tuple[FinalityTransition, ...] = field(default_factory=tuple)
    evidence: Mapping[str, Any] = field(default_factory=dict)


class StablecoinEVMReceiptVerifier:
    """Verify stored observations against read-only EVM receipt evidence.

    The verifier is intentionally narrow: it accepts only a previously stored
    observation ID and tenant ID, validates that the receipt corresponds to the
    registered stablecoin deployment, and delegates state changes to
    ``StablecoinFinalityService`` so finality history and correction flags stay
    canonical.
    """

    def __init__(
        self,
        *,
        observations: StablecoinObservationRepository | None = None,
        finality: StablecoinFinalityService | None = None,
        rpc: RPCGateway | None = None,
        registry: StablecoinDeploymentRegistry | None = None,
    ) -> None:
        self.observations = observations or StablecoinObservationRepository()
        self.finality = finality or StablecoinFinalityService(self.observations)
        self.rpc = rpc or RPCGateway()
        self.registry = registry or PLATFORM_STABLECOIN_REGISTRY

    async def verify_observation(
        self,
        *,
        tenant_id: str,
        observation_id: str,
        finality_threshold: int = 12,
    ) -> StablecoinRPCVerificationResult:
        if not tenant_id:
            raise ValueError("tenant_id is required for RPC stablecoin verification")
        if finality_threshold < 1:
            raise ValueError("finality_threshold must be positive")

        observation = await self.observations.find_by_id(observation_id)
        if not observation:
            raise ValueError(f"stablecoin observation not found: {observation_id}")
        if observation.get("tenant_id") != tenant_id:
            raise PermissionError("stablecoin RPC verification is tenant-scoped")

        deployment = self.registry.deployments.get(str(observation.get("deployment_id", "")))
        if not deployment:
            raise ValueError("registered stablecoin deployment is required for receipt verification")

        chain_id = str(observation.get("chain_id", ""))
        tx_hash = str(observation.get("transaction_hash", ""))
        receipt_response = await self.rpc.execute(chain_id, "eth_getTransactionReceipt", [tx_hash])
        receipt = receipt_response.get("result") if isinstance(receipt_response, dict) else None

        if not receipt:
            transitions = await self._transition_if_needed(
                observation_id,
                FinalityState.PENDING,
                "evm_rpc_receipt_missing",
            )
            updated = await self.observations.find_by_id(observation_id) or observation
            return StablecoinRPCVerificationResult(
                observation_id=observation_id,
                tenant_id=tenant_id,
                transaction_hash=tx_hash,
                finality_status=FinalityState(updated.get("finality_status", FinalityState.PENDING.value)),
                confirmations=0,
                receipt_status=None,
                matched_deployment=False,
                warnings=("missing_onchain_receipt",),
                finality_transitions=tuple(transitions),
                evidence={"chain_id": chain_id, "receipt": None},
            )

        if not self._receipt_matches_deployment(receipt, deployment.contract_or_mint, observation.get("log_or_instruction_index")):
            raise ValueError("EVM receipt does not match registered stablecoin deployment")

        receipt_status = str(receipt.get("status", "")).lower()
        transitions: list[FinalityTransition] = []
        if receipt_status in {"0x0", "0"}:
            previous = FinalityState(observation.get("finality_status", FinalityState.UNKNOWN.value))
            target = FinalityState.REVERTED if previous in {FinalityState.CONFIRMED, FinalityState.FINALIZED, FinalityState.DISPUTED} else FinalityState.FAILED
            transitions.extend(await self._transition_if_needed(observation_id, target, "evm_rpc_receipt_failed"))
            return StablecoinRPCVerificationResult(
                observation_id=observation_id,
                tenant_id=tenant_id,
                transaction_hash=tx_hash,
                finality_status=target,
                confirmations=0,
                receipt_status=receipt_status,
                matched_deployment=True,
                warnings=("receipt_failed",),
                finality_transitions=tuple(transitions),
                evidence={"chain_id": chain_id, "receipt_block": receipt.get("blockNumber")},
            )

        block_number = self._hex_int(receipt.get("blockNumber"))
        tip_response = await self.rpc.execute(chain_id, "eth_blockNumber", [])
        tip_value = tip_response.get("result") if isinstance(tip_response, dict) else None
        tip_number = self._hex_int(tip_value)
        confirmations = max(0, tip_number - block_number + 1)
        target = FinalityState.FINALIZED if confirmations >= finality_threshold else FinalityState.CONFIRMED
        transitions.extend(await self._advance_to_target(observation_id, target, "evm_rpc_receipt_verified"))
        updated = await self.observations.find_by_id(observation_id) or observation

        return StablecoinRPCVerificationResult(
            observation_id=observation_id,
            tenant_id=tenant_id,
            transaction_hash=tx_hash,
            finality_status=FinalityState(updated.get("finality_status", target.value)),
            confirmations=confirmations,
            receipt_status=receipt_status,
            matched_deployment=True,
            finality_transitions=tuple(transitions),
            evidence={
                "chain_id": chain_id,
                "receipt_block": receipt.get("blockNumber"),
                "tip_block": tip_value,
                "finality_threshold": finality_threshold,
            },
        )

    @staticmethod
    def _hex_int(value: Any) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value, 16) if value.startswith("0x") else int(value)
        raise ValueError(f"invalid EVM block number: {value!r}")

    @staticmethod
    def _receipt_matches_deployment(receipt: Mapping[str, Any], contract_or_mint: str, log_index: Any = None) -> bool:
        expected = contract_or_mint.lower()
        if str(receipt.get("to", "")).lower() == expected:
            return True
        for log in receipt.get("logs") or []:
            if str(log.get("address", "")).lower() != expected:
                continue
            if log_index is None:
                return True
            if StablecoinEVMReceiptVerifier._hex_int(log.get("logIndex", "0x0")) == int(log_index):
                return True
        return False

    async def _transition_if_needed(
        self,
        observation_id: str,
        target: FinalityState,
        reason: str,
    ) -> list[FinalityTransition]:
        record = await self.observations.find_by_id(observation_id)
        if not record:
            raise ValueError(f"stablecoin observation not found: {observation_id}")
        previous = FinalityState(record.get("finality_status", FinalityState.UNKNOWN.value))
        if previous == target:
            return []
        return [await self.finality.transition(observation_id, target, reason=reason)]

    async def _advance_to_target(
        self,
        observation_id: str,
        target: FinalityState,
        reason: str,
    ) -> list[FinalityTransition]:
        record = await self.observations.find_by_id(observation_id)
        if not record:
            raise ValueError(f"stablecoin observation not found: {observation_id}")
        previous = FinalityState(record.get("finality_status", FinalityState.UNKNOWN.value))
        if previous == target:
            return []
        if target == FinalityState.FINALIZED and previous in {FinalityState.OBSERVED, FinalityState.PENDING, FinalityState.UNKNOWN}:
            transitions = await self._transition_if_needed(observation_id, FinalityState.CONFIRMED, reason)
            transitions.extend(await self._transition_if_needed(observation_id, FinalityState.FINALIZED, reason))
            return transitions
        return await self._transition_if_needed(observation_id, target, reason)
