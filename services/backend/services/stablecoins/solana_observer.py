"""Read-only Solana RPC verification for Stablecoin Intelligence observations.

Solana signatures are not payment proof by themselves. This module verifies a
stored tenant-scoped stablecoin observation against `sol_getTransaction`, SPL
mint evidence, transaction execution status, and slot finality before mutating
canonical finality state. It never signs, submits, or simulates transactions.
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
class StablecoinSolanaVerificationResult:
    """Evidence emitted by the Solana verification layer."""

    observation_id: str
    tenant_id: str
    transaction_hash: str
    finality_status: FinalityState
    confirmations: int
    slot: int | None
    matched_deployment: bool
    provider: str = "solana_rpc"
    warnings: tuple[str, ...] = field(default_factory=tuple)
    finality_transitions: tuple[FinalityTransition, ...] = field(default_factory=tuple)
    evidence: Mapping[str, Any] = field(default_factory=dict)


class StablecoinSolanaTransactionVerifier:
    """Verify stored observations against read-only Solana transaction evidence."""

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
        finality_threshold_slots: int = 32,
    ) -> StablecoinSolanaVerificationResult:
        if not tenant_id:
            raise ValueError("tenant_id is required for Solana stablecoin verification")
        if finality_threshold_slots < 1:
            raise ValueError("finality_threshold_slots must be positive")

        observation = await self.observations.find_by_id(observation_id)
        if not observation:
            raise ValueError(f"stablecoin observation not found: {observation_id}")
        if observation.get("tenant_id") != tenant_id:
            raise PermissionError("stablecoin Solana verification is tenant-scoped")

        deployment = self.registry.deployments.get(str(observation.get("deployment_id", "")))
        if not deployment:
            raise ValueError("registered stablecoin deployment is required for Solana verification")
        if not deployment.token_standard.lower().startswith("spl"):
            raise ValueError("Solana verification requires an SPL-token stablecoin deployment")

        chain_id = str(observation.get("chain_id", ""))
        signature = str(observation.get("transaction_hash", ""))
        tx_response = await self.rpc.execute(
            chain_id,
            "sol_getTransaction",
            [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
            vm_type="solana",
        )
        tx = tx_response.get("result") if isinstance(tx_response, dict) else None

        if not tx:
            transitions = await self._transition_if_needed(observation_id, FinalityState.PENDING, "solana_rpc_transaction_missing")
            updated = await self.observations.find_by_id(observation_id) or observation
            return StablecoinSolanaVerificationResult(
                observation_id=observation_id,
                tenant_id=tenant_id,
                transaction_hash=signature,
                finality_status=FinalityState(updated.get("finality_status", FinalityState.PENDING.value)),
                confirmations=0,
                slot=None,
                matched_deployment=False,
                warnings=("missing_onchain_transaction",),
                finality_transitions=tuple(transitions),
                evidence={"chain_id": chain_id, "transaction": None},
            )

        if not self._transaction_matches_mint(tx, deployment.contract_or_mint, observation.get("log_or_instruction_index")):
            raise ValueError("Solana transaction does not match registered stablecoin mint")

        transitions: list[FinalityTransition] = []
        if self._transaction_failed(tx):
            previous = FinalityState(observation.get("finality_status", FinalityState.UNKNOWN.value))
            target = FinalityState.REVERTED if previous in {FinalityState.CONFIRMED, FinalityState.FINALIZED, FinalityState.DISPUTED} else FinalityState.FAILED
            transitions.extend(await self._transition_if_needed(observation_id, target, "solana_rpc_transaction_failed"))
            return StablecoinSolanaVerificationResult(
                observation_id=observation_id,
                tenant_id=tenant_id,
                transaction_hash=signature,
                finality_status=target,
                confirmations=0,
                slot=self._slot(tx),
                matched_deployment=True,
                warnings=("transaction_failed",),
                finality_transitions=tuple(transitions),
                evidence={"chain_id": chain_id, "slot": tx.get("slot"), "err": (tx.get("meta") or {}).get("err")},
            )

        slot = self._slot(tx)
        slot_response = await self.rpc.execute(chain_id, "sol_getSlot", [], vm_type="solana")
        current_slot = int(slot_response.get("result")) if isinstance(slot_response, dict) else slot
        confirmations = max(0, current_slot - slot + 1)
        target = FinalityState.FINALIZED if confirmations >= finality_threshold_slots else FinalityState.CONFIRMED
        transitions.extend(await self._advance_to_target(observation_id, target, "solana_rpc_transaction_verified"))
        updated = await self.observations.find_by_id(observation_id) or observation

        return StablecoinSolanaVerificationResult(
            observation_id=observation_id,
            tenant_id=tenant_id,
            transaction_hash=signature,
            finality_status=FinalityState(updated.get("finality_status", target.value)),
            confirmations=confirmations,
            slot=slot,
            matched_deployment=True,
            finality_transitions=tuple(transitions),
            evidence={
                "chain_id": chain_id,
                "slot": slot,
                "current_slot": current_slot,
                "finality_threshold_slots": finality_threshold_slots,
            },
        )

    @staticmethod
    def _slot(tx: Mapping[str, Any]) -> int:
        slot = tx.get("slot")
        if slot is None:
            raise ValueError("Solana transaction is missing slot")
        return int(slot)

    @staticmethod
    def _transaction_failed(tx: Mapping[str, Any]) -> bool:
        meta = tx.get("meta") or {}
        return meta.get("err") is not None

    @staticmethod
    def _transaction_matches_mint(tx: Mapping[str, Any], mint: str, instruction_index: Any = None) -> bool:
        expected = mint.lower()
        meta = tx.get("meta") or {}
        for balance in list(meta.get("preTokenBalances") or []) + list(meta.get("postTokenBalances") or []):
            if str(balance.get("mint", "")).lower() == expected:
                return True

        message = ((tx.get("transaction") or {}).get("message") or {})
        instructions = list(message.get("instructions") or [])
        inner = meta.get("innerInstructions") or []
        for group in inner:
            instructions.extend(group.get("instructions") or [])

        for index, instruction in enumerate(instructions):
            if instruction_index is not None and int(instruction_index) != index:
                continue
            parsed = instruction.get("parsed") if isinstance(instruction, Mapping) else None
            info = parsed.get("info") if isinstance(parsed, Mapping) else {}
            candidate_mints = [info.get("mint"), info.get("tokenMint")]
            if any(str(candidate or "").lower() == expected for candidate in candidate_mints):
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
