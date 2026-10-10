"""Domain-specific exceptions for the identity resolution subsystem."""

from __future__ import annotations


class IdentityError(Exception):
    """Base class for identity resolution errors."""


class CrossTenantError(IdentityError):
    """Raised when an operation would cross tenant boundaries."""

    def __init__(self, detail: str = "Cross-tenant identity operation is not permitted"):
        self.detail = detail
        super().__init__(detail)


class ConsentBlockedError(IdentityError):
    """Raised when consent gates block a sensitive identity link."""

    def __init__(self, signal_type: str, purpose: str):
        self.signal_type = signal_type
        self.purpose = purpose
        self.detail = (
            f"Consent does not allow sensitive identity linking for "
            f"signal_type={signal_type} purpose={purpose}"
        )
        super().__init__(self.detail)


class FingerprintOnlyError(IdentityError):
    """Raised when the only evidence for a hard link is device fingerprint."""

    def __init__(self) -> None:
        self.detail = "Fingerprint alone cannot create a hard identity link"
        super().__init__(self.detail)


class RevokedAliasError(IdentityError):
    """Raised when attempting to use a revoked alias for a new hard link."""

    def __init__(self, alias_id: str) -> None:
        self.alias_id = alias_id
        self.detail = f"Alias {alias_id!r} is revoked and cannot be used for new hard links"
        super().__init__(self.detail)


class IdentityNotFoundError(IdentityError):
    """Raised when a requested identity entity does not exist."""

    def __init__(self, entity_id: str) -> None:
        self.entity_id = entity_id
        self.detail = f"Identity entity {entity_id!r} not found"
        super().__init__(self.detail)


class InvalidSignalError(IdentityError):
    """Raised when an identity signal value fails validation."""

    def __init__(self, signal_type: str, reason: str) -> None:
        self.signal_type = signal_type
        self.reason = reason
        self.detail = f"Invalid signal {signal_type!r}: {reason}"
        super().__init__(self.detail)


class MergeConflictError(IdentityError):
    """Raised when two candidate entities have conflicting strong identifiers."""

    def __init__(self, entity_ids: list[str], reason: str) -> None:
        self.entity_ids = entity_ids
        self.reason = reason
        self.detail = f"Merge conflict between {entity_ids}: {reason}"
        super().__init__(self.detail)


class UnauthorizedOperatorAction(IdentityError):
    """Raised when a non-operator attempts a privileged identity mutation."""

    def __init__(self, action: str) -> None:
        self.action = action
        self.detail = f"Operator/admin permission required for action: {action}"
        super().__init__(self.detail)
