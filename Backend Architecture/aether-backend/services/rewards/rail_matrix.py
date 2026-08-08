"""Canonical reward-rail classification matrix.

Every reward rail is classified exactly once as one of:

* ``production``               — implemented, credential-only activatable, delivers;
* ``sandbox``                  — production-bounded, released sandbox-only
                                 (PARTNER_LIVE needs external credentials);
* ``explicit_beta``            — bounded implementation, flagged beta;
* ``intentionally_unsupported``— deliberately not in this release (needs a
                                 designated provider partner = external action);
                                 configuring it is refused.

The matrix is the single source of truth consumed by:
* the generated ``docs/_generated/reward-rail-matrix.json`` (via
  ``scripts/docs_extract/extract_reward_rail_matrix.py``);
* ``scripts/release/check_reward_rail_matrix.py`` (bidirectional agreement with
  ``rails._RAIL_ADAPTERS`` and the sender registry);
* the rewards credential-readiness gate.

A rail present in ``_RAIL_ADAPTERS`` but absent here (or vice versa) is a
fail-closed error — the classification can never silently drift from the code.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RailClassification:
    rail: str
    tier: str                # production | sandbox | explicit_beta | intentionally_unsupported
    delivery_mode: str       # sync_api | onchain_claim | internal_ledger | manual | none
    custody: str             # no_custody (Aether never holds/moves funds)
    external_action: str     # what (if anything) is externally blocked for PARTNER_LIVE
    summary: str

    def public_dict(self) -> dict:
        return {
            "rail": self.rail,
            "tier": self.tier,
            "delivery_mode": self.delivery_mode,
            "custody": self.custody,
            "external_action": self.external_action,
            "summary": self.summary,
        }


TIERS = ("production", "sandbox", "explicit_beta", "intentionally_unsupported")

# Configurable tiers — a rail NOT in this set cannot be configured by a tenant.
CONFIGURABLE_TIERS = ("production", "sandbox", "explicit_beta")

RAIL_MATRIX: dict[str, RailClassification] = {
    "recommend_only": RailClassification(
        "recommend_only", "production", "none", "no_custody", "",
        "Returns an eligibility recommendation; no delivery.",
    ),
    "manual_approval": RailClassification(
        "manual_approval", "production", "manual", "no_custody", "",
        "Queues the reward for manual operator approval.",
    ),
    "manual_export": RailClassification(
        "manual_export", "production", "manual", "no_custody", "",
        "Produces a batch export row the tenant fulfils out-of-band.",
    ),
    "tenant_webhook": RailClassification(
        "tenant_webhook", "production", "sync_api", "no_custody", "",
        "Signed JSON delivery to the tenant's webhook via the durable outbox; "
        "HMAC secret from the credential authority.",
    ),
    "onchain_claim": RailClassification(
        "onchain_claim", "production", "onchain_claim", "no_custody",
        "EVM mainnet real-value activation requires external contract audit evidence.",
        "EVM oracle-signed claim proof; tenant/user submits the on-chain tx "
        "(Aether never submits or holds funds).",
    ),
    "stripe_credit": RailClassification(
        "stripe_credit", "sandbox", "sync_api", "no_custody",
        "Stripe live-mode credentials (test mode covered in sandbox).",
        "Idempotent Stripe customer-balance credit via the tenant's Stripe key.",
    ),
    "internal_credit": RailClassification(
        "internal_credit", "production", "internal_ledger", "no_custody", "",
        "Double-entry credit into the internal reward ledger; fully in-repo.",
    ),
    "x402_credit": RailClassification(
        "x402_credit", "explicit_beta", "internal_ledger", "no_custody",
        "External facilitator + funded RPC for live x402 verification.",
        "Reward action → x402 credit grant through the commerce control plane; "
        "sandbox-supported, no custody.",
    ),
    "loyalty_points": RailClassification(
        "loyalty_points", "intentionally_unsupported", "none", "no_custody",
        "Requires a designated loyalty provider partner (commercial + integration).",
        "Not in this release — configuring it is refused.",
    ),
    "coupon": RailClassification(
        "coupon", "intentionally_unsupported", "none", "no_custody",
        "Requires a designated coupon/promotion provider partner.",
        "Not in this release — configuring it is refused.",
    ),
}


def classification_for(rail: str) -> RailClassification | None:
    return RAIL_MATRIX.get(rail)


def is_configurable(rail: str) -> bool:
    c = RAIL_MATRIX.get(rail)
    return bool(c and c.tier in CONFIGURABLE_TIERS)


def build_rail_matrix() -> dict:
    """Deterministic JSON-serializable rail matrix (byte-stable)."""
    rails = {name: c.public_dict() for name, c in sorted(RAIL_MATRIX.items())}
    by_tier: dict[str, int] = {}
    for c in RAIL_MATRIX.values():
        by_tier[c.tier] = by_tier.get(c.tier, 0) + 1
    return {
        "rails": rails,
        "summary": {
            "total": len(rails),
            "by_tier": dict(sorted(by_tier.items())),
        },
    }


__all__ = [
    "RailClassification",
    "RAIL_MATRIX",
    "TIERS",
    "CONFIGURABLE_TIERS",
    "classification_for",
    "is_configurable",
    "build_rail_matrix",
]
