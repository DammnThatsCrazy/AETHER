"""Provider-neutral credential platform.

Public surface:
- Structured credential shapes (:mod:`shared.credentials.types`)
- The backend interface + masked metadata (:mod:`shared.credentials.interface`)
- Concrete backends (in-memory, local-encrypted, AWS Secrets Manager)
- The :data:`credential_service` facade and backend factory
"""

from __future__ import annotations

from shared.credentials.factory import (
    build_credential_backend,
    get_credential_backend,
    reset_credential_backend_cache,
)
from shared.credentials.interface import (
    CredentialBackend,
    CredentialBackendError,
    CredentialBackendHealth,
    CredentialBackendNotConfigured,
    CredentialMetadata,
)
from shared.credentials.service import (
    CredentialService,
    byok_ref,
    connector_ref,
    credential_service,
)
from shared.credentials.types import (
    ApiKeyCredential,
    ApiKeyWebhookSecretCredential,
    ClientSecretCredential,
    KeyIdSecretCredential,
    KeypairCredential,
    MultiCredential,
    OAuthTokenCredential,
    ServiceAccountCredential,
    StructuredCredential,
    UsernameTokenCredential,
    as_structured,
    masked_identifier,
    masked_metadata,
)

__all__ = [
    "ApiKeyCredential",
    "ApiKeyWebhookSecretCredential",
    "ClientSecretCredential",
    "CredentialBackend",
    "CredentialBackendError",
    "CredentialBackendHealth",
    "CredentialBackendNotConfigured",
    "CredentialMetadata",
    "CredentialService",
    "KeyIdSecretCredential",
    "KeypairCredential",
    "MultiCredential",
    "OAuthTokenCredential",
    "ServiceAccountCredential",
    "StructuredCredential",
    "UsernameTokenCredential",
    "as_structured",
    "build_credential_backend",
    "byok_ref",
    "connector_ref",
    "credential_service",
    "get_credential_backend",
    "masked_identifier",
    "masked_metadata",
    "reset_credential_backend_cache",
]
