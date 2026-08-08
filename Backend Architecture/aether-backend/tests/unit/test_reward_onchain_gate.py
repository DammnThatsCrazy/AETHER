"""
Unit tests for the EVM mainnet reward activation audit gate (A6, deliverable 4).

Blocks EVM mainnet on-chain reward activation unless recorded external-audit
evidence is present. Local and testnet activations are unaffected.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores
from services.rewards.onchain_gate import (
    MainnetAuditRequiredError,
    assert_mainnet_audit_evidence,
    is_evm_mainnet,
)
from services.rewards.repositories import RewardAuditEvidenceRepository


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _run(coro):
    # Robust against asyncio-auto-mode tests having closed the thread's
    # loop earlier in the same worker: drive on a fresh loop each call.
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


TENANT = "tenant_audit_001"
CONTRACT = "0x5FbDB2315678afecb367f032d93F642f64180aa3"


def _repo():
    return RewardAuditEvidenceRepository()


# ═══════════════════════════════════════════════════════════════════════════
# mainnet classification
# ═══════════════════════════════════════════════════════════════════════════

def test_ethereum_mainnet_is_mainnet():
    assert is_evm_mainnet(1) is True
    assert is_evm_mainnet(137) is True   # Polygon
    assert is_evm_mainnet(8453) is True  # Base


def test_testnets_and_local_not_mainnet():
    assert is_evm_mainnet(11155111) is False  # Sepolia
    assert is_evm_mainnet(31337) is False      # hardhat
    assert is_evm_mainnet(5) is False          # Goerli
    assert is_evm_mainnet(None) is False


# ═══════════════════════════════════════════════════════════════════════════
# the gate
# ═══════════════════════════════════════════════════════════════════════════

def test_mainnet_without_evidence_blocks():
    async def run():
        await assert_mainnet_audit_evidence(
            tenant_id=TENANT, chain_id=1, contract_address=CONTRACT,
            evidence_repo=_repo(), is_local=False,
        )

    with pytest.raises(MainnetAuditRequiredError) as exc:
        _run(run())
    assert exc.value.status_code == 403
    assert exc.value.chain_id == 1


def test_mainnet_with_recorded_evidence_passes():
    async def run():
        repo = _repo()
        await repo.create(TENANT, {
            "chain_id": 1, "contract_address": CONTRACT,
            "auditor": "Trail of Bits", "report_uri": "https://audit.example/report.pdf",
        })
        # Should NOT raise.
        await assert_mainnet_audit_evidence(
            tenant_id=TENANT, chain_id=1, contract_address=CONTRACT,
            evidence_repo=repo, is_local=False,
        )
        return True

    assert _run(run()) is True


def test_revoked_evidence_re_gates():
    async def run():
        repo = _repo()
        rec = await repo.create(TENANT, {
            "chain_id": 1, "contract_address": CONTRACT, "auditor": "X",
        })
        await repo.set_status(rec["id"], TENANT, "revoked")
        await assert_mainnet_audit_evidence(
            tenant_id=TENANT, chain_id=1, contract_address=CONTRACT,
            evidence_repo=repo, is_local=False,
        )

    with pytest.raises(MainnetAuditRequiredError):
        _run(run())


def test_testnet_activation_not_gated():
    async def run():
        # Sepolia, no evidence → must NOT raise.
        await assert_mainnet_audit_evidence(
            tenant_id=TENANT, chain_id=11155111, contract_address=CONTRACT,
            evidence_repo=_repo(), is_local=False,
        )
        return True

    assert _run(run()) is True


def test_local_activation_not_gated():
    async def run():
        # Mainnet chain but local env → must NOT raise.
        await assert_mainnet_audit_evidence(
            tenant_id=TENANT, chain_id=1, contract_address=CONTRACT,
            evidence_repo=_repo(), is_local=True,
        )
        return True

    assert _run(run()) is True


def test_evidence_is_contract_scoped():
    async def run():
        repo = _repo()
        # Evidence recorded for a DIFFERENT contract must not unlock this one.
        await repo.create(TENANT, {
            "chain_id": 1, "contract_address": "0x1111111111111111111111111111111111111111",
            "auditor": "X",
        })
        await assert_mainnet_audit_evidence(
            tenant_id=TENANT, chain_id=1, contract_address=CONTRACT,
            evidence_repo=repo, is_local=False,
        )

    with pytest.raises(MainnetAuditRequiredError):
        _run(run())
