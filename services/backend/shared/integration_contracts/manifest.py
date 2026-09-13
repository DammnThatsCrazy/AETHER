"""Canonical provider manifest (§12) and its honesty invariants (§32).

A :class:`ProviderManifest` is the single, typed source of truth for what a
provider capability *is* and *needs*: its identity, readiness, availability,
authentication shape, configuration surface, account/webhook/sync behaviour,
data outputs, product destinations, and deployment requirements.

The manifest describes credential **shape** — field descriptors
(:class:`CredentialFieldSpec`) — never credential values. Value types live in
``shared.credentials.types`` and are deliberately not imported here.

Construction only enforces types and simple field bounds. The §32 honesty
invariants — the rules that stop a manifest from claiming more than its
evidence supports — are enforced by :func:`validate_manifest`, which raises a
typed :class:`ManifestValidationError`. Keeping the two apart lets callers
build a structurally-valid-but-dishonest manifest in a test and assert that the
honesty gate rejects it.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.certification.readiness import CredentialReadiness

# ── Field-shape descriptors ────────────────────────────────────────────────

CredentialFieldType = Literal[
    "string",
    "secret",
    "oauth_token",
    "json",
    "number",
    "boolean",
    "url",
]

ConfigFieldType = Literal[
    "string",
    "number",
    "boolean",
    "json",
    "url",
    "enum",
]

AuthType = Literal["oauth2", "api_key", "composite", "webhook_only", "none"]


class CredentialFieldSpec(BaseModel):
    """Describes ONE credential field's shape (never its value)."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: CredentialFieldType
    required: bool = True
    secret: bool = False


class ConfigFieldSpec(BaseModel):
    """Describes ONE non-secret configuration field."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: ConfigFieldType
    required: bool = False


# ── Manifest sub-models ────────────────────────────────────────────────────


class ManifestReadiness(BaseModel):
    """Readiness state (reused token) plus a coarse 1-5 productization level."""

    state: CredentialReadiness
    level: int = Field(ge=1, le=5)


class EnvironmentAvailability(BaseModel):
    local: bool = False
    integration: bool = False
    staging: bool = False
    production: bool = False

    def any_enabled(self) -> bool:
        return self.local or self.integration or self.staging or self.production


class Availability(BaseModel):
    tenant_self_service: bool = False
    kyber_managed: bool = False
    olympus_system: bool = False
    environments: EnvironmentAvailability = Field(default_factory=EnvironmentAvailability)


class OAuthSpec(BaseModel):
    pkce: bool = False
    scopes: list[str] = Field(default_factory=list)
    refresh_supported: bool = False


class Authentication(BaseModel):
    type: AuthType
    credential_schema: list[CredentialFieldSpec] = Field(default_factory=list)
    oauth: Optional[OAuthSpec] = None


class Configuration(BaseModel):
    fields: list[ConfigFieldSpec] = Field(default_factory=list)


class Accounts(BaseModel):
    discovery_supported: bool = False
    selection_required: bool = False


class Webhooks(BaseModel):
    supported: bool = False
    registration_supported: bool = False
    verification_scheme: Optional[str] = None


class Sync(BaseModel):
    initial_backfill: bool = False
    incremental: bool = False
    reconciliation: bool = False
    # Cursor field/strategy an incremental sync advances (e.g. "updated_at").
    cursor: Optional[str] = None


class Deployment(BaseModel):
    required_environment: list[str] = Field(default_factory=list)
    required_secrets: list[str] = Field(default_factory=list)
    required_public_urls: list[str] = Field(default_factory=list)
    provider_registration_steps: list[str] = Field(default_factory=list)


# ── The manifest ───────────────────────────────────────────────────────────


class ProviderManifest(BaseModel):
    """Canonical, typed description of a single provider capability."""

    model_config = ConfigDict(extra="forbid")

    provider_family: str
    product_id: str
    capability_id: str
    display_name: str
    # ``category`` is intentionally a free ``str``: manifests cover capabilities
    # beyond the connector taxonomy. Callers may pass a ``ConnectorCategory``
    # value where one fits.
    category: str

    readiness: ManifestReadiness
    availability: Availability
    authentication: Authentication
    configuration: Configuration = Field(default_factory=Configuration)
    accounts: Accounts = Field(default_factory=Accounts)
    webhooks: Webhooks = Field(default_factory=Webhooks)
    sync: Sync = Field(default_factory=Sync)

    # Required-but-may-be-empty: forcing an explicit value is itself the honesty
    # invariant "every manifest declares its outputs and destinations".
    data_outputs: list[str]
    product_destinations: list[str]

    deployment: Deployment = Field(default_factory=Deployment)

    @property
    def identity_key(self) -> str:
        """Canonical ``family.product.capability`` string form."""
        return f"{self.provider_family}.{self.product_id}.{self.capability_id}"


class ManifestValidationError(ValueError):
    """Raised by :func:`validate_manifest` when a §32 honesty invariant fails.

    ``violations`` carries every failure so a caller sees them all at once.
    """

    def __init__(self, violations: list[str]) -> None:
        self.violations = list(violations)
        super().__init__("; ".join(self.violations))


def validate_manifest(m: ProviderManifest) -> ProviderManifest:
    """Enforce the manifest-level §32 honesty invariants.

    Returns the manifest unchanged when honest; raises
    :class:`ManifestValidationError` (collecting every violation) otherwise.
    """

    violations: list[str] = []
    level = m.readiness.level
    envs = m.availability.environments

    # A capability enabled in ANY environment is at least replay-validated
    # material: level must be >= 3.
    if envs.any_enabled() and level < 3:
        violations.append(
            f"visible-in-environment requires level>=3, got level={level}"
        )

    # Staging is a higher bar than mere visibility: sandbox-validated (>=4).
    if envs.staging and level < 4:
        violations.append(
            f"staging=True requires level>=4, got level={level}"
        )

    # OAuth must declare the scopes it will request.
    if m.authentication.type == "oauth2":
        oauth = m.authentication.oauth
        if oauth is None or not oauth.scopes:
            violations.append(
                "authentication.type=oauth2 requires oauth.scopes to be non-empty"
            )

    # A supported webhook must declare how inbound calls are verified.
    if m.webhooks.supported and not (m.webhooks.verification_scheme or "").strip():
        violations.append(
            "webhooks.supported=True requires a non-empty verification_scheme"
        )

    # Incremental sync must declare the cursor it advances.
    if m.sync.incremental and not (m.sync.cursor or "").strip():
        violations.append(
            "sync.incremental=True requires a non-empty sync.cursor declaration"
        )

    if violations:
        raise ManifestValidationError(violations)
    return m


__all__ = [
    "Accounts",
    "AuthType",
    "Authentication",
    "Availability",
    "ConfigFieldSpec",
    "ConfigFieldType",
    "Configuration",
    "CredentialFieldSpec",
    "CredentialFieldType",
    "Deployment",
    "EnvironmentAvailability",
    "ManifestReadiness",
    "ManifestValidationError",
    "OAuthSpec",
    "ProviderManifest",
    "Sync",
    "Webhooks",
    "validate_manifest",
]
