# DO NOT EDIT — generated from packages/shared/contracts/temporal-policy-registry.json
# Run: python scripts/generate_platform_contracts.py
"""Generated temporal enforcement policy (dispositions + per-family bounds)."""

from __future__ import annotations

TEMPORAL_POLICY_VERSION = "1.0.0"

TEMPORAL_ENFORCEMENT_MODES: tuple[str, ...] = ("off", "shadow", "warn", "enforce")

TEMPORAL_DISPOSITIONS: tuple[str, ...] = ("accept", "accept_with_warning", "quarantine", "reject")

# Disposition applied to each stable temporal reason code.
TEMPORAL_REASON_DISPOSITIONS: dict[str, str] = {
    "clock_skew_warning": "accept_with_warning",
    "delivery_lag_warning": "accept_with_warning",
    "local_time_ambiguous": "quarantine",
    "local_time_nonexistent": "reject",
    "temporal_authority_missing": "reject",
    "temporal_policy_violation": "reject",
    "temporal_provenance_missing": "accept_with_warning",
    "timestamp_future": "reject",
    "timestamp_invalid": "reject",
    "timestamp_naive": "reject",
    "timestamp_too_old": "quarantine",
    "timezone_invalid": "reject",
    "timezone_offset_mismatch": "reject",
}

# Complete (default-resolved) temporal bounds per event family.
TEMPORAL_FAMILY_BOUNDS: dict[str, dict[str, int]] = {
    "agent": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "b2b": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "commerce": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "comms": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 1209600000},
    "consent": {"maxFutureSkewMs": 60000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "core": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "credit": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "derivatives": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 2592000000},
    "ecommerce": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "exposure": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "friction": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "identity": {"maxFutureSkewMs": 60000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "identity_lc": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "interop": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 2592000000},
    "journey": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "location": {"maxFutureSkewMs": 60000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "outcome": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "reward": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "server": {"maxFutureSkewMs": 60000, "warnSkewMs": 5000, "maxLatenessMs": 604800000},
    "stablecoin": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 2592000000},
    "wallet": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 604800000},
    "web3_lc": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 2592000000},
    "x402": {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 2592000000},
}

TEMPORAL_DEFAULT_BOUNDS: dict[str, int] = {"maxFutureSkewMs": 300000, "warnSkewMs": 30000, "maxLatenessMs": 604800000}

__all__ = [
    "TEMPORAL_POLICY_VERSION",
    "TEMPORAL_ENFORCEMENT_MODES",
    "TEMPORAL_DISPOSITIONS",
    "TEMPORAL_REASON_DISPOSITIONS",
    "TEMPORAL_FAMILY_BOUNDS",
    "TEMPORAL_DEFAULT_BOUNDS",
]
