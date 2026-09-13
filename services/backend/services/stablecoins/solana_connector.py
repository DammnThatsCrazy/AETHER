"""Concrete SVM/Solana ingestion connector for Stablecoin Intelligence.

Implements the ``StablecoinProviderConnector`` seam for a single registered SPL
stablecoin mint using only the read-only ``sol_get*`` methods the shared
``RPCGateway`` allows. On every pull it:

* tests the RPC connection (``sol_getSlot``) and verifies cluster/genesis
  identity (``sol_getBlock(0)`` blockhash vs a configured genesis anchor);
* walks a BOUNDED slot range, retrieving confirmed blocks (``sol_getBlock``);
* gates emission at the finalized-commitment horizon (tip slot − finalized
  depth) so fork churn below commitment never surfaces an observation;
* scans each transaction's SPL instructions + token balances for the mint,
  honoring per-transaction execution status (failed txs are skipped);
* detects a fork by re-checking the anchor slot's blockhash and rewinds +
  rolls back on divergence (reusing the runner rollback path);
* persists a durable slot cursor for restart-safe resume.

Emitted rows flow through the existing normalization + Solana finality verifier
path. This connector NEVER signs, submits, or simulates a transaction.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger
from shared.temporal import to_iso_utc

from .connector_base import (
    ConnectorCertificationMixin,
    SOLANA_FINALIZED_SLOTS,
    StablecoinConnectorCursorRepository,
    StablecoinConnectorError,
    StablecoinRpcClient,
    decode_cursor,
    encode_cursor,
    guarded_rpc,
    iso_from_unix,
)
from .ingestion import ProviderObservation
from .models import FinalityState, StablecoinDeployment, StablecoinEventType
from .providers import StablecoinProviderIngestionRunner
from .registry import PLATFORM_STABLECOIN_REGISTRY, StablecoinDeploymentRegistry

logger = get_logger("aether.stablecoins.solana_connector")

_CURSOR_VERSION = 1
_MAX_EXECUTION_HISTORY = 64

_MINT_TYPES = {"mintto", "minttochecked"}
_BURN_TYPES = {"burn", "burnchecked"}
_TRANSFER_TYPES = {"transfer", "transferchecked"}


class StablecoinSolanaIngestionConnector(ConnectorCertificationMixin):
    """Read-only Solana slot connector for one registered SPL stablecoin mint."""

    domain = "stablecoin_chain"
    cert_supported_operations = (
        "connection_test",
        "cluster_genesis_verification",
        "block_retrieval",
        "transaction_retrieval",
        "commitment_gating",
        "slot_cursor",
        "fork_detection",
        "bounded_backfill",
        "restart_safe_resume",
    )
    cert_unsupported_operations = (
        "transaction_execution",
        "transaction_simulation",
        "geyser_streaming",
    )
    cert_required_endpoints = ("solana_json_rpc",)
    cert_pagination_model = "cursor"

    def __init__(
        self,
        *,
        deployment: StablecoinDeployment,
        rpc: Optional[StablecoinRpcClient] = None,
        provider: str = "stablecoin_solana_rpc",
        source_manifest_id: str = "",
        finality_threshold_slots: int = SOLANA_FINALIZED_SLOTS,
        start_slot: int = 0,
        max_slot_span: int = 512,
        fork_rewind_slots: Optional[int] = None,
        expected_genesis_hash: str = "",
        cursors: Optional[StablecoinConnectorCursorRepository] = None,
        runner: Optional[StablecoinProviderIngestionRunner] = None,
        registry: Optional[StablecoinDeploymentRegistry] = None,
    ) -> None:
        if max_slot_span < 1:
            raise ValueError("max_slot_span must be positive")
        if finality_threshold_slots < 1:
            raise ValueError("finality_threshold_slots must be positive")
        if not deployment.token_standard.lower().startswith("spl"):
            raise ValueError("Solana ingestion requires an SPL-token stablecoin deployment")
        self.deployment = deployment
        self.chain_id = str(deployment.chain_id)
        self.network = deployment.network
        self.mint = deployment.contract_or_mint
        self.decimals = deployment.decimals
        self.provider = provider
        self.source_manifest_id = source_manifest_id or f"stablecoin_solana:{deployment.deployment_id}"
        self.rpc: StablecoinRpcClient = rpc if rpc is not None else _default_rpc()
        self.finality_threshold_slots = int(finality_threshold_slots)
        self.start_slot = max(0, int(start_slot))
        self.max_slot_span = int(max_slot_span)
        self.fork_rewind_slots = int(fork_rewind_slots) if fork_rewind_slots is not None else max(1, self.finality_threshold_slots)
        self.expected_genesis_hash = expected_genesis_hash
        self.cursors = cursors or StablecoinConnectorCursorRepository()
        self.runner = runner or StablecoinProviderIngestionRunner(registry=registry or PLATFORM_STABLECOIN_REGISTRY)
        self._genesis_verified = False

    # ── public connector surface ─────────────────────────────────────────────

    async def test_connection(self) -> dict[str, Any]:
        """RPC connection test + cluster/genesis identity verification."""
        await self._tip_slot()  # proves the endpoint answers
        genesis_ok = await self._verify_genesis()
        return {
            "ok": True,
            "chain_id": self.chain_id,
            "deployment_id": self.deployment.deployment_id,
            "genesis_verified": genesis_ok,
        }

    async def fetch_observations(
        self, *, tenant_id: str, cursor: str = "", limit: int = 100
    ) -> tuple[list[ProviderObservation], str]:
        if not tenant_id:
            raise ValueError("tenant_id is required for stablecoin Solana ingestion")
        if limit < 1:
            raise ValueError("limit must be positive")

        await self._verify_genesis()
        cursor_key = self._cursor_key(tenant_id)
        state = decode_cursor(cursor) or await self.cursors.load(cursor_key) or self._fresh_state()

        next_slot = int(state.get("next_slot", self.start_slot))
        anchor_slot = int(state.get("anchor_slot", -1))
        anchor_hash = str(state.get("anchor_hash", ""))
        history = list(state.get("executions", []))

        # Fork detection: re-fetch the last processed block; if its blockhash
        # changed (or the slot was orphaned) the cluster forked below where we
        # thought commitment held.
        if anchor_hash and anchor_slot >= 0:
            current = await self._block(anchor_slot)
            current_hash = str(current.get("blockhash", "")) if current else ""
            if current_hash != anchor_hash:
                next_slot, anchor_slot, anchor_hash, history = await self._handle_fork(
                    tenant_id=tenant_id, fork_slot=anchor_slot, history=history
                )

        tip = await self._tip_slot()
        safe_slot = tip - self.finality_threshold_slots
        if safe_slot < next_slot:
            new_state = self._state(next_slot, anchor_slot, anchor_hash, safe_slot, history)
            await self.cursors.save(cursor_key, new_state)
            return [], encode_cursor(new_state)

        to_slot = min(next_slot + self.max_slot_span - 1, safe_slot)
        execution_id = f"{self.provider}:{self.deployment.deployment_id}:{next_slot}-{to_slot}"
        observations: list[ProviderObservation] = []
        last_hash = anchor_hash
        last_slot = anchor_slot
        for slot in range(next_slot, to_slot + 1):
            block = await self._block(slot)
            if not block:
                continue  # skipped/leaderless slot — legitimate gap on Solana
            last_hash = str(block.get("blockhash", last_hash))
            last_slot = slot
            observations.extend(self._block_to_observations(tenant_id, slot, block, execution_id))

        if observations:
            history = (history + [{"execution_id": execution_id, "from_slot": next_slot, "to_slot": to_slot}])[
                -_MAX_EXECUTION_HISTORY:
            ]
        new_state = self._state(to_slot + 1, last_slot, last_hash, safe_slot, history)
        await self.cursors.save(cursor_key, new_state)
        return observations, encode_cursor(new_state)

    # ── fork handling ────────────────────────────────────────────────────────

    async def _handle_fork(
        self, *, tenant_id: str, fork_slot: int, history: list[dict[str, Any]]
    ) -> tuple[int, int, str, list[dict[str, Any]]]:
        rewind_to = max(self.start_slot, fork_slot - self.fork_rewind_slots)
        logger.warning(
            "stablecoin Solana fork detected deployment=%s fork_slot=%s rewind_to=%s",
            self.deployment.deployment_id, fork_slot, rewind_to,
        )
        survivors: list[dict[str, Any]] = []
        for entry in history:
            if int(entry.get("to_slot", -1)) >= rewind_to:
                try:
                    await self.runner.rollback_execution(
                        tenant_id=tenant_id,
                        provider=self.provider,
                        source_execution_id=str(entry.get("execution_id", "")),
                    )
                except Exception:
                    logger.warning("stablecoin Solana fork rollback failed execution=%s", entry.get("execution_id"))
            else:
                survivors.append(entry)
        return rewind_to, -1, "", survivors

    # ── RPC helpers ──────────────────────────────────────────────────────────

    async def _verify_genesis(self) -> bool:
        if self._genesis_verified:
            return True
        if not self.expected_genesis_hash:
            # Honest: cluster identity cannot be pinned without a configured
            # genesis anchor. We do not silently trust the endpoint.
            logger.warning(
                "stablecoin Solana connector deployment=%s has no expected_genesis_hash; "
                "cluster identity unverified", self.deployment.deployment_id,
            )
            return False
        genesis = await self._block(0)
        observed = str(genesis.get("blockhash", "")) if genesis else ""
        if observed != self.expected_genesis_hash:
            raise StablecoinConnectorError(
                "chain_mismatch",
                f"genesis blockhash {observed!r} != expected {self.expected_genesis_hash!r}",
            )
        self._genesis_verified = True
        return True

    async def _tip_slot(self) -> int:
        response = await guarded_rpc(self.rpc, self.chain_id, "sol_getSlot", [], vm_type="solana")
        result = response.get("result")
        if result is None:
            raise StablecoinConnectorError("bad_response", "sol_getSlot returned no result")
        return int(result)

    async def _block(self, slot: int) -> Optional[dict[str, Any]]:
        response = await guarded_rpc(
            self.rpc,
            self.chain_id,
            "sol_getBlock",
            [slot, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "transactionDetails": "full", "rewards": False}],
            vm_type="solana",
        )
        result = response.get("result")
        return result if isinstance(result, dict) else None

    # ── normalization ────────────────────────────────────────────────────────

    def _block_to_observations(
        self, tenant_id: str, slot: int, block: dict[str, Any], execution_id: str
    ) -> list[ProviderObservation]:
        observed_at = (
            iso_from_unix(block["blockTime"]) if block.get("blockTime") is not None else to_iso_utc(utc_now())
        )
        block_hash = str(block.get("blockhash", ""))
        out: list[ProviderObservation] = []
        for tx in block.get("transactions") or []:
            meta = tx.get("meta") or {}
            if meta.get("err") is not None:
                continue  # failed transaction — not an observed movement
            signature = self._signature(tx)
            for transfer in self._extract_mint_transfers(tx):
                out.append(ProviderObservation(
                    tenant_id=tenant_id,
                    provider=self.provider,
                    source_record_id=f"{signature}:{transfer['index']}",
                    source_execution_id=execution_id,
                    source_manifest_id=self.source_manifest_id,
                    observed_at=observed_at,
                    chain_id=self.chain_id,
                    network=self.network,
                    contract_or_mint=self.mint,
                    transaction_hash=signature,
                    amount_atomic=transfer["amount_atomic"],
                    from_address=transfer["from_address"],
                    to_address=transfer["to_address"],
                    log_or_instruction_index=transfer["index"],
                    event_type=transfer["event_type"],
                    finality_status=FinalityState.CONFIRMED,
                    raw_payload={
                        "slot": slot,
                        "block_hash": block_hash,
                        "instruction_index": transfer["index"],
                        "instruction_type": transfer["type"],
                    },
                ))
        return out

    def _extract_mint_transfers(self, tx: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Return one record per SPL instruction that moves our mint."""
        message = ((tx.get("transaction") or {}).get("message") or {})
        instructions = list(message.get("instructions") or [])
        meta = tx.get("meta") or {}
        for group in meta.get("innerInstructions") or []:
            instructions.extend(group.get("instructions") or [])
        balances_have_mint = any(
            str(b.get("mint", "")).lower() == self.mint.lower()
            for b in list(meta.get("preTokenBalances") or []) + list(meta.get("postTokenBalances") or [])
        )
        out: list[dict[str, Any]] = []
        for index, instruction in enumerate(instructions):
            parsed = instruction.get("parsed") if isinstance(instruction, Mapping) else None
            if not isinstance(parsed, Mapping):
                continue
            ptype = str(parsed.get("type", "")).lower()
            info = parsed.get("info") if isinstance(parsed.get("info"), Mapping) else {}
            record = self._parse_instruction(ptype, info, index, balances_have_mint)
            if record is not None:
                out.append(record)
        return out

    def _parse_instruction(
        self, ptype: str, info: Mapping[str, Any], index: int, balances_have_mint: bool
    ) -> Optional[dict[str, Any]]:
        expected = self.mint.lower()
        instr_mint = str(info.get("mint", "")).lower()
        if ptype in _TRANSFER_TYPES:
            # transferChecked carries the mint; plain transfer is matched via the
            # transaction's token balances (deterministic mint confirmation).
            if instr_mint and instr_mint != expected:
                return None
            if not instr_mint and not balances_have_mint:
                return None
            amount = self._amount(info)
            if amount is None:
                return None
            return {
                "index": index, "type": ptype, "event_type": StablecoinEventType.TRANSFER,
                "amount_atomic": amount,
                "from_address": str(info.get("source", "")),
                "to_address": str(info.get("destination", "")),
            }
        if ptype in _MINT_TYPES:
            if instr_mint != expected:
                return None
            amount = self._amount(info)
            if amount is None:
                return None
            return {
                "index": index, "type": ptype, "event_type": StablecoinEventType.MINT,
                "amount_atomic": amount, "from_address": "",
                "to_address": str(info.get("account", "")),
            }
        if ptype in _BURN_TYPES:
            if instr_mint != expected:
                return None
            amount = self._amount(info)
            if amount is None:
                return None
            return {
                "index": index, "type": ptype, "event_type": StablecoinEventType.BURN,
                "amount_atomic": amount,
                "from_address": str(info.get("account", "")), "to_address": "",
            }
        return None

    @staticmethod
    def _amount(info: Mapping[str, Any]) -> Optional[int]:
        token_amount = info.get("tokenAmount")
        if isinstance(token_amount, Mapping) and token_amount.get("amount") is not None:
            try:
                return int(token_amount["amount"])
            except (ValueError, TypeError):
                return None
        raw = info.get("amount")
        if raw is None:
            return None
        try:
            return int(raw)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _signature(tx: Mapping[str, Any]) -> str:
        signatures = ((tx.get("transaction") or {}).get("signatures")) or []
        return str(signatures[0]) if signatures else ""

    # ── cursor state ─────────────────────────────────────────────────────────

    def _cursor_key(self, tenant_id: str) -> str:
        return f"solana:{tenant_id}:{self.deployment.deployment_id}"

    def _fresh_state(self) -> dict[str, Any]:
        return {
            "v": _CURSOR_VERSION,
            "vm": "solana",
            "next_slot": self.start_slot,
            "anchor_slot": -1,
            "anchor_hash": "",
            "executions": [],
        }

    def _state(
        self, next_slot: int, anchor_slot: int, anchor_hash: str, safe_slot: int, history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "v": _CURSOR_VERSION,
            "vm": "solana",
            "next_slot": next_slot,
            "anchor_slot": anchor_slot,
            "anchor_hash": anchor_hash,
            "safe_slot": safe_slot,
            "executions": history,
        }

    # ── certification duck-typed hooks ───────────────────────────────────────

    def advance_cursor(self, cursor: str) -> str:
        state = dict(decode_cursor(cursor) or self._fresh_state())
        state["next_slot"] = int(state.get("next_slot", self.start_slot)) + 1
        return encode_cursor(state)

    def dedupe_key(self, event: Any) -> tuple:
        if isinstance(event, ProviderObservation):
            return (event.chain_id, event.transaction_hash, event.log_or_instruction_index)
        if isinstance(event, dict):
            if event.get("signature") is not None:
                return (str(event.get("signature")), event.get("index"))
            return (str(event.get("id")), event.get("seq"))
        return (repr(event),)

    def sequence_of(self, event: Any) -> tuple:
        if isinstance(event, ProviderObservation):
            return (int(event.raw_payload.get("slot", 0)), int(event.log_or_instruction_index or 0))
        if isinstance(event, dict):
            if event.get("slot") is not None:
                try:
                    return (int(event.get("slot")), int(event.get("index") or 0))
                except (ValueError, TypeError):
                    pass
            return (int(event.get("seq") or 0), str(event.get("id") or ""))
        return (str(event),)

    def normalize(self, payload: Any) -> Optional[dict[str, Any]]:
        """Canonicalize a jsonParsed SPL instruction; drift/malformed tolerant."""
        if not isinstance(payload, dict):
            return None
        parsed = payload.get("parsed")
        if not isinstance(parsed, Mapping):
            return None
        ptype = str(parsed.get("type", "")).lower()
        info = parsed.get("info") if isinstance(parsed.get("info"), Mapping) else {}
        amount = self._amount(info)
        if amount is None or ptype not in (_TRANSFER_TYPES | _MINT_TYPES | _BURN_TYPES):
            return None
        return {
            "type": ptype,
            "amount_atomic": str(amount),
            "mint": str(info.get("mint", "")),
            "source": str(info.get("source", info.get("account", ""))),
            "destination": str(info.get("destination", info.get("account", ""))),
        }


def _default_rpc() -> StablecoinRpcClient:
    from services.onchain.rpc_gateway import RPCGateway

    return RPCGateway()


__all__ = ["StablecoinSolanaIngestionConnector"]
