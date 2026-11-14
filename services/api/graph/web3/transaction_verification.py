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

from graph.onchain.rpc_gateway import RPCGateway
from graph.web3.registries import ChainRegistry, Web3ObservationRepository


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
        # EVM transaction IDs are hexadecimal and case-insensitive. Solana and
        # Sui signatures/digests are Base58 and case-sensitive.
        canonical_hash = (
            transaction_hash.lower()
            if transaction_hash.startswith(("0x", "0X"))
            else transaction_hash
        )
        key = f"{tenant_id}:{chain_id}:{canonical_hash}"
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
        if vm not in {"evm", "svm", "movevm"}:
            raise ValueError("vm_family must be 'evm', 'svm', or 'movevm' (Sui)")
        if finality_threshold < 1:
            raise ValueError("finality_threshold must be positive")

        chain = await self.chains.for_tenant(tenant_id).get_by_chain_id(chain_id)
        if not chain:
            raise LookupError("chain is not registered for this tenant")
        registered_vm = str(chain.get("vm_family") or "").lower()
        if registered_vm and registered_vm != vm:
            raise ValueError("vm_family does not match the registered chain")
        if vm == "movevm" and (
            not chain_id.lower().startswith("sui:")
            or "sui" not in str(chain.get("canonical_name") or "").lower()
        ):
            raise ValueError("movevm transaction verification currently supports Sui network IDs only")

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
        elif vm == "svm":
            result = await self._verify_solana(
                rpc, tenant_id, chain_id, transaction_hash, source_observation,
                chain.get("genesis_hash"),
            )
        else:
            result = await self._verify_sui(
                rpc, tenant_id, chain_id, transaction_hash, source_observation,
                chain.get("sui_chain_identifier"),
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

    async def _verify_sui(self, rpc, tenant_id, chain_id, digest, source, expected_chain_identifier):
        evidence: dict[str, Any] = {
            "rpc_method": "sui_graphql_transaction",
            "chain_id": chain_id,
            "finality_model": "checkpoint",
        }
        if not expected_chain_identifier:
            return TransactionVerification(
                tenant_id, chain_id, digest, "movevm", "mismatch", "unknown", 0,
                source.get("source_event_id"),
                {**evidence, "mismatch": "missing_registry_chain_identifier"},
            )

        response = await rpc.execute_sui_transaction(
            tenant_id=tenant_id, chain_id=chain_id, digest=digest,
        )
        chain_identifier = str(response.get("chain_identifier") or "")
        evidence.update({
            "expected_chain_identifier": str(expected_chain_identifier),
            "rpc_chain_identifier": chain_identifier or None,
        })
        if not _sui_chain_identifiers_match(str(expected_chain_identifier), chain_identifier):
            return TransactionVerification(
                tenant_id, chain_id, digest, "movevm", "mismatch", "unknown", 0,
                source.get("source_event_id"),
                {**evidence, "mismatch": "chain_identifier"},
            )

        tx = response.get("transaction")
        if tx is None:
            return TransactionVerification(
                tenant_id, chain_id, digest, "movevm", "pending", "unknown", 0,
                source.get("source_event_id"), evidence,
            )
        if not isinstance(tx, dict) or str(tx.get("digest") or "") != digest:
            return TransactionVerification(
                tenant_id, chain_id, digest, "movevm", "mismatch", "unknown", 0,
                source.get("source_event_id"),
                {**evidence, "mismatch": "transaction_digest"},
            )

        sender_value = tx.get("sender")
        rpc_sender = (
            sender_value.get("address")
            if isinstance(sender_value, dict)
            else sender_value
        )
        expected_sender = str(source.get("from_address") or "")
        if expected_sender and (
            not rpc_sender or not _sui_addresses_match(expected_sender, str(rpc_sender))
        ):
            return TransactionVerification(
                tenant_id, chain_id, digest, "movevm", "mismatch", "unknown", 0,
                source.get("source_event_id"),
                {**evidence, "mismatch": "sender", "observed_sender": expected_sender,
                 "rpc_sender": str(rpc_sender)},
            )

        effects = tx.get("effects") if isinstance(tx.get("effects"), dict) else {}
        execution_result = str(effects.get("status") or "").upper()
        if execution_result not in {"SUCCESS", "FAILURE"}:
            return TransactionVerification(
                tenant_id, chain_id, digest, "movevm", "mismatch", "unknown", 0,
                source.get("source_event_id"),
                {**evidence, "mismatch": "missing_execution_status"},
            )

        checkpoint = effects.get("checkpoint")
        checkpoint_number = (
            _optional_nonnegative_int(checkpoint.get("sequenceNumber"))
            if isinstance(checkpoint, dict)
            else None
        )
        failed = execution_result == "FAILURE"
        return TransactionVerification(
            tenant_id, chain_id, digest, "movevm", "finalized",
            "failed" if failed else "succeeded", 0,
            source.get("source_event_id"),
            {**evidence, "execution_status": execution_result.lower(),
             "checkpoint_sequence": checkpoint_number},
        )

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


def _optional_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _decode_base58(value: str) -> bytes | None:
    number = 0
    for char in value:
        digit = _BASE58_ALPHABET.find(char)
        if digit < 0:
            return None
        number = number * 58 + digit
    encoded = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\x00" * (len(value) - len(value.lstrip("1"))) + encoded


def _sui_chain_identifiers_match(expected: str, actual: str) -> bool:
    expected_clean = expected.strip()
    actual_clean = actual.strip()
    if not expected_clean or not actual_clean:
        return False
    # Full Sui chain identifiers use case-sensitive Base58. Only the compact
    # eight-character hexadecimal seed form is case-insensitive.
    if expected_clean == actual_clean:
        return True

    expected_is_short_hex = len(expected_clean) == 8 and all(
        char in "0123456789abcdefABCDEF" for char in expected_clean
    )
    actual_is_short_hex = len(actual_clean) == 8 and all(
        char in "0123456789abcdefABCDEF" for char in actual_clean
    )
    if expected_is_short_hex and actual_is_short_hex:
        return expected_clean.lower() == actual_clean.lower()
    if expected_is_short_hex:
        actual_bytes = _decode_base58(actual_clean)
        return actual_bytes is not None and actual_bytes[:4].hex() == expected_clean.lower()
    if actual_is_short_hex:
        expected_bytes = _decode_base58(expected_clean)
        return expected_bytes is not None and expected_bytes[:4].hex() == actual_clean.lower()

    return False


def _sui_addresses_match(expected: str, actual: str) -> bool:
    def normalize(value: str) -> str:
        candidate = value.strip().lower()
        if candidate.startswith("0x"):
            candidate = candidate[2:]
        return candidate.rjust(64, "0")

    return normalize(expected) == normalize(actual)
