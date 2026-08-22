"""Tenant-scoped reward signer resolution.

The ONLY sanctioned path to a reward proof signing key. Resolution order:

1. **Credential authority** — the tenant's ``reward_signer`` provider slot
   (``evm_reward_signer_key`` / ``svm_reward_signer_key``) for the requested
   environment. This is the production path: per-tenant, per-environment,
   KMS-encrypted, versioned, rotatable, revocable.
2. **Local bootstrap** — ONLY when ``AETHER_ENV`` is ``local``/``test``: the
   ``ORACLE_SIGNER_KEY`` environment variable (or the well-known Hardhat key)
   keeps the local dev loop credential-free.

Outside local/test there is NO environment-variable fallback: a tenant without
an active signer credential gets ``SignerUnavailableError`` (fail-closed) and
the capability stays at CREDENTIAL_WAITING. The deployment-global
``ORACLE_SIGNER_KEY`` that used to sign every tenant's proofs is retired from
staging/production paths.
"""

from __future__ import annotations

import os

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.rewards.signing")

SIGNER_PROVIDER = "reward_signer"
_HARDHAT_TEST_KEY = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

_CHAIN_FAMILY_SLOTS = {
    "evm": "evm_reward_signer_key",
    "svm": "svm_reward_signer_key",
}


class SignerUnavailableError(RuntimeError):
    """No usable signer for the (tenant, environment, chain family) coordinate."""


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").strip().lower() in ("local", "test")


def signer_slot_for(chain_family: str) -> str:
    try:
        return _CHAIN_FAMILY_SLOTS[chain_family]
    except KeyError:
        raise SignerUnavailableError(
            f"no signer slot for chain family {chain_family!r}; "
            f"supported: {sorted(_CHAIN_FAMILY_SLOTS)}"
        )


def local_bootstrap_key() -> str:
    """Local/test-only signer bootstrap (env var or the Hardhat dev key).

    Raises outside local/test — the bootstrap path must never sign anything in
    a deployed environment.
    """
    if not _is_local_env():
        raise SignerUnavailableError(
            "environment-variable signer bootstrap is local/test-only; supply a "
            "tenant reward_signer credential through the credential authority"
        )
    return os.environ.get("ORACLE_SIGNER_KEY", "") or _HARDHAT_TEST_KEY


async def resolve_reward_signer(
    tenant_id: str, environment: str, chain_family: str = "evm"
) -> str:
    """Resolve the signing key for a tenant reward proof (see module docstring).

    ``environment`` is the credential environment (``sandbox`` | ``live``).
    """
    slot_name = signer_slot_for(chain_family)
    try:
        from services.providers.credentials.authority import credential_authority

        key = await credential_authority.get_active_secret(
            tenant_id, SIGNER_PROVIDER, environment, slot_name
        )
        if key:
            metrics.increment(
                "reward_signer_resolutions",
                labels={"source": "credential_authority", "chain_family": chain_family},
            )
            return key
    except Exception as exc:  # noqa: BLE001 — classified below
        from shared.common.common import NotFoundError

        if not isinstance(exc, NotFoundError):
            logger.error(
                "reward signer resolution failed tenant=%s env=%s slot=%s: %s",
                tenant_id, environment, slot_name, type(exc).__name__,
            )
            metrics.increment(
                "reward_signer_resolutions",
                labels={"source": "error", "chain_family": chain_family},
            )
            raise SignerUnavailableError(
                f"signer credential resolution failed for {slot_name}"
            ) from exc

    if _is_local_env():
        metrics.increment(
            "reward_signer_resolutions",
            labels={"source": "local_bootstrap", "chain_family": chain_family},
        )
        return local_bootstrap_key()

    metrics.increment(
        "reward_signer_resolutions",
        labels={"source": "missing", "chain_family": chain_family},
    )
    raise SignerUnavailableError(
        f"no ACTIVE {slot_name} credential for tenant {tenant_id!r} in "
        f"environment {environment!r}; supply one via "
        f"PUT /v1/providers/credentials/{SIGNER_PROVIDER}/slots/{slot_name}"
    )


def reward_credential_environment() -> str:
    """Default credential environment for the running deployment.

    Production maps to ``live``; everything else (local/dev/integration/
    staging) maps to ``sandbox`` — mirroring the payment-rails
    ``_resolve_environment`` deployment sweep mapping.
    """
    env = os.getenv("AETHER_ENV", "local").strip().lower()
    return "live" if env in ("production", "prod") else "sandbox"


__all__ = [
    "SIGNER_PROVIDER",
    "SignerUnavailableError",
    "local_bootstrap_key",
    "resolve_reward_signer",
    "reward_credential_environment",
    "signer_slot_for",
]
