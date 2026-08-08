"""Typed error hierarchy for the Universal Provider Runtime.

Every runtime failure raises a :class:`ProviderRuntimeError` subclass so a
caller can classify and translate failures without string-matching.

Safety contract: every subclass exposes :attr:`ProviderRuntimeError.safe_message`,
a tenant/provider-safe summary built ONLY from the ``message`` the author wrote
at raise time. The ``details`` dict — which may carry provider-supplied text,
correlation ids, refs, or request state — is deliberately excluded from
``safe_message`` and must never be surfaced to a tenant or in a log that crosses
a tenant boundary.
"""

from __future__ import annotations

from typing import Any


class ProviderRuntimeError(ValueError):
    """Base error for the provider runtime.

    Every subclass exposes ``.safe_message`` (tenant/provider-safe, no secrets).
    ``details`` is diagnostic-only and is never included in ``safe_message``.
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details) if details else {}

    @property
    def safe_message(self) -> str:
        """The message only — ``details`` is deliberately excluded.

        This is the only string a caller should log or return to a tenant.
        """
        return self.message


class ProviderNotInstalled(ProviderRuntimeError):
    """The provider plugin is not installed/registered on this runtime.

    Raised when an operation needs ``plugin`` but the plugin cannot be resolved
    for the requested ``provider_identity``.
    """


class ManifestInvalid(ProviderRuntimeError):
    """A provider manifest failed structural or §32 honesty validation.

    Raised at plugin load/registration time when the manifest cannot be trusted.
    """


class PluginIncompatible(ProviderRuntimeError):
    """A plugin's runtime/ABI is incompatible with this provider runtime.

    Raised when the plugin was built against a different contract surface than
    the running runtime supports.
    """


class CredentialMissing(ProviderRuntimeError):
    """A required credential is not stored for the tenant/ref.

    Raised when an acquisition step needs a credential that has never been
    stored, was revoked, or expired.
    """


class AuthorizationFailed(ProviderRuntimeError):
    """The provider rejected the supplied credentials.

    Raised when auth validation or a live test returns an authentication
    failure (401-class) from the provider.
    """


class PermissionMissing(ProviderRuntimeError):
    """The credential is valid but lacks the scopes/permissions the operation needs.

    Raised when the provider returns a 403-class "insufficient scope" signal.
    """


class AccountSelectionRequired(ProviderRuntimeError):
    """The provider requires an account to be selected before acquisition.

    Raised when an operation is attempted before the tenant picks an account
    on a multi-account provider.
    """


class ProviderConfigurationInvalid(ProviderRuntimeError):
    """The connection's non-secret ``config`` fails the manifest's field spec.

    Raised when config fields are missing, unknown, or of the wrong type per the
    manifest's :class:`~shared.integration_contracts.manifest.Configuration`.
    """


class WebhookVerificationFailed(ProviderRuntimeError):
    """An inbound webhook signature failed verification.

    Raised when the webhook adapter's ``verify`` returns false for a delivery.
    """


class ProviderRateLimited(ProviderRuntimeError):
    """The provider rate-limited the request (429-class).

    Raised when an acquisition step observes a rate-limit signal; the error
    should carry the retry-after window in ``details`` when known.
    """


class ProviderUnavailable(ProviderRuntimeError):
    """The provider endpoint is unavailable (5xx / timeout / network).

    Raised when an acquisition step cannot reach the provider at all.
    """


class ProviderPullFailed(ProviderRuntimeError):
    """A pull/report acquisition step failed against the provider.

    Raised when a page or report could not be fetched (non-rate-limit, non-auth
    failure).
    """


class ProviderReportFailed(ProviderRuntimeError):
    """A provider-side report could not be produced or fetched.

    Raised when a report-based acquisition step fails because the report itself
    is unavailable or invalid.
    """


class NormalizationFailed(ProviderRuntimeError):
    """A raw record could not be normalized by the plugin's normalizer.

    Raised when the normalizer raised for a record rather than returning a
    dropped/skipped result.
    """


class ReconciliationFailed(ProviderRuntimeError):
    """A reconciliation snapshot step failed.

    Raised when the reconciliation adapter could not produce/apply a snapshot.
    """


class CursorInvalid(ProviderRuntimeError):
    """A cursor value is malformed or no longer valid for the provider.

    Raised when a pagination/replay cursor cannot be parsed or is rejected by
    the provider.
    """


class ConnectionStateViolation(ProviderRuntimeError):
    """A connection lifecycle transition is illegal per the state machine.

    Raised by :class:`~services.provider_runtime.connection.ConnectionOrchestrator`
    when ``can_transition`` rejects a requested
    :class:`~shared.integration_contracts.lifecycle.ConnectionState` move.
    """


__all__ = [
    "AccountSelectionRequired",
    "AuthorizationFailed",
    "ConnectionStateViolation",
    "CredentialMissing",
    "CursorInvalid",
    "ManifestInvalid",
    "NormalizationFailed",
    "PermissionMissing",
    "PluginIncompatible",
    "ProviderConfigurationInvalid",
    "ProviderNotInstalled",
    "ProviderPullFailed",
    "ProviderRateLimited",
    "ProviderReportFailed",
    "ProviderRuntimeError",
    "ProviderUnavailable",
    "ReconciliationFailed",
    "WebhookVerificationFailed",
]
