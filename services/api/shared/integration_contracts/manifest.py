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
from shared.integration_contracts.streams import StreamDescriptor

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
    # Optional bounded vocabulary for configuration that selects a credential
    # profile. Old manifests leave these empty and retain their v1 behavior.
    allowed_values: list[str] = Field(default_factory=list)
    default_value: Optional[str] = None


class CredentialProfileSpec(BaseModel):
    """One explicitly selected alternative credential shape.

    ``mode_field`` names an enumerated non-secret config field. Every allowed
    mode value must have exactly one profile; ``required_fields`` names secret
    fields required in that mode, in addition to globally required fields.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    mode_field: str
    mode_value: str
    required_fields: list[str]


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
    credential_profiles: list[CredentialProfileSpec] = Field(default_factory=list)
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
    # Explicit stream inventory for newly migrated capabilities. Empty keeps
    # v1 plugin manifests and their capability-level execution unchanged.
    streams: list[StreamDescriptor] = Field(default_factory=list)

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


def credential_profile_violations(m: ProviderManifest) -> list[str]:
    """Check alternative secret shapes without changing v1 manifests.

    Profiles are complete only when the config mode is enumerated and every
    declared value has one satisfiable required-secret set. Optional secrets
    outside those sets remain certification failures.
    """
    profiles = m.authentication.credential_profiles
    if not profiles:
        return []
    violations: list[str] = []
    fields = {field.name: field for field in m.authentication.credential_schema}
    if len(fields) != len(m.authentication.credential_schema):
        violations.append("credential schema repeats a field name")
    configs = {field.name: field for field in m.configuration.fields}
    names: set[str] = set()
    modes: set[tuple[str, str]] = set()
    mode_fields: set[str] = set()
    for profile in profiles:
        name = profile.name.strip()
        mode_field = profile.mode_field.strip()
        mode_value = profile.mode_value.strip()
        if not name or name in names:
            violations.append(f"credential profile name {profile.name!r} is empty or repeated")
        names.add(name)
        if not mode_field or not mode_value or (mode_field, mode_value) in modes:
            violations.append(f"credential profile {name!r} has an empty or repeated mode")
        modes.add((mode_field, mode_value))
        mode_fields.add(mode_field)
        config = configs.get(mode_field)
        if config is None:
            violations.append(
                f"credential profile {name!r} references undeclared config {mode_field!r}"
            )
        elif config.type not in ("enum", "string") or mode_value not in config.allowed_values:
            violations.append(
                f"credential profile {name!r} references unsupported mode {mode_value!r}"
            )
        if not profile.required_fields or len(set(profile.required_fields)) != len(
            profile.required_fields
        ):
            violations.append(f"credential profile {name!r} needs distinct required fields")
        if not any(fields.get(field) and fields[field].secret for field in profile.required_fields):
            violations.append(f"credential profile {name!r} must require a secret field")
        for field in profile.required_fields:
            if field not in fields:
                violations.append(
                    f"credential profile {name!r} references undeclared field {field!r}"
                )
    if len(mode_fields) != 1:
        violations.append("credential profiles must use one explicit mode field")
    for mode_field in mode_fields:
        config = configs.get(mode_field)
        if config is None:
            continue
        allowed = set(config.allowed_values)
        declared = {profile.mode_value for profile in profiles if profile.mode_field == mode_field}
        if not allowed or len(allowed) != len(config.allowed_values):
            violations.append(
                f"credential mode config {mode_field!r} needs distinct allowed values"
            )
        if allowed != declared:
            violations.append(
                f"credential mode config {mode_field!r} has a value without a credential profile"
            )
        if not config.required and config.default_value not in allowed:
            violations.append(f"credential mode config {mode_field!r} needs a supported default")
    return violations


def validate_manifest(m: ProviderManifest) -> ProviderManifest:
    """Enforce the manifest-level §32 honesty invariants.

    Returns the manifest unchanged when honest; raises
    :class:`ManifestValidationError` (collecting every violation) otherwise.
    """

    violations: list[str] = []
    violations.extend(credential_profile_violations(m))
    level = m.readiness.level
    envs = m.availability.environments

    # A capability enabled in ANY environment is at least replay-validated
    # material: level must be >= 3.
    if envs.any_enabled() and level < 3:
        violations.append(f"visible-in-environment requires level>=3, got level={level}")

    # Staging is a higher bar than mere visibility: sandbox-validated (>=4).
    if envs.staging and level < 4:
        violations.append(f"staging=True requires level>=4, got level={level}")

    # OAuth must declare the scopes it will request.
    if m.authentication.type == "oauth2":
        oauth = m.authentication.oauth
        if oauth is None or not oauth.scopes:
            violations.append("authentication.type=oauth2 requires oauth.scopes to be non-empty")

    # A supported webhook must declare how inbound calls are verified.
    if m.webhooks.supported and not (m.webhooks.verification_scheme or "").strip():
        violations.append("webhooks.supported=True requires a non-empty verification_scheme")

    # Legacy capability-level sync needs its one cursor. Explicit streams own
    # their cursor declarations independently (validated below).
    if m.sync.incremental and not m.streams and not (m.sync.cursor or "").strip():
        violations.append("sync.incremental=True requires a non-empty sync.cursor declaration")

    if m.streams:
        seen_ids: set[str] = set()
        seen_topics: dict[str, str] = {}
        declared = [s for s in m.streams if isinstance(s, StreamDescriptor)]
        if len(declared) != len(m.streams):
            violations.append("streams must contain only StreamDescriptor entries")

        has_backfill = any(s.initial_backfill for s in declared)
        has_incremental = any(s.incremental for s in declared)
        has_webhook = any("webhook" in s.acquisition_modes for s in declared)
        if m.sync.initial_backfill != has_backfill:
            violations.append(
                "sync.initial_backfill must match declared stream backfill capability"
            )
        if m.sync.incremental != has_incremental:
            violations.append("sync.incremental must match declared stream incremental capability")
        if m.webhooks.supported != has_webhook:
            violations.append("webhooks.supported must match declared webhook streams")

        oauth_scopes = set(m.authentication.oauth.scopes) if m.authentication.oauth else set()
        config_fields: dict[str, list[ConfigFieldSpec]] = {}
        for config_field in m.configuration.fields:
            config_fields.setdefault(config_field.name, []).append(config_field)
        for stream in declared:
            label = f"stream {stream.stream_id!r}"
            if stream.stream_id in seen_ids:
                violations.append(f"duplicate stream_id {stream.stream_id!r}")
            seen_ids.add(stream.stream_id)
            modes = set(stream.acquisition_modes)
            if len(modes) != len(stream.acquisition_modes):
                violations.append(f"{label} repeats an acquisition mode")
            if "pull" in modes and not (stream.initial_backfill or stream.incremental):
                violations.append(f"{label} claims pull without a sync operation")
            if (stream.initial_backfill or stream.incremental) and not modes.intersection(
                {"pull", "report", "stream"}
            ):
                violations.append(f"{label} declares sync without an acquisition adapter")
            if stream.incremental and not (stream.cursor_scheme or "").strip():
                violations.append(f"{label} incremental sync requires cursor_scheme")
            if "webhook" in modes and not stream.webhook_topics:
                violations.append(f"{label} webhook acquisition requires webhook_topics")
            if stream.webhook_topics and "webhook" not in modes:
                violations.append(f"{label} declares webhook_topics without webhook acquisition")
            for topic in stream.webhook_topics:
                if not topic.strip():
                    violations.append(f"{label} has an empty webhook topic")
                elif topic in seen_topics:
                    violations.append(
                        f"webhook topic {topic!r} is ambiguous between "
                        f"{seen_topics[topic]!r} and {stream.stream_id!r}"
                    )
                else:
                    seen_topics[topic] = stream.stream_id
            if len(set(stream.required_scopes)) != len(stream.required_scopes):
                violations.append(f"{label} repeats a required scope")
            if stream.required_scopes and m.authentication.type != "oauth2":
                violations.append(f"{label} requires scopes but authentication is not oauth2")
            missing_scopes = set(stream.required_scopes) - oauth_scopes
            if m.authentication.type == "oauth2" and missing_scopes:
                violations.append(
                    f"{label} requires undeclared oauth scopes: {', '.join(sorted(missing_scopes))}"
                )
            if stream.output_contract not in m.data_outputs:
                violations.append(
                    f"{label} output_contract {stream.output_contract!r} "
                    "is absent from data_outputs"
                )
            if stream.activation_config_field is not None:
                matching_fields = config_fields.get(stream.activation_config_field, [])
                if len(matching_fields) != 1:
                    violations.append(
                        f"{label} activation references undeclared or ambiguous config "
                        f"{stream.activation_config_field!r}"
                    )
                else:
                    config_field = matching_fields[0]
                    activation_value = stream.activation_config_value
                    if config_field.type not in ("enum", "string"):
                        violations.append(
                            f"{label} activation config {config_field.name!r} must be enum or string"
                        )
                    elif activation_value not in config_field.allowed_values and (
                        activation_value != config_field.default_value
                    ):
                        violations.append(
                            f"{label} activation value {activation_value!r} is not declared by "
                            f"config {config_field.name!r}"
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
    "CredentialProfileSpec",
    "CredentialFieldType",
    "Deployment",
    "EnvironmentAvailability",
    "ManifestReadiness",
    "ManifestValidationError",
    "OAuthSpec",
    "ProviderManifest",
    "Sync",
    "StreamDescriptor",
    "Webhooks",
    "validate_manifest",
    "credential_profile_violations",
]
