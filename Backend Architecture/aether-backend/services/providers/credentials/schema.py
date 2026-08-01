"""Frozen domain vocabulary for the durable provider-credential authority.

This module is the single source of truth for the *shape* of a credential
version — the state machine tokens, the environment tokens, and the exact set
of fields persisted in each ``provider_credential_versions`` row's JSONB
``data`` payload. The migration (which documents the schema), the repository,
the authority state machine, and the API all import from here so none of them
can drift from the others.

Nothing in this module performs IO or imports the payment-rail adapters; it is
import-safe and cheap so every layer can depend on it.
"""

from __future__ import annotations


class CredentialState:
    """Lifecycle states for a single credential *version*.

    A slot (tenant/provider/environment/slot_name) may hold at most one
    ``active`` version at a time. During a webhook-secret rotation the prior
    ``active`` version is demoted to ``previous`` for a *bounded* overlap window
    so in-flight provider deliveries signed with the old secret still verify;
    the overlap sweep tombstones it when the window expires.

    ``test_failed`` is a *terminal-for-this-version* marker for a pending
    credential that failed its validation probe — it never touches the active
    version, so a botched rotation cannot take down a working integration.
    """

    PENDING = "pending"          # created, not yet validated/activated
    ACTIVE = "active"            # the authoritative version for the slot
    PREVIOUS = "previous"        # demoted active, inside a bounded overlap window
    REVOKED = "revoked"          # deliberately retired; retained for audit
    TEST_FAILED = "test_failed"  # pending version failed validation
    TOMBSTONED = "tombstoned"    # cleaned up (overlap expired / purged)


CREDENTIAL_STATES: tuple[str, ...] = (
    CredentialState.PENDING,
    CredentialState.ACTIVE,
    CredentialState.PREVIOUS,
    CredentialState.REVOKED,
    CredentialState.TEST_FAILED,
    CredentialState.TOMBSTONED,
)

# States that must never be re-activated or overwritten in place.
TERMINAL_STATES: tuple[str, ...] = (CredentialState.REVOKED, CredentialState.TOMBSTONED)

# States that count as "occupying" the single-active-per-slot invariant plus the
# bounded webhook-overlap invariant. Used by the repository's uniqueness guards.
ACTIVE_STATE = CredentialState.ACTIVE
OVERLAP_STATE = CredentialState.PREVIOUS


class CredentialEnvironment:
    """Provider environment a credential version is bound to.

    Bound into the encryption context so a sandbox credential can never be
    decrypted under a live context (or vice-versa) even if a row were
    mis-selected.
    """

    SANDBOX = "sandbox"
    LIVE = "live"


CREDENTIAL_ENVIRONMENTS: tuple[str, ...] = (
    CredentialEnvironment.SANDBOX,
    CredentialEnvironment.LIVE,
)

# The financial-observability credential domain. Kept as a constant so the slot
# registry, authority, and API agree on the token the payment adapters report
# via ``certification_descriptor().domain``.
PAYMENTS_DOMAIN = "payments"


# The exact JSONB ``data`` fields of a ``provider_credential_versions`` row.
# The migration docstring, the repository, and the authority all reference this
# tuple; a unit test asserts the authority writes exactly these keys.
CREDENTIAL_VERSION_FIELDS: tuple[str, ...] = (
    "tenant_id",
    "provider",
    "domain",
    "environment",
    "slot_name",
    "credential_version",           # monotonically increasing int per slot
    "state",
    "encrypted_value",              # cipher ciphertext (never plaintext)
    "encrypted_data_key",           # KMS-wrapped data key (envelope); "" for local
    "encryption_provider",          # e.g. local_aesgcm | aws_kms_envelope
    "encryption_key_id",            # KMS key id / local key label
    "encryption_version",           # cipher format version
    "safe_fingerprint",             # non-reversible ciphertext fingerprint (display)
    "created_at",
    "created_by",
    "updated_at",
    "last_tested_at",
    "last_test_result",             # e.g. valid | unauthorized | forbidden | ...
    "last_successful_test_at",
    "activated_at",
    "rotation_overlap_expires_at",  # set when demoted to `previous`
    "revoked_at",
    "revoked_by",
    "audit_reference",              # id of the sanitized audit record
)


__all__ = [
    "CredentialState",
    "CREDENTIAL_STATES",
    "TERMINAL_STATES",
    "ACTIVE_STATE",
    "OVERLAP_STATE",
    "CredentialEnvironment",
    "CREDENTIAL_ENVIRONMENTS",
    "PAYMENTS_DOMAIN",
    "CREDENTIAL_VERSION_FIELDS",
]
