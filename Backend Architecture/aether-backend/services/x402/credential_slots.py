"""x402-domain credential slot declarations (static, server-owned).

Merged into the credential authority's slot registry so per-tenant RPC
endpoint+key pairs and external facilitator API keys live in the SAME durable,
KMS-encrypted, versioned authority as every other provider credential — never
in deployment-global settings.

Providers declared here:

* RPC endpoint providers (domain ``rpc``), one per chain family the x402 layer
  verifies against. Each holds a single ``rpc_endpoint_pair`` slot whose
  encrypted value is an atomic JSON document ``{url, api_key, auth_mode}`` — so
  one credential version is exactly one endpoint+key pair and a rotated
  endpoint can never mix with a stale key. Validation (``rpc_chain_probe``)
  asserts the RPC reports the declared chain identity.
* External facilitator providers (domain ``x402``), one per approved external
  facilitator, each holding a ``facilitator_api_key`` slot.
"""

from __future__ import annotations

from services.providers.credentials.schema import CredentialDomain

# chain-family provider ids the x402 verifier resolves RPC for.
RPC_PROVIDERS: dict[str, dict] = {
    "rpc_evm_base": {"chain_family": "evm", "chain": "eip155:8453", "display": "Base EVM RPC"},
    "rpc_evm_base_sepolia": {"chain_family": "evm", "chain": "eip155:84532", "display": "Base Sepolia RPC"},
    "rpc_svm_mainnet": {"chain_family": "svm", "chain": "solana:mainnet", "display": "Solana mainnet RPC"},
    "rpc_svm_devnet": {"chain_family": "svm", "chain": "solana:devnet", "display": "Solana devnet RPC"},
}

# external facilitators that require an API credential (the internal LOCAL
# facilitator needs none and is not listed here).
FACILITATOR_PROVIDERS: dict[str, dict] = {
    "fac_circle_v2": {"display": "Circle x402 v2 Facilitator"},
}


def _rpc_slot(chain: str) -> dict:
    return dict(
        slot_name="rpc_endpoint_pair",
        domain=CredentialDomain.RPC,
        display_name="RPC endpoint + key pair",
        purpose=(
            f"Per-tenant JSON-RPC endpoint + key for {chain} verification. "
            "Atomic {url, api_key, auth_mode} — one version is one pair."
        ),
        secret_type="endpoint_keyed_url",
        required=True,
        required_for=("chain_verification", "connection_test"),
        scope_policy="read_only",
        needs_endpoint=False,
        validation_strategy="rpc_chain_probe",
        rotation_policy="replace",
        sensitive=True,
    )


def _facilitator_slot() -> dict:
    return dict(
        slot_name="facilitator_api_key",
        domain=CredentialDomain.X402,
        display_name="Facilitator API key",
        purpose="Authenticate verification calls to the external x402 facilitator.",
        secret_type="bearer_token",
        required=True,
        required_for=("payment_verification", "connection_test"),
        scope_policy="verify_only",
        needs_endpoint=True,
        validation_strategy="live_probe",
        rotation_policy="replace",
        sensitive=True,
    )


def declared_slots() -> dict[str, tuple[dict, ...]]:
    """Slot-registry source hook (see slot_registry._STATIC_SOURCE_MODULES)."""
    slots: dict[str, tuple[dict, ...]] = {}
    for provider, meta in RPC_PROVIDERS.items():
        slots[provider] = (_rpc_slot(meta["chain"]),)
    for provider in FACILITATOR_PROVIDERS:
        slots[provider] = (_facilitator_slot(),)
    return slots


def rpc_provider_for_chain(chain: str, environment: str) -> str | None:
    """Resolve the RPC provider id for a chain + environment.

    sandbox → testnet providers (base-sepolia / solana-devnet) where they
    exist; live → mainnet providers.
    """
    sandbox = environment == "sandbox"
    if chain.startswith("eip155:"):
        return "rpc_evm_base_sepolia" if sandbox else "rpc_evm_base"
    if chain.startswith("solana:"):
        return "rpc_svm_devnet" if sandbox else "rpc_svm_mainnet"
    return None


__all__ = [
    "RPC_PROVIDERS",
    "FACILITATOR_PROVIDERS",
    "declared_slots",
    "rpc_provider_for_chain",
]
