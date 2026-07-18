"""Chain-observer chaos — RPC failure, chain reorg, cursor drift.

Drives the REAL Chainlink CCIP interop adapter (``services.interop.providers.
chainlink_ccip.ChainlinkCcipAdapter``) against an in-process fake RPC
(``MockCcipRpc`` from tests/unit/interop/ccip_fixtures.py). NO live RPC.

The fake models a chain the observer scans: ``fail_get_logs_once`` arms a
transient RPC failure (rate-limit class), rewriting ``block_hashes`` simulates a
reorg, and a checkpoint ahead of head simulates cursor corruption/drift.

Scenarios covered here:
  * RPC endpoint failure  -> scan degrades to ``rate_limited`` health, loses no
                             data, and resumes cleanly from the returned checkpoint
  * chain reorg           -> a changed block hash emits a ``reorged`` observation
                             and rewinds ``last_scanned_block`` below the fork
  * cursor corruption      -> a checkpoint ahead of head emits a ``cursor_drift``
                             reorg rather than silently skipping blocks
"""

from __future__ import annotations

from services.interop.providers.chainlink_ccip import ChainlinkCcipAdapter

from tests.unit.interop.ccip_fixtures import (
    KEY,
    SEQUENCE,
    SRC_SELECTOR,
    MockCcipRpc,
    ccip_send_requested,
)


def _lane_adapter(rpc) -> ChainlinkCcipAdapter:
    return ChainlinkCcipAdapter(
        rpc_client=rpc,
        selectors={
            SRC_SELECTOR: {"network_id": "ethereum-mainnet", "native_chain_id": "1"},
            4949039107694359620: {"network_id": "arbitrum-mainnet", "native_chain_id": "42161"},
        },
    )


# ── RPC endpoint failure -> degrade + resume ──────────────────────────────────
async def test_rpc_endpoint_failure_degrades_then_resumes():
    rpc = MockCcipRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 120}
    rpc.heads["arbitrum-mainnet"] = {"number": 0}
    rpc.logs["ethereum-mainnet"] = [ccip_send_requested(block_number=100)]
    rpc.fail_get_logs_once.add("ethereum-mainnet")  # arm one transient RPC failure
    adapter = _lane_adapter(rpc)

    # First scan hits the failing endpoint: no observations, health degraded,
    # and the checkpoint records where to resume — nothing is dropped.
    observations, checkpoint = await adapter.scan(None)
    assert observations == []
    assert any(h["state"] == "rate_limited" and h["retry_after"] == 5 for h in checkpoint["health"])

    # Second scan (the "retry after the endpoint recovered") resumes and observes.
    observations2, checkpoint2 = await adapter.scan(checkpoint)
    assert any(o["phase"] == "sent" for o in observations2)
    assert checkpoint2["networks"]["ethereum-mainnet"]["last_scanned_block"] == 105


# ── chain reorg ───────────────────────────────────────────────────────────────
async def test_chain_reorg_emits_reorged_and_rewinds_cursor():
    rpc = MockCcipRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 120}
    rpc.heads["arbitrum-mainnet"] = {"number": 0}
    rpc.logs["ethereum-mainnet"] = [ccip_send_requested(block_number=100)]
    rpc.block_hashes[("ethereum-mainnet", 105)] = "0xorig"
    adapter = _lane_adapter(rpc)
    _, checkpoint = await adapter.scan(None)

    # The chain reorganises: block 105 now has a different hash.
    rpc.block_hashes[("ethereum-mainnet", 105)] = "0xforked"
    observations, checkpoint = await adapter.scan(checkpoint)
    reorged = [o for o in observations if o["phase"] == "reorged"]
    assert reorged and reorged[0]["discontinuity_kind"] == "block_hash"
    assert checkpoint["networks"]["ethereum-mainnet"]["last_scanned_block"] < 105


# ── cursor corruption / drift ─────────────────────────────────────────────────
async def test_cursor_ahead_of_head_emits_cursor_drift_reorg():
    rpc = MockCcipRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 30}
    rpc.heads["arbitrum-mainnet"] = {"number": 0}
    adapter = _lane_adapter(rpc)
    # Corrupt checkpoint: cursor claims we already scanned block 105 but head is 30.
    corrupt = {"networks": {"ethereum-mainnet": {"last_scanned_block": 105, "recent_hashes": {}}}}
    observations, _ = await adapter.scan(corrupt)
    drift = [o for o in observations if o.get("discontinuity_kind") == "cursor_drift"]
    assert drift and drift[0]["phase"] == "reorged"


async def test_scan_is_idempotent_no_phantom_observations_on_reset():
    """Re-scanning the same window from the same checkpoint yields no new
    lifecycle observations — cursor persistence bounds re-delivery."""
    rpc = MockCcipRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 120}
    rpc.heads["arbitrum-mainnet"] = {"number": 90}
    rpc.logs["ethereum-mainnet"] = [ccip_send_requested(block_number=100)]
    adapter = _lane_adapter(rpc)
    _, checkpoint = await adapter.scan(None)
    assert checkpoint["seq_index"][f"{SRC_SELECTOR}:{SEQUENCE}"] == KEY
    # Re-scan from the advanced checkpoint: the already-scanned block is behind
    # last_scanned_block, so no phantom "sent" is re-emitted.
    observations2, _ = await adapter.scan(checkpoint)
    assert [o for o in observations2 if o["phase"] == "sent"] == []
