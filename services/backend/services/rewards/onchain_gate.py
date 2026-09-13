"""
Aether Backend — EVM mainnet reward activation gate.

Blocks activation of an EVM **mainnet** ``onchain_claim`` reward unless a
recorded external-audit-evidence entry exists for the
(tenant, chain_id, contract_address) being activated. Local and testnet
activations are unaffected.

This is a typed gate: callers get :class:`MainnetAuditRequiredError` (an
``HTTPException``-friendly value carrying a 403 status) when evidence is
missing, so the onchain path fails closed rather than silently signing a
mainnet proof for an unaudited contract.
"""

from __future__ import annotations

import os
from typing import Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.rewards.onchain_gate")


# Well-known EVM *mainnet* chain ids. Testnets and local chains are intentionally
# excluded so they are never gated. Override with REWARD_EVM_MAINNET_CHAIN_IDS
# (comma-separated) to add/replace the set for a given deployment.
_DEFAULT_EVM_MAINNET_CHAIN_IDS: frozenset[int] = frozenset({
    1,       # Ethereum
    10,      # Optimism
    56,      # BNB Smart Chain
    100,     # Gnosis
    137,     # Polygon PoS
    250,     # Fantom
    324,     # zkSync Era
    5000,    # Mantle
    8453,    # Base
    42161,   # Arbitrum One
    43114,   # Avalanche C-Chain
    59144,   # Linea
    534352,  # Scroll
    81457,   # Blast
})


class MainnetAuditRequiredError(Exception):
    """Raised when an EVM mainnet reward activation lacks external-audit evidence."""

    status_code = 403

    def __init__(self, chain_id: int, contract_address: str) -> None:
        self.chain_id = chain_id
        self.contract_address = contract_address
        super().__init__(
            f"EVM mainnet reward activation blocked: no external-audit-evidence "
            f"entry recorded for chain_id={chain_id} contract={contract_address!r}. "
            f"Record audit evidence via POST /v1/rewards/audit-evidence before "
            f"activating mainnet on-chain rewards."
        )


def evm_mainnet_chain_ids() -> frozenset[int]:
    raw = os.getenv("REWARD_EVM_MAINNET_CHAIN_IDS", "").strip()
    if not raw:
        return _DEFAULT_EVM_MAINNET_CHAIN_IDS
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            logger.warning("ignoring non-integer REWARD_EVM_MAINNET_CHAIN_IDS entry %r", part)
    return frozenset(ids) if ids else _DEFAULT_EVM_MAINNET_CHAIN_IDS


def is_evm_mainnet(chain_id: Optional[int]) -> bool:
    if chain_id is None:
        return False
    try:
        return int(chain_id) in evm_mainnet_chain_ids()
    except (TypeError, ValueError):
        return False


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() in ("local", "test")


async def assert_mainnet_audit_evidence(
    *,
    tenant_id: str,
    chain_id: Optional[int],
    contract_address: str,
    evidence_repo,
    is_local: Optional[bool] = None,
) -> None:
    """Fail closed when an EVM mainnet activation lacks recorded audit evidence.

    No-op for local/test environments and for any non-mainnet (testnet/local)
    chain. For a mainnet chain, requires a non-revoked evidence entry matching
    (tenant, chain_id, contract_address).
    """
    local = _is_local_env() if is_local is None else is_local
    if local:
        return
    if not is_evm_mainnet(chain_id):
        return

    entry = None
    try:
        entry = await evidence_repo.find_active(tenant_id, int(chain_id), contract_address)
    except Exception as exc:  # fail closed on lookup error
        logger.warning("audit-evidence lookup failed (blocking mainnet activation): %s", exc)
        entry = None

    if entry is None:
        metrics.increment(
            "rewards_mainnet_audit_gate_blocked",
            labels={"tenant_id": tenant_id, "chain_id": str(chain_id)},
        )
        raise MainnetAuditRequiredError(int(chain_id), contract_address)

    logger.info(
        "mainnet audit gate passed tenant=%s chain_id=%s contract=%s evidence=%s",
        tenant_id, chain_id, contract_address, entry.get("id"),
    )
