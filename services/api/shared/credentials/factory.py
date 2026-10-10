"""Credential backend selection.

``AETHER_CREDENTIAL_BACKEND`` (or the ``CredentialPlatformConfig``) selects the
concrete backend:

    in_memory           -> InMemoryCredentialBackend (tests only)
    local_encrypted     -> LocalEncryptedCredentialBackend (default)
    aws_secrets_manager -> AwsSecretsManagerCredentialBackend

An unknown value is a hard configuration error (ValueError).
"""

from __future__ import annotations

import functools
from typing import Any, Optional

from shared.credentials.interface import CredentialBackend

_VALID_BACKENDS = ("in_memory", "local_encrypted", "aws_secrets_manager")


def _resolve_config(cfg: Optional[Any]) -> Any:
    if cfg is not None:
        return cfg
    from config.settings import settings

    return settings.credential_platform


def build_credential_backend(cfg: Optional[Any] = None) -> CredentialBackend:
    """Construct a credential backend from config (fresh instance, uncached)."""
    cfg = _resolve_config(cfg)
    backend = getattr(cfg, "backend", "local_encrypted")

    if backend == "in_memory":
        from shared.credentials.in_memory import InMemoryCredentialBackend

        return InMemoryCredentialBackend()
    if backend == "local_encrypted":
        from shared.credentials.local_encrypted import LocalEncryptedCredentialBackend

        return LocalEncryptedCredentialBackend()
    if backend == "aws_secrets_manager":
        from shared.credentials.aws_secrets_manager import (
            AwsSecretsManagerCredentialBackend,
        )

        prefix = getattr(cfg, "aws_secret_prefix", "aether/credentials")
        return AwsSecretsManagerCredentialBackend(secret_prefix=prefix)

    raise ValueError(
        f"Unknown AETHER_CREDENTIAL_BACKEND {backend!r}; "
        f"expected one of {_VALID_BACKENDS}"
    )


@functools.lru_cache(maxsize=1)
def get_credential_backend() -> CredentialBackend:
    """Return the process-wide cached credential backend."""
    return build_credential_backend()


def reset_credential_backend_cache() -> None:
    """Test-only: drop the cached backend so config changes take effect."""
    get_credential_backend.cache_clear()


__all__ = [
    "build_credential_backend",
    "get_credential_backend",
    "reset_credential_backend_cache",
]
