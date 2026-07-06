import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Backend Architecture" / "aether-backend"))

from repositories.repos import reset_in_memory_stores
from repositories.stablecoin_repos import StablecoinObservationRepository
from services.stablecoins.models import FinalityState, StablecoinDeployment
from services.stablecoins.registry import StablecoinDeploymentRegistry
from services.stablecoins.solana_observer import StablecoinSolanaTransactionVerifier

SOL_USDC_DEPLOYMENT = "usdc:solana:mainnet:EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


class FakeSolanaRPC:
    def __init__(self, transaction, current_slot=140):
        self.transaction = transaction
        self.current_slot = current_slot
        self.calls = []

    async def execute(self, chain_id, method, params=None, vm_type="evm"):
        self.calls.append((chain_id, method, params or [], vm_type))
        if method == "sol_getTransaction":
            return {"result": self.transaction}
        if method == "sol_getSlot":
            return {"result": self.current_slot}
        raise AssertionError(f"unexpected RPC method {method}")


@pytest.fixture(autouse=True)
def clean_repos():
    reset_in_memory_stores()


@pytest.fixture
def solana_registry():
    return StablecoinDeploymentRegistry.from_iterable(
        [
            StablecoinDeployment(
                deployment_id=SOL_USDC_DEPLOYMENT,
                canonical_asset_id="usdc",
                chain_id="solana-mainnet",
                network="solana-mainnet",
                token_standard="spl-token",
                contract_or_mint=SOL_USDC_MINT,
                decimals=6,
                issuer_verified=True,
            )
        ]
    )


async def _store_observation(status=FinalityState.OBSERVED, tenant_id="tenant-a", observation_id="sol-obs-1"):
    repo = StablecoinObservationRepository()
    await repo.upsert_observation(
        {
            "observation_id": observation_id,
            "tenant_id": tenant_id,
            "chain_id": "solana-mainnet",
            "network": "solana-mainnet",
            "deployment_id": SOL_USDC_DEPLOYMENT,
            "canonical_asset_id": "usdc",
            "transaction_hash": "5nSolanaSig",
            "log_or_instruction_index": 0,
            "finality_status": status.value,
            "source": "unit",
            "source_record_id": "record-1",
            "source_execution_id": "exec-1",
            "observed_at": "2026-07-06T00:00:00Z",
            "amount_atomic": 2500000,
        }
    )
    return repo


def _transaction(*, slot=100, mint=SOL_USDC_MINT, err=None):
    return {
        "slot": slot,
        "blockTime": 1783310000,
        "meta": {
            "err": err,
            "preTokenBalances": [],
            "postTokenBalances": [{"mint": mint, "uiTokenAmount": {"amount": "2500000", "decimals": 6}}],
        },
        "transaction": {
            "message": {
                "instructions": [
                    {"program": "spl-token", "parsed": {"type": "transferChecked", "info": {"mint": mint}}}
                ]
            }
        },
    }


@pytest.mark.asyncio
async def test_solana_transaction_verification_finalizes_after_slot_threshold(solana_registry):
    repo = await _store_observation()
    verifier = StablecoinSolanaTransactionVerifier(
        observations=repo,
        rpc=FakeSolanaRPC(_transaction(slot=100), current_slot=132),
        registry=solana_registry,
    )

    result = await verifier.verify_observation(
        tenant_id="tenant-a",
        observation_id="sol-obs-1",
        finality_threshold_slots=32,
    )

    assert result.finality_status == FinalityState.FINALIZED
    assert result.confirmations == 33
    assert result.matched_deployment is True
    assert [transition.new_state for transition in result.finality_transitions] == [FinalityState.CONFIRMED, FinalityState.FINALIZED]
    stored = await repo.find_by_id("sol-obs-1")
    assert stored["finality_status"] == FinalityState.FINALIZED.value


@pytest.mark.asyncio
async def test_missing_solana_transaction_marks_pending_without_claiming_payment(solana_registry):
    repo = await _store_observation()
    verifier = StablecoinSolanaTransactionVerifier(observations=repo, rpc=FakeSolanaRPC(None), registry=solana_registry)

    result = await verifier.verify_observation(tenant_id="tenant-a", observation_id="sol-obs-1")

    assert result.finality_status == FinalityState.PENDING
    assert result.warnings == ("missing_onchain_transaction",)
    stored = await repo.find_by_id("sol-obs-1")
    assert stored["finality_status"] == FinalityState.PENDING.value


@pytest.mark.asyncio
async def test_solana_transaction_must_match_registered_mint_before_finality_change(solana_registry):
    repo = await _store_observation()
    verifier = StablecoinSolanaTransactionVerifier(
        observations=repo,
        rpc=FakeSolanaRPC(_transaction(mint="So11111111111111111111111111111111111111112")),
        registry=solana_registry,
    )

    with pytest.raises(ValueError, match="does not match registered stablecoin mint"):
        await verifier.verify_observation(tenant_id="tenant-a", observation_id="sol-obs-1")

    stored = await repo.find_by_id("sol-obs-1")
    assert stored["finality_status"] == FinalityState.OBSERVED.value


@pytest.mark.asyncio
async def test_failed_solana_transaction_reverts_confirmed_observation_for_correction(solana_registry):
    repo = await _store_observation(status=FinalityState.CONFIRMED)
    verifier = StablecoinSolanaTransactionVerifier(
        observations=repo,
        rpc=FakeSolanaRPC(_transaction(err={"InstructionError": [0, "Custom"]})),
        registry=solana_registry,
    )

    result = await verifier.verify_observation(tenant_id="tenant-a", observation_id="sol-obs-1")

    assert result.finality_status == FinalityState.REVERTED
    assert result.finality_transitions[0].correction_event == "stablecoin.transaction.reverted"
    stored = await repo.find_by_id("sol-obs-1")
    assert stored["requires_downstream_correction"] is True


@pytest.mark.asyncio
async def test_solana_verification_blocks_cross_tenant_observation_access(solana_registry):
    repo = await _store_observation(tenant_id="tenant-a")
    verifier = StablecoinSolanaTransactionVerifier(observations=repo, rpc=FakeSolanaRPC(_transaction()), registry=solana_registry)

    with pytest.raises(PermissionError, match="tenant-scoped"):
        await verifier.verify_observation(tenant_id="tenant-b", observation_id="sol-obs-1")
