import pytest

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Backend Architecture" / "aether-backend"))

from repositories.repos import reset_in_memory_stores
from repositories.stablecoin_repos import StablecoinObservationRepository
from services.stablecoins.models import FinalityState
from services.stablecoins.rpc_observer import StablecoinEVMReceiptVerifier

BASE_USDC_DEPLOYMENT = "usdc:base:mainnet:0x833589fcd6edb6e08f4c7c32d4f71b54bdA02913"
BASE_USDC_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


class FakeRPC:
    def __init__(self, receipt, tip="0x70"):
        self.receipt = receipt
        self.tip = tip
        self.calls = []

    async def execute(self, chain_id, method, params=None, vm_type="evm"):
        self.calls.append((chain_id, method, params or []))
        if method == "eth_getTransactionReceipt":
            return {"result": self.receipt}
        if method == "eth_blockNumber":
            return {"result": self.tip}
        raise AssertionError(f"unexpected RPC method {method}")


@pytest.fixture(autouse=True)
def clean_repos():
    reset_in_memory_stores()


async def _store_observation(status=FinalityState.OBSERVED, tenant_id="tenant-a", observation_id="obs-1"):
    repo = StablecoinObservationRepository()
    await repo.upsert_observation(
        {
            "observation_id": observation_id,
            "tenant_id": tenant_id,
            "chain_id": "8453",
            "network": "base-mainnet",
            "deployment_id": BASE_USDC_DEPLOYMENT,
            "canonical_asset_id": "usdc",
            "transaction_hash": "0xabc",
            "log_or_instruction_index": 3,
            "finality_status": status.value,
            "source": "unit",
            "source_record_id": "record-1",
            "source_execution_id": "exec-1",
            "observed_at": "2026-07-06T00:00:00Z",
            "amount_atomic": 1000000,
        }
    )
    return repo


def _receipt(status="0x1", address=BASE_USDC_CONTRACT, block="0x64", log_index="0x3"):
    return {
        "status": status,
        "to": "0x0000000000000000000000000000000000000000",
        "blockNumber": block,
        "logs": [{"address": address, "logIndex": log_index}],
    }


@pytest.mark.asyncio
async def test_evm_receipt_verification_finalizes_after_threshold():
    repo = await _store_observation()
    verifier = StablecoinEVMReceiptVerifier(observations=repo, rpc=FakeRPC(_receipt(), tip="0x70"))

    result = await verifier.verify_observation(tenant_id="tenant-a", observation_id="obs-1", finality_threshold=12)

    assert result.finality_status == FinalityState.FINALIZED
    assert result.confirmations == 13
    assert result.matched_deployment is True
    assert [transition.new_state for transition in result.finality_transitions] == [FinalityState.CONFIRMED, FinalityState.FINALIZED]
    stored = await repo.find_by_id("obs-1")
    assert stored["finality_status"] == FinalityState.FINALIZED.value
    assert len(stored["finality_history"]) == 2


@pytest.mark.asyncio
async def test_missing_receipt_marks_observation_pending_without_claiming_payment():
    repo = await _store_observation()
    verifier = StablecoinEVMReceiptVerifier(observations=repo, rpc=FakeRPC(None))

    result = await verifier.verify_observation(tenant_id="tenant-a", observation_id="obs-1")

    assert result.finality_status == FinalityState.PENDING
    assert result.warnings == ("missing_onchain_receipt",)
    stored = await repo.find_by_id("obs-1")
    assert stored["finality_status"] == FinalityState.PENDING.value


@pytest.mark.asyncio
async def test_receipt_must_match_registered_deployment_contract_before_finality_change():
    repo = await _store_observation()
    verifier = StablecoinEVMReceiptVerifier(
        observations=repo,
        rpc=FakeRPC(_receipt(address="0x1111111111111111111111111111111111111111")),
    )

    with pytest.raises(ValueError, match="does not match registered stablecoin deployment"):
        await verifier.verify_observation(tenant_id="tenant-a", observation_id="obs-1")

    stored = await repo.find_by_id("obs-1")
    assert stored["finality_status"] == FinalityState.OBSERVED.value


@pytest.mark.asyncio
async def test_failed_receipt_reverts_previously_confirmed_observation_for_correction():
    repo = await _store_observation(status=FinalityState.CONFIRMED)
    verifier = StablecoinEVMReceiptVerifier(observations=repo, rpc=FakeRPC(_receipt(status="0x0")))

    result = await verifier.verify_observation(tenant_id="tenant-a", observation_id="obs-1")

    assert result.finality_status == FinalityState.REVERTED
    assert result.finality_transitions[0].correction_event == "stablecoin.transaction.reverted"
    stored = await repo.find_by_id("obs-1")
    assert stored["requires_downstream_correction"] is True


@pytest.mark.asyncio
async def test_rpc_verification_blocks_cross_tenant_observation_access():
    repo = await _store_observation(tenant_id="tenant-a")
    verifier = StablecoinEVMReceiptVerifier(observations=repo, rpc=FakeRPC(_receipt()))

    with pytest.raises(PermissionError, match="tenant-scoped"):
        await verifier.verify_observation(tenant_id="tenant-b", observation_id="obs-1")
