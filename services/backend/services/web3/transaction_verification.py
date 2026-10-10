"""Read-only chain verification for SDK-observed Web3 transactions.

SDK observations establish that a client reported a wallet transaction. This
service checks that report against tenant-scoped RPC and stores separate
execution evidence. It deliberately does not create payment or settlement facts.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from services.onchain.rpc_gateway import RPCGateway
from services.web3.registries import ChainRegistry, Web3ObservationRepository


@dataclass(frozen=True)
class TransactionVerification:
    tenant_id: str
    chain_id: str
    transaction_hash: str
    vm_family: str
    status: str
    execution_status: str
    confirmations: int
    source_event_id: str | None
    evidence: dict[str, Any]


class SDKTransactionVerifier:
    """Verify a stored SDK transaction observation using read-only RPC."""

    def __init__(self, *, rpc: RPCGateway | None = None, observations=None, chains=None) -> None:
        self.rpc = rpc
        self.observations = observations or Web3ObservationRepository()
        self.chains = chains or ChainRegistry()

    @staticmethod
    def record_id(tenant_id: str, chain_id: str, transaction_hash: str) -> str:
        key = f"{tenant_id}:{chain_id}:{transaction_hash.lower()}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"aether:web3-verification:{key}"))

    async def verify(
        self,
        *,
        tenant_id: str,
        chain_id: str,
        transaction_hash: str,
        vm_family: str,
        source_observation: dict[str, Any],
        finality_threshold: int = 12,
    ) -> TransactionVerification:
        if not tenant_id or not chain_id or not transaction_hash:
            raise ValueError("tenant_id, chain_id, and transaction_hash are required")
        vm = vm_family.lower()
        if vm not in {"evm", "svm"}:
            raise ValueError("vm_family must be 'evm' or 'svm'")
        if finality_threshold < 1:
            raise ValueError("finality_threshold must be positive")

        chain = await self.chains.for_tenant(tenant_id).get_by_chain_id(chain_id)
        if not chain:
            raise LookupError("chain is not registered for this tenant")
        registered_vm = str(chain.get("vm_family") or "").lower()
        if registered_vm and registered_vm != vm:
            raise ValueError("vm_family does not match the registered chain")

        rpc = self.rpc or await RPCGateway.for_tenant(tenant_id, chain_id)
        if vm == "evm":
            result = await self._verify_evm(
                rpc,
                tenant_id,
                chain_id,
                transaction_hash,
                source_observation,
                finality_threshold,
                chain.get("evm_chain_id"),
            )
        else:
            result = await self._verify_solana(
                rpc, tenant_id, chain_id, transaction_hash, source_observation,
                chain.get("genesis_hash"),
            )
        await self._persist(result)
        return result

    async def _verify_evm(self, rpc, tenant_id, chain_id, tx_hash, source, threshold, registered_chain_id):
        expected_chain = _parse_chain_id(chain_id)
        if expected_chain is None and registered_chain_id is not None:
            expected_chain = _parse_hex_int(registered_chain_id)
        rpc_chain = _parse_hex_int((await rpc.execute(
            chain_id, "eth_chainId", [], vm_type="evm"
        )).get("result"))
        if expected_chain is None or rpc_chain != expected_chain:
            return TransactionVerification(tenant_id, chain_id, tx_hash, "evm", "mismatch",
                                           "unknown", 0, source.get("source_event_id"),
                                           {"mismatch": "rpc_chain_id", "expected_chain_id": expected_chain,
                                            "rpc_chain_id": rpc_chain})
        tx_response = await rpc.execute(chain_id, "eth_getTransactionByHash", [tx_hash], vm_type="evm")
        tx = tx_response.get("result") if isinstance(tx_response, dict) else None
        evidence: dict[str, Any] = {"rpc_method": "eth_getTransactionReceipt", "chain_id": chain_id}
        expected_from = str(source.get("from_address") or "").lower()
        if tx is None:
            return TransactionVerification(tenant_id, chain_id, tx_hash, "evm", "pending",
                                           "unknown", 0, source.get("source_event_id"), evidence)
        if not isinstance(tx, dict):
            return TransactionVerification(tenant_id, chain_id, tx_hash, "evm", "mismatch",
                                           "unknown", 0, source.get("source_event_id"),
                                           {**evidence, "mismatch": "invalid_transaction_response"})

        rpc_hash = str(tx.get("hash") or "").lower()
        if rpc_hash != tx_hash.lower():
            return TransactionVerification(tenant_id, chain_id, tx_hash, "evm", "mismatch",
                                           "unknown", 0, source.get("source_event_id"),
                                           {**evidence, "mismatch": "transaction_hash"})
        actual_from = str(tx.get("from") or "").lower()
        if expected_from and expected_from != actual_from:
            return TransactionVerification(tenant_id, chain_id, tx_hash, "evm", "mismatch",
                                           "unknown", 0, source.get("source_event_id"),
                                           {**evidence, "mismatch": "sender", "observed_sender": expected_from,
                                            "rpc_sender": actual_from})
        tx_chain = (
            _parse_hex_int(tx.get("chainId"))
            if tx.get("chainId") is not None
            else None
        )
        if tx_chain is not None and expected_chain != tx_chain:
            return TransactionVerification(tenant_id, chain_id, tx_hash, "evm", "mismatch",
                                           "unknown", 0, source.get("source_event_id"),
                                           {**evidence, "mismatch": "chain_id", "observed_chain_id": expected_chain,
                                            "rpc_chain_id": tx_chain})

        receipt_response = await rpc.execute(chain_id, "eth_getTransactionReceipt", [tx_hash], vm_type="evm")
        receipt = receipt_response.get("result") if isinstance(receipt_response, dict) else None
        if not isinstance(receipt, dict):
            return TransactionVerification(tenant_id, chain_id, tx_hash, "evm", "pending",
                                           "unknown", 0, source.get("source_event_id"), evidence)
        receipt_hash = str(receipt.get("transactionHash") or "").lower()
        if receipt_hash and receipt_hash != tx_hash.lower():
            return TransactionVerification(tenant_id, chain_id, tx_hash, "evm", "mismatch",
                                           "unknown", 0, source.get("source_event_id"),
                                           {**evidence, "mismatch": "receipt_hash"})
        receipt_status = _parse_hex_int(receipt.get("status"))
        block_number = _parse_hex_int(receipt.get("blockNumber"))
        if receipt_status == 0:
            return TransactionVerification(tenant_id, chain_id, tx_hash, "evm", "failed",
                                           "failed", 0, source.get("source_event_id"),
                                           {**evidence, "receipt_block": block_number, "receipt_status": "0x0"})
        tip_response = await rpc.execute(chain_id, "eth_blockNumber", [], vm_type="evm")
        tip = _parse_hex_int((tip_response or {}).get("result"))
        confirmations = max(0, tip - block_number + 1)
        status = "finalized" if confirmations >= threshold else "confirmed"
        return TransactionVerification(tenant_id, chain_id, tx_hash, "evm", status,
                                       "succeeded", confirmations, source.get("source_event_id"),
                                       {**evidence, "receipt_block": block_number, "tip_block": tip,
                                        "receipt_status": "0x1", "finality_threshold": threshold})

    async def _verify_solana(self, rpc, tenant_id, chain_id, signature, source, expected_genesis_hash):
        evidence: dict[str, Any] = {"rpc_method": "sol_getTransaction", "chain_id": chain_id,
                                    "commitment": "finalized"}
        if expected_genesis_hash:
            genesis_response = await rpc.execute(chain_id, "sol_getGenesisHash", [], vm_type="solana")
            genesis_hash = (genesis_response or {}).get("result")
            if genesis_hash != expected_genesis_hash:
                return TransactionVerification(tenant_id, chain_id, signature, "svm", "mismatch",
                                               "unknown", 0, source.get("source_event_id"),
                                               {**evidence, "mismatch": "genesis_hash"})
        response = await rpc.execute(
            chain_id, "sol_getTransaction",
            [signature, {"encoding": "jsonParsed", "commitment": "finalized",
                         "maxSupportedTransactionVersion": 0}],
            vm_type="solana",
        )
        tx = response.get("result") if isinstance(response, dict) else None
        if not isinstance(tx, dict):
            return TransactionVerification(tenant_id, chain_id, signature, "svm", "pending",
                                           "unknown", 0, source.get("source_event_id"), evidence)
        signatures = (((tx.get("transaction") or {}).get("signatures")) or [])
        if signatures and signature not in signatures:
            return TransactionVerification(tenant_id, chain_id, signature, "svm", "mismatch",
                                           "unknown", 0, source.get("source_event_id"),
                                           {**evidence, "mismatch": "signature"})
        failed = (tx.get("meta") or {}).get("err") is not None
        slot = tx.get("slot")
        return TransactionVerification(tenant_id, chain_id, signature, "svm",
                                       "failed" if failed else "finalized",
                                       "failed" if failed else "succeeded", 0,
                                       source.get("source_event_id"),
                                       {**evidence, "slot": int(slot) if slot is not None else None,
                                        "error": (tx.get("meta") or {}).get("err") if failed else None})

    async def _persist(self, result: TransactionVerification) -> None:
        # A deterministic tenant-and-chain scoped key makes rechecks update the
        # same evidence row while preserving the original Silver assertion.
        record_id = self.record_id(result.tenant_id, result.chain_id, result.transaction_hash)
        data = {
            "observation_id": record_id,
            "observation_type": "sdk_transaction_verification",
            "chain_id": result.chain_id,
            "transaction_hash": result.transaction_hash,
            "vm_family": result.vm_family,
            "verification_status": result.status,
            "execution_status": result.execution_status,
            "confirmations": result.confirmations,
            "source_event_id": result.source_event_id,
            "evidence": result.evidence,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "settlement_status": "unverified_by_this_check",
            "graph_projection": False,
        }
        await self.observations.for_tenant(result.tenant_id).upsert(record_id, data, result.tenant_id)


def _parse_hex_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("invalid RPC integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 16) if value.startswith("0x") else int(value)
    raise ValueError("RPC response is missing an integer value")


def _parse_chain_id(value: str) -> int | None:
    candidate = value.lower()
    if candidate.startswith("eip155:"):
        candidate = candidate.split(":", 1)[1]
    try:
        return int(candidate, 0) if candidate.startswith("0x") else int(candidate)
    except ValueError:
        return None
