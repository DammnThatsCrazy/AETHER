# DO NOT EDIT — generated from packages/shared/contracts/interaction-vocabulary.json
# Run: python scripts/generate_platform_contracts.py
"""Generated interaction vocabulary (types, namespaces, result states, evidence, actors)."""

from __future__ import annotations

INTERACTION_VOCABULARY_VERSION = "1.0.0"

# Closed canonical interaction-type vocabulary.
INTERACTION_TYPES: tuple[str, ...] = (
    "click",
    "tap",
    "double_click",
    "long_press",
    "hover",
    "focus",
    "blur",
    "input",
    "select",
    "submit",
    "scroll",
    "drag",
    "drop",
    "copy",
    "share",
    "open",
    "close",
    "expand",
    "collapse",
    "approve",
    "reject",
    "sign",
    "connect",
    "disconnect",
    "execute",
    "retry",
    "backtrack",
    "navigate",
    "search",
    "filter",
    "sort",
    "download",
    "upload",
)

# Custom interaction types must be namespaced as <namespace>.<name> using a registered namespace. Unregistered custom types stay in Bronze and are never promoted to stable Gold.
INTERACTION_CUSTOM_NAMESPACES: tuple[str, ...] = (
    "tenant",
    "wallet",
    "dapp",
    "agent",
    "financial_rail",
)

# Canonical result state of an interaction.
INTERACTION_RESULT_STATES: tuple[str, ...] = (
    "observed",
    "attempted",
    "pending",
    "succeeded",
    "failed",
    "cancelled",
    "abandoned",
    "rejected",
    "expired",
    "reverted",
    "confirmed",
    "settled",
)

# How strongly the recorded interaction is evidenced.
INTERACTION_EVIDENCE_BASIS: tuple[str, ...] = (
    "client_observed",
    "server_observed",
    "provider_observed",
    "chain_observed",
    "reconciled",
    "imported",
    "derived",
    "probabilistic",
    "experiment_supported",
    "benchmark_only",
    "insufficient_evidence",
)

# Who (or what) performed the interaction.
INTERACTION_ACTOR_KINDS: tuple[str, ...] = (
    "human",
    "agent",
    "service",
    "organization_member",
    "workspace",
    "wallet",
    "anonymous",
    "canonical_entity",
)

__all__ = [
    "INTERACTION_VOCABULARY_VERSION",
    "INTERACTION_TYPES",
    "INTERACTION_CUSTOM_NAMESPACES",
    "INTERACTION_RESULT_STATES",
    "INTERACTION_EVIDENCE_BASIS",
    "INTERACTION_ACTOR_KINDS",
]
