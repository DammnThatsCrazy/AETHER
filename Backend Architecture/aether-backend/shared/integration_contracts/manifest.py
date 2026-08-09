"""Canonical provider manifest (§12) and its honesty invariants (§32).

A :class:`ProviderManifest` is the single, typed source of truth for what a
provider capability *is* and *needs*: its identity, readiness, availability,
authentication shape, configuration surface, account/webhook/sync behaviour,
data outputs, product destinations, and deployment requirements.

The manifest describes credential **shape** — field descriptors
(:class:`CredentialFieldSpec`) — never credential values. Value types live in
``shared.credentials.types`` and are deliberately not imported here.

Beyond identity/readiness/availability/auth, the manifest also declares the
**behavioral conformance surface** a runtime needs: transport protocol, base
URL configuration, idempotency / rate-limit / read-vs-mutate semantics, health
probe, normalization version, supported event types, known-unsupported
behavior, and certification state. The three sync-overlapping attributes
(``reconciliation_support``, ``backfill_support``, ``cursor_semantics``) are
read-only projections of the canonical ``sync`` sub-model — one source of
truth, no parallel maps.

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

# Primary transport a provider capability moves events/records over. A
# webhook-plus-pull provider declares its PRIMARY transport (the pull path);
# secondary channels are expressed through the existing ``webhooks.supported`` /
# ``sync.incremental`` structure, never here.
TransportProtocol = Literal[
    "rest",
    "websocket",
    "polling",
    "webhook",
    "stream",
]

# Honest certification posture of the capability. ``uncertified`` is the truthful
# default for anything credential-gated / awaiting tenant credentials; the other
# values are earned by real offline/sandbox/live certification runs.
CertificationState = Literal[
    "uncertified",
    "replay_certified",
    "sandbox_certified",
    "live_certified",
]


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

    # ── Declarative behavior surface (§8 conformance) ──────────────────────────
    # Universal-provider conformance fields: the runtime behavior of a provider
    # capability is *declared here*, not re-derived from connector-name maps.
    # All default to the most conservative honest value so pre-existing manifests
    # keep validating unchanged. The §32 honesty gate additionally REQUIRES the
    # financial-critical trio (``read_only_mutating_boundary``, ``health_probe``,
    # ``certification_state``) to be explicitly declared for financial providers.
    transport_protocol: TransportProtocol = "rest"
    base_url_config: Optional[str] = None
    callback_requirements: list[str] = Field(default_factory=list)
    idempotency_semantics: Optional[str] = None
    rate_limit_behavior: Optional[str] = None
    read_only_mutating_boundary: Optional[str] = None
    health_probe: Optional[str] = None
    normalization_version: Optional[str] = None
    supported_event_types: list[str] = Field(default_factory=list)
    known_unsupported_behavior: list[str] = Field(default_factory=list)
    certification_state: Optional[CertificationState] = None

    @property
    def identity_key(self) -> str:
        """Canonical ``family.product.capability`` string form."""
        return f"{self.provider_family}.{self.product_id}.{self.capability_id}"

    # The three sync-overlapping declarative attributes are read-only projections
    # of the canonical ``sync`` sub-model — there is exactly ONE source of truth,
    # so no parallel map can ever drift from it. They exist as attributes so the
    # conformance surface is uniform, but a caller cannot set them (constructing a
    # manifest with ``reconciliation_support=...`` is rejected as an extra field).
    @property
    def reconciliation_support(self) -> bool:
        """Whether the provider genuinely reconciles with Aether (== ``sync.reconciliation``)."""
        return self.sync.reconciliation

    @property
    def backfill_support(self) -> bool:
        """Whether an initial historical backfill is supported (== ``sync.initial_backfill``)."""
        return self.sync.initial_backfill

    @property
    def cursor_semantics(self) -> Optional[str]:
        """Recency cursor an incremental sync advances (== ``sync.cursor``)."""
        return self.sync.cursor


class ManifestValidationError(ValueError):
    """Raised by :func:`validate_manifest` when a §32 honesty invariant fails.

    ``violations`` carries every failure so a caller sees them all at once.
    """

    def __init__(self, violations: list[str]) -> None:
        self.violations = list(violations)
        super().__init__("; ".join(self.violations))


# Financial categories get the strict conformance gate: payment rails (product
# "payment_rails") plus any capability in a financial connector category. The
# gate refuses a financial manifest that has NOT explicitly declared its
# read/mutate boundary, its health probe, and its certification posture — the
# three facts an operator must be able to trust before touching money data.
FINANCIAL_CATEGORIES: frozenset[str] = frozenset(
    {"payments", "billing", "cex", "onchain", "credit_bureau"}
)


def is_financial_provider(m: ProviderManifest) -> bool:
    """Whether a manifest describes a financial (money-adjacent) capability."""
    return m.product_id == "payment_rails" or m.category in FINANCIAL_CATEGORIES


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

    # Incremental sync must declare the cursor it advances.
    if m.sync.incremental and not (m.sync.cursor or "").strip():
        violations.append("sync.incremental=True requires a non-empty sync.cursor declaration")

    # Financial providers must explicitly declare their read/mutate boundary,
    # health probe, and certification posture. Leaving the default (None) is a
    # lie by omission for money-adjacent capabilities — the operator cannot tell
    # whether the capability observes or moves funds.
    if is_financial_provider(m):
        for field_name, value in (
            ("read_only_mutating_boundary", m.read_only_mutating_boundary),
            ("health_probe", m.health_probe),
            ("certification_state", m.certification_state),
        ):
            if not value or (isinstance(value, str) and not value.strip()):
                violations.append(f"financial provider requires a declared {field_name}")

    if violations:
        raise ManifestValidationError(violations)
    return m


__all__ = [
    "Accounts",
    "AuthType",
    "Authentication",
    "Availability",
    "CertificationState",
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
    "TransportProtocol",
    "Webhooks",
    "is_financial_provider",
    "validate_manifest",
]
