"""Concrete EVM ingestion connector for Stablecoin Intelligence.

Implements the ``StablecoinProviderConnector`` seam declared in ``polling.py``
for a single registered EVM stablecoin deployment. On every pull it:

* verifies the JSON-RPC connection + chain id (``eth_chainId``) — fails closed
  on a mismatch so a mis-pointed endpoint can never mint fake observations;
* reads the chain tip (``eth_blockNumber``) and applies a per-chain confirmation
  depth so only confirmed blocks are emitted;
* checks parent-hash continuity across pull boundaries and rewinds + rolls back
  on a detected reorg (reusing ``StablecoinProviderIngestionRunner.rollback_execution``);
* pulls Transfer/mint/burn logs (``eth_getLogs``) for the deployment contract
  over a BOUNDED block span (historical backfill, then live tail);
* persists a durable cursor + reorg anchor for restart-safe resume;
* classifies rate-limit / provider errors so the scheduler degrades health.

Emitted rows are plain ``ProviderObservation`` values; the scheduler feeds them
through the existing Bronze→Silver→observation normalization + finality verifier
path. This connector NEVER signs, submits, routes, or simulates a transaction.
"""
from __future__ import annotations

from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger
from shared.temporal import to_iso_utc

from .connector_base import (
    CONNECTOR_CHAIN_MISMATCH,
    ConnectorCertificationMixin,
    StablecoinConnectorCursorRepository,
    StablecoinConnectorError,
    StablecoinRpcClient,
    ZERO_TOPIC,
    decode_cursor,
    encode_cursor,
    evm_confirmations_for,
    guarded_rpc,
    hex_to_int,
    iso_from_unix,
    redact_secrets,
    topic_to_address,
)
from .ingestion import ProviderObservation
from .models import FinalityState, StablecoinDeployment, StablecoinEventType
from .providers import StablecoinProviderIngestionRunner
from .registry import PLATFORM_STABLECOIN_REGISTRY, StablecoinDeploymentRegistry

logger = get_logger("aether.stablecoins.evm_connector")

# keccak256("Transfer(address,address,uint256)")
TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

_CURSOR_VERSION = 1
_MAX_EXECUTION_HISTORY = 64


class StablecoinEVMIngestionConnector(ConnectorCertificationMixin):
    """Read-only EVM log connector for one registered stablecoin deployment."""

    domain = "stablecoin_chain"
    cert_supported_operations = (
        "connection_test",
        "chain_id_verification",
        "block_retrieval",
        "receipt_retrieval",
        "log_filtering",
        "confirmation_gating",
        "reorg_detection",
        "bounded_backfill",
        "cursor_checkpointing",
        "restart_safe_resume",
    )
    cert_unsupported_operations = (
        "transaction_execution",
        "transaction_simulation",
        "mempool_streaming",
        "trace_replay",
    )
    cert_required_endpoints = ("evm_json_rpc",)
    cert_pagination_model = "cursor"

    def __init__(
        self,
        *,
        deployment: StablecoinDeployment,
        rpc: Optional[StablecoinRpcClient] = None,
        provider: str = "stablecoin_evm_rpc",
        source_manifest_id: str = "",
        confirmations: Optional[int] = None,
        start_block: int = 0,
        max_block_span: int = 2000,
        reorg_rewind_depth: Optional[int] = None,
        cursors: Optional[StablecoinConnectorCursorRepository] = None,
        runner: Optional[StablecoinProviderIngestionRunner] = None,
        registry: Optional[StablecoinDeploymentRegistry] = None,
    ) -> None:
        if max_block_span < 1:
            raise ValueError("max_block_span must be positive")
        self.deployment = deployment
        self.chain_id = str(deployment.chain_id)
        self.network = deployment.network
        self.contract = deployment.contract_or_mint
        self.decimals = deployment.decimals
        # Protocol attributes read by StablecoinPollingScheduler.poll_provider.
        self.provider = provider
        self.source_manifest_id = source_manifest_id or f"stablecoin_evm:{deployment.deployment_id}"
        self.rpc: StablecoinRpcClient = rpc if rpc is not None else _default_rpc()
        self.confirmations = int(confirmations) if confirmations is not None else evm_confirmations_for(self.chain_id)
        self.start_block = max(0, int(start_block))
        self.max_block_span = int(max_block_span)
        self.reorg_rewind_depth = int(reorg_rewind_depth) if reorg_rewind_depth is not None else max(1, self.confirmations)
        self.cursors = cursors or StablecoinConnectorCursorRepository()
        # A dedicated runner drives reorg rollback; it shares the same durable
        # observation store as the scheduler's runner (repos share table dicts).
        self.runner = runner or StablecoinProviderIngestionRunner(registry=registry or PLATFORM_STABLECOIN_REGISTRY)
        self._chain_verified = False

    # ── public connector surface ─────────────────────────────────────────────

    async def test_connection(self) -> dict[str, Any]:
        """JSON-RPC connection test + chain-id verification (no writes)."""
        response = await guarded_rpc(self.rpc, self.chain_id, "eth_chainId", [])
        observed = self._result_int(response)
        if observed != int(self.chain_id):
            raise StablecoinConnectorError(
                CONNECTOR_CHAIN_MISMATCH,
                f"endpoint chain id {observed} != deployment chain id {self.chain_id}",
            )
        self._chain_verified = True
        return {"ok": True, "chain_id": self.chain_id, "deployment_id": self.deployment.deployment_id}

    async def fetch_observations(
        self, *, tenant_id: str, cursor: str = "", limit: int = 100
    ) -> tuple[list[ProviderObservation], str]:
        if not tenant_id:
            raise ValueError("tenant_id is required for stablecoin EVM ingestion")
        if limit < 1:
            raise ValueError("limit must be positive")

        await self._verify_chain()
        cursor_key = self._cursor_key(tenant_id)
        state = decode_cursor(cursor) or await self.cursors.load(cursor_key) or self._fresh_state()

        next_block = int(state.get("next_block", self.start_block))
        anchor_block = int(state.get("anchor_block", next_block - 1))
        anchor_hash = str(state.get("anchor_hash", ""))
        backfill_complete = bool(state.get("backfill_complete", False))
        history = list(state.get("executions", []))

        tip = await self._tip()
        safe_head = tip - self.confirmations

        # Parent-hash continuity: the child of the last processed block must
        # still declare our stored parent hash. If not, the chain reorged.
        if anchor_hash and 0 <= next_block <= tip:
            child = await self._block(next_block)
            if child is not None and str(child.get("parentHash", "")) != anchor_hash:
                next_block, anchor_block, anchor_hash, history = await self._handle_reorg(
                    tenant_id=tenant_id,
                    reorg_block=next_block,
                    anchor_block=anchor_block,
                    history=history,
                )

        if safe_head < next_block:
            # Nothing new has reached confirmation depth. This is a legitimate
            # empty result (not an unconditional one): the connector really
            # queried the tip and there is no confirmed work to do.
            new_state = self._state(next_block, anchor_block, anchor_hash, backfill_complete, safe_head, history)
            await self.cursors.save(cursor_key, new_state)
            return [], encode_cursor(new_state)

        to_block = min(next_block + self.max_block_span - 1, safe_head)
        logs = await self._logs(next_block, to_block)

        # Fetch (and cache) headers only for blocks that carry our logs — bounded
        # and gives authoritative on-chain timestamps for observed_at.
        block_cache: dict[int, dict[str, Any]] = {}
        observations: list[ProviderObservation] = []
        execution_id = f"{self.provider}:{self.deployment.deployment_id}:{next_block}-{to_block}"
        for log in logs:
            obs = self._log_to_observation(
                tenant_id=tenant_id,
                log=log,
                execution_id=execution_id,
                block_cache=block_cache,
            )
            if obs is not None:
                observations.append(obs)
        for block_number in {hex_to_int(log.get("blockNumber")) for log in logs}:
            if block_number not in block_cache:
                header = await self._block(block_number)
                if header is not None:
                    block_cache[block_number] = header
        # Re-stamp observed_at now that headers are loaded.
        observations = [self._restamp(obs, block_cache) for obs in observations]

        head_hash = await self._head_hash(to_block)
        backfill_complete = to_block >= safe_head
        if observations:
            history = (history + [{"execution_id": execution_id, "from_block": next_block, "to_block": to_block}])[
                -_MAX_EXECUTION_HISTORY:
            ]
        new_state = self._state(to_block + 1, to_block, head_hash, backfill_complete, safe_head, history)
        await self.cursors.save(cursor_key, new_state)
        return observations, encode_cursor(new_state)

    # ── reorg handling ───────────────────────────────────────────────────────

    async def _handle_reorg(
        self, *, tenant_id: str, reorg_block: int, anchor_block: int, history: list[dict[str, Any]]
    ) -> tuple[int, int, str, list[dict[str, Any]]]:
        rewind_to = max(self.start_block, reorg_block - self.reorg_rewind_depth)
        logger.warning(
            "stablecoin EVM reorg detected deployment=%s reorg_block=%s rewind_to=%s",
            self.deployment.deployment_id, reorg_block, rewind_to,
        )
        # Roll back every prior pull whose block range is now suspect, purging
        # orphaned observations through the canonical runner rollback path.
        survivors: list[dict[str, Any]] = []
        for entry in history:
            if int(entry.get("to_block", -1)) >= rewind_to:
                try:
                    await self.runner.rollback_execution(
                        tenant_id=tenant_id,
                        provider=self.provider,
                        source_execution_id=str(entry.get("execution_id", "")),
                    )
                except Exception:  # rollback is best-effort; re-emit stays idempotent
                    logger.warning("stablecoin EVM reorg rollback failed execution=%s", entry.get("execution_id"))
            else:
                survivors.append(entry)
        # Re-anchor at the block just below the rewind point (continuity check is
        # skipped for one pull while the canonical chain is re-established).
        new_anchor_hash = ""
        if rewind_to - 1 >= 0:
            prior = await self._block(rewind_to - 1)
            if prior is not None:
                new_anchor_hash = str(prior.get("hash", ""))
        return rewind_to, rewind_to - 1, new_anchor_hash, survivors

    # ── RPC helpers ──────────────────────────────────────────────────────────

    async def _verify_chain(self) -> None:
        if not self._chain_verified:
            await self.test_connection()

    async def _tip(self) -> int:
        response = await guarded_rpc(self.rpc, self.chain_id, "eth_blockNumber", [])
        return self._result_int(response)

    async def _block(self, number: int) -> Optional[dict[str, Any]]:
        response = await guarded_rpc(
            self.rpc, self.chain_id, "eth_getBlockByNumber", [hex(number), False]
        )
        result = response.get("result")
        return result if isinstance(result, dict) else None

    async def _head_hash(self, number: int) -> str:
        header = await self._block(number)
        return str(header.get("hash", "")) if header else ""

    async def get_receipt(self, tx_hash: str) -> Optional[dict[str, Any]]:
        """Retrieve a transaction receipt (``eth_getTransactionReceipt``).

        The connector's primary ingestion path is log-based, but per-observation
        receipt-status finality is delegated to ``StablecoinEVMReceiptVerifier``.
        This exposes the same read for connector-side receipt spot checks so the
        declared ``receipt_retrieval`` capability is backed by real code.
        """
        response = await guarded_rpc(self.rpc, self.chain_id, "eth_getTransactionReceipt", [tx_hash])
        result = response.get("result")
        return result if isinstance(result, dict) else None

    async def _logs(self, from_block: int, to_block: int) -> list[dict[str, Any]]:
        response = await guarded_rpc(
            self.rpc,
            self.chain_id,
            "eth_getLogs",
            [{
                "fromBlock": hex(from_block),
                "toBlock": hex(to_block),
                "address": self.contract,
                "topics": [TRANSFER_TOPIC0],
            }],
        )
        result = response.get("result")
        return list(result) if isinstance(result, list) else []

    # ── normalization ────────────────────────────────────────────────────────

    def _log_to_observation(
        self,
        *,
        tenant_id: str,
        log: dict[str, Any],
        execution_id: str,
        block_cache: dict[int, dict[str, Any]],
    ) -> Optional[ProviderObservation]:
        topics = log.get("topics") or []
        if not topics or str(topics[0]).lower() != TRANSFER_TOPIC0:
            return None
        if len(topics) < 3:
            return None  # non-standard Transfer (skip rather than misclassify)
        from_topic, to_topic = topics[1], topics[2]
        try:
            amount_atomic = hex_to_int(log.get("data", "0x0"))
            block_number = hex_to_int(log.get("blockNumber"))
            log_index = hex_to_int(log.get("logIndex", "0x0"))
        except ValueError:
            return None
        from_address = topic_to_address(from_topic)
        to_address = topic_to_address(to_topic)
        event_type = self._classify(from_topic, to_topic)
        header = block_cache.get(block_number)
        observed_at = (
            iso_from_unix(hex_to_int(header["timestamp"]))
            if header and header.get("timestamp") is not None
            else to_iso_utc(utc_now())
        )
        return ProviderObservation(
            tenant_id=tenant_id,
            provider=self.provider,
            source_record_id=f"{log.get('transactionHash', '')}:{log_index}",
            source_execution_id=execution_id,
            source_manifest_id=self.source_manifest_id,
            observed_at=observed_at,
            chain_id=self.chain_id,
            network=self.network,
            contract_or_mint=self.contract,
            transaction_hash=str(log.get("transactionHash", "")),
            amount_atomic=amount_atomic,
            from_address=from_address,
            to_address=to_address,
            log_or_instruction_index=log_index,
            event_type=event_type,
            # Only confirmed-depth logs are emitted; the finality verifier can
            # still advance CONFIRMED → FINALIZED (or REVERTED on a deep reorg).
            finality_status=FinalityState.CONFIRMED,
            raw_payload={
                "block_number": block_number,
                "block_hash": str(log.get("blockHash", "")),
                "log_index": log_index,
                "topics": [str(t) for t in topics],
                "data": str(log.get("data", "")),
            },
        )

    def _restamp(self, obs: ProviderObservation, block_cache: dict[int, dict[str, Any]]) -> ProviderObservation:
        block_number = int(obs.raw_payload.get("block_number", -1))
        header = block_cache.get(block_number)
        if not header or header.get("timestamp") is None:
            return obs
        try:
            observed_at = iso_from_unix(hex_to_int(header["timestamp"]))
        except ValueError:
            return obs
        if observed_at == obs.observed_at:
            return obs
        payload = dict(obs.raw_payload)
        payload["block_hash"] = str(header.get("hash", payload.get("block_hash", "")))
        return ProviderObservation(
            tenant_id=obs.tenant_id,
            provider=obs.provider,
            source_record_id=obs.source_record_id,
            source_execution_id=obs.source_execution_id,
            source_manifest_id=obs.source_manifest_id,
            observed_at=observed_at,
            chain_id=obs.chain_id,
            network=obs.network,
            contract_or_mint=obs.contract_or_mint,
            transaction_hash=obs.transaction_hash,
            amount_atomic=obs.amount_atomic,
            from_address=obs.from_address,
            to_address=obs.to_address,
            log_or_instruction_index=obs.log_or_instruction_index,
            event_type=obs.event_type,
            finality_status=obs.finality_status,
            raw_payload=payload,
        )

    @staticmethod
    def _classify(from_topic: Any, to_topic: Any) -> StablecoinEventType:
        from_zero = str(from_topic).lower() == ZERO_TOPIC
        to_zero = str(to_topic).lower() == ZERO_TOPIC
        if from_zero and not to_zero:
            return StablecoinEventType.MINT
        if to_zero and not from_zero:
            return StablecoinEventType.BURN
        return StablecoinEventType.TRANSFER

    # ── cursor state ─────────────────────────────────────────────────────────

    def _cursor_key(self, tenant_id: str) -> str:
        return f"evm:{tenant_id}:{self.deployment.deployment_id}"

    def _fresh_state(self) -> dict[str, Any]:
        return {
            "v": _CURSOR_VERSION,
            "vm": "evm",
            "next_block": self.start_block,
            "anchor_block": self.start_block - 1,
            "anchor_hash": "",
            "backfill_complete": False,
            "executions": [],
        }

    def _state(
        self,
        next_block: int,
        anchor_block: int,
        anchor_hash: str,
        backfill_complete: bool,
        safe_head: int,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "v": _CURSOR_VERSION,
            "vm": "evm",
            "next_block": next_block,
            "anchor_block": anchor_block,
            "anchor_hash": anchor_hash,
            "backfill_complete": backfill_complete,
            "safe_head": safe_head,
            "executions": history,
        }

    @staticmethod
    def _result_int(response: dict[str, Any]) -> int:
        result = response.get("result")
        return hex_to_int(result)

    # ── certification duck-typed hooks ───────────────────────────────────────

    def advance_cursor(self, cursor: str) -> str:
        """Move an opaque cursor strictly forward (certification hook)."""
        state = decode_cursor(cursor) or self._fresh_state()
        state = dict(state)
        state["next_block"] = int(state.get("next_block", self.start_block)) + 1
        return encode_cursor(state)

    def dedupe_key(self, event: Any) -> tuple:
        if isinstance(event, ProviderObservation):
            return (event.chain_id, event.transaction_hash, event.log_or_instruction_index)
        if isinstance(event, dict):
            if event.get("transactionHash") is not None:
                return (str(event.get("transactionHash")), str(event.get("logIndex")))
            return (str(event.get("id")), event.get("seq"))
        return (repr(event),)

    def sequence_of(self, event: Any) -> tuple:
        if isinstance(event, ProviderObservation):
            return (int(event.raw_payload.get("block_number", 0)), int(event.log_or_instruction_index or 0))
        if isinstance(event, dict):
            if event.get("blockNumber") is not None:
                try:
                    return (hex_to_int(event.get("blockNumber")), hex_to_int(event.get("logIndex", "0x0")))
                except ValueError:
                    pass
            return (int(event.get("seq") or 0), str(event.get("id") or ""))
        return (str(event),)

    def normalize(self, payload: Any) -> Optional[dict[str, Any]]:
        """Canonicalize a raw Transfer log; idempotent + drift/malformed tolerant."""
        if not isinstance(payload, dict):
            return None
        topics = payload.get("topics")
        if not isinstance(topics, list) or len(topics) < 3:
            return None
        try:
            amount_atomic = hex_to_int(payload.get("data", "0x0"))
        except ValueError:
            return None
        return {
            "transaction_hash": str(payload.get("transactionHash", "")),
            "log_index": str(payload.get("logIndex", "")),
            "from_address": topic_to_address(topics[1]),
            "to_address": topic_to_address(topics[2]),
            "amount_atomic": str(amount_atomic),
            "event_type": self._classify(topics[1], topics[2]).value,
            "contract": redact_secrets(payload).get("address", self.contract),
        }


def _default_rpc() -> StablecoinRpcClient:
    """Production RPC seam. Imported lazily so module import stays offline/light."""
    from services.onchain.rpc_gateway import RPCGateway

    return RPCGateway()


__all__ = ["StablecoinEVMIngestionConnector", "TRANSFER_TOPIC0"]
