"""Reward-domain credential slot declarations (static, server-owned).

The credential authority's slot registry merges these declarations with the
payment-adapter-derived slots, so reward signing keys and the tenant reward
webhook secret live in the SAME durable, KMS-encrypted, versioned authority as
every other provider credential — never in environment variables or plaintext
rail configs.

Providers declared here:

* ``reward_signer`` (domain ``signing``) — the tenant's per-environment reward
  proof signer keys. ``evm_reward_signer_key`` holds a secp256k1 private key
  (hex) whose derived address must match the contract registry's
  ``oracle_signer_address``; ``svm_reward_signer_key`` holds an ed25519 seed
  for the Solana rewards program authority (optional until the SVM rail is
  released beyond explicit beta).
* ``tenant_webhook`` (domain ``rewards``) — the HMAC signing secret for the
  tenant_webhook reward rail. Overlap rotation, mirroring the payment-rail
  webhook secret policy, so receivers verify against active+previous during a
  rotation window.
"""

from __future__ import annotations

from services.providers.credentials.schema import CredentialDomain

# Declarations consumed by services/providers/credentials/slot_registry.py.
# Shape: provider -> tuple of slot dicts (slot_name + augmentation-key fields).
REWARD_SLOT_DECLARATIONS: dict[str, tuple[dict, ...]] = {
    "reward_signer": (
        dict(
            slot_name="evm_reward_signer_key",
            domain=CredentialDomain.SIGNING,
            display_name="EVM reward signer key",
            purpose=(
                "Sign EVM reward claim proofs (secp256k1). The derived address "
                "must match the verified contract registry's oracle_signer_address."
            ),
            secret_type="signing_private_key",
            required=True,
            required_for=("proof_signing",),
            scope_policy="sign_only",
            needs_endpoint=False,
            validation_strategy="key_derivation_check",
            rotation_policy="replace",
            sensitive=True,
        ),
        dict(
            slot_name="svm_reward_signer_key",
            domain=CredentialDomain.SIGNING,
            display_name="SVM reward signer key",
            purpose=(
                "Sign Solana reward claim proofs (ed25519 seed). Optional until "
                "the SVM claim rail leaves explicit beta."
            ),
            secret_type="signing_private_key",
            required=False,
            required_for=("proof_signing",),
            scope_policy="sign_only",
            needs_endpoint=False,
            validation_strategy="key_derivation_check",
            rotation_policy="replace",
            sensitive=True,
        ),
    ),
    "tenant_webhook": (
        dict(
            slot_name="webhook_signing_secret",
            domain=CredentialDomain.REWARDS,
            display_name="Reward webhook signing secret",
            purpose=(
                "HMAC-sign outbound tenant_webhook reward deliveries "
                "(X-Aether-Signature). Rotation keeps a bounded overlap window."
            ),
            secret_type="hmac_secret",
            required=True,
            required_for=("reward_delivery",),
            scope_policy="sign_only",
            needs_endpoint=False,
            validation_strategy="signature_selfcheck",
            rotation_policy="overlap",
            sensitive=True,
        ),
    ),
}


def declared_slots() -> dict[str, tuple[dict, ...]]:
    """Slot-registry source hook (see slot_registry._STATIC_SOURCE_MODULES)."""
    return REWARD_SLOT_DECLARATIONS


__all__ = ["REWARD_SLOT_DECLARATIONS", "declared_slots"]
