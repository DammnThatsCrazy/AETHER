"""Aether Service — Commerce & Reward Rail Support Matrix.

Canonical, data-driven answer to *"which rail can I use, and where?"*.

Every rail that can be configured anywhere in the platform reports exactly one
of four support buckets — never silent:

    SUPPORTED_PRODUCTION       — the rail is wired, exercised, and safe to run
                                 against real funds/accounts in production.
    SUPPORTED_SANDBOX          — the rail is wired and exercised but only for
                                 sandbox/testnet/devnet targets; production
                                 activation is blocked.
    SUPPORTED_BETA             — the rail exists and can be built/exported but
                                 is not yet production-warrantied (validation
                                 or delivery may be stubbed / operator-gated).
    INTENTIONALLY_UNSUPPORTED  — the rail is a real-world target we deliberately
                                 refuse to support (no silent no-op, no silent
                                 fallback). Any configured use must fail loudly.

``classify_rail`` raises :class:`UnknownRailError` for anything not declared,
so a mis-configured rail can never resolve to "silently supported".

Native rails are the Aether-first-party rails: the x402 stablecoin chains and
the reward delivery rails implemented in :mod:`services.rewards.rails`. The
intentionally-unsupported declarations make the refusal explicit so operators
see *why* a rail is blocked instead of seeing nothing.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.service.commerce.rail_matrix")


class RailSupport(str, Enum):
    """One of exactly four support buckets every rail must report."""

    SUPPORTED_PRODUCTION = "supported_production"
    SUPPORTED_SANDBOX = "supported_sandbox"
    SUPPORTED_BETA = "supported_beta"
    INTENTIONALLY_UNSUPPORTED = "intentionally_unsupported"


class UnknownRailError(ValueError):
    """Raised when a rail is not declared anywhere in the matrix.

    Deliberately NOT a silent fallback: a rail that is neither native nor
    intentionally-unsupported is a configuration bug and must fail loudly.
    """

    def __init__(self, rail: str) -> None:
        self.rail = rail
        super().__init__(
            f"rail {rail!r} is not declared in the commerce rail matrix — "
            "every configured rail must report a support bucket; refusing to "
            "resolve it silently"
        )


# ── Native rail declarations ─────────────────────────────────────────────────
# Keyed by the exact string that appears in configuration (rail config rows,
# campaign.default_rail, x402 chain CAIP-2 ids, facilitator asset/chain names).

# Reward delivery rails — see services/rewards/rails.py for the adapters.
_NATIVE_REWARD_RAILS: dict[str, RailSupport] = {
    # recommend_only / manual_approval / manual_export are pure-payload rails:
    # no funds, no external system, fully exercised → production.
    "recommend_only": RailSupport.SUPPORTED_PRODUCTION,
    "manual_approval": RailSupport.SUPPORTED_PRODUCTION,
    "manual_export": RailSupport.SUPPORTED_PRODUCTION,
    # tenant_webhook is production-wired with SSRF protection, HMAC signing and
    # a durable leased outbox → production.
    "tenant_webhook": RailSupport.SUPPORTED_PRODUCTION,
    # onchain_claim: EVM proofs are production-warrantied (audit-gated on
    # mainnet); SVM proofs are exercised against devnet/test programs and are
    # not yet mainnet-warrantied → sandbox. The adapter validates vm_type.
    "onchain_claim": RailSupport.SUPPORTED_PRODUCTION,
    "onchain_claim.evm": RailSupport.SUPPORTED_PRODUCTION,
    "onchain_claim.svm": RailSupport.SUPPORTED_SANDBOX,
    "onchain_claim.bitcoin": RailSupport.INTENTIONALLY_UNSUPPORTED,
    "onchain_claim.movevm": RailSupport.SUPPORTED_BETA,
    "onchain_claim.near": RailSupport.SUPPORTED_BETA,
    "onchain_claim.tvm": RailSupport.SUPPORTED_BETA,
    "onchain_claim.cosmos": RailSupport.SUPPORTED_BETA,
    # Beta rail stubs — build/export only, no delivery.
    "stripe_credit": RailSupport.SUPPORTED_BETA,
    "loyalty_points": RailSupport.SUPPORTED_BETA,
    "coupon": RailSupport.SUPPORTED_BETA,
    "internal_credit": RailSupport.SUPPORTED_BETA,
    "x402_credit": RailSupport.SUPPORTED_BETA,
}

# x402 commerce chains (CAIP-2 identifiers used by the x402 control plane).
_NATIVE_X402_CHAINS: dict[str, RailSupport] = {
    "eip155:8453": RailSupport.SUPPORTED_PRODUCTION,   # USDC on Base mainnet
    "solana:mainnet": RailSupport.SUPPORTED_PRODUCTION,  # USDC on Solana mainnet
    "eip155:84532": RailSupport.SUPPORTED_SANDBOX,     # USDC on Base Sepolia
    "solana:devnet": RailSupport.SUPPORTED_SANDBOX,    # USDC on Solana devnet
}

# Intentionally-unsupported declarations — the refusal is explicit. These rails
# exist in the real world (or as legacy code paths) but must NOT be silently
# treated as supported.
_INTENTIONALLY_UNSUPPORTED: dict[str, str] = {
    "ach": "Domestic ACH rails are out of scope for the agentic commerce MVP; "
           "rely on stablecoin rails instead.",
    "wire": "Wire rails require a banking partner; out of scope for the "
            "agentic commerce MVP.",
    "card_surcharge": "Card surcharging is prohibited by card network rules; "
                      "never supported.",
    "crypto_custody": "Aether never holds or custodies user funds; on-chain "
                      "rail deliveries are proof-only, not custody rails.",
    "internal_credit_live": "internal_credit is a beta rail (export-only) and "
                            "must not be used for live delivery.",
    "x402_credit_live": "x402_credit is a beta rail (export-only) and must not "
                        "be used for live delivery.",
}

# Alias map: a configured rail string that is a known synonym resolves onto the
# canonical rail key. Aliases never invent support — they only point at a
# declared native rail.
_ALIASES: dict[str, str] = {
    "on_chain_claim": "onchain_claim",
    "on-chain_claim": "onchain_claim",
    "onchain": "onchain_claim",
    "base_usdc": "eip155:8453",
    "base-mainnet": "eip155:8453",
    "base_sepolia": "eip155:84532",
    "solana": "solana:mainnet",
    "solana_usdc": "solana:mainnet",
    "solana_devnet": "solana:devnet",
    "usdc_base": "eip155:8453",
}


def _resolve_canonical(rail: str) -> Optional[str]:
    """Resolve a configured rail string onto a canonical matrix key.

    Returns ``None`` only for truly unknown rails (which then raise).
    """
    if rail is None:
        return None
    key = rail.strip().lower()
    # Exact native key wins first.
    if key in _NATIVE_REWARD_RAILS or key in _NATIVE_X402_CHAINS:
        return key
    # Prefix resolution for vm-suffixed onchain_claim keys (onchain_claim.evm).
    if key.startswith("onchain_claim."):
        base = key.split(".", 1)[0]
        if base == "onchain_claim":
            return key
    # Intentional-unsupport declarations must resolve too (ach, wire, ...) —
    # otherwise they'd raise UnknownRailError instead of reporting their bucket.
    if key in _INTENTIONALLY_UNSUPPORTED:
        return key
    for known in _INTENTIONALLY_UNSUPPORTED:
        if key.startswith(known + "."):
            return known
    return _ALIASES.get(key)


def classify_rail(rail: str) -> RailSupport:
    """Return the support bucket for a configured rail.

    Never silent: an undeclared rail raises :class:`UnknownRailError`.
    """
    canonical = _resolve_canonical(rail)
    if canonical is None:
        raise UnknownRailError(rail)
    if canonical in _NATIVE_REWARD_RAILS:
        return _NATIVE_REWARD_RAILS[canonical]
    if canonical in _NATIVE_X402_CHAINS:
        return _NATIVE_X402_CHAINS[canonical]
    if canonical in _INTENTIONALLY_UNSUPPORTED:
        return RailSupport.INTENTIONALLY_UNSUPPORTED
    raise UnknownRailError(rail)


def unsupported_reason(rail: str) -> Optional[str]:
    """Return the explicit refusal reason for an intentionally-unsupported rail.

    Returns ``None`` for rails that are supported (or unknown) — the reason is
    only meaningful when :func:`classify_rail` reports INTENTIONALLY_UNSUPPORTED.
    """
    if rail is None:
        return None
    key = rail.strip().lower()
    if key in _INTENTIONALLY_UNSUPPORTED:
        return _INTENTIONALLY_UNSUPPORTED[key]
    # onchain_claim.<vm> refusal
    if key.startswith("onchain_claim."):
        vm = key.split(".", 1)[1]
        reason = _INTENTIONALLY_UNSUPPORTED.get(f"onchain_claim.{vm}")
        if reason:
            return reason
        if vm in ("bitcoin",):
            return (
                "Bitcoin onchain_claim is intentionally unsupported: no "
                "production-warrantied inscription pipeline for rewards."
            )
    # Explicitly-unsupported rail string (may carry a vm suffix).
    for known, reason in _INTENTIONALLY_UNSUPPORTED.items():
        if key.startswith(known):
            return reason
    return None


def is_supported_for_production(rail: str) -> bool:
    """True only for SUPPORTED_PRODUCTION rails (raise on unknown)."""
    return classify_rail(rail) is RailSupport.SUPPORTED_PRODUCTION


def is_supported_for_sandbox(rail: str) -> bool:
    """True for SUPPORTED_PRODUCTION or SUPPORTED_SANDBOX rails (raise on unknown)."""
    support = classify_rail(rail)
    return support in (RailSupport.SUPPORTED_PRODUCTION, RailSupport.SUPPORTED_SANDBOX)


def all_declared_rails() -> list[str]:
    """Every native rail key + every intentionally-unsupported key, sorted."""
    return sorted(set(_NATIVE_REWARD_RAILS) | set(_NATIVE_X402_CHAINS) | set(_INTENTIONALLY_UNSUPPORTED))


def native_rails() -> dict[str, RailSupport]:
    """The native (first-party) rail declarations keyed by canonical rail string."""
    return {**_NATIVE_REWARD_RAILS, **_NATIVE_X402_CHAINS}


def intentionally_unsupported() -> dict[str, str]:
    """The explicit intentional-unsupport declarations (rail → reason)."""
    return dict(_INTENTIONALLY_UNSUPPORTED)


__all__ = [
    "RailSupport",
    "UnknownRailError",
    "classify_rail",
    "unsupported_reason",
    "is_supported_for_production",
    "is_supported_for_sandbox",
    "all_declared_rails",
    "native_rails",
    "intentionally_unsupported",
]
