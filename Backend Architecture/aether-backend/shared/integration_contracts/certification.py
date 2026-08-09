"""Provider certification contracts.

:class:`ProviderReadinessLevel` is the UPR's mirror of the mission-canonical
:class:`~shared.certification.readiness.CredentialReadiness` token vocabulary —
the token string values are EXACTLY equal so a readiness token travels losslessly
between the certification surface and the credential platform. This is a
separate enum (not an alias) so the UPR surface stays independent of the legacy
connector taxonomy while remaining value-compatible.

:class:`CertificationReport` is the honest result of running the certification
harness against a plugin: every check with its pass/fail verdict, the identity
under test, the plugin version, the declared manifest readiness, and the
environment the suite ran in. ``passed`` is the conjunction of all checks.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from shared.integration_contracts.manifest import ManifestReadiness


class ProviderReadinessLevel(str, Enum):
    """UPR readiness tokens — values mirror ``CredentialReadiness`` exactly.

    The middle band (``IMPLEMENTATION_IN_PROGRESS`` .. ``PARTNER_LIVE``) is the
    honest forward progression; the off-ramp band (``SUSPENDED`` /
    ``CREDENTIAL_INVALID`` / ``ERROR`` / ``DEGRADED`` / ``DISABLED``) marks a
    provider that regressed or lost its evidence; ``SCAFFOLDED`` marks an
    adapter that is only a descriptor. The value strings MUST stay equal to
    ``shared.certification.readiness.CredentialReadiness`` (a test asserts this
    parity).
    """

    REPLAY_VALIDATED = "replay_validated"
    IMPLEMENTATION_IN_PROGRESS = "implementation_in_progress"
    CREDENTIAL_WAITING = "credential_waiting"
    OFFLINE_VALIDATED = "offline_validated"
    CONNECTION_TESTING = "connection_testing"
    SANDBOX_VALIDATED = "sandbox_validated"
    PARTNER_LIVE = "partner_live"
    SUSPENDED = "suspended"
    CREDENTIAL_INVALID = "credential_invalid"
    ERROR = "error"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    SCAFFOLDED = "scaffolded"


class CertificationCheck(BaseModel):
    """One named certification check and its verdict."""

    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    detail: str = ""


class CertificationReport(BaseModel):
    """The result of certifying one provider capability."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1"
    generated_at: str  # ISO-8601 UTC
    identity: str  # "family.product.capability"
    plugin_version: str = ""
    readiness: ManifestReadiness
    environment: str = "local"
    checks: list[CertificationCheck]
    passed: bool


__all__ = [
    "CertificationCheck",
    "CertificationReport",
    "ProviderReadinessLevel",
]
