"""Trust plane — human sessions, service credentials, public ingest identifiers.

PR 1 (trust containment). Human authentication issues durable, revocable,
server-side sessions instead of reusable API keys. Machine access uses scoped
service credentials. Public SDK ingest uses non-secret ingest-only identifiers.

This package is dependency-light (stdlib + BaseRepository) so it can be unit
tested without the FastAPI/cryptography stack.
"""

from __future__ import annotations

from .service import (
    CredentialClass,
    PublicIngestService,
    ServiceCredentialService,
    SessionIssue,
    SessionService,
    SessionValidationError,
    session_service,
    public_ingest_service,
    service_credential_service,
)

__all__ = [
    "CredentialClass",
    "PublicIngestService",
    "ServiceCredentialService",
    "SessionIssue",
    "SessionService",
    "SessionValidationError",
    "session_service",
    "public_ingest_service",
    "service_credential_service",
]
